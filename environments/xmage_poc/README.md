# XMage pilot and recording proof of concept

`xmage-poc` runs a real, headless XMage duel with two 60-card fixture decks. Controllers receive the acting player's native XMage `GameView` and an indexed action list. A separate recorder stores both hands, both ordered libraries, public zones, events, actions, and compressed engine checkpoints.

This proves the separation needed for pilot evaluations: private controller inputs paired with omniscient training records. The default self-play mode scores recording validity. A single-seat baseline against the fixed `scripted_v1` opponent scores a verified pilot win and reports recording validity separately. Small smoke runs check behavior; they do not establish playing strength.

## Build and run locally

Use Python 3.12, JDK 21, Maven 3.9+, and `uv`. Run from the Lab root with the project virtualenv active. The environment was scaffolded with `prime env init xmage-poc`.

```bash
# Compatibility pins for the Prime CLI used for this POC.
uv pip install 'prime==0.6.35' 'prime-sandboxes==0.2.41' pytest
python scripts/build_xmage_poc.py
prime env install xmage-poc --no-upgrade --plain

# Enter action indices; enter "auto" to finish with the scripted policy.
xmage-poc --interactive --output environments/xmage_poc/outputs/my-game

# Advance an entire game locally, without an inference endpoint.
xmage-poc --output environments/xmage_poc/outputs/scripted-game

# Walk through one seat against a fixed opponent. Single-option choices can advance automatically.
xmage-poc --interactive --pilot-seat player_a --auto-forced \
  --output environments/xmage_poc/outputs/pilot-walkthrough
```

Each output path must be new. Set `XMAGE_JAVA_BIN` or pass `--java-bin` if Java is outside `PATH`. Set `JAVA_HOME` for builds. `build_xmage_poc.py --help` exposes existing-checkout and Maven executable/repository options.

The builder fetches [XMage at the pinned revision](https://github.com/magefree/mage/tree/afab346e06c4960882cf148acc57754c1c50a007) into `external/xmage/`, builds its full `Mage.Sets` card module together with core, native views, human-player decision handling, and the duel implementation, and packages them with our bridge. The source checkout remains unmodified and Git-ignored. The bridge uses `org.mage:mage-sets:1.4.62` as a Maven dependency; there is no copied ten-card source list.

The packaged catalog contains 32,174 card names from XMage's non-custom expansion-set metadata at this revision. Names resolve through that metadata, including punctuation and split-card names, and use real printing information. The full module is available, but a card's decision requirements may exceed the current adapter's coverage. Wheel and sdist packages bundle the runnable JAR, default decks, build hashes, and upstream MIT license. Installed games need Java but do not need Maven, a source checkout, or a background XMage server.

The full card build uses a 4 GiB Maven heap by default; set `MAVEN_OPTS` to override it. The bundled JAR is approximately 79 MiB. Inspect the catalog and try other decklists with:

```bash
java -Xmx1g -jar environments/xmage_poc/xmage_poc/runtime/xmage-poc.jar \
  cards 'Lightning Bolt' 'Ajani, Strength of the Pride' 'Fire // Ice'
xmage-poc --deck-a path/to/white.txt --deck-b path/to/red.txt \
  --output environments/xmage_poc/outputs/custom-game
```

Decklists contain one `<count> <exact XMage card name>` per line, with optional blank lines and `#` comments. Each deck must currently contain exactly 60 cards. Unknown names fail explicitly. Format legality and copy limits are not validated. The catalog command confirms card construction; it does not establish gameplay support for every card.

## Controller boundary and recordings

The engine writes one JSON decision to stdout and waits for a response:

```json
{"type":"decision","observation":{"decision":6,"player":"player_a","player_id":"…","query_type":"SELECT","message":"Play spells and abilities","view":{"…":"native player-specific GameView"},"actions":[{"index":0,"kind":"land","label":"Plains","response_type":"uuid","value":"…"}]}}
```

Respond with `{"decision":6,"action":0}`. The Prime adapter accepts `{"action":0}` and supplies the decision number. XMage validates and executes the underlying choice. Stale decision numbers and out-of-range actions are rejected.

Native decision observations contain the controller's own hand, public permanents, stack, graveyards, life totals, and hand/library counts. The model also receives its own registered decklist as persistent setup context: card names, copy counts, and total size. This context is captured from the input deck before the engine starts, is available from the first model decision (including mulligans), and remains in the system message throughout the game. It contains neither instance IDs nor live library contents/order. The opponent's decklist and hand stay private. Unsupported hidden-target queries fail instead of being converted into named options.

| File under a game output directory | Contents |
| --- | --- |
| `players/player_a.jsonl`, `players/player_b.jsonl` | Exact observations delivered to each controller |
| `players/player_a.context.json`, `players/player_b.context.json` | Each seat's own static registered decklist, captured before engine startup |
| `internal/manifest.json` | Engine revision, seed, both decklists, seat IDs, recording contract |
| `internal/states.jsonl` | State summaries, both private hands and ordered libraries, event metadata, sequence and checkpoint hashes |
| `internal/decisions.jsonl` | Acting seat, delivered observation, response, selected action, matching pre-decision state sequence |
| `internal/checkpoints/*.game.gz` | Gzip Java serialization of the complete serializable XMage `Game` object graph |
| `internal/result.json` | Outcome, decision/snapshot counts, errors, technical-failure status |
| `engine.stderr.log` | Diagnostics |
| `runtime-build.json` | Copy of the runtime build metadata captured at startup |
| `controllers.json` | Pilot seat, fixed-opponent policy name, and one-option automation setting in single-seat mode |
| `model-controller.json` | Eval mode, pilot seat, and automatic-priority policy |
| `automatic-priority.jsonl` | Decision IDs and responses for priority passes advanced without a model call |

JSON summaries are convenient projections. Binary checkpoints preserve additional engine details such as effects, combat state, and card abilities. Snapshots occur at game events, player updates, decisions, start, and end. Events can occur during a rules operation; a decision's `state_sequence` identifies its precise pre-response checkpoint.

Internal files stay on the harness side. They are not added to prompts or offered as model tools. This API boundary assumes pilots have no access to the harness filesystem.

## Verification

```bash
python -m xmage_poc.verify environments/xmage_poc/outputs/my-game
java -Xmx512m -jar environments/xmage_poc/xmage_poc/runtime/xmage-poc.jar \
  verify environments/xmage_poc/outputs/my-game

# Run a new real game plus privacy and checkpoint tests.
XMAGE_INTEGRATION=1 python -m pytest environments/xmage_poc/tests -q

# Inspect an engine checkpoint as JSON.
java -jar environments/xmage_poc/xmage_poc/runtime/xmage-poc.jar \
  inspect environments/xmage_poc/outputs/my-game/internal/checkpoints/000001.game.gz
```

The Python audit checks hashes, card conservation at empty-stack decisions, exact own-hand IDs, public counts/life, hidden IDs including those embedded in messages/actions, and equality of player transcripts to delivered inputs. When static context files are present, it verifies each against that seat's registered deck in the internal manifest. It requires a completed game with land plays, damage, and no engine or technical errors.

The Java audit deserializes every checkpoint and compares every summary field. It reconstructs each decision's native player view and compares it with the delivered view, excluding wall-clock priority timestamps. For both seats, it swaps an unseen opponent hand card with a different library card and reverses both libraries; the player view must remain identical.

Adversarial tests introduce hidden IDs, false counts, missing own-hand cards, and internal deck metadata. Privacy checks remain enabled under Python optimization.

## Prime adapter and local endpoint smoke

A separate engine process starts per rollout and closes during cleanup. In `opponent="self_play"` mode, both seats use the configured endpoint with separate histories. In `opponent="scripted"` mode, only the pilot seat calls the endpoint. The fixed opponent uses only its own native observations and never contributes messages to the pilot's history. It keeps opening hands, plays lands and spells, selects individual attackers/blockers, and chooses opposing players as burn targets. Prompts contain the last four decisions of the pilot's seat by default; `history_decisions` changes this window. Full transcripts remain recorded. The default budget is 4,000 model decisions.

```python
from xmage_poc import load_environment

load_environment(num_games=1, seed=7, history_decisions=4)
# Optional custom decklists; both paths are resolved before game startup.
load_environment(deck_a="path/to/white.txt", deck_b="path/to/red.txt")
# A pilot baseline alternates player_a and player_b across dataset rows.
load_environment(num_games=2, opponent="scripted", pilot_seat="alternate")
# Diagnostic opt-out: also ask the endpoint to select forced priority passes.
load_environment(auto_pass_priority=False)
```

Use the canonical eval path with a configured endpoint for actual model evaluations:

```bash
prime eval run xmage-poc -e configs/endpoints.toml -m <endpoint_id> \
  -n 1 -r 1 -c 1 -t 32 -A

# Two-game pilot behavior smoke against scripted_v1, one game from each deck/seat.
prime eval run configs/eval/xmage-pilot-smoke.toml \
  -e configs/endpoints.toml -m <endpoint_id> -A
```

The local smoke starts an OpenAI-compatible scripted endpoint, runs `prime eval run` against it, and checks every HTTP request against the correct seat's observation history and registered deck context. The deck context must persist even after early observations leave the history window:

```bash
python scripts/smoke_xmage_poc_eval.py --output environments/xmage_poc/outputs/prime-smoke
```

Prime requires a configured Prime API key even for this local endpoint. No paid inference calls are made. Standard Prime saving/upload behavior remains enabled. Without Prime credentials, test the adapter and HTTP boundary locally:

```bash
python scripts/smoke_xmage_poc_eval.py --protocol-only \
  --output environments/xmage_poc/outputs/adapter-smoke
```

The last command is a protocol integration test, not a platform evaluation. Its fabricated token counts and scripted controller cannot support conclusions about model quality. CI covers build, `prime env install`, load, a real game, privacy checks, the HTTP boundary, and wheel/sdist contents. The canonical Prime eval smoke runs on `main` when `PRIME_API_KEY` is configured.

## Coverage and limits

The runtime bundles the full card module and accepts custom 60-card decklists. The bundled decks are deliberately simple and land-heavy, not current Standard decks. Individual attackers and blockers, removal of combat selections, and XMage's follow-up defender/attacker target prompts are exposed. An attack-all shortcut is also available. Multi-amount prompts expose indexed allocations obeying XMage's individual and total bounds, with its valid default allocation first; enumeration is limited to 16 dimensions, ranges spanning at most 100 per dimension, and 4,096 choices. Ordinary combat is covered for these fixtures; unusual attack/block costs, multi-block abilities, special damage mechanics, sideboarding, search/reveal effects, multiplayer, and independent model opponents still need dedicated adapter/audit tests. Unsupported hidden-card queries fail closed. The recorder's JSON/privacy audits remain tailored to these simple duel fixtures, so introducing tokens, extra zones, or reveal/search effects will also require audit updates. XMage supplies the underlying card/rules engine.

The pilot-win reward uses XMage's per-player `won` flag after the full recording passes audit. A loss, draw, interrupted rollout, invalid response, or recording failure earns no win. Deck, first-player, history-window, and opponent-policy effects need controlled runs before comparing models. The scripted opponent is a transparent baseline, not a strong MTG player. Interactive `--auto-forced` advances all one-option pilot prompts.

API evaluations default to `auto_pass_priority=True`: when XMage asks for priority and the adapter offers only pass, the environment sends that response without calling the model. This applies to both model seats in self-play and to the pilot in scripted-opponent mode, including nonempty-stack windows. A cast/activate-or-pass choice still reaches the model, as do combat selections, targets, mana payments, and other non-priority queries, even if they offer just one option. Automatic passes remain in the engine decision log and original player streams; `automatic-priority.jsonl` identifies the responses sent automatically and `model-controller.json` records the policy. Rollout state tracks the `auto_passed_priority` count. These prompts are omitted from model history and do not consume model turns. Set `auto_pass_priority=False` for diagnostics; the HTTP smoke supports `--no-auto-pass-priority` to check that path.

Checkpoints preserve the current serializable engine graph, excluding transient transport, simulation bookkeeping, rollback histories, and global RNG. They support inspection, not exact pause/resume or deterministic replay. The seed is recorded, but UUID generation and collection ordering can change traces between runs. Pilot benchmarking still needs broader decisions, opponents, deck validation, and a performance rubric. Branching from recorded decisions would also need replay/resume support.
