# Project Report Writing Instructions

Authoritative guidance for drafting the long-form technical report (target length: **6,000–7,000 words**, extend beyond if necessary). Maintain a formal academic tone throughout, anchor every assertion to concrete implementations in this repository, and iteratively align earlier sections with insights uncovered later.

---

## Global Requirements

1. **Word Count & Depth**: Produce a 6k–7k word manuscript (longer if needed for clarity). Every section must discuss both the underlying concept and the project-specific implementation.
2. **Source Fidelity**: Do not invent capabilities. Cite only behaviors that exist in the referenced scripts/directories.
3. **Iterative Consistency**: After completing each major section, revisit prior sections to reconcile terminology, metrics, and architectural descriptions introduced later.
4. **Documentation Review**: Before drafting, skim `PROJECT_README.md`, `PROJECT_REPORT.md`, and `docs/project_architecture.md` to capture existing narratives and diagrams for alignment.
5. **Citation Style**: When referencing implementation details, describe the component by its functional role (e.g., “the ingestion service that hashes resumes for deduplication”) rather than naming files, scripts, or paths.
6. **Clean Narrative**: The final manuscript must avoid explicit file paths, script names, or filenames altogether. Summarize behaviors and responsibilities using descriptive language only.
---

## Step-by-Step Writing Plan

Use the “Files to Review” pointers strictly as research aids. When drafting the report itself, rephrase every reference to those components in descriptive, plain language so the manuscript contains no explicit file paths, script names, or filenames.

### Step 1: Abstract & Executive Summary
- **Goal**: Frame the recruitment pain points, the CrewAI-driven solution, and high-level benefits.
- **Files to Review**: `PROJECT_README.md`, `PROJECT_REPORT.md`, `src/resume_screening_rag_automation/app.py` (for end-user behavior), `src/resume_screening_rag_automation/main.py` (for orchestration overview).
- **Content**: Summarize data ingestion, CrewAI orchestration, RAG-based screening, and UI affordances. Introduce metrics/goals only if supported by the codebase.

### Step 2: Problem Statement & Research Motivation
- **Files**: Same as Step 1 plus `training/` materials if you need historical context.
- **Content**: Discuss limitations of keyword ATS, necessity of semantic retrieval, and motivation for multi-agent coordination, linking claims to actual system traits.

### Step 3: System Architecture Blueprint
- **Files**: `docs/project_architecture.md`, `src/resume_screening_rag_automation/main.py`, `src/resume_screening_rag_automation/state.py`, `src/resume_screening_rag_automation/services/ingestion.py`.
- **Content**: Explain modular layers (UI, Flow, Crews, Knowledge, Memory). For each layer, detail the exact components and interactions implemented.

### Step 4: Data Ingestion & Monitoring Pipeline
- **Files**: `src/resume_screening_rag_automation/services/ingestion.py`, `src/resume_screening_rag_automation/tools/build_resume_vector_db.py`, `src/resume_screening_rag_automation/tools/vectorstore_utils.py`, `src/resume_screening_rag_automation/paths.py`.
- **Content**: Describe directory resolution, `_prune_duplicate_resume_files`, monitoring outputs, crew invocation, structured JSON emission, and dedupe/hash logic. Include methodological rationale (idempotency, integrity checks).

### Step 5: Knowledge Store & Vector Store Management
- **Files**: `src/resume_screening_rag_automation/knowledge/`, `paths.py`, `tools/build_resume_vector_db.py`, `tools/vectorstore_utils.py`, Chroma persistence under `src/knowledge_store/chroma_vectorstore`.
- **Content**: Detail filesystem layout, structured knowledge artifacts, vector collection naming, metadata schema, and lifecycle (creation, update, pruning). Explain why these decisions prevent context drift.

### Step 6: Embedding Strategy & RAG Techniques
- **Files**: `tools/vectorstore_utils.py` (token/char truncation), `tools/build_resume_vector_db.py`, `crews/screening_crew/`, `services/ingestion.py`.
- **Content**: Discuss `_TruncatingEmbedder`, OpenAI model selection, chunking strategy, embedding refresh triggers, retrieval parameters, and how screening consumes embeddings. Connect conceptual RAG theory to our concrete tooling.

### Step 7: Memory, Session, and Context Management
- **Files**: `src/resume_screening_rag_automation/session_memory.py`, `state.py`, `app.py`, `session_memory` storage directories.
- **Content**: Explain `SessionMemoryBundle`, optional Mem0 integration, how chat/knowledge states persist, and the mechanisms used to prevent context leakage (session-specific directories, ID alignment, memory pruning hooks).

### Step 8: Flow Orchestration & Routing Logic
- **Files**: `src/resume_screening_rag_automation/main.py`, `core/py_models.py`, `models.py`, `crews/query_manager_crew/`.
- **Content**: Detail `ResumeAssistantFlow`, decorator topology (`@start`, `@listen`, logical combinators), `_calculate_execution_plan`, `QueryControls`, and how routing decisions gate crew execution. Articulate the conceptual control theory and its actual implementation.

### Step 9: Crew Implementations & Tooling
- **Files**: `src/resume_screening_rag_automation/crews/` (each crew folder + configs), `crew_configs/`, `tools/` directory.
- **Content**: For each crew (Resume Parsing, Job Description, Query Manager, Screening, Discussion), outline goals, task graphs, prompt structures, and the tools they call. Discuss how persona definitions and task YAML influence outcomes.

### Step 10: Prompt Engineering & Response Optimization
- **Files**: `crew_configs/**/agents.yaml`, `crew_configs/**/tasks.yaml`, any prompt templates inside crew scripts, `tools/scenario_hint_tool.py`.
- **Content**: Analyze persona tuning, scenario hints, structured output enforcement (`response_format`), and post-processing (e.g., `_task_output_to_model`). Explain methodological intent behind each technique and cite precise locations.

### Step 11: Candidate Screening, Scoring, and Recommendation Logic
- **Files**: `crews/screening_crew/`, `models.py` (`CandidateScreeningOutput`, `CandidateInsight`), `core/constants.py` (weights), `state.py` (feature/scoring weights).
- **Content**: Describe scoring calculus, weighting, ranking outputs, insight generation, and markdown rendering. Tie conceptual models (multi-criteria decision making) to implemented code.

### Step 12: Discussion & Follow-up Handling
- **Files**: `crews/discussion_crew/`, `session_memory.py`, `main.py` (discussion phase), `app.py` (UI presentation).
- **Content**: Explain how follow-up questions leverage prior context, what data is fetched, and how outputs remain evidence-based. Mention safeguards against hallucination (memory lookups, structured responses).

### Step 13: Tools, Utilities, and Safeguards
- **Files**: `src/resume_screening_rag_automation/tools/` (vectorstore utilities, scenario hint tool, resume pipeline checker), `run_resume_pipeline_check.py`.
- **Content**: Enumerate each utility, the problem it solves, and the methodological reasoning (e.g., truncation to avoid 413 errors, pipeline validation to ensure data hygiene).

### Step 14: UI, Session Synchronization, and Persistence
- **Files**: `app.py`, `cli.py`, `state.py`, `session_memory.py`.
- **Content**: Describe Streamlit session handling, CLI behavior, how `persist_session` updates JSON manifests, and how UI sliders (scoring weights) feed back into state.

### Step 15: Context Leakage Prevention & Security Considerations
- **Files**: `services/ingestion.py` (hashing, dedupe), `paths.py` (directory sandboxing), `state.py` (session-specific IDs), memory bundle logic.
- **Content**: Document operational safeguards (per-session storage, hash verification, environment variable handling) and relate them to best practices.

### Step 16: Conclusion & Future Work
- **Files**: `PROJECT_REPORT.md` (section 9), Git history if needed.
- **Content**: Summarize achievements, outline pending items already identified (state reset automation, production hardening), and ensure coherence with earlier claims.

---

## Iterative Quality Checks

- After drafting each section, re-open previously completed sections to enforce consistent terminology (e.g., “Knowledge Store” vs. “knowledge store layer”), identical component names, and synchronized descriptions of flags (`allow_jd_incomplete`, `screen_again`, etc.).
- Cross-verify figures or diagrams against `docs/project_architecture.md` and regenerate if changes occur.
- Validate that every mention of a component references real code, yet the prose abstracts away file paths and script names for a clean narrative.

---

## Document Production

1. Complete the full manuscript while honoring the clean-narrative rule (no file paths, script names, or explicit filenames in the final text).
2. After the content is finalized, run `scripts/generate_word_report.py` from the project’s virtual environment to produce the Microsoft Word report.
3. Review the generated `.docx` to confirm formatting accuracy and adherence to the descriptive-only requirement before sharing it with stakeholders.

Following this guide will ensure the final report is comprehensive, academically rigorous, and faithful to the implemented system.
