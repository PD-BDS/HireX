import json
import logging
from typing import Any, Dict, Iterable, Optional

from crewai import Agent, Task, Crew, Process, LLM
from crewai.project import CrewBase, agent, task, crew, before_kickoff
from crewai.tasks.task_output import TaskOutput

from resume_screening_rag_automation.core.constants import (
    SCREENING_CREW_MODEL,
    SCREENING_CREW_TEMPERATURE,
)
from resume_screening_rag_automation.core.py_models import (
    CandidateAnalysisOutput,
    CandidateRetrievalOutput,
    CandidateScreeningOutput,
)
from resume_screening_rag_automation.knowledge import loader as knowledge_loader
from resume_screening_rag_automation.tools.candidate_evidence_tool import CandidateEvidenceTool
from resume_screening_rag_automation.tools.candidate_profile_tool import CandidateProfileTool
from resume_screening_rag_automation.tools.extract_candidates import ExtractCandidatesTool
from resume_screening_rag_automation.tools.search_resumes_tool import SearchResumesTool
from dotenv import load_dotenv

load_dotenv()

LOGGER = logging.getLogger(__name__)

@CrewBase
class ScreeningCrew:
    """Crew for screening and matching candidates."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    folder_name = "screening_crew"
    llm = LLM(model=SCREENING_CREW_MODEL, temperature=SCREENING_CREW_TEMPERATURE)

    def __init__(
        self,
        *args,
        session_id: Optional[str] = None,
        memory_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):

        self._session_id = session_id
        self._memory_kwargs = dict(memory_kwargs or {})
        self._memory_enabled = bool(self._memory_kwargs)
        self._interpolation_inputs: Dict[str, Any] = {}
        try:
            self.knowledge = knowledge_loader.for_screening(session_id=session_id)
        except Exception as exc:  # pragma: no cover - allow local testing without vector DB
            LOGGER.warning("Falling back to no knowledge for Screening crew: %s", exc)
            self.knowledge = None
        self._retrieval_tool = ExtractCandidatesTool()
        self._candidate_profile_tool = CandidateProfileTool()
        self._candidate_evidence_tool = CandidateEvidenceTool()
        self._search_resumes_tool = SearchResumesTool()


    @agent
    def retriever(self) -> Agent:
        """Agent responsible for retrieving and scoring top candidates."""
        return Agent(
            config=self.agents_config["retriever"],
            llm=self.llm,
            tools=[self._retrieval_tool],
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            max_iter=3,
        )

    @agent
    def analyser(self) -> Agent:
        """Agent that inspects shortlisted candidates and assembles structured insights."""
        return Agent(
            config=self.agents_config["analyser"],
            llm=self.llm,
            tools=[self._candidate_profile_tool, self._candidate_evidence_tool, self._search_resumes_tool],
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            max_iter=4,
        )

    @agent
    def presenter(self) -> Agent:
        """Agent that synthesises the final shortlist for recruiters."""
        return Agent(
            config=self.agents_config["presenter"],
            llm=self.llm,
            tools=[],
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            max_iter=3,
        )


    @task
    def retrieve_candidates(self) -> Task:
        """Task to retrieve and score the top candidates."""
        return Task(
            config=self.tasks_config["retrieve_candidates"],
            output_json=CandidateRetrievalOutput,
            validate_output=True,
            callback=self._propagate_retrieval_results,
        )

    @task
    def analyse_candidates(self) -> Task:
        """Task to enrich shortlisted candidates with structured insights."""
        return Task(
            config=self.tasks_config["analyse_candidates"],
            output_json=CandidateAnalysisOutput,
            validate_output=True,
            callback=self._propagate_analysis_results,
        )

    @task
    def present_screening_results(self) -> Task:
        """Task to deliver the final recruiter-facing shortlist."""
        return Task(
            config=self.tasks_config["present_screening_results"],
            output_pydantic=CandidateScreeningOutput,
            validate_output=True,
        )

    @crew
    def crew(self) -> Crew:
        """Create the Screening crew with sequential tasks."""
        agents = self.agents
        tasks = self.tasks
        if len(tasks) >= 2:
            tasks[1].context = [tasks[0]]
        if len(tasks) >= 3:
            tasks[2].context = [tasks[0], tasks[1]]

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            planning=True,
            verbose=True,
            memory=self._memory_enabled,
            knowledge=self.knowledge,
            cache=True,  # Enable caching for performance optimization
            **self._memory_kwargs,
        )

    @before_kickoff
    def _capture_initial_inputs(self, inputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Persist the latest interpolation inputs so callbacks can refresh task prompts."""
        base: Dict[str, Any] = dict(inputs or {})
        self._interpolation_inputs = base
        return base

    def _propagate_retrieval_results(self, output: TaskOutput) -> None:
        payload = self._extract_payload(output)
        if not payload:
            payload = {}

        candidates = payload.get("candidates") or []
        if not candidates:
            fallback = self._fallback_extract_candidates()
            if fallback:
                payload.update({
                    "candidates": fallback.get("candidates", []),
                    "scoring_weights": fallback.get("scoring_weights"),
                    "feature_weights": fallback.get("feature_weights"),
                })
                self._sync_retrieval_output(output, payload)

        updates: Dict[str, Any] = {}
        retrieval_md = payload.get("retrieval_md")
        if retrieval_md is not None:
            updates["retrieval_md"] = retrieval_md

        candidates = payload.get("candidates")
        if candidates is not None:
            updates["candidates"] = candidates

        scoring_weights = payload.get("scoring_weights")
        if scoring_weights is not None:
            updates["scoring_weights"] = scoring_weights

        feature_weights = payload.get("feature_weights")
        if feature_weights is not None:
            updates["feature_weights"] = feature_weights

        if updates:
            self._update_task_inputs(["analyse_candidates", "present_screening_results"], updates)

    def _propagate_analysis_results(self, output: TaskOutput) -> None:
        payload = self._extract_payload(output)
        if not payload:
            return

        insights = payload.get("candidate_insights")
        if insights is None:
            return

        self._update_task_inputs(["present_screening_results"], {"candidate_insights": insights})

    def _extract_payload(self, output: TaskOutput) -> Dict[str, Any]:
        if output is None:
            return {}
        if output.pydantic is not None:
            return output.pydantic.model_dump()
        if output.json_dict is not None:
            return output.json_dict
        raw = output.raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {}

    def _update_task_inputs(self, task_names: Iterable[str], updates: Dict[str, Any]) -> None:
        if not updates:
            return
        if not self._interpolation_inputs:
            self._interpolation_inputs = {}

        for key, value in updates.items():
            self._interpolation_inputs[key] = self._stringify(value)

        for task in self.tasks:
            if task.name in task_names:
                try:
                    task.interpolate_inputs_and_add_conversation_history(self._interpolation_inputs)
                except ValueError as exc:
                    LOGGER.debug("Interpolation refresh failed for task %s: %s", task.name, exc)

    @staticmethod
    def _stringify(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2, ensure_ascii=False)
        return value

    def _fallback_extract_candidates(self) -> Optional[Dict[str, Any]]:
        snapshot_raw = self._interpolation_inputs.get("job_snapshot")
        job_snapshot = self._coerce_json(snapshot_raw)
        if not isinstance(job_snapshot, dict):
            return None

        top_k_raw = self._interpolation_inputs.get("top_k", 5)
        try:
            top_k = int(self._coerce_json(top_k_raw) or top_k_raw)
        except (TypeError, ValueError):
            top_k = 5

        scoring_weights_raw = self._interpolation_inputs.get("scoring_weights")
        scoring_weights = self._coerce_json(scoring_weights_raw) or None

        feature_weights_raw = self._interpolation_inputs.get("feature_weights")
        feature_weights = self._coerce_json(feature_weights_raw) or None

        try:
            LOGGER.info("Fallback ExtractCandidatesTool run triggered due to empty shortlist")
            result = self._retrieval_tool.run(
                job_description=job_snapshot,
                top_k=top_k,
                scoring_weights=scoring_weights,
                feature_weights=feature_weights,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback only
            LOGGER.warning("Fallback ExtractCandidatesTool run failed: %s", exc)
            return None

        candidates = result.get("candidates") or []
        if not candidates:
            return None

        return {
            "candidates": candidates,
            "scoring_weights": result.get("scoring_weights"),
            "feature_weights": result.get("feature_weights"),
        }

    def _coerce_json(self, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def _sync_retrieval_output(self, output: TaskOutput, payload: Dict[str, Any]) -> None:
        try:
            refreshed = CandidateRetrievalOutput.model_validate(payload)
        except Exception:  # pragma: no cover - fallback only
            LOGGER.debug("Failed to sync retrieval output payload", exc_info=True)
            return

        output.pydantic = refreshed
        output.json_dict = refreshed.model_dump()
        try:
            output.raw = refreshed.model_dump_json()
        except Exception:  # pragma: no cover - raw serialisation optional
            output.raw = None
