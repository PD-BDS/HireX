"""Utility script to exercise the Discussion crew in isolation."""

from __future__ import annotations

import json
from typing import Any

from resume_screening_rag_automation.core.py_models import DiscussionInput
from resume_screening_rag_automation.crews.discussion_crew.discussion_crew import (
    DiscussionCrew,
)
from resume_screening_rag_automation.models import CandidateAnalysisOutput, JobDescription
from resume_screening_rag_automation.state import ChatSessionState


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
    crew = DiscussionCrew(session_id=session_id).crew()

    chat_state = ChatSessionState(session_id=session_id)
    inputs = DiscussionInput(
        user_query=(
            "Compare Janek Blankensteiner and Ronnie Elmholdt Kragh for Siemens automation leadership "
            "and safety-compliant commissioning experience."
        ),
    )

    screening_snapshot = {
        "message_md": (
            "Top candidates identified for the Senior Electrical and Automation Engineer role in Denmark.\n\n"
            "### Candidate Shortlist\n"
            "- **Janek Blankensteiner** — Managing Director leading global automation programmes (fit score 0.82)\n"
            "- **Ronnie Elmholdt Kragh** — Hazardous Energies Specialist @ Siemens Gamesa (fit score 0.78)\n"
            "- **Abhiram R.** — Electrical & Control Installation Engineer for cement plants (fit score 0.74)"
        ),
        "database_summary_md": (
            "Most retrieved candidates come from adjacent automation leadership roles. Siemens PCS 7 experience appears"
            " primarily in recent project work rather than long tenure."
        ),
        "candidate_insights": [
            {
                "metadata": {
                    "candidate_id": "CAND009",
                    "candidate_name": "Janek Blankensteiner",
                    "file_name": "JanekResume.txt",
                    "current_title": "Managing Director",
                },
                "scores": {
                    "job_fit_score": 0.82,
                    "semantic_score": 0.61,
                    "weighted_feature_score": 0.74,
                    "feature_scores": {"skills": 0.78, "experience": 0.81, "education": 0.7, "title": 0.9, "other": 0.6},
                    "similarity": 0.61,
                },
                "summary_md": "Global automation programme leader overseeing multi-plant rollouts across Europe.",
                "fit_reasoning": [
                    "Led high-value automation projects with Siemens partners",
                    "Executive stakeholder management aligns with project leadership requirement",
                ],
                "matched_features": {
                    "matching_skills": ["Siemens PCS 7", "Project leadership"],
                    "matching_experience": ["Global automation rollouts"],
                },
                "knowledge_references": {},
            },
            {
                "metadata": {
                    "candidate_id": "CAND013",
                    "candidate_name": "Ronnie Elmholdt Kragh",
                    "file_name": "RonnieElmholdtKraghResume (1).txt",
                    "current_title": "Hazardous Energies Specialist",
                },
                "scores": {
                    "job_fit_score": 0.78,
                    "semantic_score": 0.57,
                    "weighted_feature_score": 0.69,
                    "feature_scores": {"skills": 0.72, "experience": 0.77, "education": 0.65, "title": 0.68, "other": 0.6},
                    "similarity": 0.57,
                },
                "summary_md": "Safety-focused engineer maintaining hazardous energy systems for Siemens Gamesa.",
                "fit_reasoning": [
                    "Hands-on Siemens Gamesa commissioning experience",
                    "Focus on compliance and uptime maps to job responsibilities",
                ],
                "matched_features": {
                    "matching_skills": ["Commissioning", "Compliance"],
                    "matching_experience": ["Siemens Gamesa turbine maintenance"],
                },
                "knowledge_references": {},
            },
            {
                "metadata": {
                    "candidate_id": "CAND001",
                    "candidate_name": "Abhiram R.",
                    "file_name": "AbhiramResume.txt",
                    "current_title": "Electrical & Control Installation Engineer",
                },
                "scores": {
                    "job_fit_score": 0.74,
                    "semantic_score": 0.55,
                    "weighted_feature_score": 0.66,
                    "feature_scores": {"skills": 0.7, "experience": 0.72, "education": 0.6, "title": 0.65, "other": 0.55},
                    "similarity": 0.55,
                },
                "summary_md": "Electrical & control engineer delivering cement plant automation upgrades.",
                "fit_reasoning": [
                    "Recent Siemens PCS 7 project implementations",
                    "Commissioning experience across cement manufacturing lines",
                ],
                "matched_features": {
                    "matching_skills": ["Siemens PCS 7", "Commissioning"],
                    "matching_experience": ["Cement plant automation"],
                },
                "knowledge_references": {},
            },
        ],
    }

    job_snapshot = {
        "job_title": "Senior Electrical and Automation Engineer",
        "location": "Denmark (Copenhagen / Aalborg / Aarhus)",
        "required_skills": [
            "Siemens PCS 7",
            "TIA Portal",
            "CEMAT S7",
            "SCADA environments",
            "PLC programming",
            "HMI software development",
        ],
        "experience_level_years": 10,
    }

    chat_state.job_snapshot = JobDescription.model_validate(job_snapshot)
    analysis_output = CandidateAnalysisOutput.model_validate(
        {
            "candidate_insights": screening_snapshot["candidate_insights"],
            "phase": "screening",
        }
    )
    chat_state.latest_analysis_output = analysis_output

    payload = DiscussionInput(
        user_query=inputs.user_query,
        screened_candidates=analysis_output,
        job_snapshot=chat_state.job_snapshot,
    )
    kickoff_inputs = payload.model_dump(mode="json")
    kickoff_inputs.update(
        {
            "screened_candidates": json.dumps(kickoff_inputs.get("screened_candidates", {}), indent=2, ensure_ascii=False),
            "job_snapshot": json.dumps(kickoff_inputs.get("job_snapshot", {}), indent=2, ensure_ascii=False),
            "session_id": session_id,
        }
    )

    result = crew.kickoff(inputs=kickoff_inputs)

    _print_result(result)


if __name__ == "__main__":
    main()
