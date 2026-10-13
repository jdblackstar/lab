# Recorded experiments and validation

These files retain measurements from distinct development stages. They demonstrate recording and controller behavior, not model playing strength. Counts and outcomes are observations from individual runs, not deterministic expected results; a recorded seed does not reproduce UUIDs or action ordering exactly.

## Historical experiments

| Report | What it demonstrated | Recorded result |
| --- | --- | --- |
| [Initial proof](proof-report.json) | Fixture runtime, private player views, full engine checkpoints, and the HTTP boundary | Player A won on turn 15; 370 decisions and 1,610 snapshots. The separate HTTP smoke made 324 requests. |
| [Full card module](full-card-module-report.json) | Native lookup beyond the original fixtures, including Elite Vanguard and Lightning Bolt; package loading | Player B won on turn 11; 286 decisions and 1,224 snapshots. Twelve tests passed at that stage. |
| [Interactive pilot walkthrough](pilot-walkthrough-report.json) | Codex piloting White against the fixed scripted Red opponent; individual combat choices | White lost on turn 22, at 0 life versus Red's 13; 587 decisions and 2,419 snapshots. |

Read the [complete walkthrough](pilot-walkthrough.md) for the actual plays, combat damage, life totals, and all 587 recorded responses. The engine restored every checkpoint and reconstructed the delivered player views for that run; hidden-state counterfactual checks covered both seats. Of White's 291 responses, 63 were interactive choices and 228 were one-option prompts advanced automatically.

The initial proof and full-card-module reports predate the later combat adapter. The walkthrough predates persistent registered-deck context and pass-only priority automation in API evaluations. Their historical test counts and endpoint request counts should not be read as the current defaults. Each report retains its original controller and validation provenance, including relative locations of the local recordings.

## Subsequent validation

[The latest captured validation report](latest-validation-report.json) covers the added persistent own-deck context, pass-only priority automation, and their privacy tests. Its local HTTP games used a scripted endpoint: reported requests measure controller routing, not paid model inference or realistic token usage. The smoke endpoint fabricates token counts solely to exercise the protocol.

Standard API evaluations now skip pass-only priority prompts, retain every engine prompt/response, and keep each seat's own registered decklist in its system message. The latest smoke verifies that endpoint inputs match the correct seat's observation history and registered deck context. An earlier opt-out smoke also checked that disabling automation sends all pilot prompts to the endpoint.

The canonical `prime eval run` path was attempted but could not proceed without a configured Prime API key. No platform evaluation or model win-rate estimate is claimed here.

## Artifact handling

Small reports and this readable walkthrough are versioned. Raw state and decision logs, engine checkpoints, generated build metadata, JARs, distributions, and the upstream XMage checkout stay local and Git-ignored. The raw recordings are preserved rather than deleted. Build hashes are bundled in distributions and copied into new run directories so a recording can be tied to the runtime that produced it.

For build, install, privacy-audit, and evaluation commands, see the [environment README](../README.md). A fresh checkout can build and run the POC without downloading historical game recordings. Historical full recordings are required to repeat those particular checkpoint audits.
