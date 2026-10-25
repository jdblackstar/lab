package lab.xmage;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.constants.Constants;
import mage.constants.MultiAmountType;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.events.PlayerQueryEvent;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.util.MultiAmountMessage;

import java.io.BufferedReader;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.StringJoiner;
import java.util.UUID;

import static lab.xmage.Json.GSON;
import static lab.xmage.Json.object;

/**
 * The controller protocol. For each engine query, the bridge prints one
 * {@code {"type": "decision", "observation": ...}} line to stdout and reads one
 * {@code {"decision": n, "action": index}} line from stdin.
 */
final class Channel {
    static final int MAX_ALLOCATIONS = 4096;

    PlayerQueryEvent pending;
    Recorder recorder;
    /** Registration order of players and deck cards; breaks ties between equally named UUID actions. */
    final Map<UUID, Integer> objectOrder = new HashMap<>();
    final BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    int decision;

    /** Gives {@code id} the next registration position. */
    void register(UUID id) {
        objectOrder.put(id, objectOrder.size());
    }

    /** Asks the controller to answer the pending query for {@code p}, and records the exchange. */
    JsonObject request(Game g, Player p) {
        try {
            PlayerQueryEvent q = pendingQueryFor(p);
            JsonObject view = GameJson.playerView(g, p.getId()).getAsJsonObject();
            JsonArray actions = orderedActions(q, g, p, view);
            decision++;
            JsonObject observation = object(
                "decision", decision,
                "player", p.getName(),
                "player_id", p.getId(),
                "query_type", q.getQueryType(),
                "message", message(q),
                "view", view,
                "actions", actions);
            long seq = recorder.capture(g, "decision", object("decision", decision, "actor", p.getId()));
            recorder.writeView(p.getId(), observation);
            send(observation);
            JsonObject response = readResponse();
            JsonObject selected = selectedAction(response, actions);
            recorder.writeDecision(object(
                "decision", decision,
                "state_sequence", seq,
                "actor", p.getId(),
                "observation", observation,
                "response", response,
                "selected", selected));
            return selected;
        } catch (Exception e) {
            throw new IllegalStateException("Controller/recorder failed", e);
        }
    }

    private PlayerQueryEvent pendingQueryFor(Player p) {
        if (pending == null || !pending.getPlayerId().equals(p.getId())) {
            throw new IllegalStateException("Missing query");
        }
        return pending;
    }

    /** The query's legal actions in a stable order, indexed from 0. */
    private JsonArray orderedActions(PlayerQueryEvent q, Game g, Player p, JsonObject view) {
        // Hash iteration must not decide which indexed action is offered first.
        List<JsonElement> ordered = new ArrayList<>();
        for (JsonElement action : actions(q, g, p, view)) {
            ordered.add(action);
        }
        ordered.sort(actionOrder());
        JsonArray actions = new JsonArray();
        for (JsonElement action : ordered) {
            action.getAsJsonObject().addProperty("index", actions.size());
            actions.add(action);
        }
        if (actions.size() == 0) {
            throw new IllegalStateException("No actions for " + q.getQueryType());
        }
        return actions;
    }

    /**
     * Pass and cancel last, then by kind. Keep suggested allocation order; only
     * UUID choices need a card-name/registration-order tie-break instead of hash order.
     */
    private Comparator<JsonElement> actionOrder() {
        return Comparator.comparingInt(Channel::passOrCancelLast)
            .thenComparing(action -> kind(action))
            .thenComparing(action -> uuidLabel(action))
            .thenComparingInt(this::uuidRegistration);
    }

    private static int passOrCancelLast(JsonElement action) {
        String kind = kind(action);
        return kind.equals("pass") || kind.equals("cancel") ? 1 : 0;
    }

    private static String kind(JsonElement action) {
        return action.getAsJsonObject().get("kind").getAsString();
    }

    private static boolean isUuid(JsonElement action) {
        return action.getAsJsonObject().get("response_type").getAsString().equals("uuid");
    }

    private static String uuidLabel(JsonElement action) {
        return isUuid(action) ? action.getAsJsonObject().get("label").getAsString() : "";
    }

    private int uuidRegistration(JsonElement action) {
        if (!isUuid(action)) {
            return 0;
        }
        UUID id = UUID.fromString(action.getAsJsonObject().get("value").getAsString());
        return objectOrder.getOrDefault(id, Integer.MAX_VALUE);
    }

    private static String message(PlayerQueryEvent q) {
        String message = q.getMessage();
        Map<String, Serializable> options = q.getOptions();
        if (message == null && options != null) {
            Serializable title = options.getOrDefault("title", "Choose an allocation");
            message = String.valueOf(options.getOrDefault("header", title));
        }
        return message;
    }

    private static void send(JsonObject observation) {
        System.out.println(GSON.toJson(object("type", "decision", "observation", observation)));
        System.out.flush();
    }

    private JsonObject readResponse() throws IOException {
        String answer = input.readLine();
        if (answer == null) {
            throw new EOFException("Controller disconnected");
        }
        JsonObject response = JsonParser.parseString(answer).getAsJsonObject();
        if (response.get("decision").getAsInt() != decision) {
            throw new IllegalArgumentException("Stale decision");
        }
        return response;
    }

    private static JsonObject selectedAction(JsonObject response, JsonArray actions) {
        int index = response.get("action").getAsInt();
        if (index < 0 || index >= actions.size()) {
            throw new IllegalArgumentException("Invalid action index");
        }
        return actions.get(index).getAsJsonObject();
    }

    static void add(JsonArray actions, String kind, String label, String type, Object value) {
        actions.add(object(
            "index", actions.size(),
            "kind", kind,
            "label", label,
            "response_type", type,
            "value", value));
    }

    /** Every action the bridge offers for one query type. Unlisted query types fail closed. */
    JsonArray actions(PlayerQueryEvent q, Game g, Player p, JsonObject view) {
        JsonArray out = new JsonArray();
        switch (q.getQueryType()) {
            case ASK:
                add(out, "yes", "Yes", "boolean", true);
                add(out, "no", "No / keep", "boolean", false);
                break;
            case SELECT:
                selectChoices(out, q, g, p, view);
                add(out, "pass", "Done / pass priority", "boolean", true);
                break;
            case PLAY_MANA:
                playable(out, g, p, true);
                break;
            case CHOOSE_ABILITY:
            case PICK_ABILITY:
                for (Ability a : q.getAbilities()) {
                    add(out, "ability", a.getRule(), "uuid", a.getId());
                }
                break;
            case PICK_TARGET:
                targets(out, q, g, p);
                if (!q.isRequired()) {
                    add(out, "cancel", "Done / cancel", "boolean", false);
                }
                break;
            case CHOOSE_MODE:
                for (Map.Entry<UUID, String> e : q.getModes().entrySet()) {
                    add(out, "mode", e.getValue(), "uuid", e.getKey());
                }
                break;
            case CHOOSE_CHOICE:
                choices(out, q);
                break;
            case AMOUNT:
            case PLAY_X_MANA:
                amounts(out, q);
                break;
            case MULTI_AMOUNT:
                amountAllocations(out, q);
                break;
            default:
                throw new IllegalStateException("Unsupported query: " + q.getQueryType());
        }
        return out;
    }

    /** SELECT is the priority prompt, unless its message asks for attackers or blockers. */
    private void selectChoices(JsonArray out, PlayerQueryEvent q, Game g, Player p, JsonObject view) {
        if (q.getMessage().startsWith("Select attackers")) {
            combatChoices(out, q, g, view, true);
            if (q.getOptions().containsKey(Constants.Option.SPECIAL_BUTTON)) {
                add(out, "attack_all", "Attack with all eligible creatures", "string", "special");
            }
        } else if (q.getMessage().startsWith("Select blockers")) {
            combatChoices(out, q, g, view, false);
        } else {
            playable(out, g, p, false);
        }
    }

    private void targets(JsonArray out, PlayerQueryEvent q, Game g, Player p) {
        Set<UUID> ids = new LinkedHashSet<>();
        if (q.getTargets() != null) {
            ids.addAll(q.getTargets());
        }
        if (q.getCards() != null) {
            ids.addAll(q.getCards());
        }
        if (q.getPerms() != null) {
            for (Permanent perm : q.getPerms()) {
                ids.add(perm.getId());
            }
        }
        for (UUID id : ids) {
            MageObject target = g.getObject(id);
            Player targetPlayer = g.getPlayer(id);
            if (targetPlayer != null) {
                add(out, "target", targetPlayer.getName(), "uuid", id);
            } else if (target != null) {
                // Fail closed: these fixtures have no search/look effects. Never
                // convert a hidden target into a named controller option.
                if (isHiddenFrom(p, g, id)) {
                    throw new IllegalStateException("Unsupported hidden target");
                }
                add(out, "target", target.getName(), "uuid", id);
            }
        }
    }

    private static void choices(JsonArray out, PlayerQueryEvent q) {
        if (q.getChoice().getKeyChoices().isEmpty()) {
            for (String c : q.getChoice().getChoices()) {
                add(out, "choice", c, "string", c);
            }
        } else {
            for (Map.Entry<String, String> e : q.getChoice().getKeyChoices().entrySet()) {
                add(out, "choice", e.getValue(), "string", e.getKey());
            }
        }
    }

    private static void amounts(JsonArray out, PlayerQueryEvent q) {
        if (q.getMax() - q.getMin() > 100) {
            throw new IllegalStateException("Unsupported amount range");
        }
        for (int i = q.getMin(); i <= q.getMax(); i++) {
            add(out, "amount", String.valueOf(i), "integer", i);
        }
    }

    /** XMage's suggested split first, then every other legal split, then optional cancel. */
    void amountAllocations(JsonArray out, PlayerQueryEvent q) {
        List<MultiAmountMessage> constraints = q.getMessages();
        if (constraints.size() > 16) {
            throw new IllegalStateException("Unsupported allocation dimensions");
        }
        List<Integer> defaults = MultiAmountType.prepareDefaultValues(constraints, q.getMin(), q.getMax());
        if (MultiAmountType.isGoodValues(defaults, constraints, q.getMin(), q.getMax())) {
            addAllocation(out, constraints, defaults);
        }
        enumerateAllocations(out, q, new ArrayList<>(), 0);
        if (Boolean.TRUE.equals(q.getOptions().get("canCancel"))) {
            add(out, "cancel", "Cancel allocation", "boolean", false);
        }
    }

    void addAllocation(JsonArray out, List<MultiAmountMessage> constraints, List<Integer> values) {
        StringJoiner response = new StringJoiner(" ");
        StringJoiner label = new StringJoiner("; ");
        for (int i = 0; i < values.size(); i++) {
            response.add(String.valueOf(values.get(i)));
            label.add(constraints.get(i).message + ": " + values.get(i));
        }
        String encoded = response.toString();
        for (JsonElement existing : out) {
            if (existing.getAsJsonObject().get("value").getAsString().equals(encoded)) {
                return;
            }
        }
        if (out.size() >= MAX_ALLOCATIONS) {
            throw new IllegalStateException("Unsupported allocation space: more than 4096 choices");
        }
        add(out, "allocation", label.toString(), "string", encoded);
    }

    /** Depth-first over each constraint's amounts, pruning partial sums that cannot reach [min, max]. */
    void enumerateAllocations(JsonArray out, PlayerQueryEvent q, List<Integer> values, int sum) {
        if (out.size() > MAX_ALLOCATIONS) {
            throw new IllegalStateException("Unsupported allocation space: more than 4096 choices");
        }
        List<MultiAmountMessage> constraints = q.getMessages();
        if (values.size() == constraints.size()) {
            if (MultiAmountType.isGoodValues(values, constraints, q.getMin(), q.getMax())) {
                addAllocation(out, constraints, values);
            }
            return;
        }
        MultiAmountMessage constraint = constraints.get(values.size());
        if (constraint.max - constraint.min > 100) {
            throw new IllegalStateException("Unsupported allocation amount range");
        }
        int remainingMin = 0;
        int remainingMax = 0;
        for (int i = values.size() + 1; i < constraints.size(); i++) {
            remainingMin += constraints.get(i).min;
            remainingMax += constraints.get(i).max;
        }
        for (int amount = constraint.min; amount <= constraint.max; amount++) {
            if (sum + amount + remainingMin > q.getMax() || sum + amount + remainingMax < q.getMin()) {
                continue;
            }
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
        if (offered instanceof Collection) {
            for (Object value : (Collection<?>) offered) {
                UUID id = (UUID) value;
                Permanent permanent = g.getPermanent(id);
                if (permanent == null) {
                    continue;
                }
                if (!attacking && g.getCombat().getGroups().stream().noneMatch(group -> group.canBlock(permanent, g))) {
                    continue;
                }
                String label = (attacking ? "Attack with " : "Choose blocker ") + publicName(view, id);
                add(out, attacking ? "attack" : "block", label, "uuid", id);
            }
        }
        Set<UUID> selected = attacking ? g.getCombat().getAttackers() : g.getCombat().getBlockers();
        for (UUID id : selected) {
            Permanent permanent = g.getPermanent(id);
            if (permanent != null && permanent.getControllerId().equals(q.getPlayerId())) {
                String label = "Remove " + publicName(view, id) + " from combat selection";
                add(out, attacking ? "remove_attacker" : "remove_blocker", label, "uuid", id);
            }
        }
    }

    void playable(JsonArray out, Game g, Player p, boolean manaOnly) {
        Set<UUID> seen = new HashSet<>();
        for (ActivatedAbility a : p.getPlayable(g, false)) {
            if (a.isManaActivatedAbility() != manaOnly) {
                continue;
            }
            UUID id = a.getSourceId();
            MageObject c = g.getObject(id);
            if (c == null || !seen.add(id)) {
                continue;
            }
            if (isHiddenFrom(p, g, id)) {
                throw new IllegalStateException("Hidden playable object");
            }
            add(out, manaOnly ? "mana" : (c.isLand(g) ? "land" : "cast"), c.getName(), "uuid", id);
        }
    }

    /** In a library, or in a hand other than {@code p}'s. */
    private static boolean isHiddenFrom(Player p, Game g, UUID id) {
        Zone zone = g.getState().getZone(id);
        return zone == Zone.LIBRARY || (zone == Zone.HAND && !p.getHand().contains(id));
    }
}
