# Layer 3: Human-in-the-loop PlantUML editing (round-trip)

This repo supports a human-in-the-loop workflow where you can edit the generated PlantUML state machine and deterministically convert those edits back into canonical IR.

## Output layout

Every bundle now uses a revisioned folder structure:

- `outputs/<Bundle>/baseline/`            baseline NL→IR→PUML artifacts (from `nlpipeline run`)
- `outputs/<Bundle>/edits/edit_001/`      each human edit / round-trip revision (edit_002, edit_003, ...)
- `outputs/<Bundle>/current/`             convenience pointer (copied) to the latest canonical artifacts
- `outputs/<Bundle>/manifest.json`        lightweight revision log + current pointer metadata

Within each revision folder (`baseline` or `edits/edit_###`) you will see:

- `final.ir.json`
- `final.puml`
- `validation_report.json`

Additional debug/provenance artifacts:

- `raw.ir.json` (baseline debug and roundtrip parse output)
- `coerced.ir.json` (baseline only)
- `source.puml` (edits only; the exact edited input you supplied)

## Recommended user flow

1) Run the pipeline:

```bash
nlpipeline run --text "When motion is detected, turn on the hallway light. When motion stops, turn it off." --bundle-name Bundle1
```

Writes baseline artifacts to:

- `outputs/Bundle1/baseline/final.ir.json`
- `outputs/Bundle1/baseline/final.puml`
- `outputs/Bundle1/baseline/validation_report.json`

and updates the convenience pointer:

- `outputs/Bundle1/current/*`

2) Copy the baseline diagram to an editable file and edit it:

```bash
cp outputs/Bundle1/baseline/final.puml outputs/Bundle1/edited.puml
```

Edit `outputs/Bundle1/edited.puml` in VSCode (PlantUML preview recommended).

3) Round-trip your edited diagram back into IR:

```bash
nlpipeline roundtrip --puml outputs/Bundle1/edited.puml --out-bundle outputs/Bundle1
```

This creates a new edit revision folder:

- `outputs/Bundle1/edits/edit_###/`

and writes:

- `source.puml`                 copy of your edited input
- `raw.ir.json`                 direct parse output (best-effort)
- `final.ir.json`               canonical IR after normalize + transforms
- `validation_report.json`      parser + schema + catalog diagnostics
- `final.puml`                  regenerated canonical diagram
- `diff.json`                   if a baseline/current IR was found or you passed `--baseline-ir`

It also updates:

- `outputs/Bundle1/current/*`

## Inputs and outputs

### Inputs

- Required: `--puml <path>`
  - Path to the edited PlantUML file to parse.

- Optional: `--out-bundle <dir>`
  - Bundle root to write the new edit revision under.
  - If omitted, the tool tries to infer the bundle root by walking up from `--puml` and looking for
    `manifest.json` or `baseline/edits/current`. If nothing matches, it treats the `.puml` parent as the bundle root.

- Optional: `--baseline-ir <path>`
  - IR to diff against.
  - If omitted, defaults to `outputs/<Bundle>/current/final.ir.json` if available, otherwise `baseline/final.ir.json`.

### Outputs

- A new edit revision folder under `outputs/<Bundle>/edits/edit_###/`
- `outputs/<Bundle>/current/*` updated to point at the latest canonical artifacts
- `outputs/<Bundle>/manifest.json` updated with a new revision entry

## Supported label grammar

The round-trip parser supports the same label style produced by `ir_to_plantuml`:

- Trigger label:
  - `TRIGGER: <dev>.<attr> becomes "value" AND <dev>.<attr> changes AND after 30s AND schedule <cron>`

- Guard label:
  - `GUARD: (<dev>.<attr> == "value") and not (<dev>.<attr> != "value")`
  - Operators supported: `== != < <= > >= and or not` with parentheses.

- Action label (one per line):
  - `ACTION: <dev>.<command>()`
  - `ACTION: <dev>.<command>("arg", 1, true)`
  - `ACTION: delay 30s`
  - `ACTION: notify "message"`

PlantUML multiline labels are represented as `\n` inside the label.

## Notes on delay handling

If the edited IR contains `delay Ns` actions in the middle of a transition action list, the pipeline's deterministic transform will rewrite them into explicit timer states (the same behavior used in the main pipeline).

## Running from source

If you are running from the repo without installing it, prefix commands with `PYTHONPATH=src`, e.g.:

```bash
PYTHONPATH=src python -m nltouml.cli roundtrip --puml outputs/Bundle1/edited.puml --out-bundle outputs/Bundle1
```
