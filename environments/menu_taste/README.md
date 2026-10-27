# menu-taste

Can a model tell how a menu was composed? Each question shows a real catering menu with
one dish removed and asks which of four dishes was the one taken out. The three wrong
options are dishes of the same course from the caterer's *other* menus, so every option
is written in the same voice. What separates the right answer is fit: balance, pacing,
season, and service style.

- **Environment id:** `menu-taste`
- **Type:** single turn, multiple choice
- **Reward:** `correct_choice` (1 if the letter in `<answer>` tags is right); metric
  `answered` (a valid letter was given)

## Quickstart

Built on verifiers 0.4 (`verifiers.v1`): the package exports `MenuTasteTaskset` and
`MenuTasteEnv`. The env pins a plain chat: the `null` harness with no tools, the local
subprocess runtime, and one reply per question (`max_turns` 1). It refuses harnesses
that execute code, since a shell on the evaluator host could read the answer key.

Evals run through prime-rl's `uv run eval` via
[`scripts/prime_rl_eval.sh`](../../scripts/prime_rl_eval.sh). From the repo root:

```bash
scripts/prime_rl_eval.sh environments/menu_taste menu-taste \
  -m deepseek/deepseek-v4-flash -n 3 -r 1 -c 3 \
  --output-dir outputs/menu-taste --run.name smoke
```

The eval exits 0 even when rollouts error, so check
`outputs/menu-taste/smoke/monitors/file/traces/stream.index.jsonl` for `"ok": true` on
every line (`"num_errors"` stays 0 when the model call fails).

Without a question set or corpus the taskset loads 93 questions from a bundled sample of
13 synthetic menus. It exists for smoke tests; scores on it mean nothing.

Check the answer keys without a model (every gold answer must score 1, an empty reply
0). Always pass `--runtime.type subprocess`: `vf-validate` checks the taskset, not the
env, so it ignores the env's runtime and defaults to hosted Prime sandboxes.

```bash
cd environments/menu_taste
uv run vf-validate menu-taste --runtime.type subprocess
uv run pytest
```

## Results

No model has been scored on the real question set yet, so there is no table here. To
make one, freeze a question set (next section), then run every model on it from
`environments/menu_taste`:

```bash
uv run menu-taste-results private/questions-v1.jsonl -m <model> -m <model> -r 3
```

This runs each model through the environment with prime-rl's eval (`-r` answers per
question, `-c 8` at a time, Prime Inference with `PRIME_API_KEY` by default),
decompresses the traces, scores all runs together, and writes
`private/results/questions-v1/results.md`. That file is the section to paste here. It
holds:

- accuracy with 95% intervals resampled by menu, next to the question set's stored
  no-taste baselines;
- accuracy by course;
- accuracy on questions where the "most words shared with the menu" rule picks the
  answer, picks another option, or ties, and on questions whose answer shares no words
  with the menu, so a score can't come from that cue alone;
- which letters each model favors, and how often each pair of models chose the same
  dish.

The eval exits 0 even when rollouts fail. `menu-taste-results` counts failed rollouts
instead of scoring them, and exits 1 if any rollout errored or a run is incomplete.
Running it again reuses complete runs and repeats only the failed ones. Arguments after
`--` go to the eval unchanged, for example `-- --client.base-url <url>
--client.api-key-var <VAR>` for another OpenAI-compatible endpoint. Runs and traces stay
next to the question set, under `private/`.

Scores from Claude Code subagents answering batches (below) come from a different
setup and don't belong in this table.

## Running a real eval

Real evals read a **frozen question set**, so every model and every run gets the same
questions, and which menus leave the machine is decided once:

```bash
cd environments/menu_taste
uv run menu-taste-questions build private/menus.jsonl -o private/questions-v1.jsonl
uv run vf-validate menu-taste --runtime.type subprocess \
  --taskset.questions-path private/questions-v1.jsonl --output-dir private/validate

cd ../..
scripts/prime_rl_eval.sh environments/menu_taste menu-taste -m <model> -r 1 -c 8 \
  --env.taskset.questions-path "$PWD/environments/menu_taste/private/questions-v1.jsonl" \
  --output-dir environments/menu_taste/private/evals --run.name <run>
zstd -dc environments/menu_taste/private/evals/<run>/monitors/file/traces/stream/*.jsonl.zst \
  > environments/menu_taste/private/runs/<run>.jsonl
cd environments/menu_taste
uv run menu-taste-score private/questions-v1.jsonl private/runs/<run>.jsonl
```

Use `-n N` to ask the first N questions and `-s` (`--select.seed`) to shuffle them.
`menu-taste-score` also reads the `traces.jsonl` a verifiers `run_eval` writes.

`build` also writes `questions-v1.meta.json`: the corpus hash, the build settings, and
the no-taste baselines for exactly these questions, which the score report shows next to
each model.

Every trace contains a whole menu, so on private questions:

- never pass `--monitors.prime` (it uploads traces to the Prime platform), and keep
  `--output-dir` under `private/`;
- always run `vf-validate` with `--runtime.type subprocess`.

`menu-taste-score` reports accuracy with 95% intervals resampled by menu (questions from
one menu aren't independent), accuracy by course and by the word-overlap cuts under
[Results](#results), which letters each run favors, and for
two or more runs on the same questions, how often they chose the same dish and the
accuracy difference with an interval. Set `--env.taskset.rotation` (1–3) to shift
every question's options; comparing rotations shows position bias.

### Answering with Claude Code subagents

Batches let an agent answer several questions at once, for example a Claude Code
subagent on a small model:

```bash
uv run menu-taste-questions batches private/questions-v1.jsonl --out private/runs/haiku-r0
# each agent reads batch-NNN.md and writes answers-NNN.md (### q-id, reasoning, <answer>)
uv run menu-taste-questions collect private/runs/haiku-r0 -o private/runs/haiku-r0.jsonl
uv run menu-taste-score private/questions-v1.jsonl private/runs/haiku-r0.jsonl
```

Two questions from the same menu (or versions of it) never share a batch, since one
shows the dish the other hides, and no question shares a batch with one whose text
contains its hidden dish. Agents that can read files could read the answer key, so
make the question set and corpus unreadable (`chmod 000`) while they run, and check
afterward that each agent only read its batch and wrote its answers. Batched answers
come from a different setup than one-question API calls (a long context, a coding-agent
system prompt), so don't compare those scores with API eval scores. Keep batches
small (the default is 15): with 25 per batch, Haiku's accuracy fell from about 49% to
40% on the last five questions.

Taskset arguments (`--env.taskset.<name>` for evals, `--taskset.<name>` for
`vf-validate`; use dashes, e.g. `--env.taskset.max-menus 50`):

| Argument | Default | Meaning |
| --- | --- | --- |
| `questions_path` | `$MENU_TASTE_QUESTIONS` | Frozen question set; when set, the corpus arguments below are ignored |
| `rotation` | `0` | Shift each question's options by this many places (frozen sets only) |
| `menus_path` | `$MENU_TASTE_MENUS`, then the sample | JSONL corpus from `menu-taste-ingest` |
| `num_options` | `4` | Choices per question, including the right one |
| `courses` | food courses | Which courses to hide, e.g. `["main", "dessert"]` |
| `include_drinks` | `false` | Also hide cocktails, wine, and other drinks |
| `max_per_menu` | none | Cap questions per menu |
| `min_menu_items` | `4` | Don't ask about menus with fewer dishes (they still supply wrong options) |
| `max_menus` | all | Ask about a seeded sample of menus; bounds how much of the corpus one run shows a provider |
| `max_per_dish` | `2` | How many questions one dish can answer; house staples would otherwise dominate (`null` for no cap) |
| `match_surface` | `true` | Wrong options look like the answer: description or not, dietary tags or not, similar popularity |
| `seed` | `0` | Option order and distractor choice when building from a corpus; shuffle the run with `-s` |

## Building a corpus from raw menus

`menu-taste-ingest` turns a folder of menus in any format into one JSONL corpus. It
detects files by content, not extension, and handles PDFs (designed or scanned), phone
photos (rotation applied, HEIC supported), Word, PowerPoint, Excel event orders, CSV,
HTML, RTF, plain text, `.eml` emails with attachments, and ZIP archives. Legacy `.doc`
and `.xls` files work when LibreOffice is installed. Claude reads each document once and
returns structured menus.

```bash
cd environments/menu_taste
uv sync --extra ingest

uv run menu-taste-ingest inspect ~/menus/            # what was found; no API calls
uv run menu-taste-ingest run ~/menus/ -o private/menus.jsonl
uv run menu-taste-ingest stats private/menus.jsonl            # counts + question yield
uv run menu-taste-ingest render private/menus.jsonl           # read them back as text
```

Spreadsheets where each row is a menu of (title, description) column pairs, with
section headers written into the dish cells, import without any model:

```bash
uv run menu-taste-ingest layout private/raw/menus.xlsx --headers   # structure only, text hidden
uv run menu-taste-ingest import-grid private/raw/menus.xlsx -o private/menus.jsonl \
  --scrub-file private/scrub.txt --pairs 20
```

The importer reads headers ("FAMILY STYLE MAINS", "Passed Canapés") as course and
service, splits "SALAD COURSE: Frisée Salad" cells, reads dietary tags like "(VG/GF)",
reads "*GF" tags, treats "Ramen Station" as a sub-header when its dishes are listed
after it (and as the dish when nothing is), moves house bread and sides listed with
entrées into their own courses, and leaves out
vendor and staff meals, items the client provided, placeholders ("TBD", "tasting only"),
and exact duplicate rows. "Choose 4" over a longer list marks a proposal (catalog).
`--scrub-file` lists business, supplier, and venue names to remove, one per line; it
identifies the caterer, so keep it in `private/`.

`run` is resumable and skips files it has already processed (matched by content hash),
so you can add files and re-run it. Raw model output is cached in
`private/.extract-cache/`. Read `private/menus.review.md` before using a corpus: it lists
files that failed and menus flagged for possible client details.

By default it calls the Anthropic API (`claude-opus-5-5`, `ANTHROPIC_API_KEY`, with
server-side refusal fallbacks). Any Anthropic-compatible endpoint also works, for
example Prime Inference:

```bash
uv run menu-taste-ingest run ~/menus -o private/menus.jsonl \
  --base-url https://api.pinference.ai/api --api-key-env PRIME_API_KEY \
  --model anthropic/claude-opus-5.5 --no-fallbacks
```

### Privacy

- Prices, contact details, client, host, venue and company names, and exact dates are
  left out by the extractor and scrubbed again afterward. Possible names and events
  ("The Goldberg Wedding", "in honor of …") are flagged for review, not deleted.
- `environments/menu_taste/private/` is git-ignored. Keep real corpora there.
- Eval traces and `vf-validate` output contain whole menus; keep them in `private/` and
  never upload them (`--monitors.prime`).
- Both ingestion and evaluation send menu text to model providers. Check that whatever
  agreement covers the menus allows that before running them. Don't push an environment
  that bundles real menus to the Hub as public.

## The menu format

Defined in `menu_taste/schema.py`. A menu is an ordered list of sections. Each section
records its role in the meal (`course`) and how it reaches guests (`service`), so one
record can describe passed hors d'oeuvres and a raw bar display, a family-style main
course, dessert stations, and a bar.

```text
Menu
  kind        event | sample | package | catalog | unknown
  service     plated | family_style | buffet | stations | passed | display |
              reception | drop_off | mixed | unknown
  event       event_type, meal_period, month, season, guest_count (banded)
  sections[]  course     hors_doeuvres, raw_bar, display, soup, salad, appetizer, pasta,
                         intermezzo, main, side, cheese, dessert, late_night, kids,
                         cocktail, wine, beer, spirits, non_alcoholic, coffee_tea,
                         bar_service, bread, other
              service    overrides the menu's (passed bites at a plated dinner)
              selection  all | guest_choice (entrée choice) | host_choice (pick 3 of 8)
              items[]    name, description, dietary tags, role, pairing
  notes, source (content hash only), warnings
```

There are no fields for price or client.

## How questions are built

- Only `event` and `sample` menus become questions or supply wrong options. Packages and
  catalogs ("choose three of the following") list options rather than a composed meal.
- Wrong options are dishes of the same course. They never come from the target menu,
  from a near-identical version of it (half its dishes shared), or from dishes that
  resemble anything already on the menu.
- Sections in `host_choice` mode, dietary alternates, kids' meals, and upgrades are never
  hidden.
- Menus are rendered the same way no matter the source format, and section headings are
  replaced with standard course labels. A verbatim heading like "Cheese Board" would give
  the answer away without any judgment.

- Wrong options match the answer's surface: whether it has a description and dietary
  tags, and how many menus serve it. A single dish answers at most two questions.

## Checking for shortcuts

`menu-taste-baselines` answers the questions with cues that need no taste (words shared
with the menu, description length, writing style, how common a dish is) and with a
model trained to combine them, scored on held-out menus. It runs locally and sends
nothing anywhere.

```bash
uv run menu-taste-baselines private/menus.jsonl
uv run menu-taste-baselines private/menus.jsonl --no-surface-matching --max-per-dish 0  # the leaks
```

The best of these should stay near chance. Sharing words with the menu always helps a
little, because real menus repeat a theme (a summer menu uses watermelon twice); that
is the bar a model has to clear.

## Training on this

**What a model would learn.** The corpus is one caterer. The cheapest way to raise
reward on it is to memorize that caterer's habits: which dishes it puts together,
which it serves in spring, how its dish names are written. A model that learned only
that would score well on more of the same caterer's menus and know nothing about
composing menus. Taste would be the general part: a heavy main wants a light dessert,
courses shouldn't repeat a flavor, a passed course needs finger food, a summer menu
uses summer produce. Those rules also hold for other caterers. Reward alone can't tell
the two apart, so training on the whole corpus and scoring on it measures memory.

**The split.** `build --eval-fraction` writes separate train and eval sets:

```bash
uv run menu-taste-questions build private/menus.jsonl -o private/questions-v2.jsonl \
  --eval-fraction 0.2
# -> private/questions-v2-train.jsonl, private/questions-v2-eval.jsonl (+ .meta.json)
```

- Whole menu families (a menu and its versions, the relation behind
  `related_menu_ids`, joined transitively over every menu, including ones too small
  to ask about) go to one side, so no eval menu or version of it is trained on.
- Each side's questions, wrong options included, are built from that side's menus only.
  An eval question is dropped if any of its options appears in a training menu or
  option list. Every eval answer, and every wrong option next to it, is a dish the
  model never saw in training. Matching is by name (case and spacing ignored, a longer
  name containing it counts), so a renamed dish ("Plum Galette" for "Plum Tart") gets
  through.

Each `.meta.json` has a `split` block with the seed, menus and questions per side, how
many eval questions were dropped, and the largest family's question count. Versions
chain, so one family can hold much of a corpus; if it does, the split can't be
balanced. Baselines are recomputed per side. Eval questions draw wrong options from
fewer menus than an unsplit build does, so don't compare their scores with v1 scores.

**The transfer test.** Train on the train families
([`configs/rl/menu-taste.toml`](../../configs/rl/menu-taste.toml), or GEPA with
[`configs/gepa/base.toml`](../../configs/gepa/base.toml)). Then score the trained model
and the same model untrained on the eval families, on the same questions and rotations.
The RL config's eval runs before step 0, which gives the untrained number. Report both
with `menu-taste-score`, along with the eval set's baselines.

**What would count as transfer:** the trained model beats the untrained one on the eval
families, the 95% interval of the difference (resampled by menu) excludes zero, and the
gain shows up on most courses, not one. Accuracy should rise on the train families too.
If it rises there and not on the eval families, the model learned this caterer, not
composition. That outcome is plausible: eval menus show dishes it never saw, and
whatever general rules exist may be too weak in one caterer's data to learn from
binary rewards. A trained score that doesn't clear the eval set's best shortcut
baseline, or a gain that vanishes when the options are rotated, doesn't count either.

For hosted runs (`prime train`), the config needs the environment on the Hub with the
question files bundled; the steps are in the config's comments. Doing that sends the
menus to Prime.

## Known gaps

- No human ceiling yet. Some questions may be honest toss-ups (one dessert bar against
  another) that no amount of taste resolves; have a person answer a sample to find out
  how many are unfair.
- Boards and platters listed under a "passed" heading stay in the passed section, so a
  model that reasons about service rejects them. This affects 40 questions in v1 (10
  where the board is the answer); fix it in the importer before building v2.
- Only one task so far. Natural next steps: spot the intruder dish, and real vs. generic
  menus for the same brief.
