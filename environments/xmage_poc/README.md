# xmage-poc

A verifiers v1 environment where models pilot one seat of a two-player Magic: The Gathering game in the [XMage](https://github.com/magefree/mage) engine. Each game uses fixture decks (`xmage_poc/decks/`) and runs in its own JVM through a small Java bridge (`bridge/`). The opponent is either a second model seat (`self_play`) or an in-engine `random`, `scripted_v1`, or `xmage_mad` player. Pilots see only their own hand and public information, and every game is recorded and audited.

This is a proof of concept. It supports the fixture decks and the subset of decisions the bridge exposes, not arbitrary XMage formats.

## Requirements

- Python 3.12 or newer.
- Java 21 on `PATH`, or set `XMAGE_JAVA_BIN`.
- Network access to GitHub at install time.

## Install

```bash
prime env install xmage-poc
```

The install downloads a prebuilt XMage runtime: one shaded JAR with pinned XMage (`afab346e`), its full card module, and the bridge. You don't need Maven or the XMage source build. [`xmage_poc/runtime/release.json`](xmage_poc/runtime/release.json) names the GitHub Release and the SHA-256 of each asset. The build hook [`hatch_build.py`](hatch_build.py) verifies both checksums before it moves an asset into `xmage_poc/runtime/`, and a mismatch fails the install. The same hook runs for editable installs, wheels, and wheels built from the sdist, so `prime env push` publishes a wheel that already contains the JAR.

## Run

```bash
scripts/prime_rl_eval.sh environments/xmage_poc @ configs/eval/xmage-real-model-pilot.toml
```

`configs/eval/xmage-pilot-smoke.toml` and `scripts/smoke_xmage_poc_eval.py` drive the same path with a scripted local endpoint and make no paid model calls.

## Resuming checkpoints and labeling positions

A `full_audit` recording keeps a restorable engine checkpoint at every decision. The bridge can continue a game from one, the way XMage's own AIs continue copied games (`Game.resume()`). Only decisions the turn structure asks directly can be re-asked: priority, and the first declare-attackers or declare-blockers ask of a step. A choice made mid-cast (a target, a mana payment) or partway through a combat selection cannot.

- `java -cp xmage_poc/runtime/xmage-poc.jar lab.xmage.PocMain replay <recording> <decision>...|resumable` resumes each decision with the recorded answers and reports whether every later observation, every later engine event, and the winner match the original game. Only engine bookkeeping may differ: `gameCycle`, `totalEffectsCount`, `statesSavedSize`, fresh object IDs, and the events the resume itself fires (`PHASE_CHANGED`, plus the step's main event when resuming at priority).
- `... PocMain rollout <recording> <decision> [--playouts=N --seed=S --policy=greedy|random|mad --turn-cap=T]` lists every complete candidate action (a spell with its targets, an attacker subset, a blocker assignment) and plays each out from the same resampled hidden worlds. The actor's hidden information is resampled the way XMage's MCTS AI does it: the opponent's hand is shuffled into their library and redrawn, and both libraries are shuffled. `checks` confirms that the rollout seats see the recorded observation.
- `python -m xmage_poc.positions --recording <dir> --output questions.jsonl` turns those rollouts into "best move" questions. Each item has the seat's rendered board, the candidates and their win rates, and an `answer` only when the best candidate beats every alternative by a paired margin (`--z`, default 2 standard errors).

Rollout labels are only as good as the rollout policy: `greedy` and `random` are fast heuristic players, and `mad` (XMage's search AI) is far slower. A playout takes about a second on these fixture decks.

## Changing the runtime

The runtime is built from source only in CI. To change the bridge or the XMage pin:

1. Edit `bridge/` or `REVISION` in `scripts/build_xmage_poc.py`.
2. Push a tag such as `xmage-runtime-v2`. The `XMage runtime release` workflow builds XMage, runs the bridge's Java tests, and publishes `xmage-poc.jar`, `build.json`, and `release.json` as a release.
3. Pin the release: `gh release download xmage-runtime-v2 -p release.json -D environments/xmage_poc/xmage_poc/runtime --clobber`, then commit it.

The lifecycle smoke checks that the pinned `build.json` matches this checkout's bridge sources and XMage revision, so a bridge change without a new release fails CI.

To build locally instead (needs JDK 21, Maven 3.9+, and about 4 GB for the XMage checkout), run `python scripts/build_xmage_poc.py`. Then install with `XMAGE_POC_SKIP_DOWNLOAD=1`, which keeps that local runtime instead of replacing it with the pinned one.
