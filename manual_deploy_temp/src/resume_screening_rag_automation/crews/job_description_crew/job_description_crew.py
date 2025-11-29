import json
import logging
from typing import Any, Dict, Optional

from crewai import Agent, Task, Crew, Process, LLM
from crewai.project import CrewBase, agent, task, crew
from crewai.tasks.task_output import TaskOutput

from resume_screening_rag_automation.core.constants import (
    JOB_DESCRIPTION_CREW_MODEL,
    JOB_DESCRIPTION_CREW_TEMPERATURE,
)
from resume_screening_rag_automation.core.py_models import JobDescriptionOutput
from resume_screening_rag_automation.knowledge import loader as knowledge_loader
from dotenv import load_dotenv
load_dotenv()
LOGGER = logging.getLogger(__name__)

@CrewBase
class JobDescriptionCrew:
    """Crew for gathering job descriptions and composing recruiter-facing replies."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    folder_name = "job_description_crew"
    llm = LLM(model=JOB_DESCRIPTION_CREW_MODEL, temperature=JOB_DESCRIPTION_CREW_TEMPERATURE)

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
            self.knowledge = knowledge_loader.for_job_description(session_id=session_id)
        except Exception as exc:  # pragma: no cover - local smoke testing without vector DB
            LOGGER.warning("Falling back to no knowledge for JobDescription crew: %s", exc)
            self.knowledge = None

    @agent
    def requirements_elicitor(self) -> Agent:
        """Agent responsible for gathering the job description."""
        return Agent(
            config=self.agents_config["requirements_elicitor"],
            llm=self.llm,
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            max_iter=2,
        )

    @agent
    def jd_reviewer(self) -> Agent:
        """Agent responsible for composing recruiter-facing chat responses."""
        return Agent(
            config=self.agents_config["jd_reviewer"],
            llm=self.llm,
            memory=self._memory_enabled,
            verbose=True,
            allow_delegation=False,
            max_iter=2,
        )

    @task
    def gather_job_description(self) -> Task:
        """Task to gather and validate the job description"""
        return Task(
            config=self.tasks_config["gather_job_description"],
            output_pydantic=JobDescriptionOutput,
            validate_output=True,
        )

    @task
    def compose_job_description_response(self) -> Task:
        """Task to craft the recruiter-facing chat response."""
        return Task(
            config=self.tasks_config["compose_job_description_response"],
            output_pydantic=JobDescriptionOutput,
            validate_output=True,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the JobDescription crew for structured data capture and response crafting."""
        agents = self.agents
        tasks = self.tasks
        if len(tasks) >= 2:
            tasks[1].context = [tasks[0]]
        for task in tasks:
            if task.agent is not None:
                task.agent.allow_delegation = False

        specialist_role = self.agents_config["requirements_elicitor"].get("role", "")
        reviewer_role = self.agents_config["jd_reviewer"].get("role", "")

        crew_instance = Crew(
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

        def _task_callback(task_output: TaskOutput) -> None:
            if getattr(task_output, "agent", "") != specialist_role:
                return
            specialist_output = task_output.pydantic
            if not isinstance(specialist_output, JobDescriptionOutput):
                return
            inputs = getattr(crew_instance, "_inputs", {}) or {}
            inputs["job_description_output"] = json.dumps(
                specialist_output.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            for task in tasks:
                agent_role = getattr(task.agent, "role", "")
                if agent_role == reviewer_role:
                    task.interpolate_inputs_and_add_conversation_history(inputs)
                    break

        crew_instance.task_callback = _task_callback
        return crew_instance
