# Backend Deep Dive

## 1. Big-picture backend role

The backend is centered around a **canonical intermediate representation (IR)** of an IoT automation/state machine.

In the grand scheme, most backend files do one of these jobs:

1. Generate an initial IR from natural language.
2. Normalize/coerce the IR into a schema-friendly, canonical form.
3. Validate the IR deterministically against the schema and device/capability catalogs.
4. Convert the IR to PlantUML for human inspection/editing.
5. Convert edited PlantUML back into IR.
6. Apply constrained edit/repair patches instead of full rewrites.
7. Manage revisioned bundle outputs and evaluation runs.

This matches the architecture described in the draft report: NL -> IR -> PlantUML checkpoint -> round-trip back to IR -> deterministic validation -> validation/repair loop -> final canonical IR. The draft report also states that, at submission time, only Layers 1-4 were implemented and the full evaluation was still planned; the current repo now contains code for the later validation/repair stages and fuller evaluation harnesses. fileciteturn4file0

---

## 2. File-by-file table

| File | High-level role | Where it sits in the pipeline | Important notes |
|---|---|---|---|
| `pipeline.py` | Main baseline pipeline orchestrator | Primary Layer 1-4 flow | Runs NL -> IR -> coercion/normalization -> deterministic validation -> optional whole-IR repair -> PlantUML -> bundle outputs. Best first file to read. |
| `llm.py` | LLM boundary and prompt logic | Layer 1 generation, patch generation, patch repair | Contains strict prompting, OpenAI calls, retry/JSON extraction, edit-patch generation, repair-patch generation, and mock fallbacks. Core "AI interface" file. |
| `normalize.py` | Canonicalization and rescue layer | Between generation and validation | Fixes near-miss IRs from the model: key drift, malformed guards, schedule normalization, literal coercion, trigger/action shape cleanup, etc. One of the most important robustness files. |
| `transform.py` | Structural IR rewrite layer | After normalization | Converts inline delay actions into explicit timer states and `after` transitions, making the IR more state-machine-like. |
| `validate.py` | Deterministic validator | Layer 4 | Runs JSON Schema checks plus semantic checks against the device and capability catalogs. This is the hard gate for structural correctness. |
| `plantuml.py` | IR -> PlantUML generator | Layer 2 | Builds the human-readable/editable UML checkpoint. Encodes transitions, guards, triggers, actions, and state invariants in a controlled format. |
| `roundtrip.py` | PlantUML -> IR parser | Layer 3 | Parses the restricted PlantUML dialect produced by `plantuml.py`, rebuilds IR, validates it, regenerates canonical PlantUML, and stores diffs. |
| `agent_validate.py` | Higher-level logical validator | Layer 5 | Checks unreachable states, dead ends, ambiguous transitions, and duplicates. Separate from schema/type validation. |
| `refine.py` | Agentic validation/repair loop | Layers 5-7 | Loads current IR, runs deterministic + Layer 5 checks, asks the LLM for a constrained patch, validates the patch, applies it, and iterates until convergence or stop. |
| `agent_edit.py` | Human-requested edit pipeline | HITL edit path | Takes a natural-language change request, gets a constrained patch from the LLM, applies it to the current IR, validates, regenerates PlantUML, and creates a new revision. |
| `patch_utils.py` | Patch safety/shape validation | Supports edit and repair agents | Validates patch structure before application. Important because both edit and repair are patch-based. |
| `layout.py` | Bundle/revision filesystem manager | Output/revision management | Creates `baseline/`, `edits/`, and `current/`, allocates `edit_###` revisions, updates current pointers, and writes the manifest. |
| `io_utils.py` | Shared file IO helpers | Cross-cutting utility | Reads/writes JSON and text and extracts JSON from messy LLM responses. Small but used almost everywhere. |
| `config.py` | Settings/environment loader | Cross-cutting setup | Loads templates directory, model settings, and API key. |
| `cli.py` | User-facing command entry point | Overall orchestration entry | Wires up `run`, `metrics`, `metrics-full`, `roundtrip`, `agent-edit`, `refine`, `regression-checks`, and `studio`. Best file for understanding intended workflows. |
| `__main__.py` | Package entry point | Startup | Launches the CLI. |
| `__init__.py` | Package marker | Packaging | Minimal package file. |
| `studio_api.py` | FastAPI backend for studio UI | Server/API integration | Exposes backend functionality to the Studio frontend and reads bundle snapshots/status. |
| `diagram_render.py` | PlantUML rendering helper | UI/render support | Detects PlantUML + Graphviz setup and renders SVG previews. Mostly for the studio experience. |
| `metrics.py` | Early evaluation harness | Layers 1-4 evaluation | Measures completion, schema validity, validation errors, and constraint coverage for the earlier pipeline. |
| `metrics_full.py` | Full evaluation harness | Full-pipeline evaluation | Runs baseline vs refine-style evaluation, paraphrase robustness, adversarial bundles, and downstream readiness. Strong evidence that the repo has moved beyond the draft state. |
| `regression_checks.py` | Lightweight robustness tests | Internal quality guardrail | Codifies failure modes the team hit before: normalization, guard parsing, patch issues, etc. |
| `templates/ir_schema.json` | Canonical IR schema | Validation foundation | Defines the required JSON shape for the IR. |
| `templates/device_catalog.json` | Device inventory | Validation foundation | Defines known devices/global entities and their kinds. |
| `templates/capability_catalog.json` | Capability/command model | Validation foundation | Defines attributes, commands, and allowed values for device kinds. |

---

## 3. The most important architectural ideas

### 3.1 The IR is the real source of truth
PlantUML is not the canonical artifact. It is a checkpoint and interface layer. The backend always tries to return to a canonical IR.

### 3.2 Patches are preferred over rewrites
The agentic edit and repair paths do **not** freely regenerate the whole artifact. They generate **constrained patches** and then validate those patches before applying them.

### 3.3 There are two distinct validation layers
- **`validate.py`**: schema/catalog/type correctness.
- **`agent_validate.py`**: graph/logical state-machine correctness.

### 3.4 Robustness is layered, not delegated to the LLM alone
The backend improves reliability with:
- strict prompting and structured output handling in `llm.py`
- coercion/canonicalization in `normalize.py`
- deterministic validation in `validate.py`
- patch validation in `patch_utils.py`
- iterative repair in `refine.py`

### 3.5 The repo is revision-aware
The filesystem layout itself is part of the design. `baseline/`, `edits/`, `current/`, and `manifest.json` provide provenance and allow the UI to treat the backend like a revisioned modeling workspace.

---

## 4. Call graph / execution trace

## 4.1 Main baseline run (`nlpipeline run`)

```text
CLI main()
  -> load_settings()
  -> run_pipeline(text, bundle_name, settings, out_dir)
       -> load_templates()
       -> ensure_bundle_dirs()
       -> [Layer 1] generate_ir_with_llm() OR mock_generate_ir()
            -> OpenAI call / JSON extraction / retry logic
       -> write raw.ir.json
       -> coerce_ir_shape()
       -> normalize_ir()
       -> desugar_delays_to_timer_states()
       -> write coerced.ir.json
       -> [Layer 4] validate_all()
            -> validate_json_schema()
            -> validate_semantics()
       -> optional repair loop
            -> repair_ir_with_llm()
            -> coerce_ir_shape()
            -> normalize_ir()
            -> desugar_delays_to_timer_states()
            -> validate_all()
       -> [Layer 2 output] ir_to_plantuml()
       -> write final.ir.json
       -> write validation_report.json
       -> write final.puml
       -> update_current()
       -> write_manifest()
```

### What is happening conceptually
1. The model drafts an IR.
2. The system rescues and canonicalizes that draft.
3. Deterministic validation decides whether the artifact is structurally acceptable.
4. If needed, the system can attempt a full-IR repair.
5. A human-editable PlantUML representation is produced.
6. Baseline artifacts are stored and promoted to `current/`.

---

## 4.2 Round-trip from edited PlantUML (`nlpipeline roundtrip`)

```text
CLI main()
  -> run_roundtrip(puml_path, out_bundle_dir, settings, baseline_ir_path)
       -> load_templates()
       -> find_bundle_root()
       -> allocate_edit_dir()
       -> safe_copy(source.puml)
       -> parse_plantuml()
       -> fill device kinds from catalog
       -> write raw.ir.json
       -> normalize_ir()
       -> desugar_delays_to_timer_states()
       -> validate_all()
       -> ir_to_plantuml()   [regenerate canonical PlantUML]
       -> optional _simple_ir_diff()
       -> update_current()
       -> write_manifest()
```

### What is happening conceptually
1. A user edits the visual UML checkpoint.
2. The backend parses that edited diagram back into IR.
3. The parsed IR is normalized and validated.
4. The backend regenerates PlantUML from the canonical IR as the trust anchor.
5. A new `edit_###` revision is created and optionally promoted to `current/`.

---

## 4.3 Agent-mediated edit request (`nlpipeline agent-edit`)

```text
CLI main()
  -> run_agent_edit(bundle_name, out_dir, request_text, settings)
       -> load_templates()
       -> _load_parent_ir()   [prefer current/, else baseline/]
       -> allocate_edit_dir()
       -> write source.request.txt
       -> generate_edit_patch_with_llm() OR mock_generate_edit_patch()
       -> validate_patch_structure()
       -> apply_ir_patch(parent_ir, patch)
       -> write agent.patch.json
       -> write raw.ir.json
       -> compile_and_validate()
            -> coerce_ir_shape()
            -> normalize_ir()
            -> desugar_delays_to_timer_states()
            -> validate_all()
       -> optional patch-repair loop
            -> repair_edit_patch_with_llm()
            -> validate_patch_structure()
            -> apply_ir_patch()
            -> compile_and_validate()
       -> ir_to_plantuml()
       -> _simple_ir_diff()
       -> write summary.md
       -> write_manifest()
       -> update_current() if valid
```

### What is happening conceptually
1. The user asks for a change in natural language.
2. The LLM proposes a **patch**, not a replacement artifact.
3. The patch is structurally checked before application.
4. The patched IR is recompiled, normalized, validated, and regenerated.
5. A diff and summary are saved to a new revision folder.

---

## 4.4 Agentic validation/repair loop (`nlpipeline refine`)

```text
CLI main()
  -> run_refine(bundle_name, out_dir, settings)
       -> load_templates()
       -> _load_parent_ir()
       -> allocate_edit_dir()
       -> _compile_and_validate(parent_ir)
            -> coerce_ir_shape()
            -> normalize_ir()
            -> desugar_delays_to_timer_states()
            -> validate_all()
            -> validate_agentic()
       -> loop over iterations
            -> detect oscillation via IR hash
            -> generate_repair_patch_with_llm() OR mock_generate_repair_patch()
            -> validate_patch_structure()
            -> if invalid: repair_repair_patch_with_llm()
            -> apply_ir_patch()
            -> _compile_and_validate(updated_ir)
            -> ir_to_plantuml()
       -> final _compile_and_validate()
       -> write final.ir.json
       -> write validation_report.json
       -> write l5.validation_agent.json
       -> write final.puml
       -> _simple_ir_diff()
       -> write summary.md / summary.json
       -> write_manifest()
       -> update_current() if final artifact is OK
```

### What is happening conceptually
1. The current IR is first normalized and checked deterministically.
2. A second validation pass checks logical/model-level issues.
3. The repair agent proposes a minimal patch.
4. The system validates the patch before trusting it.
5. The loop continues until the artifact converges, oscillates, or hits the iteration cap.
6. If both deterministic and Layer 5 checks pass, the refined revision becomes the new current canonical artifact.

---

## 5. Practical reading order

If you want to understand the backend efficiently, this is the best order:

1. `cli.py`
2. `pipeline.py`
3. `llm.py`
4. `normalize.py`
5. `validate.py`
6. `plantuml.py`
7. `roundtrip.py`
8. `agent_edit.py`
9. `agent_validate.py`
10. `refine.py`
11. `metrics_full.py`
12. `layout.py`

That order starts with the main entrypoints, then the baseline pipeline, then the round-trip/edit/repair machinery.

---

## 6. Relationship to the draft report

The draft report describes a 7-layer architecture with deterministic validation, human-in-the-loop PlantUML checkpoints, and an agentic repair loop. It explicitly says that, at the time of submission, only the first four layers had been implemented, and that full-pipeline evaluation was planned for later. It also reports the early Layer 1-4 evaluation metrics: 20 prompts, 100% completion, 95% first-pass schema validity, and 95.65% average constraint coverage. fileciteturn4file0

From direct inspection of the current repo, the codebase has clearly moved beyond that earlier snapshot. The current backend includes:
- Layer 5-style validation in `agent_validate.py`
- Layer 6 repair-loop logic in `refine.py`
- agent-mediated edit support in `agent_edit.py`
- more complete evaluation in `metrics_full.py`

So the repo is ahead of the current PDF draft.

---

## 7. Bottom line

The backend is best understood as a **validation-first modeling pipeline** rather than a simple NL->diagram generator.

Its defining idea is:

- use the LLM to propose structure,
- use deterministic code to coerce and validate that structure,
- use PlantUML as a human-editable checkpoint,
- and use constrained patches plus iterative validation to improve reliability.

That is what makes the system feel much closer to a research prototype for trustworthy model synthesis than a one-shot prompt wrapper.
