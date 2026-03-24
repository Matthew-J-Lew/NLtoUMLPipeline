# NL → IR → PlantUML (State Machine) Pipeline

This repository converts a natural-language IoT automation requirement into a **PlantUML state machine** using a verification-first pipeline:

1. **NL → IR (JSON)** using either a mock generator or an LLM
2. **IR validation** using JSON Schema and device/capability type checking
3. **IR → PlantUML** using round-trippable transition labels
4. **Optional human-in-the-loop editing** through PlantUML round-trip
5. **Optional agentic refinement** for later pipeline layers

The project is intentionally **platform-agnostic**. The generated intermediate representation (IR) can later be adapted to targets such as Home Assistant YAML or SmartThings Rules JSON.

---

## Prerequisites

### Required
- **Python 3.10+**

### Optional
- **OpenAI API key** for LLM-backed generation
- **Node.js 20+** for the Studio frontend
- **Java** and **Graphviz** for local PlantUML rendering
- An instnace of **plantuml.jar** downloaded from the plantuml website, placed in tools/

---

## Repository Structure

- `src/` - Core pipeline implementation
- `templates/` - IR schema and device/capability catalogs
- `tools/` - Utility assets such as `plantuml.jar` if used locally
- `studio/` - MVP Studio UI
- `outputs/` - Generated bundle outputs
- `metrics_out/` - Evaluation outputs

---

## Quick Start (Mock / No LLM)

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the package:

```powershell
pip install -e .
```

Run the pipeline in mock mode:

```powershell
nlpipeline run --bundle-name Bundle1 --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off." --mock
```

This creates:

- `outputs/Bundle1/baseline/final.ir.json`
- `outputs/Bundle1/baseline/final.puml`
- `outputs/Bundle1/baseline/validation_report.json`
- `outputs/Bundle1/current/`
- `outputs/Bundle1/manifest.json`

---

## Run with OpenAI

Install the OpenAI extra:

```powershell
pip install -e ".[openai]"
```

Create a `.env` file in the repository root:

```env
OPENAI_API_KEY=YOUR_KEY
OPENAI_MODEL=gpt-5
```

Run the pipeline:

```powershell
nlpipeline run --bundle-name Front_Door_Light --text "If the front door opens, then turn on the hallway light."
```

If the first model output fails validation, the pipeline will automatically attempt a short repair loop.

---

## Human-in-the-Loop Editing (Layer 3 Round-Trip)

After generating a baseline diagram, copy it to an editable file:

```powershell
Copy-Item outputs/Bundle1/baseline/final.puml outputs/Bundle1/edited.puml
```

Edit `outputs/Bundle1/edited.puml`, then round-trip it back into IR:

```powershell
nlpipeline roundtrip --puml outputs/Bundle1/edited.puml --baseline-ir outputs/Bundle1/baseline/final.ir.json
```

Round-trip artifacts are written to a new revision directory under:

- `outputs/Bundle1/edits/edit_###/`

The latest canonical view is also updated under:

- `outputs/Bundle1/current/`

For more detail, see `LAYER3_ROUNDTRIP.md`.

---

## Agent Edit Workflow

Apply a natural-language change request to an existing bundle:

```powershell
nlpipeline agent-edit --bundle-name Bundle1 --request "Rename Idle to LightOff and change the timeout to 120 seconds."
```

This writes the result to a new revision under `outputs/Bundle1/edits/`.

---

## Refine Workflow (Later Pipeline Layers)

Run the agentic validation and repair loop on the current IR:

```powershell
nlpipeline refine --bundle-name Bundle1 --max-iters 5 --max-patch-repairs 2
```

Use `--mock` if you want to test the refine loop without an LLM.

---

## Reproduce Evaluation Metrics

Run the metrics workflow on the included scenario set:

```powershell
nlpipeline metrics --scenarios scenarios.csv --out-dir metrics_out
```

This produces files such as:

- `metrics_out/per_scenario_results.csv`
- `metrics_out/metrics_summary.csv`
- `metrics_out/metrics_summary.json`
- `metrics_out/runs/`

---

## Studio UI

The repository includes an MVP Studio UI in `studio/` with a FastAPI backend.

### Backend setup

Install the studio extra:

```powershell
pip install -e ".[studio]"
```

Run the backend API:

```powershell
nlpipeline studio --host 127.0.0.1 --port 8000
```

### Frontend setup

Open a second PowerShell window:

```powershell
cd studio
npm install
npm run dev
```

Open the app at:

`http://127.0.0.1:5173`

### Studio capabilities

- Create a new baseline run from natural language
- Browse existing bundles in `outputs/`
- Inspect IR, PlantUML, validation reports, and diffs
- Edit PlantUML directly in the UI and round-trip it back into IR
- Submit agent edit requests
- Run the refine loop from the UI
- View revision history and diagnostics in one interface

---

## Optional: Local PlantUML Rendering

To enable local diagram previews:

1. Install Java
2. Install Graphviz
3. Download `plantuml.jar`
4. Place it at:

```text
tools/plantuml.jar
```

You can also render `.puml` files using a PlantUML VS Code extension or an online/local PlantUML renderer.

---

## Notes

- The preferred CLI form is **`nlpipeline <subcommand>`**.
- The main run command is **`nlpipeline run`**.
- Legacy top-level usage may still work, but the standardized form used in this README is the recommended one.
