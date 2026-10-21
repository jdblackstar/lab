"""menu-taste taskset: pick the dish that was removed from a caterer's menu.

Each task is one multiple-choice question: a real menu with one dish hidden, the hidden
dish, and same-course dishes from the caterer's other menus. The model answers with a
letter in <answer> tags, scored deterministically against the question's key.

Real evals read a frozen question set (``questions_path``, built by
``menu-taste-questions build``), so every run asks the same questions. Without one, the
questions are built from a corpus (``menus_path``), by default the bundled synthetic
sample, which exists only for smoke tests.
"""

from __future__ import annotations

import os

import verifiers.v1 as vf

from .cloze import LETTERS, SYSTEM_PROMPT, cloze_questions
from .corpus import load_menus, resolve_corpus
from .questions import load_question_set, record, to_row
from .schema import Course
from .scoring import extract_letter

MAX_TURNS = 1
"""One model reply per question, as in v0's single-turn environment."""


class MenuTasteData(vf.TaskData):
    answer: str
    """The right letter, after ``rotation``."""
    num_options: int
    menu_id: str
    course: str
    rotation: int = 0
    target: str
    """The hidden dish."""
    options: list[str]
    """Option dish names in the order shown."""


class MenuTasteTask(vf.Task[MenuTasteData]):
    def letter(self, trace: vf.Trace) -> str | None:
        return extract_letter(trace.last_reply, self.data.num_options)

    @vf.reward(weight=1.0)
    async def correct_choice(self, trace: vf.Trace) -> float:
        """1.0 if the letter in the last <answer> tag is the hidden dish."""
        return float(self.letter(trace) == self.data.answer)

    @vf.metric
    async def answered(self, trace: vf.Trace) -> float:
        """1.0 if the reply held any valid letter in <answer> tags."""
        return float(self.letter(trace) is not None)

    async def validate(self, runtime: vf.Runtime) -> bool:
        """The key is a valid letter and points at the hidden dish."""
        data = self.data
        if data.answer not in LETTERS[: data.num_options]:
            return False
        if len(data.options) != data.num_options:
            return False
        return data.options[LETTERS.index(data.answer)] == data.target


class MenuTasteConfig(vf.TasksetConfig):
    questions_path: str | None = None
    """Frozen question set (``menu-taste-questions build``); falls back to
    ``$MENU_TASTE_QUESTIONS``. When set, the corpus fields below are ignored."""
    rotation: int = 0
    """Shift every question's options by this many places, to check position bias."""

    menus_path: str | None = None
    """Corpus to build questions from when there is no frozen set; falls back to
    ``$MENU_TASTE_MENUS``, then the bundled synthetic sample."""
    num_options: int = 4
    courses: list[str] | None = None
    """Courses to hide (``schema.Course`` values); defaults to food courses."""
    include_drinks: bool = False
    max_per_menu: int | None = None
    min_menu_items: int = 4
    max_menus: int | None = None
    """Ask about a seeded sample of this many menus; bounds what one run reveals."""
    max_per_dish: int | None = 2
    match_surface: bool = True
    seed: int = 0
    """Distractor choice when building from a corpus. Shuffle the run's questions with
    ``-s`` (``--select.seed``) instead."""


class MenuTasteTaskset(vf.Taskset[MenuTasteTask, MenuTasteConfig]):
    def load(self) -> list[MenuTasteTask]:
        config = self.config
        path = config.questions_path or os.environ.get("MENU_TASTE_QUESTIONS")
        if path:
            records = load_question_set(path)
            source = path
        else:
            corpus = resolve_corpus(config.menus_path)
            questions = cloze_questions(
                load_menus(corpus),
                num_options=config.num_options,
                courses=frozenset(Course(c) for c in config.courses)
                if config.courses
                else None,
                include_drinks=config.include_drinks,
                max_per_menu=config.max_per_menu,
                min_menu_items=config.min_menu_items,
                max_menus=config.max_menus,
                max_per_dish=config.max_per_dish,
                match_surface=config.match_surface,
                seed=config.seed,
            )
            records = [record(q) for q in questions]
            source = str(corpus)
        if not records:
            raise ValueError(
                f"No questions could be built from {source}. Each question needs "
                "same-course dishes from unrelated menus as wrong options."
            )
        tasks = []
        for rec in records:
            row = to_row(rec, config.rotation)
            info = row["info"]
            data = MenuTasteData(
                id=rec["id"],
                prompt=row["question"],
                system_prompt=SYSTEM_PROMPT,
                answer=row["answer"],
                num_options=len(rec["options"]),
                menu_id=info["menu_id"],
                course=info["course"],
                rotation=config.rotation,
                target=info["target"],
                options=_rotated(info["options"], config.rotation),
            )
            tasks.append(MenuTasteTask(data, config.task))
        return tasks


def _rotated(options: list[str], rotation: int) -> list[str]:
    r = rotation % len(options)
    return options[r:] + options[:r]


class MenuTasteEnvConfig(vf.SingleAgentEnvConfig):
    agent: vf.AgentConfig = vf.AgentConfig(
        harness={"id": "null"},
        runtime=vf.SubprocessConfig(),
        max_turns=MAX_TURNS,
    )
    """A plain chat (the tools-only ``null`` harness with no tools) on the local
    subprocess runtime, one reply per question."""


class MenuTasteEnv(vf.SingleAgentEnv, vf.Env[MenuTasteEnvConfig]):
    """The single-agent env with menu-taste's defaults pinned.

    Harnesses that execute code are refused: a shell on the evaluator host could read
    the question set's answer key or the private corpus instead of judging the menu.
    """

    def __init__(self, config: MenuTasteEnvConfig) -> None:
        super().__init__(config)
        for role, harness_config in config.agent_harnesses().items():
            if vf.load_harness(harness_config).EXECUTES_CODE:
                raise ValueError(
                    f"menu-taste needs a harness that can't run code; {role!r} uses "
                    f"{harness_config.id!r}, which could read the answer key. Use "
                    "--env.agent.harness.id null."
                )
