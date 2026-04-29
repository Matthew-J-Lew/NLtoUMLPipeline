# HITL Edit Metrics Report

This report evaluates two human-in-the-loop edit modes:

1. **Manual PlantUML edit path**: a deterministic scripted edit is rendered as an edited `.puml` artifact and passed through the existing round-trip parser/validator/regenerator.
2. **Agentic NL edit path**: a natural-language change request is sent through the existing edit-agent pipeline.

A test is counted as a HITL success only when the edit is applied, the final artifact is deterministic-valid and Layer-5-valid, regenerated PlantUML exists, the requested edit is preserved, and protected baseline behavior remains present.

## Summary

| Metric | Manual PlantUML | Agentic NL Edit | Overall |
| --- | --- | --- | --- |
| Tests | 6 | 6 | 12 |
| Post-edit overall valid | 6/6 | 5/6 | 11/12 |
| Regenerated PlantUML | 6/6 | 5/6 | 11/12 |
| Intended edit preserved | 6/6 | 5/6 | 11/12 |
| Protected behavior preserved | 6/6 | 5/6 | 11/12 |
| Unintended changes detected | 0 | 0 | 0 |
| HITL success rate | 100.00% | 83.33% | 91.67% |

## Failure stage counts

| Stage | Manual PlantUML | Agentic NL Edit | Overall |
| --- | --- | --- | --- |
| agent_edit | 0 | 1 | 1 |
| success | 6 | 5 | 11 |

## Per-test results

| Test | Mode | Edit Type | Failure Stage | Overall Valid | Edit Preserved | Protected Behavior | Success | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S10_DelayEdit | manual_puml | delay_change | success | True | True | True | True | Changed duration from 300s to 600s. / Round-trip OK (no errors). |
| S10_DelayEdit | agentic_nl_edit | delay_change | success | True | True | True | True | Agent summary: Changed the timeout for turning off the hallway light from 5 minutes to 10 minutes by updating the 'after' trigger seconds from 300 to 600. / Dif |
| S13_GuardEdit | manual_puml | guard_change | success | True | True | True | True | Changed presence guard from not present to present. / Round-trip OK (no errors). |
| S13_GuardEdit | agentic_nl_edit | guard_change | success | True | True | True | True | Agent summary: Changed the guard condition on the transition from Idle to LightOn to require User Presence to be 'present' instead of 'not present'. / Diff summ |
| S16_RemoveNotify | manual_puml | remove_action | success | True | True | True | True | Removed notify action while preserving other actions. / Round-trip OK (no errors). |
| S16_RemoveNotify | agentic_nl_edit | remove_action | success | True | True | True | True | Agent summary: Removed the notification action from the transition while keeping the alarm siren action and the location mode guard. / Diff summary: / - transit |
| S17_AddNotify | manual_puml | add_action | success | True | True | True | True | Added away-mode notification action. / Round-trip OK (no errors). |
| S17_AddNotify | agentic_nl_edit | add_action | success | True | True | True | True | Agent summary: Added a notification action to the existing transition that turns off the hallway light and locks the front door. / Diff summary: / - transitions |
| S20_NotificationEdit | manual_puml | notification_message_change | success | True | True | True | True | Changed notification message. / Round-trip OK (no errors). |
| S20_NotificationEdit | agentic_nl_edit | notification_message_change | success | True | True | True | True | Agent summary: Corrected the guard condition by removing the invalid 'timeHour' attribute and updated the notification message as requested. / Diff summary: / - |
| S12_DurationEdit | manual_puml | duration_change | success | True | True | True | True | Changed duration from 300s to 600s. / Round-trip OK (no errors). |
| S12_DurationEdit | agentic_nl_edit | duration_change | agent_edit | False | False | False | False | Agent edit FAILED (patch could not be applied). / Revision: hitl_metrics_fixed_3\runs\HITL_Agent_S12_DurationEdit\edits\edit_001 / Reason: transition index out  |
