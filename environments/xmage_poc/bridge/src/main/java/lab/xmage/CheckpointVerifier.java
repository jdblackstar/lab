package lab.xmage;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.Card;
import mage.constants.Zone;
import mage.game.Game;
import mage.players.Player;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static lab.xmage.Json.GSON;
import static lab.xmage.Json.object;

/**
 * The {@code verify} subcommand: restores every full_audit checkpoint, checks it against the
 * recorded summary and delivered views, and runs one hidden-state counterfactual per bridge seat.
 */
final class CheckpointVerifier {
    private final Path internal;

    private CheckpointVerifier(Path output) {
        internal = output.resolve("internal");
    }

    static void verify(Path output) throws Exception {
        CheckpointVerifier verifier = new CheckpointVerifier(output);
        Set<UUID> bridgePlayers = verifier.bridgePlayers();
        int count = verifier.verifyStates();
        Set<UUID> tested = verifier.verifyDecisions();
        if (bridgePlayers.isEmpty() || !tested.equals(bridgePlayers)) {
            throw new IllegalStateException("Counterfactual test must cover every controller seat");
        }
        System.out.println(GSON.toJson(object("checkpoints_restored", count, "counterfactual_seats", tested.size())));
    }

    /** The manifest's controller seats; older manifests without bridge_players list both players. */
    private Set<UUID> bridgePlayers() throws Exception {
        String text = new String(Files.readAllBytes(internal.resolve("manifest.json")), StandardCharsets.UTF_8);
        JsonObject manifest = JsonParser.parseString(text).getAsJsonObject();
        if (manifest.has("recording_mode") && !manifest.get("recording_mode").getAsString().equals("full_audit")) {
            throw new IllegalArgumentException("Checkpoint restoration/counterfactual audit requires recording_mode=full_audit; benchmark only retains decision projections");
        }
        Set<UUID> bridgePlayers = new HashSet<>();
        String key = manifest.has("bridge_players") ? "bridge_players" : "players";
        for (JsonElement id : manifest.getAsJsonArray(key)) {
            bridgePlayers.add(UUID.fromString(id.getAsString()));
        }
        return bridgePlayers;
    }

    /** Every restored checkpoint must reproduce its recorded summary; returns the checkpoint count. */
    private int verifyStates() throws Exception {
        int count = 0;
        try (BufferedReader input = Files.newBufferedReader(internal.resolve("states.jsonl"), StandardCharsets.UTF_8)) {
            String line;
            while ((line = input.readLine()) != null) {
                JsonObject recorded = JsonParser.parseString(line).getAsJsonObject();
                Game game = Checkpoints.read(internal.resolve(recorded.get("checkpoint").getAsString()));
                JsonObject restored = GameJson.summary(game);
                for (Map.Entry<String, JsonElement> e : restored.entrySet()) {
                    if (!e.getValue().equals(recorded.get(e.getKey()))) {
                        throw new IllegalStateException("Checkpoint differs: " + recorded.get("sequence") + " field " + e.getKey());
                    }
                }
                count++;
            }
        }
        return count;
    }

    /** Every delivered view must match its restored checkpoint; returns the seats counterfactually tested. */
    private Set<UUID> verifyDecisions() throws Exception {
        Set<UUID> tested = new HashSet<>();
        for (String line : Files.readAllLines(internal.resolve("decisions.jsonl"), StandardCharsets.UTF_8)) {
            JsonObject decision = JsonParser.parseString(line).getAsJsonObject();
            JsonObject obs = decision.getAsJsonObject("observation");
            UUID actor = UUID.fromString(obs.get("player_id").getAsString());
            Path checkpoint = internal.resolve(Checkpoints.fileName(decision.get("state_sequence").getAsInt()));
            Game restored = Checkpoints.read(checkpoint);
            JsonElement expectedView = obs.get("view").deepCopy();
            GameJson.stripClock(expectedView);
            if (!expectedView.equals(GameJson.playerView(restored, actor))) {
                throw new IllegalStateException("Restored checkpoint differs from delivered view at decision " + decision.get("decision"));
            }
            // Opening mulligan boundaries have private hands but no revealed cards.
            if (!tested.contains(actor) && obs.get("query_type").getAsString().equals("ASK")) {
                hiddenCounterfactual(restored, actor);
                tested.add(actor);
            }
        }
        return tested;
    }

    /** Swaps a hidden opponent card and reverses both libraries; {@code actor}'s view must not change. */
    static void hiddenCounterfactual(Game game, UUID actor) {
        JsonElement before = GameJson.playerView(game, actor);
        Player opponent = game.getPlayers().values().stream()
            .filter(p -> !p.getId().equals(actor))
            .findFirst()
            .get();
        Card hidden = opponent.getHand().getCards(game).iterator().next();
        Card replacement = opponent.getLibrary().getCards(game).stream()
            .filter(c -> !c.getName().equals(hidden.getName()))
            .findFirst()
            .get();
        opponent.getHand().remove(hidden.getId());
        opponent.getLibrary().remove(replacement.getId(), game);
        opponent.getLibrary().putOnTop(hidden, game);
        opponent.getHand().add(replacement);
        replacement.setZone(Zone.HAND, game);
        // Reverse both libraries while preserving their lengths and contents.
        for (Player p : game.getPlayers().values()) {
            List<Card> original = p.getLibrary().getCards(game);
            for (Card c : original) {
                p.getLibrary().putOnTop(c, game);
            }
        }
        if (!before.equals(GameJson.playerView(game, actor))) {
            throw new IllegalStateException("Hidden state changed player view for " + actor);
        }
    }
}
