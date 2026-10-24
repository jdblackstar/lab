package lab.xmage;

import com.google.gson.*;
import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.cards.Card;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.turn.CombatDamageStep;
import mage.game.turn.DeclareAttackersStep;
import mage.game.turn.DeclareBlockersStep;
import mage.game.turn.Phase;
import mage.game.turn.Step;
import mage.game.events.PlayerQueryEvent;
import mage.game.permanent.Permanent;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import mage.players.PlayerImpl;
import mage.target.Target;
import mage.util.RandomUtil;

import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

import static lab.xmage.PocMain.*;

/**
 * Continue a recorded game from a full_audit decision checkpoint.
 *
 * <p>XMage's own AIs resume copied games the same way: replace each seat, then
 * {@link Game#resume()}, which re-enters the saved step and asks the priority
 * player again. Java serialization keeps no call stack, so only decisions asked
 * directly by the turn structure (priority, declare attackers or blockers) can
 * be re-asked; a choice made mid-cast (targets, mana) cannot.
 */
final class Resume {
    private Resume() {}

    static final class Recording {
        final Path internal;
        final JsonObject manifest;
        final List<JsonObject> decisions = new ArrayList<>();
        Recording(Path run) throws IOException {
            internal = run.resolve("internal");
            manifest = JsonParser.parseString(Files.readString(internal.resolve("manifest.json"))).getAsJsonObject();
            if (!manifest.get("recording_mode").getAsString().equals("full_audit")) {
                throw new IllegalArgumentException("Resuming needs recording_mode=full_audit checkpoints");
            }
            for (String line : Files.readAllLines(internal.resolve("decisions.jsonl"), StandardCharsets.UTF_8)) {
                decisions.add(JsonParser.parseString(line).getAsJsonObject());
            }
        }
        JsonObject decision(int number) {
            JsonObject d = decisions.get(number - 1);
            if (d.get("decision").getAsInt() != number) throw new IllegalStateException("decisions.jsonl is not dense");
            return d;
        }
        RecordedGame saved(JsonObject decision) throws Exception {
            return (RecordedGame) readGame(internal.resolve(String.format("checkpoints/%06d.game.gz", decision.get("state_sequence").getAsInt())));
        }
        /**
         * GameImpl.readObject leaves some transient final fields (stackObjectsCheck)
         * null; the copy constructor, which XMage's AI simulations use, sets them all.
         */
        Game checkpoint(JsonObject decision) throws Exception {
            return saved(decision).copy();
        }
        /** Index into events.jsonl of the first event recorded after a state sequence. */
        int eventsBefore(int sequence) throws IOException {
            int count = 0;
            try (BufferedReader in = Files.newBufferedReader(internal.resolve("states.jsonl"), StandardCharsets.UTF_8)) {
                for (String line; (line = in.readLine()) != null; ) {
                    JsonObject state = JsonParser.parseString(line).getAsJsonObject();
                    if (state.get("sequence").getAsInt() >= sequence) break;
                    if (state.get("reason").getAsString().equals("event")) count++;
                }
            }
            return count;
        }
    }

    /**
     * Resume the saved step. A PRIORITY-part checkpoint resumes directly:
     * playPriority continues with the saved priority player and passed flags.
     *
     * <p>A PRE-part checkpoint was taken inside beginStep, at the declare
     * attackers or blockers choice. XMage's unpaused resume reruns all of
     * beginStep (refiring its begin event) and then resumes priority from the
     * chooser with stale passed flags; its paused resume finalizes the saved
     * selection without asking. Neither re-asks faithfully, so run the rest of
     * beginStep here, then enter priority as a fresh step does: passed flags
     * reset, active player first.
     */
    static void resume(Game game) {
        finishBeginStep(game);
        if (!game.checkIfGameIsOver()) game.resume();
    }

    /**
     * Engine events a resume itself emits before play continues: Turn.resumePlay
     * fires PHASE_CHANGED, and a PRIORITY-part resume refires the step's main event
     * from Step.priority (core rules only test main step events in replaceEvent).
     * Card implementations listening to a main step event would see it twice.
     */
    static List<String> resumePrelude(Step step, boolean priorityPart) {
        List<String> types = new ArrayList<>(List.of("PHASE_CHANGED"));
        if (priorityPart) {
            // CombatDamageStep.priority fires its own event first; core rules never read it.
            if (step instanceof CombatDamageStep) types.add("COMBAT_DAMAGE_STEP_PRIORITY");
            try {
                Field event = Step.class.getDeclaredField("stepEvent");
                event.setAccessible(true);
                types.add(String.valueOf(event.get(step)));
            } catch (ReflectiveOperationException e) { throw new IllegalStateException(e); }
        }
        return types;
    }

    /** Runs the rest of an interrupted beginStep; returns whether the checkpoint was in priority. */
    static boolean finishBeginStep(Game game) {
        Step step = game.getStep();
        if (step.getStepPart() == Step.StepPart.PRE) {
            if (step instanceof DeclareAttackersStep) {
                game.getCombat().selectAttackers(game);
            } else if (step instanceof DeclareBlockersStep) {
                game.getCombat().selectBlockers(game);
                if (!game.isPaused() && !game.executingRollback()) game.getCombat().acceptBlockers(game);
            } else {
                throw new IllegalArgumentException("Cannot resume inside " + step.getType() + " beginStep");
            }
            if (game.checkIfGameIsOver()) return false;
            // Turn.resumePlay walks the turn's phase and step lists, which a game
            // copy duplicates separately from currentPhase/currentStep; mark both.
            try {
                Field part = Step.class.getDeclaredField("stepPart");
                Field steps = Phase.class.getDeclaredField("steps");
                part.setAccessible(true);
                steps.setAccessible(true);
                part.set(step, Step.StepPart.PRIORITY);
                for (Object s : (List<?>) steps.get(game.getState().getTurn().getPhase(game.getTurnPhaseType()))) {
                    if (((Step) s).getType() == step.getType()) part.set(s, Step.StepPart.PRIORITY);
                }
            } catch (ReflectiveOperationException e) { throw new IllegalStateException(e); }
            game.getState().getPlayers().resetPassed();
            game.getState().setPriorityPlayerId(game.getActivePlayerId());
            return false;
        }
        return true;
    }

    /**
     * Decisions the turn structure asks directly, so resume() asks them again:
     * priority, and the first declare attackers or blockers ask. Once a creature
     * is selected, XMage finds no further available attackers and skips the ask.
     */
    static boolean resumable(JsonObject observation) {
        if (!observation.get("query_type").getAsString().equals("SELECT")) return false;
        for (JsonElement a : observation.getAsJsonArray("actions")) {
            if (a.getAsJsonObject().get("kind").getAsString().startsWith("remove_")) return false;
        }
        return true;
    }

    // ---------------------------------------------------------------- replay

    /**
     * Resume at a decision and answer with the recorded responses. Every later
     * observation and the final result must match the original game exactly.
     */
    static JsonObject replay(Recording rec, int number, Path out) throws Exception {
        JsonObject start = rec.decision(number);
        // Keep the RecordedGame type so the replay logs engine events too.
        RecordedGame game = new RecordedGame(rec.saved(start));
        StringBuilder answers = new StringBuilder();
        for (JsonObject d : rec.decisions.subList(number - 1, rec.decisions.size())) answers.append(JSON.toJson(d.get("response"))).append('\n');
        Channel channel = new Channel(new BufferedReader(new StringReader(answers.toString())),
            new PrintStream(OutputStream.nullOutputStream()));
        channel.decision = number - 1;
        List<UUID> seats = new ArrayList<>();
        for (JsonElement id : rec.manifest.getAsJsonArray("players")) seats.add(UUID.fromString(id.getAsString()));
        for (UUID id : seats) channel.objectOrder.put(id, channel.objectOrder.size());
        for (UUID id : seats) {
            BridgePlayer saved = (BridgePlayer) game.getPlayer(id);
            List<Map.Entry<UUID, Integer>> order = new ArrayList<>(saved.cardOrder.entrySet());
            order.sort(Map.Entry.comparingByValue());
            for (Map.Entry<UUID, Integer> e : order) channel.objectOrder.put(e.getKey(), channel.objectOrder.size());
            game.getState().getPlayers().put(id, new BridgePlayer(saved, channel));
        }
        game.addPlayerQueryEventListener(e -> { if (e.getQueryType() != PlayerQueryEvent.QueryType.PERSONAL_MESSAGE) channel.pending = e; });
        JsonObject report = object("decision", number, "query_type", start.getAsJsonObject("observation").get("query_type"),
            "message", start.getAsJsonObject("observation").get("message"), "resumable", resumable(start.getAsJsonObject("observation")));
        long prelude = -1;
        List<String> expectedPrelude = List.of();
        try (Recorder recorder = new Recorder(out, game, "benchmark")) {
            channel.recorder = recorder;
            game.recorder = recorder;
            try {
                Step step = game.getStep();
                boolean priorityPart = finishBeginStep(game);
                prelude = recorder.eventCount;
                expectedPrelude = resumePrelude(step, priorityPart);
                if (!game.checkIfGameIsOver()) game.resume();
            } catch (RuntimeException e) {
                report.addProperty("exception", String.valueOf(e.getCause() != null ? e.getCause() : e));
            }
        }
        List<String> replayed = Files.readAllLines(out.resolve("internal/decisions.jsonl"), StandardCharsets.UTF_8);
        int compared = 0;
        String firstMismatch = null;
        Map<String, String> fresh = new HashMap<>();
        for (String line : replayed) {
            JsonObject got = JsonParser.parseString(line).getAsJsonObject();
            JsonObject want = rec.decision(got.get("decision").getAsInt());
            JsonObject g = got.getAsJsonObject("observation").deepCopy(), w = want.getAsJsonObject("observation").deepCopy();
            stripCounters(g); stripCounters(w);
            g = blankShortIds(g); w = blankShortIds(w);
            g = renameFresh(w, g, fresh);
            if (g == null) { firstMismatch = "decision " + w.get("decision") + ": object IDs do not correspond one-to-one"; break; }
            if (!g.equals(w)) { firstMismatch = describe(w, g); break; }
            compared++;
        }
        // Every engine event after the checkpoint must recur in order: a step rerun
        // or a doubled trigger can leave every observation unchanged.
        List<String> originalEvents = Files.readAllLines(rec.internal.resolve("events.jsonl"), StandardCharsets.UTF_8);
        List<String> replayedEvents = new ArrayList<>(Files.readAllLines(out.resolve("internal/events.jsonl"), StandardCharsets.UTF_8));
        String preludeMismatch = null;
        for (String type : expectedPrelude) {
            int at = (int) prelude;
            String got = at >= 0 && at < replayedEvents.size() ? JsonParser.parseString(replayedEvents.get(at)).getAsJsonObject().get("type").getAsString() : null;
            if (!type.equals(got)) { preludeMismatch = "resume prelude: expected " + type + ", got " + got; break; }
            replayedEvents.remove(at);
        }
        int offset = rec.eventsBefore(start.get("state_sequence").getAsInt()), eventsMatched = 0;
        String firstEventMismatch = preludeMismatch;
        for (; preludeMismatch == null && eventsMatched < Math.max(replayedEvents.size(), originalEvents.size() - offset); eventsMatched++) {
            if (eventsMatched >= replayedEvents.size() || offset + eventsMatched >= originalEvents.size()) {
                firstEventMismatch = "event " + eventsMatched + ": streams differ in length";
                break;
            }
            JsonObject w = JsonParser.parseString(originalEvents.get(offset + eventsMatched)).getAsJsonObject();
            JsonObject g = renameFresh(w, JsonParser.parseString(replayedEvents.get(eventsMatched)).getAsJsonObject(), fresh);
            if (g == null || !g.equals(w)) {
                firstEventMismatch = "event " + eventsMatched + ": expected " + w + ", got " + JSON.toJson(replayedEvents.get(eventsMatched));
                break;
            }
        }
        report.addProperty("expected_events", originalEvents.size() - offset);
        report.addProperty("matched_events", eventsMatched);
        report.addProperty("first_event_mismatch", firstEventMismatch);
        report.addProperty("fresh_ids_mapped", fresh.size());
        JsonObject original = JsonParser.parseString(Files.readString(rec.internal.resolve("result.json"))).getAsJsonObject();
        boolean sameResult = game.hasEnded() && Objects.equals(game.getWinner(), original.get("winner").getAsString());
        report.addProperty("expected_decisions", rec.decisions.size() - number + 1);
        report.addProperty("matched_decisions", compared);
        report.addProperty("first_mismatch", firstMismatch);
        report.addProperty("winner", game.getWinner());
        report.addProperty("same_result", sameResult);
        report.addProperty("faithful", firstMismatch == null && firstEventMismatch == null && sameResult
            && compared == rec.decisions.size() - number + 1);
        return report;
    }

    /**
     * Engine bookkeeping in the view that a resumed game legitimately changes;
     * the renderer shows none of it.
     * <ul>
     * <li>gameCycle counts applyEffects() calls; resuming adds one.
     * <li>statesSavedSize counts rollback bookmarks, which are transient.
     * <li>totalEffectsCount: keyword singletons such as FlyingAbility readResolve
     * to the new JVM's instance, but their effects (FlyingEffect) do not, so once
     * the keyword is granted again the idempotent restriction is registered twice.
     * </ul>
     */
    static void stripCounters(JsonObject observation) {
        stripClock(observation);
        JsonObject view = observation.getAsJsonObject("view");
        view.remove("gameCycle");
        view.remove("totalEffectsCount");
        for (JsonElement p : view.getAsJsonArray("players")) p.getAsJsonObject().remove("statesSavedSize");
    }

    static final java.util.regex.Pattern UUID_TEXT = java.util.regex.Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");

    /**
     * XMage's "[abc]" short IDs repeat the first three hex digits of a UUID that
     * the observation also carries in full; they collide by chance (one in 4096),
     * so renaming them is unsafe. Blank them; the full IDs are still compared.
     */
    static JsonObject blankShortIds(JsonObject o) {
        return JsonParser.parseString(JSON.toJson(o).replaceAll("\\[[0-9a-f]{3}\\]", "[id]")).getAsJsonObject();
    }

    /**
     * Objects created after the checkpoint (spells on the stack, tokens) get
     * random UUIDs, so pair the replay's IDs with the original's by position and
     * rename them. The pairing must stay a bijection across the whole replay;
     * returns null if it cannot.
     */
    static JsonObject renameFresh(JsonObject want, JsonObject got, Map<String, String> fresh) {
        String w = JSON.toJson(canonical(want)), g = JSON.toJson(canonical(got));
        List<String> wantIds = new ArrayList<>(), gotIds = new ArrayList<>();
        for (java.util.regex.Matcher m = UUID_TEXT.matcher(w); m.find(); ) wantIds.add(m.group());
        for (java.util.regex.Matcher m = UUID_TEXT.matcher(g); m.find(); ) gotIds.add(m.group());
        if (wantIds.size() == gotIds.size()) {
            for (int i = 0; i < gotIds.size(); i++) {
                String from = gotIds.get(i), to = wantIds.get(i);
                if (from.equals(to)) continue;
                String known = fresh.get(from);
                if (known == null) {
                    if (fresh.containsValue(to)) return null;
                    fresh.put(from, to);
                } else if (!known.equals(to)) return null;
            }
        }
        g = JSON.toJson(got);
        for (Map.Entry<String, String> e : fresh.entrySet()) g = g.replace(e.getKey(), e.getValue());
        return JsonParser.parseString(g).getAsJsonObject();
    }

    /**
     * Order object members by their content with IDs blanked, so maps keyed by
     * fresh UUIDs (the stack) list the same objects in the same order in both
     * games and positional ID pairing lines up.
     */
    static JsonElement canonical(JsonElement e) {
        if (e.isJsonArray()) {
            JsonArray out = new JsonArray();
            for (JsonElement x : e.getAsJsonArray()) out.add(canonical(x));
            return out;
        }
        if (!e.isJsonObject()) return e;
        List<Map.Entry<String, JsonElement>> entries = new ArrayList<>();
        for (Map.Entry<String, JsonElement> m : e.getAsJsonObject().entrySet()) entries.add(Map.entry(m.getKey(), canonical(m.getValue())));
        entries.sort(Comparator.comparing(m -> UUID_TEXT.matcher(m.getKey() + JSON.toJson(m.getValue())).replaceAll("U")));
        JsonObject out = new JsonObject();
        for (Map.Entry<String, JsonElement> m : entries) out.add(m.getKey(), m.getValue());
        return out;
    }

    static String describe(JsonObject want, JsonObject got) {
        if (!want.get("decision").equals(got.get("decision"))) return "decision number";
        if (!want.get("query_type").equals(got.get("query_type")) || !want.get("message").equals(got.get("message"))) {
            return "decision " + want.get("decision") + ": expected " + want.get("query_type") + " '" + want.get("message")
                + "', got " + got.get("query_type") + " '" + got.get("message") + "'";
        }
        if (!want.get("actions").equals(got.get("actions"))) return "decision " + want.get("decision") + ": actions differ";
        for (String key : want.getAsJsonObject("view").keySet()) {
            if (!Objects.equals(want.getAsJsonObject("view").get(key), got.getAsJsonObject("view").get(key))) {
                return "decision " + want.get("decision") + ": view field " + key;
            }
        }
        return "decision " + want.get("decision") + ": observation differs";
    }

    // --------------------------------------------------------------- rollout

    /**
     * Seat used for playouts. Combat and every non-priority choice use XMage's
     * native AI heuristics; priority follows the chosen policy. The actor's first
     * priority answer is forced to the candidate action being evaluated.
     */
    static final class RolloutPlayer extends ComputerPlayer7 {
        final String policy;
        final Random rng;
        String forced;
        int windowActions, actions;
        String window = "";

        RolloutPlayer(Player original, String policy, int skill, Random rng) {
            super(original.getName(), RangeOfInfluence.ALL, skill);
            setPlayerId(this, original.getId());
            restore(original);
            human = false;
            setMatchPlayer(original.getMatchPlayer());
            this.policy = policy;
            this.rng = rng;
        }
        RolloutPlayer(RolloutPlayer p) {
            super(p); policy = p.policy; rng = p.rng; forced = p.forced; windowActions = p.windowActions; window = p.window; actions = p.actions;
        }

        /** A forced combat key ("attack|..." or "block|...") applies to the step's first ask. */
        @Override public void selectAttackers(Game game, UUID attackingPlayerId) {
            if (forced == null || !forced.startsWith("attack|")) { super.selectAttackers(game, attackingPlayerId); return; }
            String key = forced;
            forced = null;
            UUID defender = game.getOpponents(playerId).iterator().next();
            for (String id : key.substring("attack|".length()).split(",")) {
                if (!id.isEmpty()) declareAttacker(UUID.fromString(id), defender, game, false);
            }
        }

        @Override public void selectBlockers(Ability source, Game game, UUID defendingPlayerId) {
            if (forced == null || !forced.startsWith("block|")) { super.selectBlockers(source, game, defendingPlayerId); return; }
            String key = forced;
            forced = null;
            for (String pair : key.substring("block|".length()).split(",")) {
                if (pair.isEmpty()) continue;
                String[] ids = pair.split(">");
                declareBlocker(playerId, UUID.fromString(ids[0]), UUID.fromString(ids[1]), game);
            }
        }
        @Override public RolloutPlayer copy() { return new RolloutPlayer(this); }

        @Override public boolean priority(Game game) {
            if (forced != null) {
                String key = forced;
                forced = null;
                return apply(game, key);
            }
            if (policy.equals("mad")) return super.priority(game);
            String now = game.getTurnNum() + ":" + game.getTurnStepType() + ":" + game.getStack().size();
            if (!now.equals(window)) { window = now; windowActions = 0; }
            List<ActivatedAbility> options = playable(game);
            // Guard against free repeatable abilities looping one priority window.
            if (options.isEmpty() || windowActions >= 8) { pass(game); return false; }
            ActivatedAbility pick;
            if (policy.equals("random")) {
                int i = rng.nextInt(options.size() + 1);
                if (i == options.size()) { pass(game); return false; }
                pick = options.get(i);
            } else {
                List<ActivatedAbility> lands = new ArrayList<>();
                for (ActivatedAbility a : options) if (a.getSourceObject(game) != null && a.getSourceObject(game).isLand(game) && game.getState().getZone(a.getSourceId()) == Zone.HAND) lands.add(a);
                pick = !lands.isEmpty() ? lands.get(rng.nextInt(lands.size())) : options.get(rng.nextInt(options.size()));
            }
            windowActions++;
            actions++;
            activateAbility(pick, game);
            return true;
        }

        /** Non-mana playables, one per source, in getPlayable order. */
        List<ActivatedAbility> playable(Game game) {
            List<ActivatedAbility> out = new ArrayList<>();
            Set<UUID> seen = new HashSet<>();
            for (ActivatedAbility a : getPlayable(game, false)) {
                if (a.isManaActivatedAbility() || !seen.add(a.getSourceId())) continue;
                out.add(a);
            }
            return out;
        }

        /**
         * Every complete priority action: each playable ability with its modes
         * and targets chosen (XMage's AI option expansion), then passing.
         */
        Map<String, Ability> candidates(Game game) {
            // Sorted by key: XMage's option expansion order varies between runs.
            Map<String, Ability> all = new TreeMap<>();
            for (ActivatedAbility a : getPlayable(game, false)) {
                if (a.isManaActivatedAbility()) continue;
                List<Ability> options = getPlayableOptions(a, game);
                for (Ability option : options.isEmpty() ? List.<Ability>of(a) : options) all.putIfAbsent(key(option), option);
            }
            // Same-named cards in hand are interchangeable (permanents may differ):
            // keep the lowest-keyed copy of each such action.
            Map<String, Ability> ordered = new LinkedHashMap<>();
            Set<String> seenInHand = new HashSet<>();
            for (Map.Entry<String, Ability> e : all.entrySet()) {
                String key = e.getKey();
                UUID source = e.getValue().getSourceId();
                String[] parts = key.split("\\|", 3);
                String targets = parts.length > 2 ? parts[2] : "";
                if (game.getState().getZone(source) == Zone.HAND && !seenInHand.add(game.getObject(source).getName() + targets)) continue;
                ordered.put(key, e.getValue());
            }
            ordered.put("pass", null);
            return ordered;
        }

        /** Every attacker subset, or every blocker assignment, as candidate keys with ID labels. */
        Map<String, String> combatCandidates(Game game, boolean attacking) {
            Map<String, String> out = new LinkedHashMap<>();
            if (attacking) {
                List<Permanent> able = getAvailableAttackers(game);
                able.sort(Comparator.comparing(p -> p.getId().toString()));
                if (able.size() > 6) throw new IllegalArgumentException("More than 6 possible attackers");
                for (int mask = 0; mask < 1 << able.size(); mask++) {
                    StringJoiner ids = new StringJoiner(",");
                    for (int i = 0; i < able.size(); i++) if ((mask & 1 << i) != 0) ids.add(able.get(i).getId().toString());
                    out.put("attack|" + ids, mask == 0 ? "No attack" : "Attack with " + ids.toString().replace(",", ", "));
                }
                return out;
            }
            List<Permanent> blockers = new ArrayList<>();
            for (Permanent p : getAvailableBlockers(game)) {
                if (game.getCombat().getGroups().stream().anyMatch(g -> g.canBlock(p, game))) blockers.add(p);
            }
            blockers.sort(Comparator.comparing(p -> p.getId().toString()));
            List<UUID> attackers = new ArrayList<>(game.getCombat().getAttackers());
            attackers.sort(Comparator.comparing(UUID::toString));
            List<String> keys = new ArrayList<>(List.of("")), labels = new ArrayList<>(List.of(""));
            for (Permanent b : blockers) {
                List<String> nextKeys = new ArrayList<>(), nextLabels = new ArrayList<>();
                for (int i = 0; i < keys.size(); i++) {
                    nextKeys.add(keys.get(i)); nextLabels.add(labels.get(i));
                    for (UUID a : attackers) {
                        if (!game.getCombat().findGroup(a).canBlock(b, game)) continue;
                        nextKeys.add(keys.get(i) + (keys.get(i).isEmpty() ? "" : ",") + b.getId() + ">" + a);
                        nextLabels.add(labels.get(i) + (labels.get(i).isEmpty() ? "" : "; ") + b.getId() + " blocks " + a);
                    }
                }
                keys = nextKeys; labels = nextLabels;
                if (keys.size() > 64) throw new IllegalArgumentException("More than 64 blocker assignments");
            }
            for (int i = 0; i < keys.size(); i++) out.put("block|" + keys.get(i), labels.get(i).isEmpty() ? "No blocks" : labels.get(i));
            return out;
        }

        boolean apply(Game game, String key) {
            if (key.equals("pass")) { pass(game); return false; }
            Ability option = candidates(game).get(key);
            if (option == null) throw new IllegalStateException("Candidate is not playable after resume: " + key);
            activateAbility((ActivatedAbility) option, game);
            return true;
        }
    }

    /** Source, ability, selected modes and target IDs: stable across game copies. */
    static String key(Ability option) {
        StringJoiner key = new StringJoiner("|");
        key.add(option.getSourceId().toString()).add(option.getOriginalId().toString());
        for (UUID modeId : option.getModes().getSelectedModes()) {
            if (option.isModal()) key.add("mode=" + modeId);
            for (Target t : option.getModes().get(modeId).getTargets()) for (UUID id : t.getTargets()) key.add(id.toString());
        }
        return key.toString();
    }

    /** Candidate text with object and player IDs inline, so a renderer can alias them like the board. */
    static String label(Ability option, Game game) {
        MageObject source = game.getObject(option.getSourceId());
        Zone zone = game.getState().getZone(option.getSourceId());
        String text = (zone == Zone.HAND && source != null && source.isLand(game) ? "Play " : zone == Zone.HAND ? "Cast " : "Activate ")
            + option.getSourceId() + (zone == Zone.HAND ? "" : ": " + option.getRule());
        List<String> parts = new ArrayList<>();
        for (UUID modeId : option.getModes().getSelectedModes()) {
            if (option.isModal()) parts.add("mode " + option.getModes().get(modeId).getEffects().getText(option.getModes().get(modeId)));
            for (Target t : option.getModes().get(modeId).getTargets()) for (UUID id : t.getTargets()) parts.add(id.toString());
        }
        return parts.isEmpty() ? text : text + " -> " + String.join(", ", parts);
    }

    /** Replace inline IDs with player or object names. */
    static String named(String withIds, Game game) {
        return UUID_TEXT.matcher(withIds).replaceAll(m -> {
            UUID id = UUID.fromString(m.group());
            Player player = game.getPlayer(id);
            MageObject object = game.getObject(id);
            return java.util.regex.Matcher.quoteReplacement(player != null ? player.getName() : object != null ? object.getName() : m.group());
        });
    }

    static void setPlayerId(PlayerImpl player, UUID id) {
        try {
            Field f = PlayerImpl.class.getDeclaredField("playerId");
            f.setAccessible(true);
            f.set(player, id);
        } catch (ReflectiveOperationException e) { throw new IllegalStateException(e); }
    }

    /**
     * Resample what the actor cannot see: shuffle the opponent's hand into their
     * library and redraw it, then shuffle both libraries (the same
     * determinization as XMage's MCTS AI).
     */
    static void determinize(Game game, UUID actor) {
        for (Player p : game.getState().getPlayers().values()) {
            if (!p.getId().equals(actor)) {
                int size = p.getHand().size();
                p.getLibrary().addAll(p.getHand().getCards(game), game);
                p.getHand().clear();
                p.getLibrary().shuffle();
                for (int i = 0; i < size; i++) {
                    Card c = p.getLibrary().drawFromTop(game);
                    c.setZone(Zone.HAND, game);
                    p.getHand().add(c);
                }
            } else p.getLibrary().shuffle();
        }
    }

    static JsonObject rollout(Recording rec, int number, Map<String, String> opt) throws Exception {
        JsonObject start = rec.decision(number);
        JsonObject observation = start.getAsJsonObject("observation");
        if (!resumable(observation)) {
            throw new IllegalArgumentException("Decision " + number + " cannot be resumed: " + observation.get("query_type") + " '" + observation.get("message") + "'");
        }
        String message = observation.get("message").getAsString();
        boolean attacking = message.startsWith("Select attackers"), blocking = message.startsWith("Select blockers");
        int playouts = Integer.parseInt(opt.getOrDefault("playouts", "32"));
        long seed = Long.parseLong(opt.getOrDefault("seed", "1"));
        String policy = opt.getOrDefault("policy", "greedy");
        int skill = Integer.parseInt(opt.getOrDefault("skill", "1"));
        int turnCap = Integer.parseInt(opt.getOrDefault("turn-cap", "20"));
        boolean hidden = !opt.getOrDefault("determinize", "true").equals("false");
        if (!Arrays.asList("greedy", "random", "mad").contains(policy)) throw new IllegalArgumentException("Unknown policy: " + policy);
        UUID actor = UUID.fromString(observation.get("player_id").getAsString());
        Game base = rec.checkpoint(start);
        base.getOptions().stopOnTurn = base.getTurnNum() + turnCap;
        base.getOptions().stopAtStep = PhaseStep.UNTAP;
        // Enumerate on a throwaway copy: getPlayable simulates and must not touch base.
        Game probe = base.copy();
        for (Player p : new ArrayList<>(probe.getState().getPlayers().values())) {
            probe.getState().getPlayers().put(p.getId(), new RolloutPlayer(p, policy, skill, new Random(0)));
        }
        RolloutPlayer enumerator = (RolloutPlayer) probe.getPlayer(actor);
        // Rollout seats are rebuilt with PlayerImpl.restore(), which copies less
        // than the bridge seat's full copy; check the actor's game is unchanged.
        JsonObject recordedView = observation.deepCopy(), seatView = observation.deepCopy();
        seatView.add("view", playerView(probe, actor));
        stripCounters(recordedView); stripCounters(seatView);
        // Who controls a seat (isHuman, user preferences) is not game state.
        for (JsonObject v : List.of(recordedView, seatView)) {
            for (JsonElement p : v.getAsJsonObject("view").getAsJsonArray("players")) {
                p.getAsJsonObject().remove("isHuman");
                p.getAsJsonObject().remove("userData");
            }
        }
        // Candidate keys and labels; the engine enumerates complete actions.
        Map<String, String> candidates = new LinkedHashMap<>();
        Map<String, Ability> options = new LinkedHashMap<>();
        Set<String> engineSources = new TreeSet<>(), bridgeSources = new TreeSet<>();
        if (attacking || blocking) {
            candidates.putAll(enumerator.combatCandidates(probe, attacking));
            for (Permanent p : attacking ? enumerator.getAvailableAttackers(probe) : enumerator.getAvailableBlockers(probe)) {
                if (attacking || probe.getCombat().getGroups().stream().anyMatch(g -> g.canBlock(p, probe))) engineSources.add(p.getId().toString());
            }
        } else {
            options.putAll(enumerator.candidates(probe));
            for (Map.Entry<String, Ability> e : options.entrySet()) {
                candidates.put(e.getKey(), e.getValue() == null ? "Pass priority" : label(e.getValue(), probe));
            }
            for (ActivatedAbility a : enumerator.playable(probe)) engineSources.add(a.getSourceId().toString());
        }
        for (JsonElement e : observation.getAsJsonArray("actions")) {
            JsonObject a = e.getAsJsonObject();
            if (a.get("response_type").getAsString().equals("uuid")) bridgeSources.add(a.get("value").getAsString());
        }
        List<String> viewDiff = new ArrayList<>();
        diffPaths(recordedView, seatView, "", viewDiff);
        JsonObject checks = object("seat_view_matches", viewDiff.isEmpty(), "seat_view_diff", viewDiff,
            "sources_match", engineSources.equals(bridgeSources));
        List<String> keys = new ArrayList<>(candidates.keySet());
        List<Integer> chosen = new ArrayList<>();
        if (opt.containsKey("candidates")) for (String s : opt.get("candidates").split(",")) chosen.add(Integer.parseInt(s));
        else for (int i = 0; i < keys.size(); i++) chosen.add(i);
        JsonArray results = new JsonArray();
        for (int index : chosen) {
            String key = keys.get(index);
            Ability option = options.get(key);
            String label = candidates.get(key);
            // The bridge offers one priority action per source; record which one this refines.
            Integer bridgeIndex = null;
            for (JsonElement e : attacking || blocking ? new JsonArray() : observation.getAsJsonArray("actions")) {
                JsonObject a = e.getAsJsonObject();
                if (option == null ? a.get("kind").getAsString().equals("pass")
                    : a.get("response_type").getAsString().equals("uuid") && a.get("value").getAsString().equals(option.getSourceId().toString())) {
                    bridgeIndex = a.get("index").getAsInt();
                    break;
                }
            }
            StringBuilder outcomes = new StringBuilder();
            int wins = 0, losses = 0, draws = 0, errors = 0;
            double turns = 0, actorActions = 0, opponentActions = 0, actorLife = 0, opponentLife = 0;
            long started = System.nanoTime();
            for (int i = 0; i < playouts; i++) {
                // Common random numbers: playout i samples the same hidden world for every candidate.
                long playoutSeed = seed * 1_000_003L + i;
                RandomUtil.setSeed(playoutSeed);
                Game sim = base.copy();
                for (Player p : new ArrayList<>(sim.getState().getPlayers().values())) {
                    RolloutPlayer r = new RolloutPlayer(p, policy, skill, new Random(playoutSeed ^ p.getName().hashCode()));
                    if (p.getId().equals(actor)) r.forced = key;
                    sim.getState().getPlayers().put(p.getId(), r);
                }
                if (hidden) determinize(sim, actor);
                try {
                    resume(sim);
                } catch (RuntimeException e) {
                    errors++;
                    outcomes.append('E');
                    continue;
                }
                Player me = sim.getPlayer(actor);
                if (sim.getTotalErrorsCount() > base.getTotalErrorsCount()) { errors++; outcomes.append('E'); continue; }
                if (me.hasWon()) { wins++; outcomes.append('W'); }
                else if (me.hasLost()) { losses++; outcomes.append('L'); }
                else { draws++; outcomes.append('D'); }
                turns += sim.getTurnNum() - base.getTurnNum();
                for (Player p : sim.getPlayers().values()) {
                    if (p.getId().equals(actor)) { actorActions += ((RolloutPlayer) p).actions; actorLife += p.getLife(); }
                    else { opponentActions += ((RolloutPlayer) p).actions; opponentLife += p.getLife(); }
                }
            }
            int decided = wins + losses + draws;
            results.add(object("candidate", index, "label", named(label, probe), "ref_label", label, "bridge_action", bridgeIndex,
                "outcomes", outcomes.toString(),
                "wins", wins, "losses", losses, "draws", draws, "errors", errors,
                "win_rate", decided == 0 ? null : (wins + 0.5 * draws) / decided,
                "mean_turns", decided == 0 ? null : turns / decided,
                "mean_actions", decided == 0 ? null : object("actor", actorActions / decided, "opponent", opponentActions / decided),
                "mean_final_life", decided == 0 ? null : object("actor", actorLife / decided, "opponent", opponentLife / decided),
                "seconds", (System.nanoTime() - started) / 1e9));
        }
        return object("decision", number, "actor", observation.get("player"), "turn", observation.getAsJsonObject("view").get("turn"),
            "step", observation.getAsJsonObject("view").get("step"), "message", observation.get("message"),
            "selected", start.getAsJsonObject("selected").get("index"), "policy", policy, "skill", skill,
            "playouts", playouts, "seed", seed, "turn_cap", turnCap, "determinize", hidden, "checks", checks, "candidates", results);
    }

    /** Up to ten JSON paths where two values differ. */
    static void diffPaths(JsonElement a, JsonElement b, String path, List<String> out) {
        if (out.size() >= 10 || Objects.equals(a, b)) return;
        if (a != null && b != null && a.isJsonObject() && b.isJsonObject()) {
            Set<String> keys = new TreeSet<>(a.getAsJsonObject().keySet());
            keys.addAll(b.getAsJsonObject().keySet());
            for (String k : keys) diffPaths(a.getAsJsonObject().get(k), b.getAsJsonObject().get(k), path + "." + k, out);
        } else if (a != null && b != null && a.isJsonArray() && b.isJsonArray() && a.getAsJsonArray().size() == b.getAsJsonArray().size()) {
            for (int i = 0; i < a.getAsJsonArray().size(); i++) diffPaths(a.getAsJsonArray().get(i), b.getAsJsonArray().get(i), path + "[" + i + "]", out);
        } else out.add(path + ": " + a + " -> " + b);
    }

    static void deleteTree(Path root) throws IOException {
        try (var paths = Files.walk(root)) {
            for (Path p : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(p);
        }
    }

    static void main(String[] args) throws Exception {
        Recording rec = new Recording(Paths.get(args[1]));
        if (args[0].equals("replay")) {
            // replay <run> <decision>..., replay <run> all, or replay <run> resumable
            List<Integer> numbers = new ArrayList<>();
            if (args[2].equals("all") || args[2].equals("resumable")) {
                for (JsonObject d : rec.decisions) {
                    if (args[2].equals("all") || resumable(d.getAsJsonObject("observation"))) numbers.add(d.get("decision").getAsInt());
                }
            } else for (int i = 2; i < args.length; i++) numbers.add(Integer.parseInt(args[i]));
            for (int n : numbers) {
                Path out = Files.createTempDirectory("xmage-replay-");
                JsonObject report = replay(rec, n, out);
                // Keep the replayed recording only when it disagrees, for inspection.
                if (report.get("faithful").getAsBoolean()) deleteTree(out);
                else report.addProperty("replay_output", out.toString());
                System.out.println(JSON.toJson(report));
                System.out.flush();
            }
        } else {
            Map<String, String> opt = options(args, 3, "playouts", "seed", "policy", "skill", "turn-cap", "determinize", "candidates");
            System.out.println(JSON.toJson(rollout(rec, Integer.parseInt(args[2]), opt)));
        }
    }
}
