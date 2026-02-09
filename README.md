# NL → IR → PlantUML (State Machine) Pipeline (Verification-first)

This repo turns a natural-language automation requirement into a **PlantUML state machine** by:

1) **NL → IR (JSON)** (LLM or mock generator)
2) **IR validation** (JSON Schema + device/capability type checking)
3) **IR → PlantUML** (round-trippable transition labels)

It is intentionally **platform-neutral**: downstream code generation to Home Assistant YAML, SmartThings Rules JSON, etc. can be implemented as adapters later.

---

## Quick start (no LLM, demo mode)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

nlpipeline --bundle-name Bundle1 \
  --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off." \
  --mock
```

Outputs:
- `outputs/Bundle1/baseline/final.ir.json`
- `outputs/Bundle1/baseline/final.puml`
- `outputs/Bundle1/baseline/validation_report.json`
- `outputs/Bundle1/current/` (copies of the latest canonical `final.*` + report)
- `outputs/Bundle1/manifest.json`

---

## Using an LLM (OpenAI)

Install optional dependency:

```bash
pip install -e ".[openai]"
```

Create a `.env` file:

```env
OPENAI_API_KEY=YOUR_KEY
OPENAI_MODEL=gpt-5
```

Run:

```bash
nlpipeline --bundle-name Front_Door_Light --text "If the front door opens, then turn on the hallway light."

```

If the first model output fails validation, the pipeline will automatically attempt a short **repair loop**.

---

## Human-in-the-loop editing (Layer 3 round-trip)

After `nlpipeline run`, edit the generated diagram and round-trip it back into IR:

```bash
cp outputs/Bundle1/baseline/final.puml outputs/Bundle1/edited.puml
# edit outputs/Bundle1/edited.puml
nlpipeline roundtrip --puml outputs/Bundle1/edited.puml --out-bundle outputs/Bundle1
```

Round-trip artifacts are written to a new revision folder:

- `outputs/Bundle1/edits/edit_###/` (contains `source.puml`, `raw.ir.json`, `final.ir.json`, `validation_report.json`, `final.puml`, and optional `diff.json`)

The convenience pointer is also updated:

- `outputs/Bundle1/current/`

For full details, see `LAYER3_ROUNDTRIP.md`.

## Rendering the PlantUML

The output is PlantUML text (`.puml`). To render to PNG/SVG you can:

- Use the PlantUML VSCode extension, or
- Use a local PlantUML jar, or
- Paste into any PlantUML renderer.

---

## Templates used

- `templates/ir_schema.json`
- `templates/device_catalog.json`
- `templates/capability_catalog.json`

The device and capability catalogs will be expanded later for more scenarios.

## How to run:
1. Activate virtual environment
```bash
.\.venv\Scripts\Activate.ps1
```
2. Run the pipeline on a scenario
```bash
nlpipeline run --bundle-name L1234_Test --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off."
```
3. Copy the baseline UML to an editing area
```bash
Copy-Item outputs/L1234_Test/baseline/final.puml outputs/L1234_Test/edited.puml
```
Now you can edit the .puml
4. Roundtrip the edited .puml back into layer 4
```bash
nlpipeline roundtrip --puml outputs/L1234_Test/edited.puml --baseline-ir outputs/L1234_Test/baseline/final.ir.json
```
Now the results are the finished version of layer 4