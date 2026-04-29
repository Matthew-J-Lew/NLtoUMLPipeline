# Full Pipeline Evaluation Report

Output directory: `metrics_final_out_1`

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
| Avg issues before | 0.3 |
| Avg issues after | 0.1 |
| Avg issues removed | 0.2 |
| Avg iterations | 1.2 |
| Avg pre coverage | 0.962 |
| Avg post coverage | 0.9745 |

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
| Pre validity consistency rate | 0.75 |
| Post validity consistency rate | 0.95 |
| Post exact token/topology consistency rate | 0.55 |
| Mean post similarity score | 0.7875 |

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
| Per-scenario CSV | metrics_final_out_1\scenario_results.csv |
| Paraphrase CSV | metrics_final_out_1\paraphrase_results.csv |
| Adversarial CSV | metrics_final_out_1\adversarial_results.csv |
| Summary CSV | metrics_final_out_1\summary.csv |
| Summary JSON | metrics_final_out_1\summary.json |
