package lab.xmage;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.MageObject;
import mage.cards.Card;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.view.GameView;

import java.util.Collection;
import java.util.Map;
import java.util.UUID;

import static lab.xmage.Json.GSON;
import static lab.xmage.Json.object;

/** JSON projections of a game: the full engine summary and one player's view. */
final class GameJson {
    private GameJson() {
    }

    /** Complete engine state, including hidden zones. Recorded and audited, never shown to a pilot. */
    static JsonObject summary(Game g) {
        JsonArray players = new JsonArray();
        for (Player p : g.getPlayers().values()) {
            players.add(object(
                "id", p.getId(),
                "name", p.getName(),
                "life", p.getLife(),
                "hand", cards(p.getHand().getCards(g), g),
                "library", cards(p.getLibrary().getCards(g), g),
                "graveyard", cards(p.getGraveyard().getCards(g), g),
                "sideboard", cards(p.getSideboard().getCards(g), g),
                "mana", p.getManaPool().toString(),
                "won", p.hasWon(),
                "lost", p.hasLost()));
        }
        return object(
            "game_id", g.getId(),
            "turn", g.getState().getTurnNum(),
            "phase", g.getTurnPhaseType(),
            "step", g.getTurnStepType(),
            "active_player", g.getActivePlayerId(),
            "priority_player", g.getState().getPriorityPlayerId(),
            "players", players,
            "battlefield", cards(g.getBattlefield().getAllPermanents(), g),
            "stack", cards(g.getStack(), g),
            "exile", g.getExile().toString(),
            "ended", g.hasEnded(),
            "winner", g.getWinner(),
            "errors", g.getTotalErrorsCount());
    }

    static JsonArray cards(Collection<? extends MageObject> objects, Game g) {
        JsonArray out = new JsonArray();
        for (MageObject c : objects) {
            out.add(card(c, g));
        }
        return out;
    }

    static JsonObject card(MageObject c, Game g) {
        JsonObject out = object(
            "id", c.getId(),
            "name", c.getName(),
            "type", c.getCardType(g),
            "zone", g.getState().getZone(c.getId()));
        if (c instanceof Card) {
            Card card = (Card) c;
            out.addProperty("owner", card.getOwnerId().toString());
            out.add("rules", GSON.toJsonTree(card.getRules(g)));
        }
        if (c instanceof Permanent) {
            Permanent p = (Permanent) c;
            out.add("permanent", object(
                "controller", p.getControllerId(),
                "tapped", p.isTapped(),
                "power", p.getPower().getValue(),
                "toughness", p.getToughness().getValue(),
                "damage", p.getDamage(),
                "counters", p.getCounters(g).toString()));
        }
        return out;
    }

    /** XMage's own client view for {@code actor}, without wall-clock fields. */
    static JsonElement playerView(Game g, UUID actor) {
        JsonElement view = JsonParser.parseString(new GameView(g.getState(), g, actor, null).toJson());
        stripClock(view);
        return view;
    }

    // Wall-clock priority timers are the only permitted counterfactual difference.
    static void stripClock(JsonElement value) {
        if (value.isJsonObject()) {
            JsonObject o = value.getAsJsonObject();
            o.remove("priorityTimeSavedTimeMs");
            for (Map.Entry<String, JsonElement> e : o.entrySet()) {
                stripClock(e.getValue());
            }
        } else if (value.isJsonArray()) {
            for (JsonElement e : value.getAsJsonArray()) {
                stripClock(e);
            }
        }
    }
}
