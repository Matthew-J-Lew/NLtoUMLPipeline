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
- `outputs/Bundle1/final.ir.json`
- `outputs/Bundle1/final.puml`
- `outputs/Bundle1/validation_report.json`

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
nlpipeline --bundle-name Bundle1 --text "When motion is detected, turn on the hallway light. When motion stops, turn it off."
nlpipeline --bundle-name Bundle1 --text "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off."
nlpipeline --bundle-name Ex1_MotionLightBasic --text "When motion is detected, turn on the hallway light. When motion stops for 2 minutes, turn it off."
nlpipeline --bundle-name Ex2_DoorAlarmImmediate --text "When the front door opens, turn on the alarm. When the front door closes, turn the alarm off."
nlpipeline --bundle-name Ex3_PresenceLock --text "When I am not present, lock the front door. When I become present, unlock the front door."
nlpipeline --bundle-name Ex4_DoorAlarmDelayed --text "When the front door opens, wait 30 seconds. If the front door is still open, turn on the alarm. When the front door closes, turn the alarm off."
nlpipeline --bundle-name Ex5_MotionPresenceLighting --text "When I become not present, lock the front door and turn off the hallway light. When I become present, unlock the front door."
nlpipeline --bundle-name Ex10_TimedLightBurst --text 'When motion is detected, turn on the hallway light for 30 seconds, then turn it off.' --max-repairs 2
nlpipeline --bundle-name Ex11_DoorWaitThenAlarm --text 'When the front door opens, wait 30 seconds, then turn on the alarm. When the front door closes, turn the alarm off.' --max-repairs 2



```

If the first model output fails validation, the pipeline will automatically attempt a short **repair loop**.

---

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
