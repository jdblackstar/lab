package lab.xmage;

import com.google.gson.*;
import mage.MageObject;
import mage.abilities.ActivatedAbility;
import mage.cards.Card;
import mage.cards.CardSetInfo;
import mage.cards.ExpansionSet;
import mage.cards.Sets;
import mage.cards.decks.Deck;
import mage.constants.*;
import mage.game.*;
import mage.game.events.GameEvent;
import mage.game.events.PlayerQueryEvent;
import mage.game.mulligan.MulliganType;
import mage.game.match.MatchOptions;
import mage.game.match.MatchPlayer;
import mage.game.permanent.Permanent;
import mage.player.ai.ComputerPlayer7;
import mage.player.human.HumanPlayer;
import mage.player.human.PlayerResponse;
import mage.players.Player;
import mage.players.net.UserData;
import mage.util.RandomUtil;
import mage.view.GameView;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/** A headless adapter with limited choice coverage. XMage performs all game rules. */
public final class PocMain {
    static final String REVISION = "afab346e06c4960882cf148acc57754c1c50a007";
    static final Gson JSON = new GsonBuilder().serializeNulls().create();

    static JsonObject object(Object... pairs) {
        JsonObject out = new JsonObject();
        for (int i = 0; i < pairs.length; i += 2) out.add((String) pairs[i], JSON.toJsonTree(pairs[i + 1]));
        return out;
    }

    static JsonObject card(MageObject c, Game g) {
        JsonObject out = object("id", c.getId(), "name", c.getName(), "type", c.getCardType(g),
            "zone", g.getState().getZone(c.getId()));
        if (c instanceof Card) {
            out.addProperty("owner", ((Card) c).getOwnerId().toString());
            out.add("rules", JSON.toJsonTree(((Card) c).getRules(g)));
        }
        if (c instanceof Permanent) {
            Permanent p = (Permanent) c;
            out.add("permanent", object("controller", p.getControllerId(), "tapped", p.isTapped(),
                "power", p.getPower().getValue(), "toughness", p.getToughness().getValue(),
                "damage", p.getDamage(), "counters", p.getCounters(g).toString()));
        }
        return out;
    }

    static JsonArray cards(Collection<? extends MageObject> cs, Game g) {
        JsonArray out = new JsonArray();
        for (MageObject c : cs) out.add(card(c, g));
        return out;
    }

    /** HumanPlayer's existing rule/choice handling with a synchronous pipe transport. */
    static final class BridgePlayer extends HumanPlayer {
        final transient PlayerResponse reply;
        final transient Channel channel;
        BridgePlayer(String name, Channel channel) { this(name, channel, new PlayerResponse()); }
        private BridgePlayer(String name, Channel channel, PlayerResponse reply) {
            super(new HumanPlayer(name, RangeOfInfluence.ALL, 1), reply);
            this.reply = reply;
            this.channel = channel;
            UserData user = UserData.getDefaultUserDataView();
            user.setAutoTargetLevel(0);
            user.getUserSkipPrioritySteps().getYourTurn().setUpkeep(true);
            user.getUserSkipPrioritySteps().getYourTurn().setDraw(true);
            user.getUserSkipPrioritySteps().getYourTurn().setBeforeCombat(true);
            user.getUserSkipPrioritySteps().getYourTurn().setEndOfCombat(true);
            user.getUserSkipPrioritySteps().getYourTurn().setEndOfTurn(true);
            user.getUserSkipPrioritySteps().getOpponentTurn().setUpkeep(true);
            user.getUserSkipPrioritySteps().getOpponentTurn().setDraw(true);
            user.getUserSkipPrioritySteps().getOpponentTurn().setBeforeCombat(true);
            user.getUserSkipPrioritySteps().getOpponentTurn().setEndOfCombat(true);
            user.getUserSkipPrioritySteps().getOpponentTurn().setEndOfTurn(true);
            setUserData(user);
        }
        private BridgePlayer(BridgePlayer p) { super(p); reply = p.reply; channel = p.channel; }
        @Override public BridgePlayer copy() { return new BridgePlayer(this); }
        @Override protected void waitForResponse(Game game) {
            reply.resetAnswers();
            JsonObject action = channel.request(game, this);
            String type = action.get("response_type").getAsString();
            JsonElement value = action.get("value");
            switch (type) {
                case "boolean": reply.setBoolean(value.getAsBoolean()); break;
                case "integer": reply.setInteger(value.getAsInt()); break;
                case "string": reply.setString(value.getAsString()); break;
                case "uuid": reply.setUUID(UUID.fromString(value.getAsString())); break;
                default: throw new IllegalStateException("Unsupported response: " + type);
            }
        }
    }

    static final class RecordedGame extends TwoPlayerDuel {
        transient Recorder recorder;
        String technicalFailure;
        RecordedGame() {
            super(MultiplayerAttackOption.LEFT, RangeOfInfluence.ALL,
                MulliganType.GAME_DEFAULT.getMulligan(0), 60, 20, 7);
        }
        @Override public TwoPlayerDuel copy() { return new TwoPlayerDuel(this); }
        @Override public void fireEvent(GameEvent e) {
            super.fireEvent(e);
            if (recorder != null) recorder.capture(this, "event", object("type", e.getType(),
                "source", e.getSourceId(), "target", e.getTargetId(), "player", e.getPlayerId(),
                "amount", e.getAmount(), "flag", e.getFlag()));
        }
        @Override public void fireUpdatePlayersEvent() {
            super.fireUpdatePlayersEvent();
            if (recorder != null) recorder.capture(this, "update", new JsonObject());
        }
        @Override public void endWithTechnicalWinner(String reason) {
            technicalFailure = reason;
            super.endWithTechnicalWinner(reason);
        }
    }

    static final class Recorder implements Closeable {
        final Path root;
        final BufferedWriter states;
        final BufferedWriter decisions;
        final Map<UUID, BufferedWriter> views = new LinkedHashMap<>();
        long sequence = 0;
        boolean capturing;
        Recorder(Path root, Game game) throws IOException {
            this.root = root;
            Files.createDirectories(root.resolve("internal/checkpoints"));
            Files.createDirectories(root.resolve("players"));
            states = Files.newBufferedWriter(root.resolve("internal/states.jsonl"), StandardCharsets.UTF_8);
            decisions = Files.newBufferedWriter(root.resolve("internal/decisions.jsonl"), StandardCharsets.UTF_8);
            for (Player p : game.getPlayers().values()) {
                views.put(p.getId(), Files.newBufferedWriter(root.resolve("players/" + p.getName() + ".jsonl"), StandardCharsets.UTF_8));
            }
        }
        long capture(Game g, String reason, JsonObject event) {
            if (capturing || g.isSimulation()) return sequence;
            capturing = true;
            try {
                long seq = ++sequence;
                String file = String.format("checkpoints/%06d.game.gz", seq);
                // Preserve the entire serializable engine graph, rather than treating a
                // selective JSON projection as a complete engine checkpoint.
                try (ObjectOutputStream out = new ObjectOutputStream(new GZIPOutputStream(
                    Files.newOutputStream(root.resolve("internal").resolve(file))))) { out.writeObject(g); }
                JsonObject state = summary(g);
                state.addProperty("sequence", seq);
                state.addProperty("reason", reason);
                state.add("event", event);
                state.addProperty("checkpoint", file);
                state.addProperty("sha256", hash(root.resolve("internal").resolve(file)));
                line(states, state);
                return seq;
            } catch (Exception e) { throw new IllegalStateException("Recording failed; discard this run", e); }
            finally { capturing = false; }
        }
        @Override public void close() throws IOException {
            states.close(); decisions.close();
            for (BufferedWriter w : views.values()) w.close();
        }
    }

    static String hash(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] bytes = Files.readAllBytes(file);
        StringBuilder out = new StringBuilder();
        for (byte b : digest.digest(bytes)) out.append(String.format("%02x", b & 255));
        return out.toString();
    }

    static void line(BufferedWriter writer, JsonObject o) throws IOException {
        writer.write(JSON.toJson(o)); writer.newLine(); writer.flush();
    }

    static JsonObject summary(Game g) {
        JsonArray players = new JsonArray();
        for (Player p : g.getPlayers().values()) {
            players.add(object("id", p.getId(), "name", p.getName(), "life", p.getLife(),
                "hand", cards(p.getHand().getCards(g), g),
                "library", cards(p.getLibrary().getCards(g), g),
                "graveyard", cards(p.getGraveyard().getCards(g), g),
                "sideboard", cards(p.getSideboard().getCards(g), g),
                "mana", p.getManaPool().toString(), "won", p.hasWon(), "lost", p.hasLost()));
        }
        return object("game_id", g.getId(), "turn", g.getState().getTurnNum(),
            "phase", g.getTurnPhaseType(), "step", g.getTurnStepType(),
            "active_player", g.getActivePlayerId(), "priority_player", g.getState().getPriorityPlayerId(),
            "players", players, "battlefield", cards(g.getBattlefield().getAllPermanents(), g),
            "stack", cards(g.getStack(), g), "exile", g.getExile().toString(),
            "ended", g.hasEnded(), "winner", g.getWinner(), "errors", g.getTotalErrorsCount());
    }

    static final class Channel {
        PlayerQueryEvent pending;
        Recorder recorder;
        final BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        int decision;

        static void add(JsonArray actions, String kind, String label, String type, Object value) {
            actions.add(object("index", actions.size(), "kind", kind, "label", label, "response_type", type, "value", value));
        }

        JsonObject request(Game g, Player p) {
            try {
                if (pending == null || !pending.getPlayerId().equals(p.getId())) throw new IllegalStateException("Missing query");
                PlayerQueryEvent q = pending;
                JsonObject view = JsonParser.parseString(new GameView(g.getState(), g, p.getId(), null).toJson()).getAsJsonObject();
                JsonArray actions = actions(q, g, p, view);
                if (actions.size() == 0) throw new IllegalStateException("No actions for " + q.getQueryType());
                String message = q.getMessage();
                if (message == null && q.getOptions() != null) message = String.valueOf(q.getOptions().getOrDefault("header", q.getOptions().getOrDefault("title", "Choose an allocation")));
                JsonObject observation = object("decision", ++decision, "player", p.getName(), "player_id", p.getId(),
                    "query_type", q.getQueryType(), "message", message, "view", view, "actions", actions);
                long seq = recorder.capture(g, "decision", object("decision", decision, "actor", p.getId()));
                line(recorder.views.get(p.getId()), observation);
                System.out.println(JSON.toJson(object("type", "decision", "observation", observation)));
                System.out.flush();
                String answer = input.readLine();
                if (answer == null) throw new EOFException("Controller disconnected");
                JsonObject response = JsonParser.parseString(answer).getAsJsonObject();
                if (response.get("decision").getAsInt() != decision) throw new IllegalArgumentException("Stale decision");
                int index = response.get("action").getAsInt();
                if (index < 0 || index >= actions.size()) throw new IllegalArgumentException("Invalid action index");
                JsonObject selected = actions.get(index).getAsJsonObject();
                line(recorder.decisions, object("decision", decision, "state_sequence", seq,
                    "actor", p.getId(), "observation", observation, "response", response, "selected", selected));
                return selected;
            } catch (Exception e) { throw new IllegalStateException("Controller/recorder failed", e); }
        }

        JsonArray actions(PlayerQueryEvent q, Game g, Player p, JsonObject view) {
            JsonArray out = new JsonArray();
            switch (q.getQueryType()) {
                case ASK:
                    add(out, "yes", "Yes", "boolean", true); add(out, "no", "No / keep", "boolean", false); break;
                case SELECT:
                    if (q.getMessage().startsWith("Select attackers")) {
                        combatChoices(out, q, g, view, true);
                        if (q.getOptions().containsKey(Constants.Option.SPECIAL_BUTTON)) add(out, "attack_all", "Attack with all eligible creatures", "string", "special");
                    } else if (q.getMessage().startsWith("Select blockers")) {
                        combatChoices(out, q, g, view, false);
                    } else {
                        playable(out, g, p, false);
                    }
                    add(out, "pass", "Done / pass priority", "boolean", true); break;
                case PLAY_MANA:
                    playable(out, g, p, true); break;
                case CHOOSE_ABILITY: case PICK_ABILITY:
                    for (mage.abilities.Ability a : q.getAbilities()) add(out, "ability", a.getRule(), "uuid", a.getId()); break;
                case PICK_TARGET:
                    Set<UUID> ids = new LinkedHashSet<>();
                    if (q.getTargets() != null) ids.addAll(q.getTargets());
                    if (q.getCards() != null) ids.addAll(q.getCards());
                    if (q.getPerms() != null) for (Permanent perm : q.getPerms()) ids.add(perm.getId());
                    for (UUID id : ids) {
                        MageObject target = g.getObject(id);
                        Player targetPlayer = g.getPlayer(id);
                        if (targetPlayer != null) add(out, "target", targetPlayer.getName(), "uuid", id);
                        else if (target != null) {
                            // Fail closed: these fixtures have no search/look effects. Never
                            // convert a hidden target into a named controller option.
                            Zone zone = g.getState().getZone(id);
                            if (zone == Zone.LIBRARY || (zone == Zone.HAND && !p.getHand().contains(id))) throw new IllegalStateException("Unsupported hidden target");
                            add(out, "target", target.getName(), "uuid", id);
                        }
                    }
                    if (!q.isRequired()) add(out, "cancel", "Done / cancel", "boolean", false);
                    break;
                case CHOOSE_MODE:
                    for (Map.Entry<UUID, String> e : q.getModes().entrySet()) add(out, "mode", e.getValue(), "uuid", e.getKey()); break;
                case CHOOSE_CHOICE:
                    if (q.getChoice().getKeyChoices().isEmpty()) {
                        for (String c : q.getChoice().getChoices()) add(out, "choice", c, "string", c);
                    } else for (Map.Entry<String, String> e : q.getChoice().getKeyChoices().entrySet()) add(out, "choice", e.getValue(), "string", e.getKey());
                    break;
                case AMOUNT: case PLAY_X_MANA:
                    if (q.getMax() - q.getMin() > 100) throw new IllegalStateException("Unsupported amount range");
                    for (int i = q.getMin(); i <= q.getMax(); i++) add(out, "amount", String.valueOf(i), "integer", i); break;
                case MULTI_AMOUNT:
                    amountAllocations(out, q); break;
                default: throw new IllegalStateException("Unsupported query: " + q.getQueryType());
            }
            return out;
        }

        void amountAllocations(JsonArray out, PlayerQueryEvent q) {
            List<mage.util.MultiAmountMessage> constraints = q.getMessages();
            if (constraints.size() > 16) throw new IllegalStateException("Unsupported allocation dimensions");
            List<Integer> defaults = mage.constants.MultiAmountType.prepareDefaultValues(constraints, q.getMin(), q.getMax());
            if (mage.constants.MultiAmountType.isGoodValues(defaults, constraints, q.getMin(), q.getMax())) addAllocation(out, constraints, defaults);
            enumerateAllocations(out, q, new ArrayList<>(), 0);
            if (Boolean.TRUE.equals(q.getOptions().get("canCancel"))) add(out, "cancel", "Cancel allocation", "boolean", false);
        }

        void addAllocation(JsonArray out, List<mage.util.MultiAmountMessage> constraints, List<Integer> values) {
            StringJoiner response = new StringJoiner(" ");
            StringJoiner label = new StringJoiner("; ");
            for (int i = 0; i < values.size(); i++) {
                response.add(String.valueOf(values.get(i)));
                label.add(constraints.get(i).message + ": " + values.get(i));
            }
            String encoded = response.toString();
            for (JsonElement existing : out) if (existing.getAsJsonObject().get("value").getAsString().equals(encoded)) return;
            if (out.size() >= 4096) throw new IllegalStateException("Unsupported allocation space: more than 4096 choices");
            add(out, "allocation", label.toString(), "string", encoded);
        }

        void enumerateAllocations(JsonArray out, PlayerQueryEvent q, List<Integer> values, int sum) {
            if (out.size() > 4096) throw new IllegalStateException("Unsupported allocation space: more than 4096 choices");
            List<mage.util.MultiAmountMessage> constraints = q.getMessages();
            if (values.size() == constraints.size()) {
                if (mage.constants.MultiAmountType.isGoodValues(values, constraints, q.getMin(), q.getMax())) addAllocation(out, constraints, values);
                return;
            }
            mage.util.MultiAmountMessage constraint = constraints.get(values.size());
            if (constraint.max - constraint.min > 100) throw new IllegalStateException("Unsupported allocation amount range");
            int remainingMin = 0, remainingMax = 0;
            for (int i = values.size() + 1; i < constraints.size(); i++) { remainingMin += constraints.get(i).min; remainingMax += constraints.get(i).max; }
            for (int amount = constraint.min; amount <= constraint.max; amount++) {
                if (sum + amount + remainingMin > q.getMax() || sum + amount + remainingMax < q.getMin()) continue;
                values.add(amount);
                enumerateAllocations(out, q, values, sum + amount);
                values.remove(values.size() - 1);
            }
        }

        String publicName(JsonObject view, UUID id) {
            for (JsonElement player : view.getAsJsonArray("players")) {
                JsonObject battlefield = player.getAsJsonObject().getAsJsonObject("battlefield");
                if (battlefield.has(id.toString())) {
                    return battlefield.getAsJsonObject(id.toString()).get("name").getAsString();
                }
            }
            throw new IllegalStateException("Combat choice absent from public player view: " + id);
        }

        void combatChoices(JsonArray out, PlayerQueryEvent q, Game g, JsonObject view, boolean attacking) {
            Object offered = q.getOptions().get(attacking ? Constants.Option.POSSIBLE_ATTACKERS : Constants.Option.POSSIBLE_BLOCKERS);
            if (offered instanceof Collection) for (Object value : (Collection<?>) offered) {
                UUID id = (UUID) value;
                Permanent permanent = g.getPermanent(id);
                if (permanent == null) continue;
                if (!attacking && g.getCombat().getGroups().stream().noneMatch(group -> group.canBlock(permanent, g))) continue;
                add(out, attacking ? "attack" : "block", (attacking ? "Attack with " : "Choose blocker ") + publicName(view, id), "uuid", id);
            }
            Set<UUID> selected = attacking ? g.getCombat().getAttackers() : g.getCombat().getBlockers();
            for (UUID id : selected) {
                Permanent permanent = g.getPermanent(id);
                if (permanent != null && permanent.getControllerId().equals(q.getPlayerId())) {
                    add(out, attacking ? "remove_attacker" : "remove_blocker", "Remove " + publicName(view, id) + " from combat selection", "uuid", id);
                }
            }
        }

        void playable(JsonArray out, Game g, Player p, boolean manaOnly) {
            Set<UUID> seen = new HashSet<>();
            for (ActivatedAbility a : p.getPlayable(g, false)) {
                if (a.isManaActivatedAbility() != manaOnly) continue;
                UUID id = a.getSourceId();
                MageObject c = g.getObject(id);
                if (c == null || !seen.add(id)) continue;
                Zone zone = g.getState().getZone(id);
                if (zone == Zone.LIBRARY || (zone == Zone.HAND && !p.getHand().contains(id))) throw new IllegalStateException("Hidden playable object");
                add(out, manaOnly ? "mana" : (c.isLand(g) ? "land" : "cast"), c.getName(), "uuid", id);
            }
        }
    }

    static final class CardDefinition {
        final Class<?> cardClass;
        final CardSetInfo setInfo;
        CardDefinition(ExpansionSet set, ExpansionSet.SetCardInfo info) {
            cardClass = info.getCardClass();
            setInfo = new CardSetInfo(info.getName(), set.getCode(), info.getCardNumber(), info.getRarity(), info.getGraphicInfo());
        }
        Card create(UUID owner) throws Exception {
            return (Card) cardClass.getConstructor(UUID.class, CardSetInfo.class).newInstance(owner, setInfo);
        }
    }

    static final class CardCatalog {
        static final Map<String, CardDefinition> DEFINITIONS = load();
        static Map<String, CardDefinition> load() {
            Map<String, CardDefinition> cards = new TreeMap<>();
            List<ExpansionSet> sets = new ArrayList<>(Sets.getInstance().values());
            sets.sort(Comparator.comparing(ExpansionSet::getCode));
            for (ExpansionSet set : sets) {
                if (set.getSetType().isCustomSet()) continue;
                List<ExpansionSet.SetCardInfo> infos = new ArrayList<>(set.getSetCardInfo());
                infos.sort(Comparator.comparing(ExpansionSet.SetCardInfo::getCardNumber));
                for (ExpansionSet.SetCardInfo info : infos) {
                    if (Card.class.isAssignableFrom(info.getCardClass())) {
                        cards.putIfAbsent(info.getName(), new CardDefinition(set, info));
                    }
                }
            }
            if (cards.isEmpty()) throw new IllegalStateException("XMage card catalog is empty; rebuild with Mage.Sets");
            return Collections.unmodifiableMap(cards);
        }
    }

    static Card createCard(String name, UUID owner) throws Exception {
        CardDefinition definition = CardCatalog.DEFINITIONS.get(name);
        if (definition == null) throw new IllegalArgumentException("Unknown card in pinned XMage catalog: " + name);
        return definition.create(owner);
    }

    static Deck deck(Path file, Player p) throws Exception {
        Deck d = new Deck();
        for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] parts = line.split("\\s+", 2);
            if (parts.length != 2) throw new IllegalArgumentException("Expected '<count> <card name>': " + line);
            int count = Integer.parseInt(parts[0]);
            if (count < 1 || count > 60) throw new IllegalArgumentException("Count must be between 1 and 60: " + line);
            String name = parts[1].trim();
            for (int i = 0; i < count; i++) {
                d.getCards().add(createCard(name, p.getId()));
            }
        }
        if (d.getCards().size() != 60) throw new IllegalArgumentException("Fixture must contain 60 cards");
        return d;
    }

    static Game readGame(Path file) throws Exception {
        try (ObjectInputStream in = new ObjectInputStream(new GZIPInputStream(Files.newInputStream(file)))) {
            return (Game) in.readObject();
        }
    }

    // Wall-clock priority timers are the only permitted counterfactual difference.
    static void stripClock(JsonElement value) {
        if (value.isJsonObject()) {
            JsonObject o = value.getAsJsonObject();
            o.remove("priorityTimeSavedTimeMs");
            for (Map.Entry<String, JsonElement> e : o.entrySet()) stripClock(e.getValue());
        } else if (value.isJsonArray()) for (JsonElement e : value.getAsJsonArray()) stripClock(e);
    }

    static JsonElement playerView(Game g, UUID actor) {
        JsonElement view = JsonParser.parseString(new GameView(g.getState(), g, actor, null).toJson());
        stripClock(view);
        return view;
    }

    static void hiddenCounterfactual(Game game, UUID actor) {
        JsonElement before = playerView(game, actor);
        Player opponent = game.getPlayers().values().stream().filter(p -> !p.getId().equals(actor)).findFirst().get();
        Card hidden = opponent.getHand().getCards(game).iterator().next();
        Card replacement = opponent.getLibrary().getCards(game).stream()
            .filter(c -> !c.getName().equals(hidden.getName())).findFirst().get();
        opponent.getHand().remove(hidden.getId());
        opponent.getLibrary().remove(replacement.getId(), game);
        opponent.getLibrary().putOnTop(hidden, game);
        opponent.getHand().add(replacement);
        replacement.setZone(Zone.HAND, game);
        // Reverse both libraries while preserving their lengths and contents.
        for (Player p : game.getPlayers().values()) {
            List<Card> original = p.getLibrary().getCards(game);
            for (Card c : original) p.getLibrary().putOnTop(c, game);
        }
        if (!before.equals(playerView(game, actor))) throw new IllegalStateException("Hidden state changed player view for " + actor);
    }

    static void verifyCheckpoints(Path output) throws Exception {
        int count = 0;
        Path internal = output.resolve("internal");
        JsonObject manifest = JsonParser.parseString(new String(Files.readAllBytes(internal.resolve("manifest.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        Set<UUID> bridgePlayers = new HashSet<>();
        for (JsonElement id : manifest.getAsJsonArray(manifest.has("bridge_players") ? "bridge_players" : "players")) {
            bridgePlayers.add(UUID.fromString(id.getAsString()));
        }
        try (BufferedReader input = Files.newBufferedReader(internal.resolve("states.jsonl"), StandardCharsets.UTF_8)) {
            String line;
            while ((line = input.readLine()) != null) {
                JsonObject recorded = JsonParser.parseString(line).getAsJsonObject();
                Game game = readGame(internal.resolve(recorded.get("checkpoint").getAsString()));
                JsonObject restored = summary(game);
                for (Map.Entry<String, JsonElement> e : restored.entrySet()) {
                    if (!e.getValue().equals(recorded.get(e.getKey()))) {
                        throw new IllegalStateException("Checkpoint differs: " + recorded.get("sequence") + " field " + e.getKey());
                    }
                }
                count++;
            }
        }
        Set<UUID> tested = new HashSet<>();
        for (String line : Files.readAllLines(internal.resolve("decisions.jsonl"), StandardCharsets.UTF_8)) {
            JsonObject decision = JsonParser.parseString(line).getAsJsonObject();
            JsonObject obs = decision.getAsJsonObject("observation");
            UUID actor = UUID.fromString(obs.get("player_id").getAsString());
            Path checkpoint = internal.resolve(String.format("checkpoints/%06d.game.gz", decision.get("state_sequence").getAsInt()));
            Game restored = readGame(checkpoint);
            JsonElement expectedView = obs.get("view").deepCopy();
            stripClock(expectedView);
            if (!expectedView.equals(playerView(restored, actor))) {
                throw new IllegalStateException("Restored checkpoint differs from delivered view at decision " + decision.get("decision"));
            }
            // Opening mulligan boundaries have private hands but no revealed cards.
            if (!tested.contains(actor) && obs.get("query_type").getAsString().equals("ASK")) {
                hiddenCounterfactual(restored, actor);
                tested.add(actor);
            }
        }
        if (bridgePlayers.isEmpty() || !tested.equals(bridgePlayers)) throw new IllegalStateException("Counterfactual test must cover every controller seat");
        System.out.println(JSON.toJson(object("checkpoints_restored", count, "counterfactual_seats", tested.size())));
    }

    public static void main(String[] args) throws Exception {
        if (args[0].equals("cards")) {
            JsonArray requested = new JsonArray();
            for (int i = 1; i < args.length; i++) {
                Card c = createCard(args[i], UUID.randomUUID());
                requested.add(object("requested_name", args[i], "name", c.getName(), "class", c.getClass().getName(),
                    "set", c.getExpansionSetCode(), "card_number", c.getCardNumber()));
            }
            System.out.println(JSON.toJson(object("xmage_revision", REVISION, "catalog_names", CardCatalog.DEFINITIONS.size(), "cards", requested)));
            return;
        }
        if (args[0].equals("verify")) { verifyCheckpoints(Paths.get(args[1])); return; }
        if (args[0].equals("inspect")) {
            try (ObjectInputStream in = new ObjectInputStream(new GZIPInputStream(Files.newInputStream(Paths.get(args[1]))))) {
                System.out.println(JSON.toJson(summary((Game) in.readObject())));
            }
            return;
        }
        Path output = Paths.get(args[0]);
        long seed = Long.parseLong(args[1]);
        RandomUtil.setSeed(seed);
        Channel channel = new Channel();
        RecordedGame game = new RecordedGame();
        GameOptions options = new GameOptions();
        options.rollbackTurnsAllowed = false;
        game.setGameOptions(options);
        String aiSeat = args.length > 4 ? args[4] : "none";
        if (!Arrays.asList("none", "player_a", "player_b").contains(aiSeat)) throw new IllegalArgumentException("Invalid AI seat: " + aiSeat);
        // The server uses ComputerPlayerControllableProxy, a ComputerPlayer7 subclass
        // that adds human takeover support. A headless opponent needs only the AI.
        Player a = aiSeat.equals("player_a") ? new ComputerPlayer7("player_a", RangeOfInfluence.ALL, 4) : new BridgePlayer("player_a", channel);
        Player b = aiSeat.equals("player_b") ? new ComputerPlayer7("player_b", RangeOfInfluence.ALL, 4) : new BridgePlayer("player_b", channel);
        List<UUID> bridgePlayers = new ArrayList<>();
        for (Player p : Arrays.asList(a, b)) if (p instanceof BridgePlayer) bridgePlayers.add(p.getId());
        Deck deckA = deck(Paths.get(args[2]), a), deckB = deck(Paths.get(args[3]), b);
        MatchOptions matchOptions = new MatchOptions("POC", "Two Player Duel", false);
        matchOptions.setWinsNeeded(1);
        TwoPlayerMatch match = new TwoPlayerMatch(matchOptions);
        a.setMatchPlayer(new MatchPlayer(a, deckA, match));
        b.setMatchPlayer(new MatchPlayer(b, deckB, match));
        a.init(game);
        b.init(game);
        game.loadCards(deckA.getCards(), a.getId());
        game.loadCards(deckB.getCards(), b.getId());
        game.addPlayer(a, deckA);
        game.addPlayer(b, deckB);
        game.addPlayerQueryEventListener(e -> { if (e.getQueryType() != PlayerQueryEvent.QueryType.PERSONAL_MESSAGE) channel.pending = e; });
        try (Recorder recorder = new Recorder(output, game)) {
            channel.recorder = recorder;
            game.recorder = recorder;
            Files.write(output.resolve("internal/manifest.json"), JSON.toJson(object("schema_version", 1,
                "xmage_revision", REVISION, "seed", seed, "deck_a", Files.readAllLines(Paths.get(args[2])),
                "deck_b", Files.readAllLines(Paths.get(args[3])), "players", Arrays.asList(a.getId(), b.getId()),
                "bridge_players", bridgePlayers, "engine_ai", aiSeat.equals("none") ? null : object("seat", aiSeat,
                    "class", ComputerPlayer7.class.getName(), "skill", 4, "max_depth", 4, "max_think_seconds", 12,
                    "information", "perfect: searches the full copied game, including the pilot's real hand and exact library order",
                    "budget", "wall-clock 12s per search on a shared 5-thread pool; hardware/load dependent and non-deterministic"),
                "checkpoint_format", "gzip Java serialization of complete Game graph; transport fields are transient",
                "card_module", "org.mage:mage-sets:1.4.62", "catalog_names", CardCatalog.DEFINITIONS.size(),
                "coverage", "two 60-card decks; limited query adapter; snapshots at game events, updates, decisions, start and end")).getBytes(StandardCharsets.UTF_8));
            recorder.capture(game, "start", new JsonObject());
            game.start(a.getId());
            recorder.capture(game, "end", new JsonObject());
            JsonObject result = object("type", "result", "ended", game.hasEnded(), "winner", game.getWinner(),
                "errors", game.getTotalErrorsCount(), "technical_failure", game.technicalFailure,
                "decisions", channel.decision, "snapshots", recorder.sequence);
            JsonArray outcomes = new JsonArray();
            for (Player p : game.getPlayers().values()) outcomes.add(object("id", p.getId(), "name", p.getName(), "won", p.hasWon(), "lost", p.hasLost()));
            result.add("players", outcomes);
            Files.write(output.resolve("internal/result.json"), JSON.toJson(result).getBytes(StandardCharsets.UTF_8));
            System.out.println(JSON.toJson(result));
        }
    }
}
