# Resume Screening Assistant Implementation Guide

## 1. Current System Overview

- **Data ingestion (`src/resume_screening_rag_automation/services/ingestion.py`)**: Handles resume deduplication, crew parsing fallback, structured JSON persistence, and vector store sync.
- **Pipeline monitor (`src/resume_screening_rag_automation/run_resume_pipeline_check.py`)**: CLI that orchestrates folder monitoring, ingestion updates, and optional embedding rebuilds.
- **Knowledge store (`src/resume_screening_rag_automation/knowledge/structured_resumes.json`)**: Canonical structured resume data consumed by downstream crews and the vector database.
- **Conversation storage (`conversation_sessions/`)**: Persisted transcripts and metadata from previous crew executions.
- **Crew suites (`src/resume_screening_rag_automation/crews/`)**: Modular CrewAI definitions for resume parsing, query management, job description synthesis, screening, and conversational follow-up.

## 2. Crew Architecture Snapshot

- **`query_manager_crew`**: Determines conversation phase, sets control flags, and prepares routing hints for downstream crews. Configured via `config/tasks.yaml` and `config/agents.yaml`.
- **`resume_parsing_crew`**: Converts raw resume text into structured `Resume` models; invoked by ingestion.
- **`job_description_crew`**: Generates or enriches job descriptions based on recruiter prompts and structured resume data.
- **`screening_crew`**: Filters and ranks candidates, producing interview shortlists and insights.
- **`discussion_crew`**: Manages follow-up dialogue, clarifications, or human-in-the-loop summaries after screening.

Crews are instantiated through their respective `kickoff_*.py` helpers. Each crew consumes typed payloads defined in `src/resume_screening_rag_automation/models.py` and shares state via the knowledge store and conversation sessions.

## 3. Planned Chat Application Flow

1. **User query ingestion** in a Streamlit chat UI.
2. **Query Manager phase detection**: Initial message routed to `query_manager_crew`, which returns phase (`job_description`, `screening`, `discussion`, etc.) plus control flags.
3. **Conditional crew chaining**: Based on flags, dispatch to job description, screening, or discussion crews. Each crew returns structured responses to the UI.
4. **State persistence**: Conversation session state (chat history) and knowledge session state (Flow state, embeddings, filtered resumes) saved per session for recall.
5. **Vector and knowledge sync**: When resumes change, ingestion updates data so crews operate on fresh artifacts.

## 4. Implementation Roadmap

Follow the steps below; after completing each numbered step, return to this document, tick the checklist entry in Section 6, and append notes if behavior deviates.

### Step 1. Integrate CrewAI Flow in `main.py`

Goal: Align with CrewAI Flow documentation to orchestrate the chat routing pipeline.

1. Review Flow concepts in `crewAI-main/crewAI-main/docs/en/concepts/flows.mdx` and the starter tutorial `crewAI-main/crewAI-main/docs/en/guides/flows/first-flow.mdx`.
2. Model the user journey as a `Flow` instance instantiated per chat session. Define nodes:
   - `query_manager` node → wraps `query_manager_crew().kickoff()`.
   - `job_description`, `screening`, `discussion` nodes → call respective crews.
   - Transition functions inspect flags from the `query_manager` payload to decide routing.
3. Implement `src/resume_screening_rag_automation/main.py` (create if missing) to expose a `build_flow()` helper that returns the configured Flow.
4. Ensure Flow state objects serialize control flags, candidate filters, and conversation context using the data models in `models.py`.
5. Add logging hooks (`logging.getLogger(__name__)`) so downstream debugging captures Flow transitions.

### Step 2. Implement `state.py` for crew/UI synchronization

1. Read Flow state persistence guidance in `crewAI-main/crewAI-main/docs/en/guides/flows/mastering-flow-state.mdx`.
2. Create `src/resume_screening_rag_automation/state.py` with:
   - Data classes for `ChatSessionState` and `KnowledgeSessionState` (reuse Pydantic models where possible).
   - Helpers to load/save state snapshots to `conversation_sessions/` and `knowledge/` directories.
   - Methods to bind Flow state to Streamlit `st.session_state` keys.
3. Provide utility functions (`get_or_create_session`, `persist_session`) to ensure Streamlit sessions rehydrate Flow state before each user turn.
4. Document serialization format (JSON with ISO timestamps) in code comments to keep ingestion and UI aligned.

### Step 3. Align crew scripts with Flow routing

1. Audit each crew’s kickoff script (`crews/*/kickoff_*.py`) to accept the Flow state payloads you designed in Step 2.
2. Update crew config YAMLs (`crews/*/config/*.yaml`) so prompt templates reference the new control flags and session context variables (`current_phase`, `required_outcome`, etc.).
3. Verify data models in `models.py` cover all inputs/outputs. Extend them if Flow nodes require richer context (e.g., ranking weights, candidate IDs).
4. Where crews share knowledge artifacts, ensure they read from `structured_resumes.json`, `generated_screening_insights.json` and any Flow-specific caches rather than reloading raw text.
5. Run unit or smoke tests for each crew by executing their kickoff scripts with representative payloads. Capture issues and update this file with test notes.

### Step 4. Build Streamlit Chat Interface (`streamlit_app/app.py`)

1. Review Streamlit chat examples in `crewAI-main/crewAI-main/docs/en/examples` (focus on agent chat flows, if present).
2. Key UI requirements:
   - **Chat Tab**: Displays user/assistant messages in reverse chronological order. Messages pulled from Flow outputs and persisted via `state.py` helpers.
   - **Session Navigator Tab**: Lists stored chat sessions (conversation session IDs) and knowledge sessions. Selecting a session rehydrates Flow and updates the chat view.
   - **Search & Feature Weighting Tab**: Provide human-friendly sliders or toggles to indicate emphasis on feature weights and sementic wieghts using plain language.
3. Instantiate `build_flow()` per session. For each user input:
   - Append to chat history.
   - Invoke Flow.run with current state.
   - Stream intermediate crew responses (use Streamlit `st.chat_message` + `Flow` streaming hooks when available).
4. Store conversation transcripts after each turn in `conversation_sessions/` (JSON plus metadata). Ensure knowledge session ID is tracked and visible in the UI.
5. Provide a reset action that clears chat inputs but maintains archived sessions for selection.

## 5. Reference Summary

- Flow concepts: `crewAI-main/crewAI-main/docs/en/concepts/flows.mdx`
- Flow tutorial: `crewAI-main/crewAI-main/docs/en/guides/flows/first-flow.mdx`
- Flow state management: `crewAI-main/crewAI-main/docs/en/guides/flows/mastering-flow-state.mdx`
- Data models: `src/resume_screening_rag_automation/models.py`
- Crew configurations: `src/resume_screening_rag_automation/crews/*/config/*.yaml`
- the current kickoff scripts for each crew: `src/resume_screening_rag_automation/crews/*/kickoff_*.py`, do not use them directly but refer to them to understand kickoff integration.

## 6. Implementation Checklist

Update this list continuously. Mark completed tasks with `[x]`, include brief notes or commit hashes beside each item, and add new subtasks as they emerge.

- [x] Step 1: Flow orchestration implemented in `main.py`, referencing Flow docs. *(Flow orchestrator + CLI harness added 2025-11-11)*
- [x] Step 2: `state.py` created with session persistence and UI bindings. *(Session/knowledge persistence helpers in place, JSON + ISO timestamps documented)*
- [ ] Step 3: Crew scripts and configs updated to consume Flow state.
   - Kickoff scripts now hydrate typed session payloads; config prompt updates and crew-level smoke tests still pending.
- [ ] Step 4: Streamlit chat interface revamped with session navigation and feature emphasis controls.
- [ ] End-to-end test: Run Streamlit app, send multi-phase query, verify correct crew routing and state restoration.

## 7. Maintenance Instructions

- After each major implementation increment, return here to:
  1. Check off the relevant checklist item.
  2. Document deviations, TODOs, or testing gaps beneath the item.
  3. Add any new discoveries under a “Notes” subsection (create if absent).
- Keep references current. If documentation paths change, update Section 5.
- When onboarding new contributors, point them to this guide before they modify crews or Flow logic.
