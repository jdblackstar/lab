package lab.xmage;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import mage.game.events.PlayerQueryEvent;
import mage.util.MultiAmountMessage;
import org.junit.Test;
import java.io.Serializable;
import java.util.*;
import static org.junit.Assert.*;

public class AllocationTest {
    @Test public void exposesEveryLegalSplitOfThreeDamage() {
        PlayerQueryEvent query = PlayerQueryEvent.multiAmountEvent(UUID.randomUUID(), Arrays.asList(
            new MultiAmountMessage("Knight", 0, 3, 1), new MultiAmountMessage("Ox", 0, 3, 2)), 3, 3, new HashMap<>());
        JsonArray actions = new JsonArray();
        new PocMain.Channel().amountAllocations(actions, query);
        Set<String> offered = new HashSet<>();
        for (JsonElement action : actions) offered.add(action.getAsJsonObject().get("value").getAsString());
        assertEquals(new HashSet<>(Arrays.asList("0 3", "1 2", "2 1", "3 0")), offered);
        assertEquals("1 2", actions.get(0).getAsJsonObject().get("value").getAsString());
    }

    @Test public void obeysIndividualBoundsAndOptionalCancellation() {
        Map<String, Serializable> options = new HashMap<>();
        options.put("canCancel", true);
        PlayerQueryEvent query = PlayerQueryEvent.multiAmountEvent(UUID.randomUUID(), Arrays.asList(
            new MultiAmountMessage("A", 1, 2, 1), new MultiAmountMessage("B", 0, 2, 1)), 2, 3, options);
        JsonArray actions = new JsonArray();
        new PocMain.Channel().amountAllocations(actions, query);
        Set<String> offered = new HashSet<>();
        for (JsonElement action : actions) if (action.getAsJsonObject().get("kind").getAsString().equals("allocation")) offered.add(action.getAsJsonObject().get("value").getAsString());
        assertEquals(new HashSet<>(Arrays.asList("1 1", "1 2", "2 0", "2 1")), offered);
        assertEquals("cancel", actions.get(actions.size() - 1).getAsJsonObject().get("kind").getAsString());
    }

    @Test(expected = IllegalStateException.class) public void rejectsUnboundedEnumeration() {
        PlayerQueryEvent query = PlayerQueryEvent.multiAmountEvent(UUID.randomUUID(), Collections.singletonList(
            new MultiAmountMessage("Huge", 0, 10000, 0)), 0, 10000, new HashMap<>());
        new PocMain.Channel().amountAllocations(new JsonArray(), query);
    }
}
