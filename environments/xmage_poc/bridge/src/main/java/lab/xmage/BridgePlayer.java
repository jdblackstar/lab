package lab.xmage;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.events.GameEvent;
import mage.player.human.HumanPlayer;
import mage.player.human.PlayerResponse;
import mage.players.Player;
import mage.players.net.SkipPrioritySteps;
import mage.players.net.UserData;
import mage.util.CardUtil;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.UUID;

import static lab.xmage.Json.GSON;

/** HumanPlayer's existing rule/choice handling with a synchronous pipe transport. */
final class BridgePlayer extends HumanPlayer {
    final transient PlayerResponse reply;
    final transient Channel channel;
    final long seed;
    final Map<UUID, Integer> cardOrder = new HashMap<>();
    long deckSeed;
    long shuffles;

    BridgePlayer(String name, Channel channel, long seed) {
        this(name, channel, seed, new PlayerResponse());
    }

    private BridgePlayer(String name, Channel channel, long seed, PlayerResponse reply) {
        super(new HumanPlayer(name, RangeOfInfluence.ALL, 1), reply);
        this.reply = reply;
        this.channel = channel;
        this.seed = seed;
        UserData user = UserData.getDefaultUserDataView();
        user.setAutoTargetLevel(0);
        stopAtEveryPriorityStep(user.getUserSkipPrioritySteps().getYourTurn());
        stopAtEveryPriorityStep(user.getUserSkipPrioritySteps().getOpponentTurn());
        setUserData(user);
    }

    private BridgePlayer(BridgePlayer p) {
        super(p);
        reply = p.reply;
        channel = p.channel;
        seed = p.seed;
        deckSeed = p.deckSeed;
        shuffles = p.shuffles;
        cardOrder.putAll(p.cardOrder);
    }

    // Despite the "Skip" name, true enables a stop: HumanPlayer.checkPassStep
    // passes when !isPhaseStepSet(...). Keep every instant-speed window;
    // Python's auto_pass_priority drains only prompts with no legal play.
    private static void stopAtEveryPriorityStep(SkipPrioritySteps turn) {
        turn.setUpkeep(true);
        turn.setDraw(true);
        turn.setBeforeCombat(true);
        turn.setEndOfCombat(true);
        turn.setEndOfTurn(true);
    }

    @Override
    public BridgePlayer copy() {
        return new BridgePlayer(this);
    }

    @Override
    public void restore(Player p) {
        super.restore(p);
        BridgePlayer saved = (BridgePlayer) p;
        deckSeed = saved.deckSeed;
        shuffles = saved.shuffles;
    }

    @Override
    public void useDeck(Deck deck, Game game) {
        super.useDeck(deck, game);
        // Deck.getMaindeckCards() collects into an unordered HashSet upstream.
        Set<Card> ordered = new LinkedHashSet<>();
        List<String> names = new ArrayList<>();
        cardOrder.clear();
        for (Card card : deck.getCards()) {
            if (card.isExtraDeckCard()) {
                continue;
            }
            cardOrder.put(card.getId(), cardOrder.size());
            ordered.add(card);
            names.add(card.getName());
        }
        library.clear();
        library.addAll(ordered, game);
        // Deck identity, not seat or UUID, keys an independent shuffle stream.
        deckSeed = seed ^ low64NameUuid(GSON.toJson(names));
        shuffles = 0;
    }

    @Override
    public void shuffleLibrary(Ability source, Game game) {
        // Preserve PlayerImpl's replacement check, logging and shuffle event.
        if (game.replaceEvent(GameEvent.getEvent(GameEvent.EventType.SHUFFLE_LIBRARY, playerId, source, playerId))) {
            return;
        }
        List<Card> shuffled = library.getCards(game);
        // Mulligans return an unordered hand to the library. Canonicalize
        // every shuffle, not only the opening deck, for registered cards.
        shuffled.sort(Comparator.comparingInt(c -> cardOrder.getOrDefault(c.getId(), Integer.MAX_VALUE)));
        long shuffleSeed = low64NameUuid(deckSeed + ":" + shuffles);
        shuffles++;
        Collections.shuffle(shuffled, new Random(shuffleSeed));
        library.clear();
        library.addAll(new LinkedHashSet<>(shuffled), game);
        if (!game.isSimulation()) {
            game.informPlayers(getLogName() + "'s library is shuffled" + CardUtil.getSourceLogName(game, source));
        }
        game.fireEvent(GameEvent.getEvent(GameEvent.EventType.LIBRARY_SHUFFLED, playerId, source, playerId));
    }

    /** low64(nameUUID(text)), as named by the manifest's shuffle_algorithm. */
    private static long low64NameUuid(String text) {
        return UUID.nameUUIDFromBytes(text.getBytes(StandardCharsets.UTF_8)).getLeastSignificantBits();
    }

    @Override
    protected void waitForResponse(Game game) {
        reply.resetAnswers();
        JsonObject action = channel.request(game, this);
        String type = action.get("response_type").getAsString();
        JsonElement value = action.get("value");
        switch (type) {
            case "boolean":
                reply.setBoolean(value.getAsBoolean());
                break;
            case "integer":
                reply.setInteger(value.getAsInt());
                break;
            case "string":
                reply.setString(value.getAsString());
                break;
            case "uuid":
                reply.setUUID(UUID.fromString(value.getAsString()));
                break;
            default:
                throw new IllegalStateException("Unsupported response: " + type);
        }
    }
}
