# Full Pipeline Evaluation Report

Output directory: `metrics_full_out_3`

## Primary scenario benchmark

| Metric | Value |
| --- | --- |
| Scenarios requested | 20 |
| Scenarios completed | 20 |
| Pre structural validity rate | 0.85 |
| Pre overall validity rate | 0.85 |
| Post structural validity rate | 1.0 |
| Post overall validity rate | 1.0 |
| Repair effectiveness rate | 1.0 |
| Pre downstream readiness rate | 0.85 |
| Post downstream readiness rate | 1.0 |
| Avg issues before | 0.4 |
| Avg issues after | 0.2 |
| Avg issues removed | 0.2 |
| Avg iterations | 1.2 |
| Avg pre coverage | 0.9745 |
| Avg post coverage | 0.962 |

## Refine stop reasons

| Stop reason | Count |
| --- | --- |
| Converged (deterministic + agentic OK). | 20 |

## Scenario failures / unresolved cases

All completed scenario runs finished valid after refinement.

## Paraphrase robustness

| Metric | Value |
| --- | --- |
| Paraphrase pairs evaluated | 20 |
| Primary variant pre-valid rate | 0.85 |
| Paraphrase variant pre-valid rate | 0.9 |
| Primary variant post-valid rate | 1.0 |
| Paraphrase variant post-valid rate | 0.95 |
| Pre validity consistency rate | 0.85 |
| Post validity consistency rate | 0.95 |
| Post exact token/topology consistency rate | 0.45 |
| Mean post similarity score | 0.725 |

## Adversarial repair suite

| Metric | Value |
| --- | --- |
| Bundles requested | 6 |
| Bundles completed | 6 |
| Initially invalid bundles | 6 |
| Repair effectiveness rate | 1.0 |
| Final valid rate | 1.0 |
| Avg issues removed | 5.8333 |
| Avg iterations | 2.3333 |

| Bundle | Pre valid | Post valid | Issues removed | Iterations | Stop reason |
| --- | --- | --- | --- | --- | --- |
| UnreachableState | False | True | 3 | 2 | Converged (deterministic + agentic OK). |
| DuplicateTransitions | False | True | 1 | 2 | Converged (deterministic + agentic OK). |
| DeadEndState | False | True | 3 | 2 | Converged (deterministic + agentic OK). |
| DisconnectedSubgraph | False | True | 6 | 2 | Converged (deterministic + agentic OK). |
| MultiIssueRepair | False | True | 7 | 2 | Converged (deterministic + agentic OK). |
| MaxItersStop | False | True | 15 | 4 | Converged (deterministic + agentic OK). |

## Artifacts

| Artifact | Path |
| --- | --- |
| Per-scenario CSV | metrics_full_out_3\scenario_results.csv |
| Paraphrase CSV | metrics_full_out_3\paraphrase_results.csv |
| Adversarial CSV | metrics_full_out_3\adversarial_results.csv |
| Summary CSV | metrics_full_out_3\summary.csv |
| Summary JSON | metrics_full_out_3\summary.json |
