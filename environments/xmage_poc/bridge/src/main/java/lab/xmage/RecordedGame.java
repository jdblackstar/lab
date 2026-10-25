package lab.xmage;

import com.google.gson.JsonObject;
import mage.constants.MultiplayerAttackOption;
import mage.constants.RangeOfInfluence;
import mage.game.TwoPlayerDuel;
import mage.game.events.GameEvent;
import mage.game.mulligan.MulliganType;

import static lab.xmage.Json.object;

/** A two-player duel that reports every event and player update to the recorder. */
final class RecordedGame extends TwoPlayerDuel {
    transient Recorder recorder;
    String technicalFailure;

    RecordedGame() {
        super(MultiplayerAttackOption.LEFT, RangeOfInfluence.ALL, MulliganType.GAME_DEFAULT.getMulligan(0), 60, 20, 7);
    }

    @Override
    public TwoPlayerDuel copy() {
        return new TwoPlayerDuel(this);
    }

    @Override
    public void fireEvent(GameEvent e) {
        super.fireEvent(e);
        if (recorder == null) {
            return;
        }
        recorder.capture(this, "event", object(
            "type", e.getType(),
            "source", e.getSourceId(),
            "target", e.getTargetId(),
            "player", e.getPlayerId(),
            "amount", e.getAmount(),
            "flag", e.getFlag()));
    }

    @Override
    public void fireUpdatePlayersEvent() {
        super.fireUpdatePlayersEvent();
        if (recorder != null) {
            recorder.capture(this, "update", new JsonObject());
        }
    }

    @Override
    public void endWithTechnicalWinner(String reason) {
        technicalFailure = reason;
        super.endWithTechnicalWinner(reason);
    }
}
