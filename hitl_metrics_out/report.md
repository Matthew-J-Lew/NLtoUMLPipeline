# HITL Edit Metrics Report

This report evaluates two human-in-the-loop edit modes:

1. **Manual PlantUML edit path**: a deterministic scripted edit is rendered as an edited `.puml` artifact and passed through the existing round-trip parser/validator/regenerator.
2. **Agentic NL edit path**: a natural-language change request is sent through the existing edit-agent pipeline.

A test is counted as a HITL success only when the edit is applied, the final artifact is deterministic-valid and Layer-5-valid, regenerated PlantUML exists, the requested edit is preserved, and protected baseline behavior remains present.

## Summary

| Metric | Manual PlantUML | Agentic NL Edit | Overall |
| --- | --- | --- | --- |
| Tests | 6 | 6 | 12 |
| Post-edit overall valid | 5/6 | 5/6 | 10/12 |
| Regenerated PlantUML | 5/6 | 5/6 | 10/12 |
| Intended edit preserved | 5/6 | 5/6 | 10/12 |
| Protected behavior preserved | 5/6 | 5/6 | 10/12 |
| Unintended changes detected | 0 | 0 | 0 |
| HITL success rate | 83.33% | 83.33% | 83.33% |

## Per-test results

| Test | Mode | Edit Type | Overall Valid | Edit Preserved | Protected Behavior | Success | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S10_DelayEdit | manual_puml | delay_change | True | True | True | True | Changed duration from 300s to 600s. / Round-trip OK (no errors). |
| S10_DelayEdit | agentic_nl_edit | delay_change | True | True | True | True | Agent summary: Changed the timeout for turning off the hallway light from 5 minutes to 10 minutes. / Diff summary: / - transitions added (1) / - transitions rem |
| S13_GuardEdit | manual_puml | guard_change | True | True | True | True | Changed presence guard from not present to present. / Round-trip OK (no errors). |
| S13_GuardEdit | agentic_nl_edit | guard_change | True | True | True | True | Agent summary: Changed the guard condition to turn on the hallway light only when User Presence is present instead of not present. / Diff summary: / - transitio |
| S16_RemoveNotify | manual_puml | remove_action | True | True | True | True | Removed notify action while preserving other actions. / Round-trip OK (no errors). |
| S16_RemoveNotify | agentic_nl_edit | remove_action | True | True | True | True | Agent summary: Removed the notification action from the transition while keeping the alarm siren action and the location mode guard. / Diff summary: / - transit |
| S17_AddNotify | manual_puml | add_action | True | True | True | True | Added away-mode notification action. / Round-trip OK (no errors). |
| S17_AddNotify | agentic_nl_edit | add_action | True | True | True | True | Agent summary: Added a notification action to the existing transition that turns off the hallway light and locks the front door. / Diff summary: / - transitions |
| S20_NotificationEdit | manual_puml | notification_message_change | False | False | False | False | ERROR: argument of type 'int' is not iterable |
| S20_NotificationEdit | agentic_nl_edit | notification_message_change | False | False | False | False | ERROR: argument of type 'int' is not iterable |
| S12_DurationEdit | manual_puml | duration_change | True | True | True | True | Changed duration from 300s to 600s. / Round-trip OK (no errors). |
| S12_DurationEdit | agentic_nl_edit | duration_change | True | True | True | True | Agent summary: Updated the duration condition from 5 minutes to 10 minutes on the transition from DoorOpen to Idle, keeping the front door contact sensor trigge |
