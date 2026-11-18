package lab.xmage;

import mage.game.Game;

import java.io.IOException;
import java.io.ObjectInputStream;
import java.io.ObjectOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/** full_audit checkpoints: gzip Java serialization of a complete Game graph. */
final class Checkpoints {
    private Checkpoints() {
    }

    /** Checkpoint path relative to {@code internal/} for a state sequence number. */
    static String fileName(long sequence) {
        return String.format("checkpoints/%06d.game.gz", sequence);
    }

    static void write(Path file, Game game) throws IOException {
        try (ObjectOutputStream out = new ObjectOutputStream(new GZIPOutputStream(Files.newOutputStream(file)))) {
            out.writeObject(game);
        }
    }

    static Game read(Path file) throws IOException, ClassNotFoundException {
        try (ObjectInputStream in = new ObjectInputStream(new GZIPInputStream(Files.newInputStream(file)))) {
            return (Game) in.readObject();
        }
    }

    static String sha256(Path file) throws IOException, NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] bytes = Files.readAllBytes(file);
        StringBuilder out = new StringBuilder();
        for (byte b : digest.digest(bytes)) {
            out.append(String.format("%02x", b & 255));
        }
        return out.toString();
    }
}
