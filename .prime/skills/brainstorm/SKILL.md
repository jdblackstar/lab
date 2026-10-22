---
name: brainstorm
description: Guides interactive research planning for this repo's verifiers 0.4 environments, evaluations, prompt optimization, and RL experiments. Use for ideation, concept teaching, literature review, or experiment roadmaps.
---

# Brainstorm

Turn research goals into concrete, testable environment/evaluation plans. Clarify the
objective, model, data access, budget, and timeline without blocking on choices that can
be grounded in the repo.

## Ground plans in the current stack

1. Read `AGENTS.md`, `environments/AGENTS.md`, relevant package READMEs, and the applicable
   `.prime/skills/` workflow. The repo uses verifiers 0.4's `verifiers.v1` taskset/task/env
   model and pinned prime-rl eval runner; don't propose v0 factory/rubric APIs.
2. Match ideas to the actual task/reward/data contract. Distinguish binary and continuous
   rewards, model capability from harness capability, and smoke data from real benchmarks.
3. Check current CLI help/source before promising GEPA, hosted training, or trainer config
   support. Use `vf-gepa` for the v1 prompt-optimization path and verify training integration
   separately. The endpoint registry and generated configs are not universal runner inputs.
4. For literature-dependent claims, use primary sources and include dates. Don't impose
   an arbitrary publication cutoff or recommend model families from stale template lists.
5. Respect answer-key isolation and private menu data: local validation, private outputs,
   no implicit uploads, and permission before provider calls on real data.

Present a short ranked set of ideas, then develop the selected direction. Plans should
include assumptions, implementation effort, metrics, held-out evaluation, milestones,
go/no-go criteria, risks, and decisions that genuinely need the user. Publishing is an
optional distribution step after validation, not a prerequisite for experiments; get
explicit destination and visibility approval before any push.
