"""CrewAI Flow orchestration for the resume screening assistant."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from crewai.flow.flow import Flow, and_, listen, or_, start
from crewai.tasks.task_output import TaskOutput

from resume_screening_rag_automation.crews.discussion_crew.discussion_crew import (
    DiscussionCrew,
)
from resume_screening_rag_automation.crews.job_description_crew.job_description_crew import (
    JobDescriptionCrew,
)
from resume_screening_rag_automation.crews.query_manager_crew.query_manager_crew import (
    QueryManagerCrew,
)
from resume_screening_rag_automation.crews.screening_crew.screening_crew import (
    ScreeningCrew,
)
from resume_screening_rag_automation.knowledge.insight_store import (
    append_screening_insights,
)
from resume_screening_rag_automation.core.py_models import AppState, QueryRoutingInput
from resume_screening_rag_automation.models import (
    CandidateAnalysisOutput,
    CandidateInsight,
    CandidateScreeningOutput,
    ChatMessage,
    ConversationPhase,
    JobDescription,
    DiscussionInput,
    DiscussionOutput,
    JobDescriptionInput,
    JobDescriptionOutput,
    Metadata,
    QueryControls,
    QueryRoutingOutput,
    ScreeningInput,
    format_outstanding_questions_md,
)
from resume_screening_rag_automation.state import (
    ChatSessionState,
    KnowledgeSessionState,
    ResumeAssistantFlowState,
)
from resume_screening_rag_automation.session_memory import SessionMemoryBundle

LOGGER = logging.getLogger(__name__)


def _suppress_crewai_tracing_prompt() -> None:
    """Mark CrewAI tracing as initialised to avoid first-run CLI prompt."""
    try:
        from crewai.events.listeners.tracing.utils import mark_first_execution_done
    except ImportError:
        LOGGER.debug("CrewAI tracing utilities unavailable; skipping prompt suppression")
        return
    try:
        mark_first_execution_done()
    except Exception as exc:  # pragma: no cover - defensive logging only
        LOGGER.debug("Unable to suppress CrewAI tracing prompt: %s", exc)


_suppress_crewai_tracing_prompt()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _as_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _task_output_to_model(task_output: TaskOutput, model_cls: Any) -> Any:
    if task_output is None:
        raise ValueError("Crew returned no output")

    payload = getattr(task_output, "pydantic", None)
    if payload is not None:
        return payload

    json_dict = getattr(task_output, "json_dict", None)
    if json_dict is not None:
        return model_cls.model_validate(json_dict)

    raw = getattr(task_output, "raw", None)
    if raw:
        return model_cls.model_validate_json(raw)

    raise ValueError(f"Unable to coerce crew output into {model_cls.__name__}")


def _is_job_snapshot_complete(snapshot: JobDescription) -> bool:
    if snapshot is None:
        return False
    if not snapshot.job_title:
        return False
    if snapshot.outstanding_questions:
        return False
    completeness_markers = [
        snapshot.location,
        snapshot.required_skills,
        snapshot.job_responsibilities,
        snapshot.experience_level_years,
    ]
    return any(bool(marker) for marker in completeness_markers)


def _synchronise_query_controls(chat_state: ChatSessionState) -> None:
    controls = chat_state.query_controls
    if controls is None:
        controls = QueryControls()
        chat_state.query_controls = controls

    controls.last_completed_phase = (
        chat_state.last_completed_phase.value if chat_state.last_completed_phase else None
    )
    controls.jd_complete = _is_job_snapshot_complete(chat_state.job_snapshot)
    controls.candidates_ready = bool(
        chat_state.latest_screening_output
        and chat_state.latest_screening_output.candidate_insights
    )


def _derive_missing_job_details(snapshot: JobDescription) -> List[str]:
    """Generate follow-up questions for incomplete job description fields."""

    if snapshot is None:
        snapshot = JobDescription()

    prompts: List[str] = []

    if not snapshot.job_title:
        prompts.append("What is the job title for this role?")
    if not snapshot.location:
        prompts.append("Where is the role primarily located?")
    if snapshot.experience_level_years is None:
        prompts.append("How many years of experience should candidates have?")
    if not snapshot.required_skills:
        prompts.append("Which specific skills are required for this position?")
    if not snapshot.job_responsibilities:
        prompts.append("What are the key responsibilities for this role?")
    if snapshot.job_type is None:
        prompts.append("What is the employment type (e.g. full-time, contract, hybrid)?")
    if not snapshot.education_requirements:
        prompts.append("Are there any education requirements or preferred degrees?")
    if not snapshot.language_requirements:
        prompts.append("Should candidates possess any particular language skills?")
    if not snapshot.certification_requirements:
        prompts.append("Are there certifications that are required or preferred?")

    return prompts


def _merge_outstanding_questions(existing: List[str], derived: List[str]) -> List[str]:
    seen_lower = set()
    merged: List[str] = []
    for question in (existing or []) + (derived or []):
        key = question.strip()
        if not key:
            continue
        lower = key.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        merged.append(key)
    return merged


def _conversation_history(messages: List[ChatMessage], limit: int = 20) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    if not messages:
        return history
    for message in messages[-limit:]:
        history.append(
            {
                "role": message.role,
                "phase": message.phase.value if message.phase else None,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
                "content": message.content_md,
            }
        )
    return history


def _split_screening_message_sections(message_md: str) -> Dict[str, str]:
    if not message_md:
        return {"table": "", "recommendations": ""}
    lines = message_md.splitlines()
    table_lines: List[str] = []
    recommendation_lines: List[str] = []
    mode = "table"
    summary_tokens = {"summary", "## summary", "### summary"}
    recommendation_tokens = {"recommendations", "## recommendations", "### recommendations"}
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered in summary_tokens:
            mode = "summary"
            continue
        if lowered in recommendation_tokens:
            mode = "recommendations"
            continue
        if mode == "table":
            table_lines.append(line)
        elif mode == "recommendations":
            recommendation_lines.append(line)
        else:
            # skip summary content; we'll rebuild reasoning separately
            continue
    return {
        "table": "\n".join(table_lines).strip(),
        "recommendations": "\n".join(recommendation_lines).strip(),
    }


def _format_candidate_reasoning(insights: List[CandidateInsight]) -> str:
    if not insights:
        return ""
    blocks: List[str] = []
    for idx, insight in enumerate(insights, start=1):
        candidate_name = _candidate_display_name(insight, idx)
        heading = f"#### {idx}. {candidate_name}"
        body_parts: List[str] = []
        summary = (insight.summary_md or "").strip()
        if summary:
            body_parts.append(summary)
        reasoning_points = [point.strip() for point in insight.fit_reasoning or [] if point and point.strip()]
        if reasoning_points:
            bullets = "\n".join(f"- {point}" for point in reasoning_points)
            body_parts.append(bullets)
        if not body_parts:
            continue
        blocks.append(f"{heading}\n\n" + "\n\n".join(body_parts))
    if not blocks:
        return ""
    return "### Reasoning\n\n" + "\n\n".join(blocks)


def _format_recommendations(recommendations_md: str) -> str:
    text = (recommendations_md or "").strip()
    if not text:
        return ""
    if text.lower().startswith("recommendations"):
        return text
    return "### Recommendations\n\n" + text


def _format_database_summary(summary_md: Optional[str]) -> str:
    text = (summary_md or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("#") or lowered.startswith("database summary"):
        return text
    return "### Database Summary\n\n" + text


def _candidate_display_name(insight: CandidateInsight, index: int) -> str:
    metadata = insight.metadata or Metadata()
    return (
        (metadata.candidate_name or "").strip()
        or (metadata.file_name or "").strip()
        or (metadata.current_title or "").strip()
        or (metadata.candidate_id or "").strip()
        or f"Candidate {index}"
    )


def _format_candidate_table(insights: List[CandidateInsight]) -> str:
    if not insights:
        return ""

    sorted_insights = sorted(
        insights,
        key=lambda insight: getattr(getattr(insight, "scores", None), "job_fit_score", 0.0),
        reverse=True,
    )

    header = "### Candidate Overview\n\n| Rank | Candidate | Fit Score | Highlight |\n| --- | --- | --- | --- |"
    rows: List[str] = []
    for idx, insight in enumerate(sorted_insights, start=1):
        candidate_name = _candidate_display_name(insight, idx)
        score = getattr(getattr(insight, "scores", None), "job_fit_score", None)
        score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "-"
        # Construct highlight from specific matched features
        matched = insight.matched_features
        parts = []
        
        if matched.matching_skills:
            skills = ", ".join(matched.matching_skills[:3])
            parts.append(f"Skills: {skills}")
            
        if matched.matching_experience:
            exp = ", ".join(matched.matching_experience[:2])
            parts.append(f"Exp: {exp}")
            
        if matched.matching_education:
            edu = matched.matching_education[0]
            parts.append(f"Edu: {edu}")
            
        highlight = "; ".join(parts)
        
        # Fallback if no specific features matched
        if not highlight:
            summary = (insight.summary_md or "").strip().splitlines()[0] if insight.summary_md else ""
            highlight = summary or (insight.fit_reasoning[0].strip() if insight.fit_reasoning else "")
            
        highlight = highlight[:140] + ("…" if len(highlight) > 140 else "")
        rows.append(f"| {idx} | {candidate_name} | {score_text} | {highlight or '—'} |")

    return header + "\n" + "\n".join(rows)


def _compose_screening_markdown(output: CandidateScreeningOutput) -> str:
    parts: List[str] = []
    db_summary = _format_database_summary(output.database_summary_md)
    if db_summary:
        parts.append(db_summary)

    candidate_table = _format_candidate_table(output.candidate_insights)
    if candidate_table:
        parts.append(candidate_table)
    elif output.message_md:
        table_candidate_section = _split_screening_message_sections(output.message_md or "").get("table", "").strip()
        if table_candidate_section:
            parts.append(table_candidate_section)

    reasoning_section = _format_candidate_reasoning(output.candidate_insights)
    if reasoning_section:
        parts.append(reasoning_section)

    screening_rationale = (output.reasoning or "").strip()
    if screening_rationale:
        parts.append("### Screening Rationale\n\n" + screening_rationale)

    # Preserve any recommendations generated by the crew if present.
    sections = _split_screening_message_sections(output.message_md or "")
    recommendations = _format_recommendations(sections.get("recommendations", ""))
    if recommendations:
        parts.append(recommendations)
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


class ResumeAssistantFlow(Flow[ResumeAssistantFlowState]):
    """Flow that sequences query management, parsing, screening, and discussion crews."""

    initial_state = ResumeAssistantFlowState
    name = "ResumeScreeningFlow"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._logger = LOGGER.getChild(self.__class__.__name__)
        self._session_memory_bundle: Optional[SessionMemoryBundle] = None

    @start()
    def run_query_manager(self) -> Optional[QueryRoutingOutput]:
        """Capture the latest recruiter turn and determine the next phases."""

        self.state.turn_responses = []
        self.state.turn_finalised = False
        self.state.completed_phases = []
        self.state.execution_plan = []

        chat_state = self.state.chat_state
        self._memory_bundle()  # ensure storage dir is active for the turn
        message = (self.state.latest_user_message or "").strip()
        if not message:
            self.state.errors.append("Received an empty recruiter message; skipping routing")
            return None

        _synchronise_query_controls(chat_state)

        timestamp = _utc_now()
        chat_state.last_user_message = message
        user_message = ChatMessage(role="user", content_md=message, timestamp=timestamp)
        chat_state.messages.append(user_message)
        self._record_message_in_memory(user_message)

        last_phase = chat_state.last_completed_phase.value if chat_state.last_completed_phase else ""
        previous_plan = [phase.value for phase in chat_state.pending_phases]
        analysis = self.state.analysis_output or chat_state.latest_analysis_output
        candidate_insights = analysis.candidate_insights if analysis else []

        routing_state = AppState(
            job_description=chat_state.job_snapshot,
            candidate_insights=candidate_insights,
            last_completed_phase=chat_state.last_completed_phase,
            pending_phases=list(chat_state.pending_phases),
            query_controls=chat_state.query_controls,
        )
        routing_input = QueryRoutingInput(
            user_query=message,
            state=routing_state,
            conversation_history=_conversation_history(chat_state.messages),
            session_id=chat_state.session_id,
        )

        crew_manager = QueryManagerCrew(
            session_id=chat_state.session_id,
            memory_kwargs=self._memory_kwargs(),
        )
        inputs = {
            "user_query": routing_input.user_query,
            "last_phase": last_phase,
            "previous_plan": _as_json(previous_plan),
            "query_control": routing_state.query_controls.model_dump_json(indent=2),
            "state": _as_json(routing_input.state.model_dump(mode="json")),
            "conversation_history": _as_json(routing_input.conversation_history),
            "session_id": routing_input.session_id,
        }

        result = crew_manager.crew().kickoff(inputs=inputs)
        routing = _task_output_to_model(result, QueryRoutingOutput)
        self.state.routing_decision = routing
        chat_state.latest_routing = routing
        chat_state.query_controls = routing.query_controls
        if routing.top_k_hint:
            try:
                chat_state.top_k = int(routing.top_k_hint)
            except (TypeError, ValueError):
                self._logger.debug("Invalid top_k_hint received: %s", routing.top_k_hint)

        _synchronise_query_controls(chat_state)

        execution_plan = self._calculate_execution_plan(routing)
        self.state.execution_plan = execution_plan
        chat_state.pending_phases = list(execution_plan)
        if not execution_plan and routing.query_controls.phase_sequence:
            self._logger.info(
                "No executable phases derived from requested sequence %s",
                routing.query_controls.phase_sequence,
            )
        return routing

    @listen(run_query_manager)
    def run_job_description(self, routing: Optional[QueryRoutingOutput]) -> Optional[JobDescriptionOutput]:
        """Update the structured job description and recruiter-facing summary when needed."""

        chat_state = self.state.chat_state
        if not self._should_run_phase(routing, ConversationPhase.job_description):
            return None

        current_snapshot = chat_state.job_snapshot
        derived_questions = _derive_missing_job_details(current_snapshot)
        merged_questions = _merge_outstanding_questions(
            list(current_snapshot.outstanding_questions or []),
            derived_questions,
        )
        current_snapshot.outstanding_questions = merged_questions

        payload = JobDescriptionInput(
            user_query=self.state.latest_user_message,
            job_description=current_snapshot,
            requirement_questions_md=chat_state.requirement_questions_md(),
        )

        kickoff_inputs = payload.model_dump(mode="json")
        kickoff_inputs.update(
            {
                "job_description": _as_json(kickoff_inputs.get("job_description", {})),
                "job_description_output": _as_json(
                    chat_state.latest_job_output.model_dump(mode="json")
                    if chat_state.latest_job_output
                    else {}
                ),
                "requirement_questions_md": payload.requirement_questions_md
                or format_outstanding_questions_md(merged_questions),
                "session_id": chat_state.session_id,
            }
        )

        crew_result = JobDescriptionCrew(
            session_id=chat_state.session_id,
            memory_kwargs=self._memory_kwargs(),
        ).crew().kickoff(inputs=kickoff_inputs)

        task_outputs = list(getattr(crew_result, "tasks_output", []) or [])
        specialist_output: Optional[JobDescriptionOutput] = None
        reviewer_output: Optional[JobDescriptionOutput] = None

        if task_outputs:
            try:
                reviewer_output = _task_output_to_model(task_outputs[-1], JobDescriptionOutput)
            except Exception:  # pragma: no cover - defensive casting
                self._logger.debug("Unable to coerce JD reviewer output", exc_info=True)
            if specialist_output is None:
                try:
                    specialist_output = _task_output_to_model(task_outputs[0], JobDescriptionOutput)
                except Exception:  # pragma: no cover - defensive casting
                    self._logger.debug("Unable to coerce JD specialist output", exc_info=True)
        if reviewer_output is None:
            reviewer_output = _task_output_to_model(crew_result, JobDescriptionOutput)

        job_output = reviewer_output.model_copy(deep=True)
        if specialist_output and specialist_output.jd:
            reviewer_snapshot = reviewer_output.jd
            if reviewer_snapshot and reviewer_snapshot != specialist_output.jd:
                self._logger.debug("JD reviewer altered snapshot; restoring specialist output")
            job_output.jd = specialist_output.jd.model_copy(deep=True)
        else:
            job_output.jd = (job_output.jd or JobDescription()).model_copy(deep=True)

        updated_snapshot = job_output.jd or JobDescription()

        remaining_questions = _derive_missing_job_details(updated_snapshot)
        if remaining_questions != list(updated_snapshot.outstanding_questions or []):
            updated_snapshot.outstanding_questions = remaining_questions
        if job_output.message:
            job_output.message.recommended = list(remaining_questions)
            job_output.message_md = job_output.message.render_markdown()

        self.state.job_description_output = job_output
        chat_state.job_snapshot = updated_snapshot
        self._record_job_snapshot(updated_snapshot)
        chat_state.latest_job_output = job_output
        chat_state.last_completed_phase = ConversationPhase.job_description
        _synchronise_query_controls(chat_state)
        self.state.completed_phases.append(ConversationPhase.job_description)

        message_md = job_output.message_md or (
            job_output.message.render_markdown() if job_output.message else ""
        )
        if message_md:
            self._append_assistant_message(message_md, ConversationPhase.job_description)

        return job_output

    @listen(and_(run_query_manager, run_job_description))
    def run_screening(self, _: Optional[Any]) -> Optional[CandidateScreeningOutput]:
        """Execute the screening crew when requested and job details are ready."""

        routing = self.state.routing_decision
        if not self._should_run_phase(routing, ConversationPhase.screening):
            return None

        chat_state = self.state.chat_state

        screening_input = ScreeningInput(
            user_query=self.state.latest_user_message,
            job_snapshot=chat_state.job_snapshot,
            top_k=chat_state.top_k,
            phase=ConversationPhase.screening,
            session_id=chat_state.session_id,
            scoring_weights=chat_state.scoring_weights,
            feature_weights=chat_state.feature_weights,
        )

        kickoff_inputs = screening_input.model_dump(mode="json")
        kickoff_inputs.update(
            {
                "job_snapshot": _as_json(kickoff_inputs.get("job_snapshot", {})),
                "scoring_weights": _as_json(kickoff_inputs.get("scoring_weights", {})),
                "feature_weights": _as_json(kickoff_inputs.get("feature_weights", {})),
                "retrieval_md": "",
                "candidates": "[]",
                "candidate_insights": "[]",
                "session_id": chat_state.session_id,
            }
        )

        result = ScreeningCrew(
            session_id=chat_state.session_id,
            memory_kwargs=self._memory_kwargs(),
        ).crew().kickoff(inputs=kickoff_inputs)

        screening_output = _task_output_to_model(result, CandidateScreeningOutput)
        self.state.screening_output = screening_output
        chat_state.latest_screening_output = screening_output
        self._record_candidate_insights(screening_output.candidate_insights)

        try:
            analysis_output = CandidateAnalysisOutput(
                candidate_insights=screening_output.candidate_insights,
                phase=ConversationPhase.screening,
            )
            self.state.analysis_output = analysis_output
            chat_state.latest_analysis_output = analysis_output
        except Exception:
            self._logger.debug("Unable to capture CandidateAnalysisOutput from screening payload", exc_info=True)

        chat_state.last_completed_phase = ConversationPhase.screening
        _synchronise_query_controls(chat_state)
        self.state.completed_phases.append(ConversationPhase.screening)

        screening_markdown = _compose_screening_markdown(screening_output)
        if screening_markdown:
            self._append_assistant_message(screening_markdown, ConversationPhase.screening)

        knowledge_state = self.state.knowledge_state
        knowledge_state.active_candidate_ids = [
            (candidate.metadata.candidate_id or "").strip()
            for candidate in screening_output.candidate_insights
            if candidate.metadata and candidate.metadata.candidate_id
        ]

        try:
            append_screening_insights(
                session_id=chat_state.session_id,
                job_title=chat_state.job_snapshot.job_title,
                output=screening_output,
            )
        except Exception:  # pragma: no cover - defensive persistence
            self._logger.warning("Failed to persist screening insights", exc_info=True)

        return screening_output

    @listen(and_(run_query_manager, run_screening))
    def run_discussion(self, _: Optional[Any]) -> Optional[DiscussionOutput]:
        """Invoke the discussion crew for follow-up recruiter questions."""

        routing = self.state.routing_decision
        if not self._should_run_phase(routing, ConversationPhase.discussion):
            return None

        chat_state = self.state.chat_state
        analysis_output = self.state.analysis_output or chat_state.latest_analysis_output
        if analysis_output is None:
            self._logger.info("Skipping discussion crew because no screening analysis is available")
            return None

        try:
            analysis_payload: Optional[Any] = analysis_output.model_dump(mode="python")
        except AttributeError:
            analysis_payload = analysis_output

        job_snapshot = chat_state.job_snapshot
        try:
            job_snapshot_payload: Optional[Any] = job_snapshot.model_dump(mode="python") if job_snapshot else None
        except AttributeError:
            job_snapshot_payload = job_snapshot

        discussion_input = DiscussionInput(
            user_query=self.state.latest_user_message,
            screened_candidates=analysis_payload,
            job_snapshot=job_snapshot_payload,
            phase=ConversationPhase.discussion,
        )

        kickoff_inputs = discussion_input.model_dump(mode="json")
        kickoff_inputs.update(
            {
                "screened_candidates": _as_json(kickoff_inputs.get("screened_candidates", {})),
                "job_snapshot": _as_json(kickoff_inputs.get("job_snapshot", {})),
                "session_id": chat_state.session_id,
            }
        )

        result = DiscussionCrew(
            session_id=chat_state.session_id,
            memory_kwargs=self._memory_kwargs(),
        ).crew().kickoff(inputs=kickoff_inputs)
        discussion_output = _task_output_to_model(result, DiscussionOutput)
        self.state.discussion_output = discussion_output
        chat_state.latest_discussion_output = discussion_output
        chat_state.last_completed_phase = ConversationPhase.discussion
        self.state.completed_phases.append(ConversationPhase.discussion)

        message = discussion_output.message_md
        if message:
            composed = "\n\n".join(
                part
                for part in [
                    message.acknowledgement,
                    message.query_answers,
                    message.reasoning,
                    message.follow_ups,
                    message.closing,
                ]
                if part
            )
            if composed:
                self._append_assistant_message(composed, ConversationPhase.discussion)

        return discussion_output

    @listen(or_(run_discussion, run_screening, run_job_description, run_query_manager))
    def finalise_turn(self, _: Optional[Any]) -> List[ChatMessage]:
        """Return the assistant messages produced during the current turn."""

        if self.state.turn_finalised:
            return self.state.turn_responses
        self.state.turn_finalised = True
        self.state.chat_state.pending_phases = list(self.state.completed_phases)
        return self.state.turn_responses

    def attach_memory_bundle(self, bundle: Optional[SessionMemoryBundle]) -> None:
        self._session_memory_bundle = bundle
        if bundle is None:
            return
        try:
            bundle.activate()
        except Exception:  # pragma: no cover - defensive logging
            self._logger.debug("Failed to activate session memory bundle", exc_info=True)

    def _memory_bundle(self) -> Optional[SessionMemoryBundle]:
        bundle = self._session_memory_bundle
        if bundle is None:
            return None
        try:
            bundle.activate()
        except Exception:  # pragma: no cover - defensive logging
            self._logger.debug("Failed to activate session memory bundle", exc_info=True)
        return bundle

    def _memory_kwargs(self) -> Dict[str, Any]:
        bundle = self._memory_bundle()
        if not bundle:
            return {}
        try:
            return dict(bundle.crew_kwargs())
        except Exception:  # pragma: no cover - defensive logging
            self._logger.debug("Failed to derive crew kwargs from memory bundle", exc_info=True)
            return {}

    def _record_message_in_memory(self, message: ChatMessage) -> None:
        bundle = self._session_memory_bundle
        if not bundle or message is None:
            return
        try:
            bundle.record_message(message)
        except Exception:  # pragma: no cover - telemetry only
            self._logger.debug("Unable to record message in session memory", exc_info=True)

    def _record_job_snapshot(self, job_snapshot: JobDescription) -> None:
        bundle = self._session_memory_bundle
        if not bundle or job_snapshot is None:
            return
        try:
            bundle.record_job_snapshot(job_snapshot)
        except Exception:  # pragma: no cover - telemetry only
            self._logger.debug("Unable to record job snapshot in session memory", exc_info=True)

    def _record_candidate_insights(self, insights: Iterable[CandidateInsight]) -> None:
        bundle = self._session_memory_bundle
        if not bundle or not insights:
            return
        try:
            bundle.record_candidates(insights)
        except Exception:  # pragma: no cover - telemetry only
            self._logger.debug("Unable to record candidate insights in session memory", exc_info=True)

    def _calculate_execution_plan(self, routing: Optional[QueryRoutingOutput]) -> List[ConversationPhase]:
        plan: List[ConversationPhase] = []
        if routing is None:
            return plan

        chat_state = self.state.chat_state
        controls = routing.query_controls
        requested_raw = controls.phase_sequence or []
        requested: List[ConversationPhase] = []
        for label in requested_raw:
            try:
                requested.append(ConversationPhase(label))
            except ValueError:
                self._logger.warning("Ignoring unknown phase label '%s' in routing output", label)

        if not requested:
            if controls.update_jd or controls.new_job_search or not chat_state.job_snapshot.job_title:
                requested = [ConversationPhase.job_description]
            elif controls.allow_jd_incomplete or controls.jd_complete or controls.screen_again:
                requested = [ConversationPhase.screening]
            elif controls.candidates_ready:
                requested = [ConversationPhase.discussion]

        sequential_requested = [phase.value for phase in requested] == [
            ConversationPhase.job_description.value,
            ConversationPhase.screening.value,
        ]

        def include_job_description() -> bool:
            should_run = False
            if ConversationPhase.job_description in requested:
                if controls.update_jd or controls.new_job_search or not chat_state.job_snapshot.job_title:
                    should_run = True
            if should_run and ConversationPhase.job_description not in plan:
                plan.append(ConversationPhase.job_description)
            return should_run

        def screening_allowed() -> bool:
            return bool(controls.allow_jd_incomplete or controls.jd_complete or controls.screen_again)

        def include_screening() -> bool:
            if ConversationPhase.screening not in requested:
                return False
            if not screening_allowed():
                self._logger.debug(
                    "Skipping screening because allow_jd_incomplete/jd_complete/screen_again flags are not set"
                )
                return False
            if ConversationPhase.screening not in plan:
                plan.append(ConversationPhase.screening)
            return True

        def include_discussion() -> bool:
            if ConversationPhase.discussion not in requested:
                return False
            if not controls.candidates_ready:
                self._logger.debug("Skipping discussion because candidates_ready flag is false")
                return False
            if ConversationPhase.discussion not in plan:
                plan.append(ConversationPhase.discussion)
            return True

        job_selected = include_job_description()

        if sequential_requested:
            if ConversationPhase.job_description in requested and not job_selected:
                plan.append(ConversationPhase.job_description)
                job_selected = True

            if controls.new_job_search:
                return plan
            if controls.update_jd and not (controls.allow_jd_incomplete or controls.jd_complete):
                return plan

            include_screening()
            return plan

        if not requested:
            return plan

        first = requested[0]
        if first is ConversationPhase.job_description:
            if not job_selected:
                include_job_description()
        elif first is ConversationPhase.screening:
            include_screening()
        elif first is ConversationPhase.discussion:
            include_discussion()

        return plan

    def _should_run_phase(
        self,
        routing: Optional[QueryRoutingOutput],
        phase: ConversationPhase,
    ) -> bool:
        if routing is None:
            return False
        plan = self.state.execution_plan or []
        return phase in plan

    def _append_assistant_message(self, content: str, phase: ConversationPhase) -> None:
        message = ChatMessage(
            role="assistant",
            content_md=content,
            phase=phase,
            timestamp=_utc_now(),
        )
        self.state.chat_state.messages.append(message)
        self.state.turn_responses.append(message)
        self._record_message_in_memory(message)


def build_flow(
    *,
    chat_state: Optional[ChatSessionState] = None,
    knowledge_state: Optional[KnowledgeSessionState] = None,
    memory_bundle: Optional[SessionMemoryBundle] = None,
) -> ResumeAssistantFlow:
    """Initialise a Flow instance wired with the provided session state."""

    flow = ResumeAssistantFlow()
    if chat_state is not None:
        flow.state.chat_state = chat_state
    if knowledge_state is not None:
        flow.state.knowledge_state = knowledge_state
    flow.attach_memory_bundle(memory_bundle)
    return flow


__all__ = ["ResumeAssistantFlow", "build_flow"]
