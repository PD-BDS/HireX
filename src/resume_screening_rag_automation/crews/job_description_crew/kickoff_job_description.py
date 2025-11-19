"""Utility script to exercise the JobDescription crew in isolation."""

from __future__ import annotations

import json
from typing import Any

from resume_screening_rag_automation.core.py_models import (
    JobDescription,
    JobDescriptionInput,
    JobType,
    format_outstanding_questions_md,
)
from resume_screening_rag_automation.crews.job_description_crew.job_description_crew import (
    JobDescriptionCrew,
)


def _print_result(result: Any) -> None:
    payload = getattr(result, "pydantic", None)
    if payload is not None:
        print(payload.model_dump_json(indent=2))
        return

    json_dict = getattr(result, "json_dict", None)
    if json_dict is not None:
        print(json.dumps(json_dict, indent=2, ensure_ascii=False))
        return

    raw = getattr(result, "raw", None)
    if raw:
        print(raw)
        return

    print(result)


def main() -> None:
    session_id = "kickoff-demo"
    crew = JobDescriptionCrew(session_id=session_id).crew()

    job_snapshot = JobDescription(
        job_title="Senior Electrical and Automation Engineer",
        location="Denmark (Copenhagen / Aalborg / Aarhus)",
        experience_level_years=10,
        job_type=JobType.full_time,
        outstanding_questions=[
            "Any certifications required or preferred?",
            "Any additional preferences or nice-to-haves?",
        ],
    )

    inputs = JobDescriptionInput(
        user_query=(
            "Here are the confirmed requirements for the Senior Electrical and Automation Engineer role in Denmark. "
            "Please update the structured job description accordingly.\n\n"
            "Role: Senior Electrical and Automation Engineer\n"
            "Job type: Full Time\n"
            "Location: Denmark (Copenhagen / Aalborg / Aarhus)\n"
            "Experience: 10 years\n"
            "Skills: Siemens PCS 7, TIA Portal, CEMAT S7, SCADA environments, PLC programming, "
            "HMI software development, EPLAN, AutoCAD, process instrumentation, project management\n"
            "Education: Master’s Degree in Electrical Engineering or Industrial Automation\n"
            "Languages: Fluent in English, Working knowledge of Polish, Working knowledge of Russian\n"
            "Responsibilities: Lead the design and configuration of PCS systems, develop PLC/HMI "
            "software, design electrical control cabinets, manage instrumentation integration, oversee "
            "project lifecycle through commissioning, mentor the automation team, optimise plant "
            "uptime, coordinate with cross-functional engineers, run risk assessments and FAT/SAT testing, "
            "support supplier quality checks, and maintain engineering documentation."
        ),
        job_description=job_snapshot,
        requirement_questions_md=format_outstanding_questions_md(
            job_snapshot.outstanding_questions
        ),
    )

    result = crew.kickoff(
        inputs={
            "user_query": inputs.user_query,
            "job_description": json.dumps(
                inputs.job_description.model_dump(exclude_none=True, exclude_unset=True)
                if inputs.job_description
                else {},
                indent=2,
                ensure_ascii=False,
            ),
            "job_description_output": json.dumps(
                {
                    "jd": {
                        "job_title": job_snapshot.job_title,
                        "location": job_snapshot.location,
                        "experience_level_years": job_snapshot.experience_level_years,
                        "job_type": JobType.full_time.value,
                        "outstanding_questions": job_snapshot.outstanding_questions,
                    }
                },
                indent=2,
                ensure_ascii=False,
            ),
            "requirement_questions_md": inputs.requirement_questions_md or "",
            "session_id": session_id,
        }
    )

    _print_result(result)


if __name__ == "__main__":
    main()
