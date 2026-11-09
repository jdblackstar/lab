package lab.xmage;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;

import java.io.BufferedWriter;
import java.io.IOException;

/** The bridge's single JSON encoder, shared by stdout, recordings and audits. */
final class Json {
    static final Gson GSON = new GsonBuilder().serializeNulls().create();

    private Json() {
    }

    /** Builds an object from alternating key/value arguments, in argument order. */
    static JsonObject object(Object... pairs) {
        JsonObject out = new JsonObject();
        for (int i = 0; i < pairs.length; i += 2) {
            out.add((String) pairs[i], GSON.toJsonTree(pairs[i + 1]));
        }
        return out;
    }

    /** Appends one JSONL record and flushes it, so a crashed run keeps every completed line. */
    static void writeLine(BufferedWriter writer, JsonObject record) throws IOException {
        writer.write(GSON.toJson(record));
        writer.newLine();
        writer.flush();
    }
}
