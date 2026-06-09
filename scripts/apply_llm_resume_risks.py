#!/usr/bin/env python
"""Apply LLM-generated resume risks to candidate_profile.json.

The LLM produces a strict JSON risk assessment after reading source_resume.md
and candidate_profile.json. This script validates the result, writes the
canonical risks back into candidate_profile.json, refreshes resume_risks.md,
and regenerates resume rewrite suggestions by default.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from suggest_resume_rewrites import generate_resume_rewrite_suggestions


VALID_SEVERITIES = {"high", "medium", "low"}
REQUIRED_FIELDS = [
    "project",
    "severity",
    "area",
    "evidence",
    "why_it_matters",
    "suggested_fix",
    "likely_followup",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def one_line(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_").lower()
    return slug[:40] or "risk"


def extract_risk_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        risks = payload
    elif isinstance(payload, dict):
        risks = payload.get("resume_risks", payload.get("risks", []))
    else:
        raise ValueError("Risk payload must be a JSON object or array.")

    if not isinstance(risks, list):
        raise ValueError("Risk payload must contain a resume_risks array.")
    if not all(isinstance(item, dict) for item in risks):
        raise ValueError("Every risk item must be a JSON object.")
    return risks


def normalize_risks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        project = one_line(item.get("project") or item.get("project_name") or "整体简历")
        severity = one_line(item.get("severity")).lower()
        if severity not in VALID_SEVERITIES:
            severity = "medium"

        risk = {
            "id": one_line(item.get("id")) or f"{slugify(project)}_{index}",
            "project": project,
            "severity": severity,
            "area": one_line(item.get("area")),
            "evidence": one_line(item.get("evidence")),
            "why_it_matters": one_line(item.get("why_it_matters")),
            "suggested_fix": one_line(item.get("suggested_fix")),
            "likely_followup": one_line(item.get("likely_followup")),
        }

        missing = [field for field in REQUIRED_FIELDS if not risk.get(field)]
        if missing:
            raise ValueError(f"Risk #{index} is missing required fields: {', '.join(missing)}")

        for optional_field in ("confidence", "source_quote", "source_path", "jd_relevance"):
            if optional_field in item and one_line(item.get(optional_field)):
                risk[optional_field] = one_line(item.get(optional_field))

        normalized.append(risk)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(normalized, key=lambda risk: (severity_order.get(risk["severity"], 9), risk["project"], risk["area"]))


def risk_for_project(risk: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in risk.items() if key not in {"id", "project"}}


def update_project_risks(profile: dict[str, Any], risks: list[dict[str, Any]]) -> None:
    projects = profile.get("candidate_profile", {}).get("projects", []) or []
    project_lookup = {one_line(project.get("name")): project for project in projects if isinstance(project, dict)}

    for project in project_lookup.values():
        project["possible_risks"] = []

    for risk in risks:
        project = project_lookup.get(one_line(risk.get("project")))
        if project is not None:
            project.setdefault("possible_risks", []).append(risk_for_project(risk))


def render_risks_md(profile: dict[str, Any]) -> str:
    risks = profile.get("resume_risks", []) or []
    lines = [
        "# 简历风险点",
        "",
        "> 来源：大模型读取解析后的简历产物后生成；用于面试追问和简历补强，不等同于事实裁定。",
        "",
    ]
    if not risks:
        lines.append("未识别到明显风险点。")
        return "\n".join(lines) + "\n"

    for index, risk in enumerate(risks, start=1):
        lines.extend(
            [
                f"## {index}. [{risk['severity']}] {risk['area']}",
                f"- 项目：{risk['project']}",
                f"- 证据：{risk['evidence']}",
                f"- 为什么会被追问：{risk['why_it_matters']}",
                f"- 建议补充：{risk['suggested_fix']}",
                f"- 可能追问：{risk['likely_followup']}",
            ]
        )
        if risk.get("confidence"):
            lines.append(f"- 置信度：{risk['confidence']}")
        if risk.get("source_quote"):
            lines.append(f"- 来源摘录：{risk['source_quote']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def apply_llm_risks(
    profile_json: Path,
    risks_json: Path,
    output_json: Path | None = None,
    risk_report: Path | None = None,
    skip_rewrites: bool = False,
) -> dict[str, str]:
    profile = read_json(profile_json)
    payload = read_json(risks_json)
    risks = normalize_risks(extract_risk_items(payload))

    profile["resume_risks"] = risks
    profile["risk_evaluation"] = {
        "method": "llm",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source_risks_json": str(risks_json),
        "prompt_reference": "references/resume-risk-llm-evaluation.md",
    }
    update_project_risks(profile, risks)

    profile_json = profile_json.resolve()
    output_json = (output_json or profile_json.parent / "resume_risks.llm.json").resolve()
    risk_report = (risk_report or profile_json.parent / "resume_risks.md").resolve()

    write_json(profile_json, profile)
    write_json(
        output_json,
        {
            "schema_version": "1.0",
            "kind": "llm_resume_risk_evaluation",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_profile": str(profile_json),
            "resume_risks": risks,
        },
    )
    risk_report.write_text(render_risks_md(profile), encoding="utf-8")

    outputs = {
        "profile_json": str(profile_json),
        "risk_json": str(output_json),
        "risk_report": str(risk_report),
    }
    if not skip_rewrites:
        _, rewrite_outputs = generate_resume_rewrite_suggestions(profile_json, output_dir=profile_json.parent)
        outputs.update(
            {
                "rewrite_json": rewrite_outputs["rewrite_json"],
                "rewrite_markdown": rewrite_outputs["rewrite_markdown"],
            }
        )
    return outputs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply LLM-generated resume risks to candidate_profile.json.")
    parser.add_argument("candidate_profile_json", help="Path to candidate_profile.json.")
    parser.add_argument("risks_json", help="Path to LLM-generated risk JSON.")
    parser.add_argument("--output-json", help="Canonical risk JSON path. Default: <parsed_dir>/resume_risks.llm.json.")
    parser.add_argument("--risk-report", help="Markdown report path. Default: <parsed_dir>/resume_risks.md.")
    parser.add_argument("--skip-rewrites", action="store_true", help="Do not regenerate resume rewrite suggestions.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    outputs = apply_llm_risks(
        Path(args.candidate_profile_json),
        Path(args.risks_json),
        output_json=Path(args.output_json) if args.output_json else None,
        risk_report=Path(args.risk_report) if args.risk_report else None,
        skip_rewrites=args.skip_rewrites,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
