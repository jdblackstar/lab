package lab.xmage;

import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

public class OptionsTest {
    static final String[] GAME = {"out", "7", "a.txt", "b.txt"};

    static String[] with(String... options) {
        String[] args = Arrays.copyOf(GAME, GAME.length + options.length);
        System.arraycopy(options, 0, args, GAME.length, options.length);
        return args;
    }

    @Test public void parsesNamedOptionsAfterPositionalArguments() {
        assertEquals(Collections.emptyMap(), PocMain.options(GAME, 4, "recording-mode"));
        assertEquals(Collections.singletonMap("recording-mode", "benchmark"),
            PocMain.options(with("--recording-mode=benchmark"), 4, "recording-mode"));
    }

    @Test public void rejectsPositionalUnknownAndDuplicateOptions() {
        for (String[] args : Arrays.asList(
                with("benchmark"),
                with("--recording-mode"),
                with("--seat=player_a"),
                with("--recording-mode=benchmark", "--recording-mode=full_audit"))) {
            try {
                PocMain.options(args, 4, "recording-mode");
                fail("Accepted " + Arrays.toString(args));
            } catch (IllegalArgumentException expected) {
            }
        }
    }
}
