# Query Manager Training Module

This module packages everything needed to train the Query Manager crew to set the correct phase sequence and control flags for common recruiter interactions.

## Contents

- `scenarios.jsonl` &mdash; ten curated training scenarios with inputs, expected outputs, and feedback hints.
- `run_training.py` &mdash; helper script to launch an interactive CrewAI training session that replays the scenarios.
- `trained_query_manager.pkl` (generated) &mdash; consolidated guidance produced after you complete training; the crew loads this automatically on future runs.

## Preparing for Training

1. **Review the scenarios**: `scenarios.jsonl` mirrors the smoke-test harness cases and documents the required phase order and flags for each situation (JD updates, reruns, discussions, new role pivots, etc.). Keep it open while you train so your feedback stays consistent.
2. **Decide on a model**: Use an LLM with at least 7B parameters (e.g., `gpt-4o`, `claude-3-sonnet`) for reliable adherence to feedback, per CrewAI guidance.
3. **Activate your virtual environment**: `poetry shell` or equivalent, then `cd` into `resume_screening_rag_automation_v1_crewai-project`.

## Running Interactive Training

You have two options: CLI or Python helper.

### Option A: CrewAI CLI

```powershell
cd D:\RAG_CV\resume_screening_rag_automation_v1_crewai-project
crewai train -n 1 -f training\query_manager\trained_query_manager.pkl
```

- The CLI will prompt you for human feedback after each attempt. Reference the matching entry in `training/query_manager/scenarios.jsonl` to coach the agent toward the listed `phase_sequence` and `flags`.
- Rerun the command with `-n` set to the number of iterations you want. Training data accumulates in the same `.pkl` file, so use the same `-f` path for subsequent sessions.

### Option B: Guided Python Script

```powershell
cd D:\RAG_CV\resume_screening_rag_automation_v1_crewai-project
poetry run python training\query_manager\run_training.py --iterations 1
```

- The script prints each scenario, the expected routing, and suggested feedback talking points before starting the CrewAI training loop.<br>
- Provide corrective feedback when prompted until the agent matches the expected output. Repeat for all scenarios (10 by default).
- To focus on specific cases you can pass scenario names or indices, for example:
  - `--scenario 8` (only scenario 8)
  - `--scenario "Discussion requested without candidates"`
  - Multiple `--scenario` flags run in the order supplied.

### Feedback Tips

- Demand the exact `phase_sequence` listed. If the agent omits `discussion` when required, tell it explicitly: "You must return `[\"job_description\", \"discussion\"]` because...".
- Call out missing flags (e.g., `screen_again`, `new_job_search`). Encourage the agent to leave unrelated flags unset.
- Reinforce `allow_jd_incomplete` usage only when screening proceeds with an incomplete brief.
- For composite requests, remind the agent to keep the phases in dependency order.

## After Training

1. Confirm the artifact exists:
   ```powershell
   dir training\query_manager\trained_query_manager.pkl
   ```
2. Re-run the smoke tests to verify improvements:
   ```powershell
   poetry run python -m resume_screening_rag_automation.crews.query_manager_crew.kickoff_query_manager
   ```
3. Commit the updated `.pkl` and any notes once you are satisfied (unless you keep the trained data out of version control).

## Updating the Scenario Set

- Edit `scenarios.jsonl` to add new edge cases or adjust expectations as routing logic evolves. Maintain one JSON object per line.
- If you change the crew inputs or schema, ensure both `run_training.py` and the smoke-test harness reflect the same structure.
- Regenerate the training artifact whenever the instructions or scenarios change significantly.

With these assets in place, the Query Manager crew can be trained interactively to handle the full range of recruiter requests while preserving consistent routing behavior.
