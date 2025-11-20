import logging
from typing import Any, Dict, Optional

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task

from resume_screening_rag_automation.core.constants import (
    QUERY_MANAGER_CREW_MODEL,
    QUERY_MANAGER_CREW_TEMPERATURE,
)
from resume_screening_rag_automation.core.py_models import QueryRoutingOutput
from resume_screening_rag_automation.knowledge import loader as knowledge_loader
from resume_screening_rag_automation.tools.scenario_hint_tool import ScenarioHintTool

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()

@CrewBase
class QueryManagerCrew:
    """Crew that analyses user intent and selects the next conversation phases."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    folder_name = "query_manager_crew"
    llm = LLM(model=QUERY_MANAGER_CREW_MODEL, temperature=QUERY_MANAGER_CREW_TEMPERATURE)

    def __init__(
        self,
        *args: Any,
        session_id: Optional[str] = None,
        memory_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:

        self._session_id = session_id
        self._memory_kwargs = dict(memory_kwargs or {})
        self._memory_enabled = bool(self._memory_kwargs)
        try:
            self.knowledge = knowledge_loader.for_query_manager(session_id=session_id)
        except Exception as exc:  # pragma: no cover - knowledge optional during local smoke tests
            logger.warning("Falling back to no knowledge for QueryManager crew: %s", exc)
            self.knowledge = None
        self._scenario_hint_tool = ScenarioHintTool()

    @agent
    def query_routing_manager(self) -> Agent:
        """Agent that analyses recruiter intent and sequences the next phases."""
        return Agent(
            config=self.agents_config["query_routing_manager"],
            llm=self.llm,
            tools=[self._scenario_hint_tool],
            memory=self._memory_enabled,
            allow_delegation=False,
            max_iter=3,
        )

    @task
    def route_query(self) -> Task:
        """Task that inspects the flow state and queues the next phases."""
        return Task(
            config=self.tasks_config["route_query"],
            output_pydantic=QueryRoutingOutput,
            validate_output=True,
        )

    @crew
    def crew(self) -> Crew:
        """Create the QueryManager crew instance."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            planning=True,
            verbose=True,
            memory=self._memory_enabled,
            knowledge=self.knowledge,
            **self._memory_kwargs,
        )
