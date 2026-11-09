package lab.xmage;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.constants.RangeOfInfluence;
import mage.game.GameOptions;
import mage.game.TwoPlayerMatch;
import mage.game.events.PlayerQueryEvent;
import mage.game.match.MatchOptions;
import mage.game.match.MatchPlayer;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import mage.util.RandomUtil;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static lab.xmage.Json.GSON;
import static lab.xmage.Json.object;

/**
 * A headless adapter with limited choice coverage. XMage performs all game rules.
 *
 * <pre>
 * cards &lt;name&gt;...                       resolve names against the pinned card catalog
 * verify &lt;output&gt;                       restore and audit a full_audit recording
 * inspect &lt;checkpoint.game.gz&gt;          print one checkpoint's engine summary
 * &lt;output&gt; &lt;seed&gt; &lt;deck_a&gt; &lt;deck_b&gt; [--recording-mode=full_audit|benchmark]
 *     [--starting-player=player_a|player_b] [--engine-ai-seat=none|player_a|player_b]
 * </pre>
 */
public final class PocMain {
    static final String REVISION = "afab346e06c4960882cf148acc57754c1c50a007";

    private PocMain() {
    }

    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "cards":
                printCards(args);
                return;
            case "verify":
                CheckpointVerifier.verify(Paths.get(args[1]));
                return;
            case "inspect":
                System.out.println(GSON.toJson(GameJson.summary(Checkpoints.read(Paths.get(args[1])))));
                return;
            default:
                playGame(args);
        }
    }

    private static void printCards(String[] args) throws Exception {
        JsonArray requested = new JsonArray();
        for (int i = 1; i < args.length; i++) {
            Card c = CardCatalog.createCard(args[i], UUID.randomUUID());
            requested.add(object(
                "requested_name", args[i],
                "name", c.getName(),
                "class", c.getClass().getName(),
                "set", c.getExpansionSetCode(),
                "card_number", c.getCardNumber()));
        }
        System.out.println(GSON.toJson(object(
            "xmage_revision", REVISION,
            "catalog_names", CardCatalog.DEFINITIONS.size(),
            "cards", requested)));
    }

    /** Named --name=value options after the four positional game arguments. */
    static Map<String, String> options(String[] args, int start, String... known) {
        Map<String, String> options = new HashMap<>();
        for (int i = start; i < args.length; i++) {
            if (!args[i].startsWith("--") || !args[i].contains("=")) {
                throw new IllegalArgumentException("Expected --name=value option: " + args[i]);
            }
            String[] pair = args[i].substring(2).split("=", 2);
            if (!Arrays.asList(known).contains(pair[0])) {
                throw new IllegalArgumentException("Unknown option: --" + pair[0]);
            }
            if (options.put(pair[0], pair[1]) != null) {
                throw new IllegalArgumentException("Duplicate option: --" + pair[0]);
            }
        }
        return options;
    }

    private static void playGame(String[] args) throws Exception {
        Path output = Paths.get(args[0]);
        long seed = Long.parseLong(args[1]);
        Map<String, String> bridgeOptions = options(args, 4, "recording-mode", "starting-player", "engine-ai-seat");
        String mode = recordingMode(bridgeOptions);
        String startingPlayer = startingPlayer(bridgeOptions);
        RandomUtil.setSeed(seed);
        Channel channel = new Channel();
        RecordedGame game = new RecordedGame();
        GameOptions options = new GameOptions();
        options.rollbackTurnsAllowed = false;
        game.setGameOptions(options);
        String aiSeat = engineAiSeat(bridgeOptions);
        Player a = seat("player_a", aiSeat, channel, seed);
        Player b = seat("player_b", aiSeat, channel, seed);
        List<UUID> bridgePlayers = new ArrayList<>();
        for (Player p : Arrays.asList(a, b)) {
            if (p instanceof BridgePlayer) {
                bridgePlayers.add(p.getId());
            }
        }
        Path deckFileA = Paths.get(args[2]);
        Path deckFileB = Paths.get(args[3]);
        Deck deckA = CardCatalog.loadDeck(deckFileA, a);
        Deck deckB = CardCatalog.loadDeck(deckFileB, b);
        registerObjectOrder(channel, a, b, deckA, deckB);
        joinMatch(game, a, deckA, b, deckB);
        // Fix play/draw as an experimental factor, not a controller decision.
        game.setStartingPlayerId(startingPlayer.equals("player_a") ? a.getId() : b.getId());
        game.addPlayerQueryEventListener(e -> {
            if (e.getQueryType() != PlayerQueryEvent.QueryType.PERSONAL_MESSAGE) {
                channel.pending = e;
            }
        });
        try (Recorder recorder = new Recorder(output, game, mode)) {
            channel.recorder = recorder;
            game.recorder = recorder;
            JsonObject manifest = manifest(seed, startingPlayer, deckFileA, deckFileB, a, b, bridgePlayers, aiSeat, mode, recorder.fullAudit);
            Files.write(output.resolve("internal/manifest.json"), GSON.toJson(manifest).getBytes(StandardCharsets.UTF_8));
            recorder.capture(game, "start", new JsonObject());
            game.start(a.getId());
            recorder.capture(game, "end", new JsonObject());
            JsonObject result = result(game, startingPlayer, channel, recorder);
            Files.write(output.resolve("internal/result.json"), GSON.toJson(result).getBytes(StandardCharsets.UTF_8));
            System.out.println(GSON.toJson(result));
        }
    }

    private static String recordingMode(Map<String, String> options) {
        String mode = options.getOrDefault("recording-mode", "full_audit");
        if (!mode.equals("full_audit") && !mode.equals("benchmark")) {
            throw new IllegalArgumentException("Unknown recording mode: " + mode);
        }
        return mode;
    }

    private static String startingPlayer(Map<String, String> options) {
        String startingPlayer = options.getOrDefault("starting-player", "player_a");
        if (!startingPlayer.equals("player_a") && !startingPlayer.equals("player_b")) {
            throw new IllegalArgumentException("Starting player must be player_a or player_b");
        }
        return startingPlayer;
    }

    private static String engineAiSeat(Map<String, String> options) {
        String aiSeat = options.getOrDefault("engine-ai-seat", "none");
        if (!Arrays.asList("none", "player_a", "player_b").contains(aiSeat)) {
            throw new IllegalArgumentException("Invalid AI seat: " + aiSeat);
        }
        return aiSeat;
    }

    // The server uses ComputerPlayerControllableProxy, a ComputerPlayer7 subclass
    // that adds human takeover support. A headless opponent needs only the AI.
    // Only bridge seats get the canonical deck order and per-deck shuffle stream.
    private static Player seat(String name, String aiSeat, Channel channel, long seed) {
        if (aiSeat.equals(name)) {
            return new ComputerPlayer7(name, RangeOfInfluence.ALL, 4);
        }
        return new BridgePlayer(name, channel, seed);
    }

    /** Players first, then each deck's cards in fixture order. */
    private static void registerObjectOrder(Channel channel, Player a, Player b, Deck deckA, Deck deckB) {
        channel.register(a.getId());
        channel.register(b.getId());
        for (Card c : deckA.getCards()) {
            channel.register(c.getId());
        }
        for (Card c : deckB.getCards()) {
            channel.register(c.getId());
        }
    }

    private static void joinMatch(RecordedGame game, Player a, Deck deckA, Player b, Deck deckB) {
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
    }

    /** internal/manifest.json. The Python audit reads these keys and strings verbatim. */
    private static JsonObject manifest(long seed, String startingPlayer, Path deckFileA, Path deckFileB, Player a, Player b,
                                       List<UUID> bridgePlayers, String aiSeat, String mode, boolean fullAudit) throws Exception {
        JsonObject engineAi = aiSeat.equals("none") ? null : object(
            "seat", aiSeat,
            "class", ComputerPlayer7.class.getName(),
            "skill", 4,
            "max_depth", 4,
            "max_think_seconds", 12,
            "information", "perfect: searches the full copied game, including the pilot's real hand and exact library order",
            "budget", "wall-clock 12s per search on a shared 5-thread pool; hardware/load dependent and non-deterministic");
        return object(
            "schema_version", 2,
            "xmage_revision", REVISION,
            "seed", seed,
            "starting_player", startingPlayer,
            "deck_a", Files.readAllLines(deckFileA),
            "deck_b", Files.readAllLines(deckFileB),
            "players", Arrays.asList(a.getId(), b.getId()),
            "bridge_players", bridgePlayers,
            "engine_ai", engineAi,
            "recording_mode", mode,
            "privacy_audit", "all delivered observations/actions compared to paired decision projections; hidden IDs and public counts checked; fixture-limited",
            "checkpoint_format", fullAudit
                ? "gzip Java serialization of complete Game graph; transport fields are transient"
                : "none; decision projections are not restorable engine checkpoints",
            "determinism", "ordered deck input; per-deck seed and shuffle ordinal; stable known-card action ordering; UUIDs, clocks and engine internals are not deterministic",
            "shuffle_algorithm", "java.util.Collections.shuffle / Random(low64(nameUUID(deck_seed + ':' + shuffle_ordinal))); deck_seed = seed XOR low64(nameUUID(JSON ordered card names)); ordinal starts at 0",
            "card_module", "org.mage:mage-sets:1.4.62",
            "catalog_names", CardCatalog.DEFINITIONS.size(),
            "coverage", fullAudit
                ? "two 60-card decks; limited query adapter; full checkpoints at game events, updates, decisions, start and end"
                : "two 60-card decks; limited query adapter; JSON projections at every decision, start and end; compact event log; no restoration or hidden-state counterfactual audit");
    }

    /** internal/result.json and the final stdout line. */
    private static JsonObject result(RecordedGame game, String startingPlayer, Channel channel, Recorder recorder) {
        JsonObject result = object(
            "type", "result",
            "ended", game.hasEnded(),
            "winner", game.getWinner(),
            "starting_player", startingPlayer,
            "errors", game.getTotalErrorsCount(),
            "technical_failure", game.technicalFailure,
            "decisions", channel.decision,
            "snapshots", recorder.sequence);
        JsonArray outcomes = new JsonArray();
        for (Player p : game.getPlayers().values()) {
            outcomes.add(object(
                "id", p.getId(),
                "name", p.getName(),
                "won", p.hasWon(),
                "lost", p.hasLost()));
        }
        result.add("players", outcomes);
        return result;
    }
}
