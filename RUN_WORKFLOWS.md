# NL→UML Pipeline — Run & Edit Workflows (Layers 1–4)

This guide shows the **front-to-back** workflow for:
- **Baseline generation (Layers 1–4)**
- **Agentic editing (Option A: edit IR via an agent)**
- **Manual diagram editing (edit PlantUML + roundtrip compile)**

It assumes the repo is installed in a Python virtual environment and the CLI command is `nlpipeline`.

---

## 0) One-time setup

### Windows (PowerShell)
```powershell
cd "C:\path\to\NLtoUMLPipeline"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### macOS / Linux (bash/zsh)
```bash
cd /path/to/NLtoUMLPipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Real run vs mock run

- **Real run** uses your LLM API key.
- **Mock run** is deterministic and does not require a key.

#### Set API key (PowerShell)
```powershell
$env:OPENAI_API_KEY="YOUR_KEY_HERE"
```

#### Set API key (macOS/Linux)
```bash
export OPENAI_API_KEY="YOUR_KEY_HERE"
```

> Tip: You can also put your key in a `.env` file in the repo root (the CLI loads it automatically).

---

## 1) Baseline run (Layers 1–4)

Use this example scenario:

> **Scenario:** When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off.

### Command (real run)
```bash
nlpipeline run --bundle-name FullPipelineTest --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off."
```

### Command (mock run)
```bash
nlpipeline run --bundle-name FullPipelineTest --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off." --mock
```

### What should be created (expected files)

After the run, you should see:

```
outputs/FullPipelineTest/
  baseline/
    raw.ir.json
    coerced.ir.json
    final.ir.json
    final.puml
    validation_report.json
  current/
    final.ir.json
    final.puml
    validation_report.json
  manifest.json
```

**Sanity check:** open `outputs/FullPipelineTest/baseline/validation_report.json`
- It should indicate validation success (e.g., `ok: true` / no errors).

---

## 2) Agentic editing workflow (Option A)

This workflow lets a stakeholder provide a **natural-language change request**, and an agent will:
1) propose constrained edits to the **current IR**
2) re-run normalization + validation (Layer 4)
3) regenerate `final.puml`
4) write a new revision under `edits/edit_###/`
5) print a human-friendly summary + diff + validation status

### Step A — Run an agent edit
```bash
nlpipeline agent-edit --bundle-name FullPipelineTest --request "Rename Idle to LightOff, change the off-delay to 2 minutes, and add a notify action when motion becomes active."
```

> If you want to test without an API key:
```bash
nlpipeline agent-edit --bundle-name FullPipelineTest --request "Rename Idle to LightOff" --mock
```

### Step B — Verify outputs

A new folder should appear:

```
outputs/FullPipelineTest/edits/edit_001/
  source.request.txt
  agent.patch.json
  raw.ir.json
  final.ir.json
  final.puml
  validation_report.json
  diff.json
  summary.md
```

**Check these:**
- `summary.md` — short NL summary, diff bullets, validation status
- `validation_report.json` — should show OK if the patch compiled cleanly
- `final.puml` — regenerated diagram the user can review

### Step C — Confirm `current/` updated (only if validation OK)
If validation succeeded, `outputs/FullPipelineTest/current/*` is updated to match `edit_001`.

---

## 3) Manual editing workflow (PlantUML → roundtrip compile)

This workflow is for technical users who want to edit the diagram directly, then “compile” it back into IR.

### Step A — Create an editable copy of the current diagram
Copy the latest canonical diagram from `current/`:

**PowerShell**
```powershell
Copy-Item outputs/FullPipelineTest/current/final.puml outputs/FullPipelineTest/edited.puml
```

**macOS/Linux**
```bash
cp outputs/FullPipelineTest/current/final.puml outputs/FullPipelineTest/edited.puml
```

### Step B — Edit `outputs/FullPipelineTest/edited.puml`
Make safe edits like:
- rename state **display labels** while keeping aliases stable
  `state "LightOff" as Idle`
- modify `TRIGGER:` / `ACTION:` lines following the header guide

> Important: do **not** rename the alias (the `as <Alias>` part) unless you know the parser supports it.

### Step C — Roundtrip compile back into IR + validate (Layer 4)
```bash
nlpipeline roundtrip --puml outputs/FullPipelineTest/edited.puml --baseline-ir outputs/FullPipelineTest/current/final.ir.json
```

### Step D — Verify outputs

A new folder should appear, e.g.:

```
outputs/FullPipelineTest/edits/edit_002/
  source.puml
  raw.ir.json
  final.ir.json
  final.puml
  validation_report.json
  diff.json
```

**Check:**
- `validation_report.json` is OK
- `final.puml` is the regenerated canonical diagram
- `current/` updated (only if validation OK)

---

## 4) Optional: “must fail” guardrail test (manual roundtrip)

This confirms the parser rejects edits that break the contract.

1) In `edited.puml`, intentionally break an alias, e.g. change:
```plantuml
state "LightOff" as Idle
```
to:
```plantuml
state "LightOff" as LightOff
```

2) Run roundtrip again:
```bash
nlpipeline roundtrip --puml outputs/FullPipelineTest/edited.puml --baseline-ir outputs/FullPipelineTest/current/final.ir.json
```

Expected:
- validation fails
- the new `edit_###` folder will contain a failed report
- `current/` should **not** update

---

## Notes on the “good path”

- The baseline run (`nlpipeline run`) remains the default “good path.”
- Agentic edits and manual edits both write **revision folders** under `edits/` and then update `current/` only when validation succeeds.
- Later layers (5–7) can always take input from:
  - `outputs/<bundle>/current/final.ir.json`
  regardless of whether edits were agentic, manual, or none.
