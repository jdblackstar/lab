package lab.xmage;

import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.util.RandomUtil;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;

public class ShuffleTest {
    static final class Fixture {
        final RecordedGame game = new RecordedGame();
        final BridgePlayer player;
        final List<UUID> registered = new ArrayList<>();

        Fixture(String seat, long seed) throws Exception {
            player = new BridgePlayer(seat, new Channel(), seed);
            Deck deck = new Deck();
            for (int i = 0; i < 60; i++) {
                Card card = CardCatalog.createCard(i < 40 ? "Plains" : "Youthful Knight", player.getId());
                deck.getCards().add(card);
                registered.add(card.getId());
            }
            player.init(game);
            game.loadCards(deck.getCards(), player.getId());
            game.addPlayer(player, deck);
        }

        List<Integer> shuffle() {
            player.shuffleLibrary(null, game);
            List<Integer> order = new ArrayList<>();
            for (UUID id : player.getLibrary().getCardList()) order.add(registered.indexOf(id));
            return order;
        }
    }

    @Test public void reproducesEveryRegisteredCardAcrossSeatsAndReshuffles() throws Exception {
        Fixture a = new Fixture("player_a", 7), b = new Fixture("player_b", 7);
        List<Integer> first = a.shuffle();
        // Other RNG users (including the opposing deck) cannot alter this stream.
        for (int i = 0; i < 100; i++) RandomUtil.nextInt();
        assertEquals(first, b.shuffle());
        assertEquals(60, new HashSet<>(first).size());
        assertNotEquals(first, new Fixture("player_a", 8).shuffle());

        // London mulligans return hands in collection order. It must not become
        // an input to the next random permutation.
        List<Card> reordered = b.player.getLibrary().getCards(b.game);
        Collections.reverse(reordered);
        b.player.getLibrary().clear();
        b.player.getLibrary().addAll(new LinkedHashSet<>(reordered), b.game);
        List<Integer> second = a.shuffle();
        assertEquals(second, b.shuffle());
        assertNotEquals(first, second);

        // Engine bookmark/restore must restore the shuffle position too.
        BridgePlayer saved = a.player.copy();
        List<Integer> third = a.shuffle();
        a.player.restore(saved);
        assertEquals(third, a.shuffle());
    }
}
