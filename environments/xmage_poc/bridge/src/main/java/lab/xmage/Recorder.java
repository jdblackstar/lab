package lab.xmage;

import com.google.gson.JsonObject;
import mage.game.Game;
import mage.players.Player;

import java.io.BufferedWriter;
import java.io.Closeable;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import static lab.xmage.Json.writeLine;

/**
 * Writes a run's recording under {@code root}:
 * {@code internal/states.jsonl}, {@code internal/decisions.jsonl}, {@code internal/events.jsonl},
 * {@code internal/checkpoints/} (full_audit only), and {@code players/<name>.jsonl}.
 */
final class Recorder implements Closeable {
    final Path root;
    final boolean fullAudit;
    final BufferedWriter states;
    final BufferedWriter decisions;
    final BufferedWriter events;
    final Map<UUID, BufferedWriter> views = new LinkedHashMap<>();
    long sequence = 0;
    boolean capturing;

    Recorder(Path root, Game game, String mode) throws IOException {
        this.root = root;
        fullAudit = mode.equals("full_audit");
        Files.createDirectories(root.resolve("internal"));
        if (fullAudit) {
            Files.createDirectories(root.resolve("internal/checkpoints"));
        }
        Files.createDirectories(root.resolve("players"));
        states = Files.newBufferedWriter(root.resolve("internal/states.jsonl"), StandardCharsets.UTF_8);
        decisions = Files.newBufferedWriter(root.resolve("internal/decisions.jsonl"), StandardCharsets.UTF_8);
        events = Files.newBufferedWriter(root.resolve("internal/events.jsonl"), StandardCharsets.UTF_8);
        for (Player p : game.getPlayers().values()) {
            Path view = root.resolve("players/" + p.getName() + ".jsonl");
            views.put(p.getId(), Files.newBufferedWriter(view, StandardCharsets.UTF_8));
        }
    }

    /** Records a state snapshot and returns its sequence number, or the latest one when skipped. */
    long capture(Game g, String reason, JsonObject event) {
        if (capturing || g.isSimulation()) {
            return sequence;
        }
        capturing = true;
        try {
            if (reason.equals("event")) {
                writeLine(events, event);
            }
            // Benchmark privacy audits retain every decision's engine projection,
            // not event/update projections or restorable engine graphs.
            if (!fullAudit && (reason.equals("event") || reason.equals("update"))) {
                return sequence;
            }
            long seq = ++sequence;
            JsonObject state = GameJson.summary(g);
            state.addProperty("sequence", seq);
            state.addProperty("reason", reason);
            state.add("event", event);
            if (fullAudit) {
                // Only full_audit claims complete, restorable engine graphs.
                String file = Checkpoints.fileName(seq);
                Path checkpoint = root.resolve("internal").resolve(file);
                Checkpoints.write(checkpoint, g);
                state.addProperty("checkpoint", file);
                state.addProperty("sha256", Checkpoints.sha256(checkpoint));
            }
            writeLine(states, state);
            return seq;
        } catch (Exception e) {
            throw new IllegalStateException("Recording failed; discard this run", e);
        } finally {
            capturing = false;
        }
    }

    /** Appends what {@code player} was shown to {@code players/<name>.jsonl}. */
    void writeView(UUID player, JsonObject observation) throws IOException {
        writeLine(views.get(player), observation);
    }

    void writeDecision(JsonObject decision) throws IOException {
        writeLine(decisions, decision);
    }

    @Override
    public void close() throws IOException {
        states.close();
        decisions.close();
        events.close();
        for (BufferedWriter w : views.values()) {
            w.close();
        }
    }
}
