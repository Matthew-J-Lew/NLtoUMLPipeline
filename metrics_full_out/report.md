# Full Pipeline Evaluation Report

Output directory: `metrics_full_out`

## Primary scenario benchmark

| Metric | Value |
| --- | --- |
| Scenarios requested | 20 |
| Scenarios completed | 17 |
| Pre structural validity rate | 1.0 |
| Pre overall validity rate | 1.0 |
| Post structural validity rate | 1.0 |
| Post overall validity rate | 1.0 |
| Repair effectiveness rate | 0.0 |
| Pre downstream readiness rate | 1.0 |
| Post downstream readiness rate | 1.0 |
| Avg issues before | 0.1765 |
| Avg issues after | 0.1765 |
| Avg issues removed | 0.0 |
| Avg iterations | 1.0 |
| Avg pre coverage | 0.9784 |
| Avg post coverage | 0.9784 |

## Refine stop reasons

| Stop reason | Count |
| --- | --- |
| Baseline failed | 1 |
| Converged (deterministic + agentic OK). | 17 |
| Refine failed | 2 |

## Scenario failures / unresolved cases

| Scenario | Pre valid | Post valid | Pre issues | Post issues | Iterations | Stop reason |
| --- | --- | --- | --- | --- | --- | --- |
| S10 | False | False | 0 | 0 | 0 | Baseline failed |
| S13 | False | False | 2 | 0 | 0 | Refine failed |
| S19 | False | False | 1 | 0 | 0 | Refine failed |

## Paraphrase robustness

| Metric | Value |
| --- | --- |
| Paraphrase pairs evaluated | 20 |
| Primary variant pre-valid rate | 0.85 |
| Paraphrase variant pre-valid rate | 0.85 |
| Primary variant post-valid rate | 0.85 |
| Paraphrase variant post-valid rate | 0.85 |
| Pre validity consistency rate | 0.8 |
| Post validity consistency rate | 0.8 |
| Post exact token/topology consistency rate | 0.35 |
| Mean post similarity score | 0.625 |

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
| Per-scenario CSV | metrics_full_out\scenario_results.csv |
| Paraphrase CSV | metrics_full_out\paraphrase_results.csv |
| Adversarial CSV | metrics_full_out\adversarial_results.csv |
| Summary CSV | metrics_full_out\summary.csv |
| Summary JSON | metrics_full_out\summary.json |
