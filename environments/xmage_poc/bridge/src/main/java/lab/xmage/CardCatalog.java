package lab.xmage;

import mage.cards.Card;
import mage.cards.CardSetInfo;
import mage.cards.ExpansionSet;
import mage.cards.Sets;
import mage.cards.decks.Deck;
import mage.players.Player;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;

/** Card names resolved against the pinned XMage card module, and fixture decks built from them. */
final class CardCatalog {
    /** One printing per name: the first non-custom set by code, then the lowest card number. */
    static final Map<String, CardDefinition> DEFINITIONS = load();

    private CardCatalog() {
    }

    static final class CardDefinition {
        final Class<?> cardClass;
        final CardSetInfo setInfo;

        CardDefinition(ExpansionSet set, ExpansionSet.SetCardInfo info) {
            cardClass = info.getCardClass();
            setInfo = new CardSetInfo(info.getName(), set.getCode(), info.getCardNumber(), info.getRarity(), info.getGraphicInfo());
        }

        Card create(UUID owner) throws Exception {
            return (Card) cardClass.getConstructor(UUID.class, CardSetInfo.class).newInstance(owner, setInfo);
        }
    }

    static Map<String, CardDefinition> load() {
        Map<String, CardDefinition> cards = new TreeMap<>();
        List<ExpansionSet> sets = new ArrayList<>(Sets.getInstance().values());
        sets.sort(Comparator.comparing(ExpansionSet::getCode));
        for (ExpansionSet set : sets) {
            if (set.getSetType().isCustomSet()) {
                continue;
            }
            List<ExpansionSet.SetCardInfo> infos = new ArrayList<>(set.getSetCardInfo());
            infos.sort(Comparator.comparing(ExpansionSet.SetCardInfo::getCardNumber));
            for (ExpansionSet.SetCardInfo info : infos) {
                if (Card.class.isAssignableFrom(info.getCardClass())) {
                    cards.putIfAbsent(info.getName(), new CardDefinition(set, info));
                }
            }
        }
        if (cards.isEmpty()) {
            throw new IllegalStateException("XMage card catalog is empty; rebuild with Mage.Sets");
        }
        return Collections.unmodifiableMap(cards);
    }

    static Card createCard(String name, UUID owner) throws Exception {
        CardDefinition definition = DEFINITIONS.get(name);
        if (definition == null) {
            throw new IllegalArgumentException("Unknown card in pinned XMage catalog: " + name);
        }
        return definition.create(owner);
    }

    /** Reads a 60-card fixture of {@code <count> <card name>} lines; blank and {@code #} lines are skipped. */
    static Deck loadDeck(Path file, Player p) throws Exception {
        Deck d = new Deck();
        for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            String[] parts = line.split("\\s+", 2);
            if (parts.length != 2) {
                throw new IllegalArgumentException("Expected '<count> <card name>': " + line);
            }
            int count = Integer.parseInt(parts[0]);
            if (count < 1 || count > 60) {
                throw new IllegalArgumentException("Count must be between 1 and 60: " + line);
            }
            String name = parts[1].trim();
            for (int i = 0; i < count; i++) {
                d.getCards().add(createCard(name, p.getId()));
            }
        }
        if (d.getCards().size() != 60) {
            throw new IllegalArgumentException("Fixture must contain 60 cards");
        }
        return d;
    }
}
