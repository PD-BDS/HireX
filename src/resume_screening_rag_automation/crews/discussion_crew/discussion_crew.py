import logging
from typing import Any, Dict, Optional

from crewai import Agent, Task, Crew, Process, LLM
from crewai.project import CrewBase, agent, task, crew

from resume_screening_rag_automation.core.constants import (
    DISCUSSION_CREW_MODEL,
    DISCUSSION_CREW_TEMPERATURE,
)
from resume_screening_rag_automation.core.py_models import (
    DiscussionAnalysisOutput,
    DiscussionOutput,
)
from resume_screening_rag_automation.knowledge import loader as knowledge_loader
from resume_screening_rag_automation.tools.candidate_profile_tool import CandidateProfileTool
from resume_screening_rag_automation.tools.candidate_evidence_tool import CandidateEvidenceTool
from resume_screening_rag_automation.tools.search_resumes_tool import SearchResumesTool

LOGGER = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()

@CrewBase
class DiscussionCrew:
    """Crew for handling follow-up conversations about candidates."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    folder_name = "discussion_crew"
    llm = LLM(model=DISCUSSION_CREW_MODEL, temperature=DISCUSSION_CREW_TEMPERATURE)

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
        try:
            self.knowledge = knowledge_loader.for_discussion(session_id=session_id)
        except Exception as exc:  # pragma: no cover - allow local testing without vector DB
            LOGGER.warning("Falling back to no knowledge for Discussion crew: %s", exc)
            self.knowledge = None

        self._candidate_profile_tool = CandidateProfileTool()
        self._candidate_evidence_tool = CandidateEvidenceTool()
        self._search_resumes_tool = SearchResumesTool()

    @agent
    def discussion_analyser(self) -> Agent:
        """Agent responsible for compiling context before responding."""
        return Agent(
            config=self.agents_config["discussion_analyser"],
            llm=self.llm,
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            tools=[
                self._candidate_profile_tool,
                self._candidate_evidence_tool,
                self._search_resumes_tool,
            ],
        )

    @agent
    def structured_responder(self) -> Agent:
        """Agent that crafts the final recruiter-facing reply."""
        return Agent(
            config=self.agents_config["structured_responder"],
            llm=self.llm,
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            tools=[
                self._candidate_profile_tool,
                self._candidate_evidence_tool,
                self._search_resumes_tool,
            ],
        )

    @task
    def analyse_user_query(self) -> Task:
        """Task that prepares a structured briefing for the responder."""
        return Task(
            config=self.tasks_config["analyse_user_query"],
            output_pydantic=DiscussionAnalysisOutput,
            validate_output=True,
        )

    @task
    def compose_structured_response(self) -> Task:
        """Task that delivers the recruiter-ready discussion reply."""
        return Task(
            config=self.tasks_config["compose_structured_response"],
            output_pydantic=DiscussionOutput,
            validate_output=True,
        )

    @crew
    def crew(self) -> Crew:
        """Create the Discussion crew with planning and shared knowledge."""
        agents = self.agents
        tasks = self.tasks
        if len(tasks) >= 2:
            tasks[1].context = [tasks[0]]

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            planning=True,
            verbose=True,
            memory=self._memory_enabled,
            knowledge=self.knowledge,
            **self._memory_kwargs,
        )
