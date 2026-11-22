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

## Results: Claude vs `scripted_v1`, 100 games each

Four Claude models each piloted the same 100 games against the `scripted_v1` opponent: Haiku 4.5 and Sonnet 4.5 on 2026-11-16, and Haiku 5.5 and Sonnet 5.5 on 2026-11-20 and 21. Every game finished and passed the recording audit. [`examples/scripted-v1-100-game-results.csv`](examples/scripted-v1-100-game-results.csv) has one row per game and model, and every number below can be recomputed from it. The 5.5 runs used a few different settings, listed in [What differs for the 5.5 runs](#what-differs-for-the-55-runs).

| | Haiku 4.5 | Sonnet 4.5 | Haiku 5.5 | Sonnet 5.5 |
| --- | --- | --- | --- | --- |
| Win rate (95% Wilson CI) | 73% (64–81%) | 80% (71–87%) | 90% (83–94%) | 96% (90–98%) |
| Wins / losses / draws | 73 / 27 / 0 | 80 / 20 / 0 | 90 / 10 / 0 | 96 / 4 / 0 |
| Truncated by `max_turns` / errored | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Invalid replies / fallback actions | 10 / 0 | 0 / 0 | 4 / 0 | 1 / 0 |
| Model calls per game (including retries) | 52.8 | 58.9 | 62.1 | 68.6 |
| One-option prompts answered without the model, per game (`auto_forced`) | 19.4 | 17.0 | 18.5 | 18.6 |
| Pass-only priority prompts answered without the model, per game | 167.1 | 146.5 | 140.6 | 134.6 |
| Tokens per game (input / output) | 124.7k / 23.0k | 132.4k / 23.6k | 180.5k / 14.9k | 201.8k / 16.0k |
| Cost per game / total, as paid | $0.24 / $23.96 (list) | $0.75 / $75.18 (list) | $0.013 / $1.28 (batch) | $0.28 / $28.18 (batch) |
| Cost per game at list prices | $0.24 | $0.75 | $0.026 | $0.56 |

Paired results on the 100 shared games, with an exact McNemar test:

| First vs second model | Both won | Only first won | Only second won | Neither won | p |
| --- | --- | --- | --- | --- | --- |
| Haiku 4.5 vs Sonnet 4.5 | 62 | 11 | 18 | 9 | 0.26 |
| Haiku 5.5 vs Sonnet 5.5 | 89 | 1 | 7 | 3 | 0.07 |
| Haiku 4.5 vs Haiku 5.5 | 68 | 5 | 22 | 5 | 0.002 |
| Sonnet 4.5 vs Sonnet 5.5 | 77 | 3 | 19 | 1 | 0.0009 |

**Sonnet's lead over Haiku is not statistically significant in either generation.** **Each 5.5 model beats its 4.5 predecessor on these games**, though that comparison also includes the setting changes below.

| Win rate by condition (95% CI) | Haiku 4.5 | Sonnet 4.5 | Haiku 5.5 | Sonnet 5.5 |
| --- | --- | --- | --- | --- |
| Pilot plays White (`deck_a`) | 80% (67–89%) | 88% (76–94%) | 88% (76–94%) | 96% (87–99%) |
| Pilot plays Red (`deck_b`) | 66% (52–78%) | 72% (58–83%) | 92% (81–97%) | 96% (87–99%) |
| On the play | 72% (58–83%) | 76% (63–86%) | 88% (76–94%) | 96% (87–99%) |
| On the draw | 74% (60–84%) | 84% (71–92%) | 92% (81–97%) | 96% (87–99%) |

Notes:

- 9 of Haiku 4.5's 10 invalid replies contained two `<answer>` blocks, because the model changed its mind mid-reply. The other chose an index that was not offered. All 5 invalid replies in the 5.5 runs were unparseable. Every invalid reply was corrected on retry.
- Cost is computed from token counts, with no prompt-cache discounts. List prices per million input / output tokens: Haiku 4.5 $1 / $5, Sonnet 4.5 $3 / $15, Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10. The 5.5 runs paid batch prices, half of list; the `pricing` column in the CSV says which applies to each row. prime-rl reports no cost.
- `scripted_v1` is a simple baseline, not a strong player. These numbers describe these two fixture decks and this opponent only.

### What differs for the 5.5 runs

- **No temperature.** Claude 5.5 models reject sampling parameters, so they ran at the API default. The 4.5 runs used temperature 0.
- **Thinking at its lowest setting.** Haiku 5.5 ran with `thinking: {"type": "disabled"}` and Sonnet 5.5 with `thinking: {"type": "between_tools"}`, the lowest setting Sonnet 5.5 accepts; without tools, its replies are text only. Both models think adaptively by default, so these are not their default settings. The 4.5 models do not think unless asked, so neither generation used thinking.
- **Batch pricing.** Every 5.5 call went through Anthropic's Message Batches API, at half the list price.
- **Minutes per game are not comparable.** Each call waited for its batch to finish, about 2 minutes, so a 5.5 game took about 2 hours. The `minutes` column measures batch waits, not model speed.

The output limit was the same, 4,096 tokens, and no 5.5 reply reached it.

### Reproducing the results

Each model ran once with `scripts/prime_rl_eval.sh`, at prime-rl `d61df569` and runtime `xmage-runtime-v3` (XMage `afab346e`), on Java 21. The 4.5 runs sent inference straight to Anthropic's API with `ANTHROPIC_API_KEY` set:

```bash
scripts/prime_rl_eval.sh environments/xmage_poc xmage-poc \
  -m claude-sonnet-4-5 -n 100 -r 1 -c 6 \
  --client.base-url https://api.anthropic.com/v1 \
  --client.api-key-var ANTHROPIC_API_KEY --client.skip-model-check \
  --sampling.max-tokens 4096 --sampling.temperature 0.0 \
  --env.taskset.num-games 100 --env.taskset.seed 7 \
  --env.taskset.pilot-seat player_a --env.taskset.pilot-deck balanced \
  --env.taskset.pilot-play-order balanced \
  --env.opponent scripted --env.history-decisions 1 \
  --env.auto-pass-priority true --env.auto-forced true \
  --env.recording-mode benchmark --env.pilot.max-turns 256 \
  --env.timeout.episode 7200 \
  --output-dir environments/xmage_poc/outputs/evals --run.name sonnet45-100 --no-dashboard
```

For Haiku, use `-m claude-haiku-4-5` and another `--run.name`. Six games ran at a time (`-c 6`), and each game's JVM was capped with `JAVA_TOOL_OPTIONS=-Xmx1g` so they fit in 8 GB of memory.

The 5.5 runs used the code at `bd0ea88` (this environment as of the 4.5 results) and sent inference to a local proxy on `127.0.0.1:8787`. **The proxy is not in this repository.** It was a one-off script that accepted OpenAI chat-completions requests, converted each to an Anthropic Messages request (system prompt at the top level, temperature dropped, thinking set as above), submitted the requests as Message Batches, and returned each reply's text when its batch ended. To reproduce these runs, you need an endpoint that does the same. The command was the 4.5 command with these changes:

```bash
scripts/prime_rl_eval.sh environments/xmage_poc xmage-poc \
  -m claude-sonnet-5-5 -n 100 -r 1 -c 8 \
  --client.base-url http://127.0.0.1:8787/v1 \
  --client.api-key-var ANTHROPIC_API_KEY --client.skip-model-check \
  --sampling.max-tokens 4096 \
  --env.taskset.num-games 100 --env.taskset.seed 7 \
  --env.taskset.pilot-seat player_a --env.taskset.pilot-deck balanced \
  --env.taskset.pilot-play-order balanced \
  --env.opponent scripted --env.history-decisions 1 \
  --env.auto-pass-priority true --env.auto-forced true \
  --env.recording-mode benchmark --env.pilot.max-turns 256 \
  --env.output-dir environments/xmage_poc/outputs/games-sonnet55-100 \
  --env.timeout.episode 172800 \
  --output-dir environments/xmage_poc/outputs/evals --run.name sonnet55-100 --no-dashboard
```

For Haiku 5.5, use `-m claude-haiku-5-5` and its own `--env.output-dir` and `--run.name`. Both runs went at the same time, 8 games each, on one desktop machine.

- **Games:** seeds 7 to 31. Each seed is played four times: the pilot plays White and then Red, each on the play and on the draw. The pilot always sits in `player_a`. Each deck's shuffle is keyed by the seed and its card list, so swapping seats on one seed would replay the same shuffles.
- **Prompts:** text observations, a history of 1 decision, and up to 3 replies per decision before the fallback action.
- **Not deterministic:** engine internals and the models themselves vary between runs, even with the same seed, so a rerun will give close but not identical results.
- **Resumed runs:** some runs were finished with prime-rl's `--resume`, which keeps finished games and replays the rest from the start. Only finished games are counted.
  - The Sonnet 4.5 run was stopped after 78 games and resumed; 6 games interrupted mid-play were replayed.
  - In the 5.5 runs, the proxy at first did not retry failed API calls. Two failed batches and one proxy restart failed 49 Sonnet 5.5 games and 7 Haiku 5.5 games with provider errors. Each run was resumed once, and those games were replayed; Sonnet's resume ran 10 games at a time, with `--resume.skip-checks`. The failed attempts cost $2.37, which the totals above leave out.

## Architecture

### Vocabulary

- **Seat**: one of the two XMage players, always named `player_a` and `player_b`. The names are fixed; which deck a seat gets is a task factor (`XMageTaskset.decks_for`). An observation carries both the seat name (`player`) and the engine's player UUID (`player_id`).
- **Pilot, rival, opponent**: roles in `XMageEnvConfig`. The **pilot** is the agent that plays the row's `pilot_seat`. **`opponent`** chooses who plays the other seat: `self_play` hands it to the **rival** agent; `random` and `scripted_v1` (alias `scripted`) are host-side policies in `PilotSession`; `xmage_mad` is XMage's own `ComputerPlayer7` running inside the JVM. The rival is unused unless `opponent = "self_play"`.
- **Decision** means three linked things:
  1. the integer `decision` number. The bridge assigns it from 1 and increments it once per prompt across both seats, so one seat's decisions have gaps;
  2. the engine prompt itself: an XMage player query turned into an observation (the seat's native `GameView` plus an indexed `actions` list), answered with `{"decision": n, "action": i}`. The bridge rejects a stale number or an index outside the list;
  3. the recorded row in `internal/decisions.jsonl`: `decision`, `state_sequence` (the pre-decision snapshot in `states.jsonl`), `actor`, `observation`, `response`, and `selected` action.

  Every bridge prompt is a decision, including automatic priority passes and moves by the `random`/`scripted_v1` policies. Only some of them reach a model.
- **Actor**: the player UUID of the seat answering a decision. It is the `actor` field in `decisions.jsonl` and in the decision snapshot's `event`, and it equals the observation's `player_id`.
- **Controller**: whatever answers a seat's decisions from the observation alone. That is `XMageGame` for model seats (it calls itself the host-side controller), the `random`/`scripted_v1` policy, or a person at `xmage-poc --interactive`. `model-controller.json` and `controllers.json` record which controller settings a game used.
- **Bridge player**: `BridgePlayer` (`bridge/src/main/java/lab/xmage/BridgePlayer.java`), an XMage `HumanPlayer` whose `waitForResponse` sends each query over the stdin/stdout pipe instead of a UI. Every seat is a bridge player except an `xmage_mad` seat. The manifest lists their IDs as `bridge_players`, and both verifiers require every bridge player to have received decisions. Only bridge players get the canonical deck order and per-deck shuffle stream.
- **Block**: one decision's messages in a seat's `SeatPrompt` (`environment.py`). `SeatPrompt.blocks` holds one list per decision: the rendered observation, then any model replies and corrections for it. `SeatPrompt.messages()` builds each inference's prompt from scratch: a system message (instructions, the public card-rules glossary in text mode, and the seat's own decklist) followed by the last `history_decisions` blocks, so trimming removes whole decisions and never the current observation. Each seat has its own `SeatPrompt`, so the other seat's hand, replies, and corrections never enter it.
- **Correction**: the user message `XMageGame.reply` appends after an invalid reply. It is fixed-schema JSON: `error`, `decision`, `attempts_remaining`, `instruction`, and `fallback_action` once `max_action_attempts` is exhausted and the host submits the fallback (pass, then no, then cancel, else the first action). The `error` and `instruction` strings come from a fixed set (`verify.CORRECTION_TEXT`), so no game state other than the decision number and an offered index can enter a prompt through a correction.
- **`recording_mode`**: both modes write privacy projections, which are JSON summaries of the full engine state (both hands, both ordered libraries) that the audit compares against what each seat saw. `full_audit` snapshots at every engine event, player update, decision, start, and end, and writes a restorable checkpoint for each. `benchmark` snapshots only at start, decisions, and end, and writes no checkpoints, so the Java restoration audit refuses it.

### Processes

A rollout runs one game. `XMageEnv.run` opens an agent interaction for each model seat, then starts a JVM for the game:

```text
┌────────────────────────────┐  stdout: {"type":"decision",...}  ┌──────────────────────────────┐   prompt    ┌──────────────────────┐
│ JVM bridge                 │ ────────────────────────────────▶ │ Host controller (Python)     │ ──────────▶ │ Model endpoint       │
│ bridge/src/main/java/      │                                   │ XMageGame (environment.py)   │             │ via XMageHarness     │
│   lab/xmage/*.java         │ ◀──────────────────────────────── │ GameSession / PilotSession   │ ◀────────── │ (pilot; rival under  │
│ XMage rules + Recorder     │  stdin: {"decision":n,"action":i} │   (transport.py)             │   reply     │  self_play)          │
└────────────────────────────┘                                   └──────────────────────────────┘             └──────────────────────┘
       writes internal/,                                           writes model-*.jsonl/json,
       players/<seat>.jsonl                                        automatic-*.jsonl,
                                                                   context files, stderr log
```

The bridge is one class per responsibility in `lab.xmage`: `PocMain` dispatches the `cards`, `verify`, `inspect`, `replay`, and `rollout` subcommands and plays a game; `Resume` continues a `full_audit` checkpoint for `replay` and `rollout`; `Channel` speaks the stdin/stdout protocol and orders actions; `BridgePlayer` is a seat; `RecordedGame`, `Recorder`, and `Checkpoints` write `internal/`; `CheckpointVerifier` is the `verify` subcommand; `CardCatalog` loads the pinned catalog and decks; `GameJson` and `Json` serialize.

- The **bridge** runs the game with XMage's rules. Each time a bridge player must decide, it builds the observation, snapshots the state, writes the observation to `players/<seat>.jsonl`, prints it, and blocks on stdin for the response.
- **`GameSession`** launches the JVM and validates each response index locally. **`PilotSession`** wraps it for single-seat games: it answers the other seat with the `random`/`scripted_v1` policy (or fails if an `xmage_mad` seat ever asks) and returns only the pilot's decisions.
- **`XMageGame`** answers pass-only priority prompts (`auto_pass_priority`) and other one-option prompts (`auto_forced`) itself, renders each remaining observation into the acting seat's history, builds that seat's prompt, sends it through the seat's agent interaction, and parses the `<answer>` reply. After the result arrives it runs `verify` on the recording.
- **`XMageHarness`** makes one streamed chat completion per prompt against the rollout's endpoint.

### Recording directory

Each game writes a new directory under `output_dir`:

| File | Written by | Contents |
| --- | --- | --- |
| `internal/manifest.json` | bridge, at startup | XMage revision, seed, starting player, both decklists, player and bridge-player IDs, `engine_ai` settings for `xmage_mad`, `recording_mode`, and descriptions of the checkpoint format and determinism |
| `internal/states.jsonl` | bridge `Recorder` | One snapshot per line: `sequence`, `reason` (`start`, `event`, `update`, `decision`, `end`), the triggering `event`, and the full state, including both hands and ordered libraries. Under `full_audit` it also has `checkpoint` and `sha256` |
| `internal/decisions.jsonl` | bridge `Channel.request` | One row per decision (see Vocabulary), written after the response is accepted |
| `internal/events.jsonl` | bridge `Recorder` | Every engine event, in both modes; no verifier reads it |
| `internal/result.json` | bridge, at game end | `ended`, `winner`, per-player `won`/`lost`, error count, `technical_failure`, decision and snapshot counts |
| `internal/checkpoints/NNNNNN.game.gz` | bridge `Recorder`, `full_audit` only | The gzipped, Java-serialized XMage `Game` for that snapshot |
| `players/<seat>.jsonl` | bridge `Channel.request` | Every observation delivered to that seat. An `xmage_mad` seat's file is empty |
| `players/<seat>.context.json` | `GameSession`, before the JVM starts | That seat's registered decklist (names and counts, no IDs or order). It is appended to the seat's system message |
| `model-controller.json` | `XMageEnv.run` | Task factors and controller settings: seat, decks, play/draw, opponent, `auto_pass_priority`, `auto_forced`, `observation_format`, `history_decisions`, `max_action_attempts`, fallback rule |
| `model-prompts.jsonl` | `XMageGame.prompt` | Every message list sent to a model, including retries, with its `decision`, `player`, and play/draw factors. It is written before the call |
| `automatic-priority.jsonl` | `XMageGame.receive_for_model` | `decision`, `player`, and `action` of each pass-only priority prompt answered without a model call |
| `automatic-forced.jsonl` | `XMageGame.receive_for_model` | The same fields for every other one-option prompt answered without a model call |
| `controllers.json` | `PilotSession`; absent under `self_play` | Pilot seat, opponent policy, and the CLI's `--auto-forced`. Evals leave that off and answer one-option prompts in `XMageGame` instead, as `model-controller.json` records |
| `engine.stderr.log` | `GameSession` (the JVM's stderr) | Diagnostics |
| `runtime-build.json` | `GameSession` | Copy of the installed runtime's `build.json`, if present |

`internal/` stays on the host. It is never put in a prompt or offered as a tool, on the assumption that the model cannot read the host filesystem.

### Verification

`xmage_poc/verify.py` (`python -m xmage_poc.verify <dir>`) runs after every game. If it fails, the rollout fails. It checks:

- **The recording against itself**: snapshot sequences and decision numbers are contiguous; a checkpoint's SHA-256 matches `sha256` (`full_audit`), or no snapshot claims a checkpoint and every snapshot is `start`/`decision`/`end` (`benchmark`); no card appears in two zones; all 120 cards are accounted for at empty-stack decisions; the first turn's active player is the manifest's starting player; each decision's `state_sequence` points to a `decision` snapshot of the same actor and number; and the `selected` action is the one at the response's index.
- **Each delivered observation against its decision snapshot**: the own hand IDs match, public hand and library counts and life totals match, no sideboard or library top is shown, no hidden card ID (any library card or the other seat's hand) appears anywhere in the observation, and no internal key (`library`, `deck_a`, `deck_b`, `checkpoint`, `sha256`) appears.
- **Player transcripts against decisions**: each `players/<seat>.jsonl` equals the observations in `decisions.jsonl` for that seat, every bridge player received decisions, and each `players/<seat>.context.json` equals the context derived from the manifest's decklist for that seat.
- **Model prompts against the audited observations**: from `decisions.jsonl` and `model-controller.json`, it works out which decisions should have reached a model and requires `model-prompts.jsonl` to cover exactly those, in order. It then re-renders each prompt's system message and observations and requires the recorded messages to match, with exactly the seat's last `history_decisions` observations and only fixed-schema corrections. Assistant messages are the model's own replies and are only type-checked.
- **The result**: the game ended with no errors or technical failure, the counts in `result.json` match the recording, the last snapshot is `end`, and play passed turn 1.

The JVM's `verify` command (`java -jar xmage_poc/runtime/xmage-poc.jar verify <dir>`) works only on `full_audit` recordings. It deserializes every checkpoint and compares its summary with the `states.jsonl` line. It restores each decision's checkpoint and rebuilds the actor's view, which must equal the delivered view apart from the wall-clock priority timer. At each bridge player's first `ASK` (mulligan) decision, it swaps an opponent hand card for a different library card and reverses both libraries, and the actor's view must not change. The integration tests (`XMAGE_INTEGRATION=1`) run it. Evals do not.

### Why the harness and the package look the way they do

`XMageHarness` subclasses verifiers' `NullHarness`, the tool-less chat loop, and replaces its `launch` and `resume`. The default `resume` sends the accumulated conversation plus the new turn. This environment rebuilds each seat's whole prompt per decision instead: it trims history to the last few blocks, regrows the glossary in the system message in text mode, and adds that seat's private corrections. So each model call must be exactly the message list recorded in `model-prompts.jsonl`, which is what the prompt audit checks. A game makes hundreds of calls, so the harness streams each completion in-process with `AsyncOpenAI` instead of launching the chat program per call. It still calls the rollout's interception endpoint, so the trace records every call. `XMageEnv.run` rejects seats configured with any other harness.

`xmage_poc/__init__.py` exports `XMageEnv`, `XMageTaskset`, and `XMageHarness` through a lazy module `__getattr__`. Importing them eagerly would load `verifiers` and `openai` whenever anything under `xmage_poc` is imported. The standalone CLIs, `xmage-poc` (`transport.main`) and `python -m xmage_poc.verify`, then start without Verifiers. `verify` imports `environment` only when a recording has model prompts to audit.

## Resuming checkpoints and labeling positions

A `full_audit` recording keeps a restorable engine checkpoint at every decision. The bridge can continue a game from one, the way XMage's own AIs continue copied games (`Game.resume()`). Only decisions the turn structure asks directly can be re-asked: priority, and the first declare-attackers or declare-blockers ask of a step. A choice made mid-cast (a target, a mana payment) or partway through a combat selection cannot.

- `java -cp xmage_poc/runtime/xmage-poc.jar lab.xmage.PocMain replay <recording> <decision>...|resumable` resumes each decision with the recorded answers and reports whether every later observation, every later engine event, and the winner match the original game. Only engine bookkeeping may differ: `gameCycle`, `totalEffectsCount`, `statesSavedSize`, fresh object IDs, and the events the resume itself fires (`PHASE_CHANGED`, plus the step's main event when resuming at priority).
- `... PocMain rollout <recording> <decision> [--playouts=N --seed=S --policy=greedy|random|mad --turn-cap=T]` lists every complete candidate action (a spell with its targets, an attacker subset, a blocker assignment) and plays each out from the same resampled hidden worlds. The actor's hidden information is resampled the way XMage's MCTS AI does it: the opponent's hand is shuffled into their library and redrawn, and both libraries are shuffled. `checks` confirms that the rollout seats see the recorded observation.
- `python -m xmage_poc.positions --recording <dir> --output questions.jsonl` turns those rollouts into "best move" questions. Each item has the seat's rendered board, the candidates and their win rates, and an `answer` only when the best candidate beats every alternative by a paired margin (`--z`, default 2 standard errors against one alternative, raised by a Bonferroni correction when there are more, since the best is picked from the same playouts). By default (`--boundary empty-stack`) only decisions with an empty stack become questions, so none needs "in response to" context; `--boundary any` also uses priority with spells or abilities on the stack. Either way the engine resumes at the question's own decision, mid-turn included, so the graded position is exactly the one shown.

Rollout labels are only as good as the rollout policy: `greedy` and `random` are fast heuristic players, and `mad` (XMage's search AI) is far slower. A playout takes about a second on these fixture decks.

## Coverage and limits

- **Cards and decks**: the runtime contains XMage's full card module, and `deck_a`/`deck_b` accept custom decklists, one `<count> <exact XMage card name>` per line with blank lines and `#` comments. Each deck must have exactly 60 cards, and unknown names fail. Format legality and copy limits are not checked. That a card loads does not mean the bridge can handle all of its decisions. The bundled White and Red decks are simple 24-land fixtures with no search, look, or reveal effects.
- **Decisions the bridge exposes**: yes/no, priority (play a land, cast, activate, or pass), mana payment, ability and mode choices, choice lists, targets, amounts and X (ranges up to 100), individual attackers and blockers, removing a combat selection, and an attack-all shortcut when XMage offers it. Multi-amount prompts list every allocation within XMage's per-field and total bounds, with XMage's default allocation first. Enumeration stops at 16 fields, a range of 100 per field, and 4,096 choices. Any other query type raises an error, and so does a target or playable object in a hidden zone. A hidden option is never turned into a named one.
- **What text prompts omit**: XMage's helper emblems (`myHelperEmblems`: the storm count, day/night, and radiation) are engine bookkeeping that no bundled card uses, so text observations neither list them nor add their rules to the glossary. The storm emblem's text changed with every spell, which added one glossary entry per count. They remain in `players/<seat>.jsonl` and in `json` observations. A custom deck with storm, daybound, or rad-counter cards would need them rendered again. Recordings whose model prompts include the old emblem block no longer pass the prompt audit, which re-renders with the current renderer.
- **Audit scope**: the privacy audit fits these duel fixtures. It assumes 120 cards in hand, library, graveyard, and battlefield, an empty sideboard, and no revealed library top. Tokens, exile or other extra zones, and search or reveal effects would need audit changes as well as adapter changes. Sideboarding and multiplayer are not supported.
- **Automatic answers**: a prompt that offers exactly one action is answered without a model call, because the bridge rejects every other index. Two settings, both on by default, cover this, for both model seats under `self_play`. `auto_pass_priority` covers `SELECT` priority prompts that offer only pass, at every priority stop the bridge keeps, including when the stack is not empty. `auto_forced` covers every other one-option prompt: mana payments (with the bundled decks, XMage offers one mana source per payment step), attack or block prompts whose only action is to finish, and required targets with one legal choice. Any prompt with two or more actions reaches the model. Automatic answers still appear in `decisions.jsonl` and `players/<seat>.jsonl`, and `automatic-priority.jsonl` and `automatic-forced.jsonl` list them. They are left out of model history, use no model turns, and are counted in the trace's `auto_passed_priority` and `auto_forced_decisions`. The prompt audit reads both settings from `model-controller.json`; recordings made before `auto_forced` existed are audited as if it were off. `scripts/smoke_xmage_poc_eval.py --no-auto-pass-priority` and `--no-auto-forced` exercise the opt-outs.
- **Scoring**: under `self_play`, the reward is `recording_validity`, which is 1 when the recording passes the audit. Against an in-engine opponent, the reward is `pilot_win`, XMage's `won` flag for the pilot's seat, counted only after the audit passes, and `recording_validity` is reported with weight 0. A loss, draw, rollout stopped by `max_turns` or a model error, or failed recording earns no win. An invalid reply alone does not: it gets a correction and, after `max_action_attempts`, the fallback action. `max_turns` counts model attempts per seat, including retries. Deck, seat, play/draw, history window, and opponent all affect results, so compare models only on controlled, balanced runs.
- **Opponents**: `scripted_v1` is a simple, readable baseline, not a strong player. `xmage_mad` (`ComputerPlayer7`, skill 4) searches a full copy of the game, including the pilot's real hand and library order, on a 12-second wall-clock budget shared across a 5-thread pool. Its strength depends on hardware and load, and its play is not deterministic. Pilot observations stay private either way.
- **Determinism and checkpoints**: decks are read in order, and each bridge player's shuffles come from a stream keyed by the seed and the deck's card list. Action order is stable for known cards. XMage's global `RandomUtil` generator is seeded too. UUIDs, clocks, and other engine internals are not deterministic, so the same seed can produce different traces. Checkpoints are the serializable `Game` graph with transport fields left out. Static state such as the global generator is outside that graph. They are for inspection (`xmage-poc.jar inspect <checkpoint>`), restoration audits, and resuming the decisions described in [Resuming checkpoints and labeling positions](#resuming-checkpoints-and-labeling-positions).

## Changing the runtime

The runtime is built from source only in CI. To change the bridge or the XMage pin:

1. Edit `bridge/` or `REVISION` in `scripts/build_xmage_poc.py`.
2. Push a tag such as `xmage-runtime-v2`. The `XMage runtime release` workflow builds XMage, runs the bridge's Java tests, and publishes `xmage-poc.jar`, `build.json`, and `release.json` as a release.
3. Pin the release: `gh release download xmage-runtime-v2 -p release.json -D environments/xmage_poc/xmage_poc/runtime --clobber`, then commit it.

The lifecycle smoke checks that the pinned `build.json` matches this checkout's bridge sources and XMage revision, so a bridge change without a new release fails CI.

To build locally instead (needs JDK 21, Maven 3.9+, and about 4 GB for the XMage checkout), run `python scripts/build_xmage_poc.py`. Then install with `XMAGE_POC_SKIP_DOWNLOAD=1`, which keeps that local runtime instead of replacing it with the pinned one.
