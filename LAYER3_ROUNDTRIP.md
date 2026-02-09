# Layer 3: Human-in-the-loop PlantUML editing (round-trip)

This repo now supports a human-in-the-loop workflow where you can edit the generated PlantUML state machine and deterministically convert those edits back into canonical IR.

## What this adds

### 1) A new CLI command: `roundtrip`

Parses an edited `.puml` file back into IR, re-runs deterministic normalization + delay desugaring, validates against schema + catalogs, and regenerates a canonical `.puml` so you can diff what the system understood.

### 2) A parseable PlantUML format (by design)

The PlantUML generator now emits:

- A comment "cheat sheet" at the top describing the label grammar
- Explicit state declarations so you can rename display labels safely:

  `state "Hallway Light On" as LightOn`

The alias (`LightOn`) is treated as the stable state ID. You can change the quoted display label without breaking round-trip parsing.

### 3) Deterministic diagnostics with line numbers

If the parser hits unsupported syntax or malformed labels, it emits diagnostics with a `puml:L<line>` location and an error code.

## Recommended user flow

1) Run the pipeline as usual:

```bash
nlpipeline run --text "When motion is detected, turn on the hallway light. When motion stops, turn it off." --bundle-name Bundle1
```

This writes:

- `outputs/Bundle1/final.ir.json`
- `outputs/Bundle1/final.puml`
- `outputs/Bundle1/validation_report.json`

2) Copy and edit the diagram:

```bash
cp outputs/Bundle1/final.puml outputs/Bundle1/edited.puml
```

Open `outputs/Bundle1/edited.puml` in VSCode (with PlantUML preview) and edit states/transitions/triggers/actions.

3) Round-trip the edited diagram back into IR:

```bash
nlpipeline roundtrip --puml outputs/Bundle1/edited.puml --baseline-ir outputs/Bundle1/final.ir.json
```

## Inputs and outputs

### Inputs

- Required: `--puml <path>`
  - The edited PlantUML file to parse.

- Optional: `--baseline-ir <path>`
  - A baseline IR to generate a small semantic diff against.

- Optional: `--out-bundle <dir>`
  - Where to write the round-trip artifacts (defaults to the `.puml` file's parent folder).

### Outputs (written next to the edited `.puml` by default)

- `edited.raw.ir.json`
  - The direct result of parsing (best-effort).

- `edited.ir.json`
  - Parsed IR after deterministic normalization and delay desugaring.

- `edited.validation_report.json`
  - Combined report containing:
    - Parser diagnostics (line-numbered)
    - Schema validation errors
    - Catalog/type validation errors

- `edited.regenerated.puml`
  - Canonical PlantUML regenerated from `edited.ir.json`.

- `edited.diff.json` (only if `--baseline-ir` is provided)
  - Lightweight diff of initial state, added/removed states, and added/removed transitions.

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
PYTHONPATH=src python -m nltouml.cli roundtrip --puml outputs/Bundle1/edited.puml
```
