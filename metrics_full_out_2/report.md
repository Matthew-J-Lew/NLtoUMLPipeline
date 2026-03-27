# Full Pipeline Evaluation Report

Output directory: `metrics_full_out_2`

## Primary scenario benchmark

| Metric | Value |
| --- | --- |
| Scenarios requested | 20 |
| Scenarios completed | 19 |
| Pre structural validity rate | 0.2632 |
| Pre overall validity rate | 0.2632 |
| Post structural validity rate | 0.7368 |
| Post overall validity rate | 0.7368 |
| Repair effectiveness rate | 0.6429 |
| Pre downstream readiness rate | 0.2632 |
| Post downstream readiness rate | 0.7368 |
| Avg issues before | 1.6316 |
| Avg issues after | 0.5263 |
| Avg issues removed | 1.1053 |
| Avg iterations | 2.5263 |
| Avg pre coverage | 0.945 |
| Avg post coverage | 0.9687 |

## Refine stop reasons

| Stop reason | Count |
| --- | --- |
| Converged (deterministic + agentic OK). | 14 |
| Detected oscillation (IR repeated). | 4 |
| Reached max iterations. | 1 |
| Refine failed | 1 |

## Scenario failures / unresolved cases

| Scenario | Pre valid | Post valid | Pre issues | Post issues | Iterations | Stop reason |
| --- | --- | --- | --- | --- | --- | --- |
| S05 | False | False | 2 | 2 | 5 | Detected oscillation (IR repeated). |
| S06 | False | False | 2 | 2 | 5 | Detected oscillation (IR repeated). |
| S09 | False | False | 3 | 2 | 5 | Detected oscillation (IR repeated). |
| S10 | False | False | 4 | 2 | 5 | Reached max iterations. |
| S20 | False | False | 2 | 1 | 5 | Detected oscillation (IR repeated). |
| S08 | False | False | 4 | 0 | 0 | Refine failed |

## Paraphrase robustness

| Metric | Value |
| --- | --- |
| Paraphrase pairs evaluated | 20 |
| Primary variant pre-valid rate | 0.25 |
| Paraphrase variant pre-valid rate | 0.2 |
| Primary variant post-valid rate | 0.7 |
| Paraphrase variant post-valid rate | 0.7 |
| Pre validity consistency rate | 0.85 |
| Post validity consistency rate | 0.7 |
| Post exact token/topology consistency rate | 0.5 |
| Mean post similarity score | 0.7375 |

## Adversarial repair suite

| Metric | Value |
| --- | --- |
| Bundles requested | 6 |
| Bundles completed | 6 |
| Initially invalid bundles | 6 |
| Repair effectiveness rate | 1.0 |
| Final valid rate | 1.0 |
| Avg issues removed | 5.8333 |
| Avg iterations | 2.1667 |

| Bundle | Pre valid | Post valid | Issues removed | Iterations | Stop reason |
| --- | --- | --- | --- | --- | --- |
| UnreachableState | False | True | 3 | 2 | Converged (deterministic + agentic OK). |
| DuplicateTransitions | False | True | 1 | 2 | Converged (deterministic + agentic OK). |
| DeadEndState | False | True | 3 | 2 | Converged (deterministic + agentic OK). |
| DisconnectedSubgraph | False | True | 6 | 2 | Converged (deterministic + agentic OK). |
| MultiIssueRepair | False | True | 7 | 2 | Converged (deterministic + agentic OK). |
| MaxItersStop | False | True | 15 | 3 | Converged (deterministic + agentic OK). |

## Artifacts

| Artifact | Path |
| --- | --- |
| Per-scenario CSV | metrics_full_out_2\scenario_results.csv |
| Paraphrase CSV | metrics_full_out_2\paraphrase_results.csv |
| Adversarial CSV | metrics_full_out_2\adversarial_results.csv |
| Summary CSV | metrics_full_out_2\summary.csv |
| Summary JSON | metrics_full_out_2\summary.json |
