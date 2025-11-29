from __future__ import annotations

from typing import Any, Dict, List

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, before_kickoff, crew, task
from resume_screening_rag_automation.tools.utf8_file_read_tool import UTF8FileReadTool

from resume_screening_rag_automation.core.constants import (
    RESUME_PARSING_CREW_MODEL,
    RESUME_PARSING_CREW_TEMPERATURE,
)
from resume_screening_rag_automation.core.ingestion_models import (
    ResumeParsingInput,
    ResumeParsingOutput,
)
from resume_screening_rag_automation.core.py_models import (
    ResumeFileInfo,
)


@CrewBase
class ResumeParsingCrew:
    """Crew responsible for converting raw resume text into structured records."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    llm = LLM(model=RESUME_PARSING_CREW_MODEL, temperature=RESUME_PARSING_CREW_TEMPERATURE)
    file_reader = UTF8FileReadTool()

    @before_kickoff
    def prepare_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = ResumeParsingInput.model_validate(inputs)
        except Exception:
            payload = ResumeParsingInput()

        resume_batch: List[Dict[str, Any]] = []
        for file_info in payload.files:
            if not isinstance(file_info, ResumeFileInfo):
                try:
                    file_info = ResumeFileInfo.model_validate(file_info)  # type: ignore[arg-type]
                except Exception:
                    continue

            entry: Dict[str, Any] = {
                "file_name": file_info.file_name,
                "file_path": file_info.path,
                "content_hash": file_info.content_hash,
                "size_bytes": file_info.size_bytes,
                "modified_at": file_info.modified_at,
            }

            if payload.resume_texts:
                preview = payload.resume_texts.get(file_info.file_name)
                if preview:
                    entry["inline_preview"] = preview[:2000]

            resume_batch.append(entry)

        return {
            "resume_batch": resume_batch,
            "existing_records": payload.existing_records,
        }

    @agent
    def resume_parsing_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["resume_parsing_analyst"],
            llm=self.llm,
            tools=[self.file_reader],
            memory=False,
            verbose=True,
        )

    @task
    def structure_resumes(self) -> Task:
        return Task(
            config=self.tasks_config["structure_resumes"],
            output_pydantic=ResumeParsingOutput,
            validate_output=True,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
        )
