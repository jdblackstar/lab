# Recorded XMage match — seed 17

White (`player_a`): Codex interactive choices in this chat. Red (`player_b`): fixed `scripted_v1` opponent.

**Result:** Red wins on game turn 22. Final life: White 0, Red 13. No recorded engine errors.

This document renders the existing recording; no gameplay or decision reasoning has been invented. The play-by-play is from White’s information perspective: White’s draws/hand are shown, while Red’s unrevealed draws/hand and both library orders are omitted. Public plays are shown when they happen.

The source recording contains 587 decision requests/responses and 2,419 state snapshots, each with a serialized engine checkpoint. Of the decisions, 63 were manual Codex choices, 228 were White prompts advanced automatically because only one option was offered, and 296 were answered by the scripted opponent. Routine phase transitions, untaps, mana payments, and priority passes are abbreviated in the play-by-play; all 587 responses are listed in the appendix. Full prompt observations and event/state data remain in the raw files.

Game turns below alternate White and Red. They are distinct from model decision turns. Creature names include an eight-character instance ID to distinguish copies. `D` references the decision number; `S` references the recorded snapshot sequence.

## Source and controller policy

This is the actual seed-17 interactive walkthrough, with White piloted by Codex and Red by `scripted_v1`. It is a protocol demonstration, not an independent API-model benchmark. This run preceded persistent registered-deck context and automatic priority passing in API evaluations. Its interactive `--auto-forced` policy advanced every one-option White prompt, including mana payments.

Raw logs and checkpoints remain locally under `environments/xmage_poc/outputs/pilot-walkthrough-seed17/`, which is Git-ignored. The source files are `internal/decisions.jsonl`, `internal/states.jsonl`, and `players/player_a.jsonl`. Decision and snapshot IDs below refer to those files. The raw recordings were preserved when this portable document was exported.

To start another interactive walkthrough:

```bash
xmage-poc --interactive --pilot-seat player_a --auto-forced --seed 17 \
  --output environments/xmage_poc/outputs/another-walkthrough
```

The seed does not guarantee identical UUIDs or action ordering; checkpoints support inspection rather than exact replay.

## Opening

White’s opening hand: 5× Plains, 1× Pillarfield Ox, 1× Youthful Knight.

D1: White selects White as the starting player. D2: White keeps seven cards. D3: Red keeps seven cards; their identities are hidden from White.

## Turn-by-turn play-by-play

| Game turn | Active player | Life after turn |
| --- | --- | --- |
| 1 | White (Codex) | White 20 — Red 20 |
| 2 | Red (scripted) | White 18 — Red 20 |
| 3 | White (Codex) | White 18 — Red 20 |
| 4 | Red (scripted) | White 18 — Red 20 |
| 5 | White (Codex) | White 18 — Red 20 |
| 6 | Red (scripted) | White 18 — Red 20 |
| 7 | White (Codex) | White 19 — Red 19 |
| 8 | Red (scripted) | White 19 — Red 19 |
| 9 | White (Codex) | White 20 — Red 18 |
| 10 | Red (scripted) | White 20 — Red 18 |
| 11 | White (Codex) | White 21 — Red 17 |
| 12 | Red (scripted) | White 18 — Red 17 |
| 13 | White (Codex) | White 19 — Red 16 |
| 14 | Red (scripted) | White 16 — Red 16 |
| 15 | White (Codex) | White 17 — Red 15 |
| 16 | Red (scripted) | White 11 — Red 15 |
| 17 | White (Codex) | White 12 — Red 14 |
| 18 | Red (scripted) | White 8 — Red 14 |
| 19 | White (Codex) | White 9 — Red 13 |
| 20 | Red (scripted) | White 2 — Red 13 |
| 21 | White (Codex) | White 2 — Red 13 |
| 22 | Red (scripted) | White 0 — Red 13 |

### Game turn 1: White (Codex)

Life at start: White 20 — Red 20.

- S42: White (Codex) plays Plains.
- No attackers declared.

**Life after turn:** White 20 — Red 20.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D6 / S40 | Play spells and abilities | index 0: Plains [cfa820c2] | 6 |

Other recorded responses this turn: 7 automatic White prompts; 7 scripted Red prompts. See the decision appendix for each response.

### Game turn 2: Red (scripted)

Life at start: White 20 — Red 20.

- S99: Red draws one card; identity hidden from White.
- S114: Red (scripted) plays Mountain.
- S126: Red (scripted) casts Shock.
- S131: Damage: Shock deals 2 to White (Codex).
- No attackers declared.

**Life after turn:** White 18 — Red 20.

Other recorded responses this turn: 9 automatic White prompts; 13 scripted Red prompts. See the decision appendix for each response.

### Game turn 3: White (Codex)

Life at start: White 18 — Red 20.

- S190: White (Codex) draws Healer's Hawk [e90e630e].
- S205: White (Codex) plays Plains.
- S222: White (Codex) casts Youthful Knight [10efb749].
- No attackers declared.

**Life after turn:** White 18 — Red 20.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D45 / S203 | Play spells and abilities | index 0: Plains [d4fa6220] | 6 |
| D46 / S206 | Play spells and abilities | index 0: Youthful Knight [10efb749] | 3 |

Other recorded responses this turn: 11 automatic White prompts; 9 scripted Red prompts. See the decision appendix for each response.

### Game turn 4: Red (scripted)

Life at start: White 18 — Red 20.

- S284: Red draws one card; identity hidden from White.
- S299: Red (scripted) plays Mountain.
- S316: Red (scripted) casts Goblin Piker [fde75872].
- No attackers declared.

**Life after turn:** White 18 — Red 20.

Other recorded responses this turn: 9 automatic White prompts; 13 scripted Red prompts. See the decision appendix for each response.

### Game turn 5: White (Codex)

Life at start: White 18 — Red 20.

- S379: White (Codex) draws Plains.
- S394: White (Codex) plays Plains.
- S405: White (Codex) casts Healer's Hawk [e90e630e].
- S432: Attackers: Youthful Knight [10efb749].
- S435: Goblin Piker [fde75872] blocks Youthful Knight [10efb749].
- S444: First-strike damage: Youthful Knight [10efb749] deals 2 to Goblin Piker [fde75872].
- S448: Goblin Piker [fde75872] dies.

**Life after turn:** White 18 — Red 20.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D89 / S392 | Play spells and abilities | index 0: Plains [2fc8ede5] | 6 |
| D90 / S395 | Play spells and abilities | index 0: Healer's Hawk [e90e630e] | 2 |
| D98 / S423 | Select attackers | index 0: Attack with Youthful Knight [10efb749] | 3 |
| D99 / S424 | Select attackers | index 1: Done / pass priority | 2 |

Other recorded responses this turn: 13 automatic White prompts; 14 scripted Red prompts. See the decision appendix for each response.

### Game turn 6: Red (scripted)

Life at start: White 18 — Red 20.

- S499: Red draws one card; identity hidden from White.
- S514: Red (scripted) plays Mountain.
- S531: Red (scripted) casts Goblin Piker [89244db1].
- No attackers declared.

**Life after turn:** White 18 — Red 20.

Other recorded responses this turn: 9 automatic White prompts; 13 scripted Red prompts. See the decision appendix for each response.

### Game turn 7: White (Codex)

Life at start: White 18 — Red 20.

- S594: White (Codex) draws Plains.
- S609: White (Codex) plays Plains.
- S638: White (Codex) casts Pillarfield Ox [d0954cb8].
- S667: Attackers: Youthful Knight [10efb749], Healer's Hawk [e90e630e].
- S671: Goblin Piker [89244db1] blocks Youthful Knight [10efb749].
- S680: First-strike damage: Youthful Knight [10efb749] deals 2 to Goblin Piker [89244db1].
- S684: Goblin Piker [89244db1] dies.
- S690: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S691: White (Codex) gains 1 life.

**Life after turn:** White 19 — Red 19.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D142 / S607 | Play spells and abilities | index 0: Plains [9d9a5765] | 5 |
| D143 / S610 | Play spells and abilities | index 0: Pillarfield Ox [d0954cb8] | 2 |
| D154 / S656 | Select attackers | index 0: Attack with Youthful Knight [10efb749] | 4 |
| D155 / S657 | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] | 4 |
| D156 / S658 | Select attackers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 16 automatic White prompts; 14 scripted Red prompts. See the decision appendix for each response.

### Game turn 8: Red (scripted)

Life at start: White 19 — Red 19.

- S738: Red draws one card; identity hidden from White.
- S753: Red (scripted) plays Mountain.
- S782: Red (scripted) casts Hill Giant [d7d1ae69].
- No attackers declared.

**Life after turn:** White 19 — Red 19.

Other recorded responses this turn: 9 automatic White prompts; 15 scripted Red prompts. See the decision appendix for each response.

### Game turn 9: White (Codex)

Life at start: White 19 — Red 19.

- S849: White (Codex) draws Plains.
- S864: White (Codex) plays Plains.
- S887: Attackers: Healer's Hawk [e90e630e].
- S897: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S898: White (Codex) gains 1 life.

**Life after turn:** White 20 — Red 18.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D201 / S862 | Play spells and abilities | index 0: Plains [ba12e661] | 5 |
| D206 / S878 | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] | 5 |
| D207 / S879 | Select attackers | index 4: Done / pass priority | 5 |

Other recorded responses this turn: 10 automatic White prompts; 11 scripted Red prompts. See the decision appendix for each response.

### Game turn 10: Red (scripted)

Life at start: White 20 — Red 18.

- S947: Red draws one card; identity hidden from White.
- S962: Red (scripted) plays Mountain.
- S991: Red (scripted) casts Hill Giant [db6dcf53].
- S1018: Attackers: Hill Giant [d7d1ae69].
- S1021: Pillarfield Ox [d0954cb8] blocks Hill Giant [d7d1ae69].
- S1030: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Hill Giant [d7d1ae69].
- S1031: Combat damage: Hill Giant [d7d1ae69] deals 3 to Pillarfield Ox [d0954cb8].

**Life after turn:** White 20 — Red 18.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D241 / S1018 | Select blockers | index 1: Choose blocker Pillarfield Ox [d0954cb8] | 3 |
| D242 / S1019 | Select blockers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 11 automatic White prompts; 19 scripted Red prompts. See the decision appendix for each response.

### Game turn 11: White (Codex)

Life at start: White 20 — Red 18.

- S1077: White (Codex) draws Plains.
- S1092: White (Codex) plays Plains.
- S1115: Attackers: Healer's Hawk [e90e630e].
- S1125: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S1126: White (Codex) gains 1 life.

**Life after turn:** White 21 — Red 17.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D257 / S1090 | Play spells and abilities | index 0: Plains [9c88e369] | 5 |
| D262 / S1106 | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] | 5 |
| D263 / S1107 | Select attackers | index 4: Done / pass priority | 5 |

Other recorded responses this turn: 10 automatic White prompts; 11 scripted Red prompts. See the decision appendix for each response.

### Game turn 12: Red (scripted)

Life at start: White 21 — Red 17.

- S1176: Red draws one card; identity hidden from White.
- S1191: Red (scripted) plays Mountain.
- S1226: Red (scripted) casts Fire Elemental [ac58a505].
- S1255: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53].
- S1260: Pillarfield Ox [d0954cb8] blocks Hill Giant [d7d1ae69].
- S1269: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Hill Giant [d7d1ae69].
- S1270: Combat damage: Hill Giant [d7d1ae69] deals 3 to Pillarfield Ox [d0954cb8].
- S1272: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).

**Life after turn:** White 18 — Red 17.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D299 / S1255 | Select blockers | index 1: Choose blocker Pillarfield Ox [d0954cb8] | 3 |
| D300 / S1256 | Select attacker to block | index 0: Hill Giant [d7d1ae69] | 3 |
| D301 / S1257 | Select blockers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 11 automatic White prompts; 21 scripted Red prompts. See the decision appendix for each response.

### Game turn 13: White (Codex)

Life at start: White 18 — Red 17.

- S1318: White (Codex) draws Plains.
- S1333: White (Codex) plays Plains.
- S1356: Attackers: Healer's Hawk [e90e630e].
- S1366: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S1367: White (Codex) gains 1 life.

**Life after turn:** White 19 — Red 16.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D316 / S1331 | Play spells and abilities | index 0: Plains [a798abe7] | 5 |
| D321 / S1347 | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] | 5 |
| D322 / S1348 | Select attackers | index 4: Done / pass priority | 5 |

Other recorded responses this turn: 10 automatic White prompts; 11 scripted Red prompts. See the decision appendix for each response.

### Game turn 14: Red (scripted)

Life at start: White 19 — Red 16.

- S1419: Red draws one card; identity hidden from White.
- S1434: Red (scripted) plays Mountain.
- S1451: Red (scripted) casts Goblin Piker [eb892b9b].
- S1482: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53], Fire Elemental [ac58a505].
- S1489: Pillarfield Ox [d0954cb8] blocks Hill Giant [d7d1ae69].
- S1491: Youthful Knight [10efb749] blocks Fire Elemental [ac58a505].
- S1501: First-strike damage: Youthful Knight [10efb749] deals 2 to Fire Elemental [ac58a505].
- S1509: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Hill Giant [d7d1ae69].
- S1510: Combat damage: Hill Giant [d7d1ae69] deals 3 to Pillarfield Ox [d0954cb8].
- S1512: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).
- S1513: Combat damage: Fire Elemental [ac58a505] deals 5 to Youthful Knight [10efb749].
- S1517: Youthful Knight [10efb749] dies.

**Life after turn:** White 16 — Red 16.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D356 / S1482 | Select blockers | index 0: Choose blocker Youthful Knight [10efb749] | 3 |
| D357 / S1483 | Select attacker to block | index 0: Fire Elemental [ac58a505] | 4 |
| D358 / S1484 | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] | 3 |
| D359 / S1485 | Select attacker to block | index 1: Hill Giant [d7d1ae69] | 4 |
| D360 / S1486 | Select blockers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 12 automatic White prompts; 20 scripted Red prompts. See the decision appendix for each response.

### Game turn 15: White (Codex)

Life at start: White 16 — Red 16.

- S1560: White (Codex) draws Savannah Lions [50682576].
- S1575: White (Codex) plays Plains.
- S1586: White (Codex) casts Savannah Lions [50682576].
- S1614: Attackers: Healer's Hawk [e90e630e], Pillarfield Ox [d0954cb8].
- S1618: Goblin Piker [eb892b9b] blocks Pillarfield Ox [d0954cb8].
- S1628: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S1629: Combat damage: Goblin Piker [eb892b9b] deals 2 to Pillarfield Ox [d0954cb8].
- S1630: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Goblin Piker [eb892b9b].
- S1631: White (Codex) gains 1 life.
- S1635: Goblin Piker [eb892b9b] dies.

**Life after turn:** White 17 — Red 15.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D377 / S1573 | Play spells and abilities | index 0: Plains [58a1e7a1] | 5 |
| D378 / S1576 | Play spells and abilities | index 0: Savannah Lions [50682576] | 2 |
| D386 / S1604 | Select attackers | index 2: Attack with all eligible creatures | 4 |
| D387 / S1605 | Select attackers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 12 automatic White prompts; 13 scripted Red prompts. See the decision appendix for each response.

### Game turn 16: Red (scripted)

Life at start: White 17 — Red 15.

- S1682: Red draws one card; identity hidden from White.
- S1697: Red (scripted) plays Mountain.
- S1724: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53], Fire Elemental [ac58a505].
- S1730: Savannah Lions [50682576] blocks Fire Elemental [ac58a505].
- S1740: Combat damage: Hill Giant [d7d1ae69] deals 3 to White (Codex).
- S1742: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).
- S1743: Combat damage: Savannah Lions [50682576] deals 2 to Fire Elemental [ac58a505].
- S1744: Combat damage: Fire Elemental [ac58a505] deals 5 to Savannah Lions [50682576].
- S1748: Savannah Lions [50682576] dies.

**Life after turn:** White 11 — Red 15.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D417 / S1724 | Select blockers | index 0: Choose blocker Savannah Lions [50682576] | 2 |
| D418 / S1725 | Select attacker to block | index 0: Fire Elemental [ac58a505] | 4 |
| D419 / S1726 | Select blockers | index 1: Done / pass priority | 2 |

Other recorded responses this turn: 10 automatic White prompts; 15 scripted Red prompts. See the decision appendix for each response.

### Game turn 17: White (Codex)

Life at start: White 11 — Red 15.

- S1793: White (Codex) draws Savannah Lions [8cb79102].
- S1808: White (Codex) plays Plains.
- S1819: White (Codex) casts Savannah Lions [8cb79102].
- S1850: Attackers: Healer's Hawk [e90e630e].
- S1855: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S1856: White (Codex) gains 1 life.

**Life after turn:** White 12 — Red 14.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D434 / S1806 | Play spells and abilities | index 0: Plains [50e7b128] | 4 |
| D435 / S1809 | Play spells and abilities | index 0: Savannah Lions [8cb79102] | 2 |
| D443 / S1837 | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] | 4 |
| D444 / S1838 | Select attackers | index 3: Done / pass priority | 4 |

Other recorded responses this turn: 12 automatic White prompts; 11 scripted Red prompts. See the decision appendix for each response.

### Game turn 18: Red (scripted)

Life at start: White 12 — Red 14.

- S1904: Red draws one card; identity hidden from White.
- S1927: Red (scripted) casts Raging Goblin [9ba79b01].
- S1960: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53], Fire Elemental [ac58a505], Raging Goblin [9ba79b01].
- S1968: Pillarfield Ox [d0954cb8] blocks Hill Giant [d7d1ae69].
- S1970: Savannah Lions [8cb79102] blocks Fire Elemental [ac58a505].
- S1980: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Hill Giant [d7d1ae69].
- S1981: Combat damage: Hill Giant [d7d1ae69] deals 3 to Pillarfield Ox [d0954cb8].
- S1983: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).
- S1984: Combat damage: Savannah Lions [8cb79102] deals 2 to Fire Elemental [ac58a505].
- S1985: Combat damage: Fire Elemental [ac58a505] deals 5 to Savannah Lions [8cb79102].
- S1987: Combat damage: Raging Goblin [9ba79b01] deals 1 to White (Codex).
- S1991: Savannah Lions [8cb79102] dies.

**Life after turn:** White 8 — Red 14.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D476 / S1960 | Select blockers | index 1: Choose blocker Savannah Lions [8cb79102] | 3 |
| D477 / S1961 | Select attacker to block | index 1: Fire Elemental [ac58a505] | 5 |
| D478 / S1962 | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] | 3 |
| D479 / S1963 | Select attacker to block | index 2: Hill Giant [d7d1ae69] | 5 |
| D480 / S1964 | Select blockers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 11 automatic White prompts; 18 scripted Red prompts. See the decision appendix for each response.

### Game turn 19: White (Codex)

Life at start: White 8 — Red 14.

- S2035: White (Codex) draws Plains.
- S2050: White (Codex) plays Plains.
- S2077: Attackers: Healer's Hawk [e90e630e].
- S2082: Combat damage: Healer's Hawk [e90e630e] deals 1 to Red (scripted).
- S2083: White (Codex) gains 1 life.

**Life after turn:** White 9 — Red 13.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D495 / S2048 | Play spells and abilities | index 0: Plains [bb2b1784] | 3 |
| D500 / S2064 | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] | 4 |
| D501 / S2065 | Select attackers | index 3: Done / pass priority | 4 |

Other recorded responses this turn: 10 automatic White prompts; 10 scripted Red prompts. See the decision appendix for each response.

### Game turn 20: Red (scripted)

Life at start: White 9 — Red 13.

- S2133: Red draws one card; identity hidden from White.
- S2148: Red (scripted) plays Mountain.
- S2177: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53], Fire Elemental [ac58a505], Raging Goblin [9ba79b01].
- S2184: Pillarfield Ox [d0954cb8] blocks Fire Elemental [ac58a505].
- S2194: Combat damage: Hill Giant [d7d1ae69] deals 3 to White (Codex).
- S2196: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).
- S2197: Combat damage: Pillarfield Ox [d0954cb8] deals 2 to Fire Elemental [ac58a505].
- S2198: Combat damage: Fire Elemental [ac58a505] deals 5 to Pillarfield Ox [d0954cb8].
- S2200: Combat damage: Raging Goblin [9ba79b01] deals 1 to White (Codex).
- S2204: Pillarfield Ox [d0954cb8] dies.

**Life after turn:** White 2 — Red 13.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D530 / S2177 | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] | 2 |
| D531 / S2178 | Select attacker to block | index 1: Fire Elemental [ac58a505] | 5 |
| D532 / S2179 | Select blockers | index 1: Done / pass priority | 2 |

Other recorded responses this turn: 10 automatic White prompts; 16 scripted Red prompts. See the decision appendix for each response.

### Game turn 21: White (Codex)

Life at start: White 2 — Red 13.

- S2247: White (Codex) draws Healer's Hawk [4c91aba9].
- S2270: White (Codex) casts Healer's Hawk [4c91aba9].
- S2277: White (Codex) plays Plains.
- No attackers declared.

**Life after turn:** White 2 — Red 13.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D547 / S2260 | Play spells and abilities | index 1: Healer's Hawk [4c91aba9] | 3 |
| D551 / S2275 | Play spells and abilities | index 0: Plains [3fb58070] | 2 |
| D556 / S2291 | Select attackers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 10 automatic White prompts; 9 scripted Red prompts. See the decision appendix for each response.

### Game turn 22: Red (scripted)

Life at start: White 2 — Red 13.

- S2339: Red draws one card; identity hidden from White.
- S2354: Red (scripted) plays Mountain.
- S2383: Attackers: Hill Giant [d7d1ae69], Hill Giant [db6dcf53], Fire Elemental [ac58a505], Raging Goblin [9ba79b01].
- S2391: Healer's Hawk [4c91aba9] blocks Hill Giant [d7d1ae69].
- S2393: Healer's Hawk [e90e630e] blocks Fire Elemental [ac58a505].
- S2403: Combat damage: Healer's Hawk [4c91aba9] deals 1 to Hill Giant [d7d1ae69].
- S2404: Combat damage: Hill Giant [d7d1ae69] deals 3 to Healer's Hawk [4c91aba9].
- S2406: Combat damage: Hill Giant [db6dcf53] deals 3 to White (Codex).
- S2407: Combat damage: Healer's Hawk [e90e630e] deals 1 to Fire Elemental [ac58a505].
- S2408: Combat damage: Fire Elemental [ac58a505] deals 5 to Healer's Hawk [e90e630e].
- S2410: Combat damage: Raging Goblin [9ba79b01] deals 1 to White (Codex).
- S2411: White (Codex) gains 1 life.
- S2412: White (Codex) gains 1 life.
- S2416: White (Codex) loses the game.
- S2417: Healer's Hawk [e90e630e] dies.
- S2418: Healer's Hawk [4c91aba9] dies.

**Life after turn:** White 0 — Red 13.

White’s manual decisions this turn:

| Decision | Prompt | Selected response | Options offered |
| --- | --- | --- | --- |
| D581 / S2383 | Select blockers | index 0: Choose blocker Healer's Hawk [e90e630e] | 3 |
| D582 / S2384 | Select attacker to block | index 1: Fire Elemental [ac58a505] | 5 |
| D583 / S2385 | Select blockers | index 0: Choose blocker Healer's Hawk [4c91aba9] | 3 |
| D584 / S2386 | Select attacker to block | index 2: Hill Giant [d7d1ae69] | 5 |
| D585 / S2387 | Select blockers | index 2: Done / pass priority | 3 |

Other recorded responses this turn: 6 automatic White prompts; 12 scripted Red prompts. See the decision appendix for each response.

## All 587 decision responses

One row per original decision, including setup and routine passes. These are the recorded offered-action selections, not invented strategic explanations. Red’s alternative offered actions are kept in the private raw observations and are not reproduced here.

| Decision / snapshot | Game turn / step | Controller | Prompt | Selected response |
| --- | --- | --- | --- | --- |
| D1 / S4 | 1 / setup | Codex choice | Select a starting player | index 0: player_a |
| D2 / S20 | 1 / setup | Codex choice | Mulligan down to 6 cards? | index 1: No / keep |
| D3 / S22 | 1 / setup | scripted opponent | Mulligan down to 6 cards? | index 1: No / keep |
| D4 / S31 | 1 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D5 / S32 | 1 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D6 / S40 | 1 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [cfa820c2] |
| D7 / S43 | 1 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D8 / S44 | 1 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D9 / S52 | 1 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D10 / S53 | 1 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D11 / S58 | 1 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D12 / S59 | 1 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D13 / S64 | 1 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D14 / S65 | 1 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D15 / S73 | 1 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D16 / S74 | 1 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D17 / S82 | 1 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D18 / S83 | 1 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D19 / S96 | 2 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D20 / S97 | 2 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D21 / S103 | 2 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D22 / S104 | 2 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D23 / S112 | 2 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [cc91f02d] |
| D24 / S115 | 2 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Shock [b48599c9] |
| D25 / S119 | 2 / PRECOMBAT_MAIN | scripted opponent | Select any target | index 1: player_a |
| D26 / S120 | 2 / PRECOMBAT_MAIN | scripted opponent | Pay {R}Shock [b48] | index 0: Mountain [cc91f02d] |
| D27 / S127 | 2 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D28 / S128 | 2 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D29 / S134 | 2 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D30 / S135 | 2 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D31 / S143 | 2 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D32 / S144 | 2 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D33 / S149 | 2 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D34 / S150 | 2 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D35 / S155 | 2 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D36 / S156 | 2 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D37 / S164 | 2 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D38 / S165 | 2 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D39 / S173 | 2 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D40 / S174 | 2 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D41 / S187 | 3 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D42 / S188 | 3 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D43 / S194 | 3 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D44 / S195 | 3 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D45 / S203 | 3 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [d4fa6220] |
| D46 / S206 | 3 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Youthful Knight [10efb749] |
| D47 / S210 | 3 / PRECOMBAT_MAIN | automatic: one option | Pay {1}{W}Youthful Knight [10e] | index 0: Plains [cfa820c2] |
| D48 / S216 | 3 / PRECOMBAT_MAIN | automatic: one option | Pay {1}Youthful Knight [10e] | index 0: Plains [d4fa6220] |
| D49 / S223 | 3 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D50 / S224 | 3 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D51 / S227 | 3 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D52 / S228 | 3 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D53 / S236 | 3 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D54 / S237 | 3 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D55 / S242 | 3 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D56 / S243 | 3 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D57 / S248 | 3 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D58 / S249 | 3 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D59 / S257 | 3 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D60 / S258 | 3 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D61 / S266 | 3 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D62 / S267 | 3 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D63 / S281 | 4 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D64 / S282 | 4 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D65 / S288 | 4 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D66 / S289 | 4 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D67 / S297 | 4 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [861c1b35] |
| D68 / S300 | 4 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Goblin Piker [fde75872] |
| D69 / S304 | 4 / PRECOMBAT_MAIN | scripted opponent | Pay {1}{R}Goblin Piker [fde] | index 0: Mountain [cc91f02d] |
| D70 / S310 | 4 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Goblin Piker [fde] | index 0: Mountain [861c1b35] |
| D71 / S317 | 4 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D72 / S318 | 4 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D73 / S321 | 4 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D74 / S322 | 4 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D75 / S330 | 4 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D76 / S331 | 4 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D77 / S336 | 4 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D78 / S337 | 4 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D79 / S342 | 4 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D80 / S343 | 4 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D81 / S351 | 4 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D82 / S352 | 4 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D83 / S360 | 4 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D84 / S361 | 4 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D85 / S376 | 5 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D86 / S377 | 5 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D87 / S383 | 5 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D88 / S384 | 5 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D89 / S392 | 5 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [2fc8ede5] |
| D90 / S395 | 5 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Healer's Hawk [e90e630e] |
| D91 / S399 | 5 / PRECOMBAT_MAIN | automatic: one option | Pay {W}Healer's Hawk [e90] | index 0: Plains [cfa820c2] |
| D92 / S406 | 5 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D93 / S407 | 5 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D94 / S410 | 5 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D95 / S411 | 5 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D96 / S419 | 5 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D97 / S420 | 5 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D98 / S423 | 5 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 0: Attack with Youthful Knight [10efb749] |
| D99 / S424 | 5 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 1: Done / pass priority |
| D100 / S428 | 5 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D101 / S429 | 5 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D102 / S432 | 5 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Choose blocker Goblin Piker [fde75872] |
| D103 / S433 | 5 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 1: Done / pass priority |
| D104 / S440 | 5 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D105 / S441 | 5 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D106 / S449 | 5 / FIRST_COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D107 / S450 | 5 / FIRST_COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D108 / S456 | 5 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D109 / S457 | 5 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D110 / S462 | 5 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D111 / S463 | 5 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D112 / S471 | 5 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D113 / S472 | 5 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D114 / S480 | 5 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D115 / S481 | 5 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D116 / S496 | 6 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D117 / S497 | 6 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D118 / S503 | 6 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D119 / S504 | 6 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D120 / S512 | 6 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [bca83957] |
| D121 / S515 | 6 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Goblin Piker [89244db1] |
| D122 / S519 | 6 / PRECOMBAT_MAIN | scripted opponent | Pay {1}{R}Goblin Piker [892] | index 0: Mountain [cc91f02d] |
| D123 / S525 | 6 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Goblin Piker [892] | index 0: Mountain [861c1b35] |
| D124 / S532 | 6 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D125 / S533 | 6 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D126 / S536 | 6 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D127 / S537 | 6 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D128 / S545 | 6 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D129 / S546 | 6 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D130 / S551 | 6 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D131 / S552 | 6 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D132 / S557 | 6 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D133 / S558 | 6 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D134 / S566 | 6 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D135 / S567 | 6 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D136 / S575 | 6 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D137 / S576 | 6 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D138 / S591 | 7 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D139 / S592 | 7 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D140 / S598 | 7 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D141 / S599 | 7 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D142 / S607 | 7 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [9d9a5765] |
| D143 / S610 | 7 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Pillarfield Ox [d0954cb8] |
| D144 / S614 | 7 / PRECOMBAT_MAIN | automatic: one option | Pay {3}{W}Pillarfield Ox [d09] | index 0: Plains [cfa820c2] |
| D145 / S620 | 7 / PRECOMBAT_MAIN | automatic: one option | Pay {3}Pillarfield Ox [d09] | index 0: Plains [d4fa6220] |
| D146 / S626 | 7 / PRECOMBAT_MAIN | automatic: one option | Pay {2}Pillarfield Ox [d09] | index 0: Plains [2fc8ede5] |
| D147 / S632 | 7 / PRECOMBAT_MAIN | automatic: one option | Pay {1}Pillarfield Ox [d09] | index 0: Plains [9d9a5765] |
| D148 / S639 | 7 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D149 / S640 | 7 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D150 / S643 | 7 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D151 / S644 | 7 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D152 / S652 | 7 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D153 / S653 | 7 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D154 / S656 | 7 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 0: Attack with Youthful Knight [10efb749] |
| D155 / S657 | 7 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] |
| D156 / S658 | 7 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 2: Done / pass priority |
| D157 / S663 | 7 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D158 / S664 | 7 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D159 / S667 | 7 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Choose blocker Goblin Piker [89244db1] |
| D160 / S668 | 7 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 1: Done / pass priority |
| D161 / S676 | 7 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D162 / S677 | 7 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D163 / S685 | 7 / FIRST_COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D164 / S686 | 7 / FIRST_COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D165 / S695 | 7 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D166 / S696 | 7 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D167 / S701 | 7 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D168 / S702 | 7 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D169 / S710 | 7 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D170 / S711 | 7 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D171 / S719 | 7 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D172 / S720 | 7 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D173 / S735 | 8 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D174 / S736 | 8 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D175 / S742 | 8 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D176 / S743 | 8 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D177 / S751 | 8 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [d37b30ae] |
| D178 / S754 | 8 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Hill Giant [d7d1ae69] |
| D179 / S758 | 8 / PRECOMBAT_MAIN | scripted opponent | Pay {3}{R}Hill Giant [d7d] | index 0: Mountain [cc91f02d] |
| D180 / S764 | 8 / PRECOMBAT_MAIN | scripted opponent | Pay {3}Hill Giant [d7d] | index 0: Mountain [861c1b35] |
| D181 / S770 | 8 / PRECOMBAT_MAIN | scripted opponent | Pay {2}Hill Giant [d7d] | index 0: Mountain [bca83957] |
| D182 / S776 | 8 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Hill Giant [d7d] | index 0: Mountain [d37b30ae] |
| D183 / S783 | 8 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D184 / S784 | 8 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D185 / S787 | 8 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D186 / S788 | 8 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D187 / S796 | 8 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D188 / S797 | 8 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D189 / S802 | 8 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D190 / S803 | 8 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D191 / S808 | 8 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D192 / S809 | 8 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D193 / S817 | 8 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D194 / S818 | 8 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D195 / S826 | 8 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D196 / S827 | 8 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D197 / S846 | 9 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D198 / S847 | 9 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D199 / S853 | 9 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D200 / S854 | 9 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D201 / S862 | 9 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [ba12e661] |
| D202 / S865 | 9 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D203 / S866 | 9 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D204 / S874 | 9 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D205 / S875 | 9 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D206 / S878 | 9 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] |
| D207 / S879 | 9 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 4: Done / pass priority |
| D208 / S883 | 9 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D209 / S884 | 9 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D210 / S887 | 9 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Done / pass priority |
| D211 / S892 | 9 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D212 / S893 | 9 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D213 / S902 | 9 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D214 / S903 | 9 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D215 / S908 | 9 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D216 / S909 | 9 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D217 / S917 | 9 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D218 / S918 | 9 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D219 / S926 | 9 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D220 / S927 | 9 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D221 / S944 | 10 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D222 / S945 | 10 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D223 / S951 | 10 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D224 / S952 | 10 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D225 / S960 | 10 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 1: Mountain [8d57a2a1] |
| D226 / S963 | 10 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Hill Giant [db6dcf53] |
| D227 / S967 | 10 / PRECOMBAT_MAIN | scripted opponent | Pay {3}{R}Hill Giant [db6] | index 0: Mountain [cc91f02d] |
| D228 / S973 | 10 / PRECOMBAT_MAIN | scripted opponent | Pay {3}Hill Giant [db6] | index 0: Mountain [861c1b35] |
| D229 / S979 | 10 / PRECOMBAT_MAIN | scripted opponent | Pay {2}Hill Giant [db6] | index 0: Mountain [bca83957] |
| D230 / S985 | 10 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Hill Giant [db6] | index 0: Mountain [d37b30ae] |
| D231 / S992 | 10 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D232 / S993 | 10 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D233 / S996 | 10 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D234 / S997 | 10 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D235 / S1005 | 10 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D236 / S1006 | 10 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D237 / S1009 | 10 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D238 / S1010 | 10 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 1: Done / pass priority |
| D239 / S1014 | 10 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D240 / S1015 | 10 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D241 / S1018 | 10 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 1: Choose blocker Pillarfield Ox [d0954cb8] |
| D242 / S1019 | 10 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 2: Done / pass priority |
| D243 / S1026 | 10 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D244 / S1027 | 10 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D245 / S1035 | 10 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D246 / S1036 | 10 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D247 / S1041 | 10 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D248 / S1042 | 10 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D249 / S1050 | 10 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D250 / S1051 | 10 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D251 / S1059 | 10 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D252 / S1060 | 10 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D253 / S1074 | 11 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D254 / S1075 | 11 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D255 / S1081 | 11 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D256 / S1082 | 11 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D257 / S1090 | 11 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [9c88e369] |
| D258 / S1093 | 11 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D259 / S1094 | 11 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D260 / S1102 | 11 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D261 / S1103 | 11 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D262 / S1106 | 11 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] |
| D263 / S1107 | 11 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 4: Done / pass priority |
| D264 / S1111 | 11 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D265 / S1112 | 11 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D266 / S1115 | 11 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Done / pass priority |
| D267 / S1120 | 11 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D268 / S1121 | 11 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D269 / S1130 | 11 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D270 / S1131 | 11 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D271 / S1136 | 11 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D272 / S1137 | 11 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D273 / S1145 | 11 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D274 / S1146 | 11 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D275 / S1154 | 11 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D276 / S1155 | 11 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D277 / S1173 | 12 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D278 / S1174 | 12 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D279 / S1180 | 12 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D280 / S1181 | 12 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D281 / S1189 | 12 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 1: Mountain [16b9e1b3] |
| D282 / S1192 | 12 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Fire Elemental [ac58a505] |
| D283 / S1196 | 12 / PRECOMBAT_MAIN | scripted opponent | Pay {3}{R}{R}Fire Elemental [ac5] | index 0: Mountain [cc91f02d] |
| D284 / S1202 | 12 / PRECOMBAT_MAIN | scripted opponent | Pay {3}{R}Fire Elemental [ac5] | index 0: Mountain [861c1b35] |
| D285 / S1208 | 12 / PRECOMBAT_MAIN | scripted opponent | Pay {3}Fire Elemental [ac5] | index 0: Mountain [bca83957] |
| D286 / S1214 | 12 / PRECOMBAT_MAIN | scripted opponent | Pay {2}Fire Elemental [ac5] | index 0: Mountain [d37b30ae] |
| D287 / S1220 | 12 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Fire Elemental [ac5] | index 0: Mountain [8d57a2a1] |
| D288 / S1227 | 12 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D289 / S1228 | 12 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D290 / S1231 | 12 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D291 / S1232 | 12 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D292 / S1240 | 12 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D293 / S1241 | 12 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D294 / S1244 | 12 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D295 / S1245 | 12 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D296 / S1246 | 12 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 2: Done / pass priority |
| D297 / S1251 | 12 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D298 / S1252 | 12 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D299 / S1255 | 12 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 1: Choose blocker Pillarfield Ox [d0954cb8] |
| D300 / S1256 | 12 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 0: Hill Giant [d7d1ae69] |
| D301 / S1257 | 12 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 2: Done / pass priority |
| D302 / S1265 | 12 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D303 / S1266 | 12 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D304 / S1276 | 12 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D305 / S1277 | 12 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D306 / S1282 | 12 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D307 / S1283 | 12 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D308 / S1291 | 12 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D309 / S1292 | 12 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D310 / S1300 | 12 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D311 / S1301 | 12 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D312 / S1315 | 13 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D313 / S1316 | 13 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D314 / S1322 | 13 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D315 / S1323 | 13 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D316 / S1331 | 13 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [a798abe7] |
| D317 / S1334 | 13 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D318 / S1335 | 13 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D319 / S1343 | 13 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D320 / S1344 | 13 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D321 / S1347 | 13 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 1: Attack with Healer's Hawk [e90e630e] |
| D322 / S1348 | 13 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 4: Done / pass priority |
| D323 / S1352 | 13 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D324 / S1353 | 13 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D325 / S1356 | 13 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Done / pass priority |
| D326 / S1361 | 13 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D327 / S1362 | 13 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D328 / S1371 | 13 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D329 / S1372 | 13 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D330 / S1377 | 13 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D331 / S1378 | 13 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D332 / S1386 | 13 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D333 / S1387 | 13 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D334 / S1395 | 13 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D335 / S1396 | 13 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D336 / S1416 | 14 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D337 / S1417 | 14 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D338 / S1423 | 14 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D339 / S1424 | 14 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D340 / S1432 | 14 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 1: Mountain [0ec77327] |
| D341 / S1435 | 14 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Goblin Piker [eb892b9b] |
| D342 / S1439 | 14 / PRECOMBAT_MAIN | scripted opponent | Pay {1}{R}Goblin Piker [eb8] | index 0: Mountain [cc91f02d] |
| D343 / S1445 | 14 / PRECOMBAT_MAIN | scripted opponent | Pay {1}Goblin Piker [eb8] | index 0: Mountain [861c1b35] |
| D344 / S1452 | 14 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D345 / S1453 | 14 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D346 / S1456 | 14 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D347 / S1457 | 14 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D348 / S1465 | 14 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D349 / S1466 | 14 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D350 / S1469 | 14 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D351 / S1470 | 14 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D352 / S1471 | 14 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Fire Elemental [ac58a505] |
| D353 / S1472 | 14 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 3: Done / pass priority |
| D354 / S1478 | 14 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D355 / S1479 | 14 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D356 / S1482 | 14 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Youthful Knight [10efb749] |
| D357 / S1483 | 14 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 0: Fire Elemental [ac58a505] |
| D358 / S1484 | 14 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] |
| D359 / S1485 | 14 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 1: Hill Giant [d7d1ae69] |
| D360 / S1486 | 14 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 2: Done / pass priority |
| D361 / S1497 | 14 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D362 / S1498 | 14 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D363 / S1505 | 14 / FIRST_COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D364 / S1506 | 14 / FIRST_COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D365 / S1518 | 14 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D366 / S1519 | 14 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D367 / S1524 | 14 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D368 / S1525 | 14 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D369 / S1533 | 14 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D370 / S1534 | 14 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D371 / S1542 | 14 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D372 / S1543 | 14 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D373 / S1557 | 15 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D374 / S1558 | 15 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D375 / S1564 | 15 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D376 / S1565 | 15 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D377 / S1573 | 15 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [58a1e7a1] |
| D378 / S1576 | 15 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Savannah Lions [50682576] |
| D379 / S1580 | 15 / PRECOMBAT_MAIN | automatic: one option | Pay {W}Savannah Lions [506] | index 0: Plains [cfa820c2] |
| D380 / S1587 | 15 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D381 / S1588 | 15 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D382 / S1591 | 15 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D383 / S1592 | 15 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D384 / S1600 | 15 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D385 / S1601 | 15 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D386 / S1604 | 15 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 2: Attack with all eligible creatures |
| D387 / S1605 | 15 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 2: Done / pass priority |
| D388 / S1610 | 15 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D389 / S1611 | 15 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D390 / S1614 | 15 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 0: Choose blocker Goblin Piker [eb892b9b] |
| D391 / S1615 | 15 / DECLARE_BLOCKERS | scripted opponent | Select blockers | index 1: Done / pass priority |
| D392 / S1623 | 15 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D393 / S1624 | 15 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D394 / S1636 | 15 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D395 / S1637 | 15 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D396 / S1642 | 15 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D397 / S1643 | 15 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D398 / S1651 | 15 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D399 / S1652 | 15 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D400 / S1660 | 15 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D401 / S1661 | 15 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D402 / S1679 | 16 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D403 / S1680 | 16 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D404 / S1686 | 16 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D405 / S1687 | 16 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D406 / S1695 | 16 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [3f57ae44] |
| D407 / S1698 | 16 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D408 / S1699 | 16 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D409 / S1707 | 16 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D410 / S1708 | 16 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D411 / S1711 | 16 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D412 / S1712 | 16 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D413 / S1713 | 16 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Fire Elemental [ac58a505] |
| D414 / S1714 | 16 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 3: Done / pass priority |
| D415 / S1720 | 16 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D416 / S1721 | 16 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D417 / S1724 | 16 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Savannah Lions [50682576] |
| D418 / S1725 | 16 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 0: Fire Elemental [ac58a505] |
| D419 / S1726 | 16 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 1: Done / pass priority |
| D420 / S1735 | 16 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D421 / S1736 | 16 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D422 / S1749 | 16 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D423 / S1750 | 16 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D424 / S1755 | 16 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D425 / S1756 | 16 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D426 / S1764 | 16 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D427 / S1765 | 16 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D428 / S1773 | 16 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D429 / S1774 | 16 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D430 / S1790 | 17 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D431 / S1791 | 17 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D432 / S1797 | 17 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D433 / S1798 | 17 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D434 / S1806 | 17 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [50e7b128] |
| D435 / S1809 | 17 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Savannah Lions [8cb79102] |
| D436 / S1813 | 17 / PRECOMBAT_MAIN | automatic: one option | Pay {W}Savannah Lions [8cb] | index 0: Plains [cfa820c2] |
| D437 / S1820 | 17 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D438 / S1821 | 17 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D439 / S1824 | 17 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D440 / S1825 | 17 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D441 / S1833 | 17 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D442 / S1834 | 17 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D443 / S1837 | 17 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] |
| D444 / S1838 | 17 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 3: Done / pass priority |
| D445 / S1842 | 17 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D446 / S1843 | 17 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D447 / S1850 | 17 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D448 / S1851 | 17 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D449 / S1860 | 17 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D450 / S1861 | 17 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D451 / S1866 | 17 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D452 / S1867 | 17 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D453 / S1875 | 17 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D454 / S1876 | 17 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D455 / S1884 | 17 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D456 / S1885 | 17 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D457 / S1901 | 18 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D458 / S1902 | 18 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D459 / S1908 | 18 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D460 / S1909 | 18 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D461 / S1917 | 18 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Raging Goblin [9ba79b01] |
| D462 / S1921 | 18 / PRECOMBAT_MAIN | scripted opponent | Pay {R}Raging Goblin [9ba] | index 0: Mountain [cc91f02d] |
| D463 / S1928 | 18 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D464 / S1929 | 18 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D465 / S1932 | 18 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D466 / S1933 | 18 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D467 / S1941 | 18 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D468 / S1942 | 18 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D469 / S1945 | 18 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D470 / S1946 | 18 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D471 / S1947 | 18 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Fire Elemental [ac58a505] |
| D472 / S1948 | 18 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Raging Goblin [9ba79b01] |
| D473 / S1949 | 18 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 4: Done / pass priority |
| D474 / S1956 | 18 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D475 / S1957 | 18 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D476 / S1960 | 18 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 1: Choose blocker Savannah Lions [8cb79102] |
| D477 / S1961 | 18 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 1: Fire Elemental [ac58a505] |
| D478 / S1962 | 18 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] |
| D479 / S1963 | 18 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 2: Hill Giant [d7d1ae69] |
| D480 / S1964 | 18 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 2: Done / pass priority |
| D481 / S1976 | 18 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D482 / S1977 | 18 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D483 / S1992 | 18 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D484 / S1993 | 18 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D485 / S1998 | 18 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D486 / S1999 | 18 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D487 / S2007 | 18 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D488 / S2008 | 18 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D489 / S2016 | 18 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D490 / S2017 | 18 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D491 / S2032 | 19 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D492 / S2033 | 19 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D493 / S2039 | 19 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D494 / S2040 | 19 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D495 / S2048 | 19 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [bb2b1784] |
| D496 / S2051 | 19 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D497 / S2052 | 19 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D498 / S2060 | 19 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D499 / S2061 | 19 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D500 / S2064 | 19 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 0: Attack with Healer's Hawk [e90e630e] |
| D501 / S2065 | 19 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 3: Done / pass priority |
| D502 / S2069 | 19 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D503 / S2070 | 19 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D504 / S2077 | 19 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D505 / S2078 | 19 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D506 / S2087 | 19 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D507 / S2088 | 19 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D508 / S2093 | 19 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D509 / S2094 | 19 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D510 / S2102 | 19 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D511 / S2103 | 19 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D512 / S2111 | 19 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D513 / S2112 | 19 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D514 / S2130 | 20 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D515 / S2131 | 20 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D516 / S2137 | 20 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D517 / S2138 | 20 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D518 / S2146 | 20 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [6df6dd8e] |
| D519 / S2149 | 20 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D520 / S2150 | 20 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D521 / S2158 | 20 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D522 / S2159 | 20 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D523 / S2162 | 20 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D524 / S2163 | 20 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D525 / S2164 | 20 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Fire Elemental [ac58a505] |
| D526 / S2165 | 20 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Raging Goblin [9ba79b01] |
| D527 / S2166 | 20 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 4: Done / pass priority |
| D528 / S2173 | 20 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D529 / S2174 | 20 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D530 / S2177 | 20 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Pillarfield Ox [d0954cb8] |
| D531 / S2178 | 20 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 1: Fire Elemental [ac58a505] |
| D532 / S2179 | 20 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 1: Done / pass priority |
| D533 / S2189 | 20 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D534 / S2190 | 20 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D535 / S2205 | 20 / COMBAT_DAMAGE | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D536 / S2206 | 20 / COMBAT_DAMAGE | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D537 / S2211 | 20 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D538 / S2212 | 20 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D539 / S2220 | 20 / POSTCOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D540 / S2221 | 20 / POSTCOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D541 / S2229 | 20 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D542 / S2230 | 20 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D543 / S2244 | 21 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D544 / S2245 | 21 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D545 / S2251 | 21 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D546 / S2252 | 21 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D547 / S2260 | 21 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 1: Healer's Hawk [4c91aba9] |
| D548 / S2264 | 21 / PRECOMBAT_MAIN | automatic: one option | Pay {W}Healer's Hawk [4c9] | index 0: Plains [cfa820c2] |
| D549 / S2271 | 21 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D550 / S2272 | 21 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D551 / S2275 | 21 / PRECOMBAT_MAIN | Codex choice | Play spells and abilities | index 0: Plains [3fb58070] |
| D552 / S2278 | 21 / PRECOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D553 / S2279 | 21 / PRECOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D554 / S2287 | 21 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D555 / S2288 | 21 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D556 / S2291 | 21 / DECLARE_ATTACKERS | Codex choice | Select attackers | index 2: Done / pass priority |
| D557 / S2294 | 21 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D558 / S2295 | 21 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D559 / S2300 | 21 / END_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D560 / S2301 | 21 / END_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D561 / S2309 | 21 / POSTCOMBAT_MAIN | automatic: one option | Play spells and abilities | index 0: Done / pass priority |
| D562 / S2310 | 21 / POSTCOMBAT_MAIN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D563 / S2318 | 21 / END_TURN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D564 / S2319 | 21 / END_TURN | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D565 / S2336 | 22 / UPKEEP | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D566 / S2337 | 22 / UPKEEP | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D567 / S2343 | 22 / DRAW | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D568 / S2344 | 22 / DRAW | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D569 / S2352 | 22 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Mountain [bc49ef59] |
| D570 / S2355 | 22 / PRECOMBAT_MAIN | scripted opponent | Play spells and abilities | index 0: Done / pass priority |
| D571 / S2356 | 22 / PRECOMBAT_MAIN | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D572 / S2364 | 22 / BEGIN_COMBAT | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D573 / S2365 | 22 / BEGIN_COMBAT | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D574 / S2368 | 22 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [d7d1ae69] |
| D575 / S2369 | 22 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Hill Giant [db6dcf53] |
| D576 / S2370 | 22 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Fire Elemental [ac58a505] |
| D577 / S2371 | 22 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 0: Attack with Raging Goblin [9ba79b01] |
| D578 / S2372 | 22 / DECLARE_ATTACKERS | scripted opponent | Select attackers | index 4: Done / pass priority |
| D579 / S2379 | 22 / DECLARE_ATTACKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D580 / S2380 | 22 / DECLARE_ATTACKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
| D581 / S2383 | 22 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Healer's Hawk [e90e630e] |
| D582 / S2384 | 22 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 1: Fire Elemental [ac58a505] |
| D583 / S2385 | 22 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 0: Choose blocker Healer's Hawk [4c91aba9] |
| D584 / S2386 | 22 / DECLARE_BLOCKERS | Codex choice | Select attacker to block | index 2: Hill Giant [d7d1ae69] |
| D585 / S2387 | 22 / DECLARE_BLOCKERS | Codex choice | Select blockers | index 2: Done / pass priority |
| D586 / S2399 | 22 / DECLARE_BLOCKERS | scripted opponent | Play instants and activated abilities | index 0: Done / pass priority |
| D587 / S2400 | 22 / DECLARE_BLOCKERS | automatic: one option | Play instants and activated abilities | index 0: Done / pass priority |
