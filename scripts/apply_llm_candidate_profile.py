#!/usr/bin/env python
"""Apply an LLM-generated candidate profile to the parsed resume directory.

The raw LLM JSON is an input, not a default long-lived artifact. Prefer a
temporary UTF-8 JSON file with --delete-input on Windows; use "-" only when the
stdin pipe is known to preserve UTF-8 text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_profile_payload(source: str) -> dict[str, Any]:
    if source == "-":
        payload = json.loads(sys.stdin.read())
    else:
        payload = read_json(Path(source).resolve())
    if not isinstance(payload, dict):
        raise ValueError("LLM profile JSON must be an object.")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def one_line(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_string_list(value: Any) -> list[str]:
    return [one_line(item) for item in as_list(value) if one_line(item)]


def normalize_contact(value: Any) -> dict[str, list[str]]:
    contact = value if isinstance(value, dict) else {}
    return {
        "emails": normalize_string_list(contact.get("emails")),
        "phones": normalize_string_list(contact.get("phones")),
        "urls": normalize_string_list(contact.get("urls")),
    }


def normalize_project(project: dict[str, Any]) -> dict[str, Any]:
    risks = []
    for risk in as_list(project.get("possible_risks")):
        if isinstance(risk, dict):
            risks.append(normalize_risk(risk, default_project=one_line(project.get("name"))))
    return {
        "name": one_line(project.get("name")) or "未命名项目",
        "period": one_line(project.get("period")),
        "background": one_line(project.get("background")),
        "role": one_line(project.get("role")),
        "tech_stack": normalize_string_list(project.get("tech_stack")),
        "metrics": normalize_string_list(project.get("metrics")),
        "claims": normalize_string_list(project.get("claims")),
        "results": one_line(project.get("results")),
        "possible_risks": risks,
    }


def normalize_risk(risk: dict[str, Any], default_project: str = "整体简历") -> dict[str, Any]:
    severity = one_line(risk.get("severity")).lower()
    if severity not in {"high", "medium", "low"}:
        severity = "medium"
    return {
        "project": one_line(risk.get("project")) or default_project or "整体简历",
        "severity": severity,
        "area": one_line(risk.get("area")),
        "evidence": one_line(risk.get("evidence")),
        "why_it_matters": one_line(risk.get("why_it_matters")),
        "suggested_fix": one_line(risk.get("suggested_fix")),
        "likely_followup": one_line(risk.get("likely_followup")),
    }


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_").lower()
    return slug[:40] or "risk"


def normalize_profile_payload(payload: dict[str, Any], source_resume_md: Path | None) -> dict[str, Any]:
    candidate = payload.get("candidate_profile", payload)
    if not isinstance(candidate, dict):
        raise ValueError("LLM profile JSON must contain candidate_profile object.")

    projects = [normalize_project(item) for item in as_list(candidate.get("projects")) if isinstance(item, dict)]
    risks = [normalize_risk(item) for item in as_list(payload.get("resume_risks")) if isinstance(item, dict)]

    if not risks:
        for project in projects:
            for risk in project.get("possible_risks", []):
                item = dict(risk)
                item["project"] = item.get("project") or project.get("name") or "整体简历"
                risks.append(normalize_risk(item, default_project=project.get("name", "整体简历")))

    for index, risk in enumerate(risks, start=1):
        risk.setdefault("id", f"{slugify(risk.get('project', 'risk'))}_{index}")
        missing = [
            field
            for field in ("project", "severity", "area", "evidence", "why_it_matters", "suggested_fix", "likely_followup")
            if not risk.get(field)
        ]
        if missing:
            raise ValueError(f"Risk #{index} missing required fields: {', '.join(missing)}")

    project_lookup = {project["name"]: project for project in projects}
    for project in projects:
        project["possible_risks"] = []
    for risk in risks:
        project = project_lookup.get(risk.get("project", ""))
        if project is not None:
            project["possible_risks"].append({key: value for key, value in risk.items() if key not in {"id", "project"}})

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if source_resume_md:
        source.setdefault("source_path", str(source_resume_md))
        markdown_path = str(source_resume_md)
    else:
        markdown_path = one_line(payload.get("markdown_path"))

    normalized = {
        "schema_version": "0.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "markdown_path": markdown_path,
        "candidate_profile": {
            "name": one_line(candidate.get("name")) or "未识别",
            "contact": normalize_contact(candidate.get("contact")),
            "education": as_list(candidate.get("education")),
            "target_roles": normalize_string_list(candidate.get("target_roles")),
            "skills": candidate.get("skills") if isinstance(candidate.get("skills"), dict) else {},
            "projects": projects,
            "research": one_line(candidate.get("research")),
            "publications": normalize_string_list(candidate.get("publications")),
            "experience": one_line(candidate.get("experience")),
            "internships": as_list(candidate.get("internships")),
            "awards": one_line(candidate.get("awards")),
            "award_items": normalize_string_list(candidate.get("award_items")),
            "interview_focus": normalize_string_list(candidate.get("interview_focus")),
        },
        "resume_risks": risks,
        "profile_generation": {
            "method": "llm",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "prompt_reference": "references/resume-profile-llm-generation.md",
        },
    }
    return normalized


def render_profile_md(profile: dict[str, Any]) -> str:
    candidate = profile["candidate_profile"]
    lines = [
        "# 候选人画像",
        "",
        f"- 姓名：{candidate.get('name', '未识别')}",
        f"- 来源：{profile.get('source', {}).get('source_path', '未识别')}",
        f"- Markdown：{profile.get('markdown_path', '未识别')}",
        "",
        "## 目标方向推断",
        f"- {', '.join(candidate.get('target_roles', [])) or '未识别'}",
    ]
    if candidate.get("interview_focus"):
        lines.extend(["", "## 建议面试重点"])
        lines.extend(f"- {item}" for item in candidate["interview_focus"])

    lines.extend(["", "## 技能画像"])
    for category, values in (candidate.get("skills") or {}).items():
        if isinstance(values, list):
            rendered = ", ".join(str(item) for item in values) or "未识别"
        else:
            rendered = one_line(values) or "未识别"
        lines.append(f"- {category}: {rendered}")

    lines.extend(["", "## 项目画像"])
    projects = candidate.get("projects", []) or []
    if not projects:
        lines.append("- 未识别")
    for project in projects:
        lines.extend(
            [
                f"### {project.get('name', '未命名项目')}",
                f"- 时间：{project.get('period') or '未识别'}",
                f"- 背景：{project.get('background') or '未识别'}",
                f"- 个人职责：{project.get('role') or '未识别'}",
                f"- 技术栈：{', '.join(project.get('tech_stack', [])) or '未识别'}",
                f"- 指标：{', '.join(project.get('metrics', [])) or '未识别'}",
            ]
        )
        if project.get("claims"):
            lines.append("- 关键表述：")
            lines.extend(f"  - {claim}" for claim in project["claims"][:8])
        if project.get("possible_risks"):
            lines.append("- 初步风险：")
            lines.extend(
                f"  - [{risk.get('severity')}] {risk.get('area')}：{risk.get('why_it_matters')}"
                for risk in project["possible_risks"]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_risks_md(profile: dict[str, Any]) -> str:
    risks = profile.get("resume_risks", []) or []
    lines = [
        "# 简历风险点",
        "",
        "> 来源：大模型读取解析后简历、JD 和用户修正后生成；用于面试追问和简历补强。",
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
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def apply_llm_profile(
    payload: dict[str, Any],
    output_dir: Path,
    source_resume_md: Path | None = None,
    keep_llm_json: bool = False,
) -> dict[str, str]:
    profile = normalize_profile_payload(payload, source_resume_md)
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_json = output_dir / "candidate_profile.json"
    profile_md = output_dir / "candidate_profile.md"
    risks_md = output_dir / "resume_risks.md"
    canonical_llm_json = output_dir / "candidate_profile.llm.json"

    write_json(profile_json, profile)
    profile_md.write_text(render_profile_md(profile), encoding="utf-8")
    risks_md.write_text(render_risks_md(profile), encoding="utf-8")

    outputs = {
        "profile_json": str(profile_json),
        "profile_markdown": str(profile_md),
        "risk_report": str(risks_md),
        "source_markdown": str(source_resume_md or profile.get("markdown_path", "")),
    }
    if keep_llm_json:
        write_json(canonical_llm_json, payload)
        outputs["llm_profile_json"] = str(canonical_llm_json)
    else:
        canonical_llm_json.unlink(missing_ok=True)
    return outputs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply an LLM-generated candidate profile to a parsed resume directory.")
    parser.add_argument("llm_profile_json", help="Path to the temporary UTF-8 LLM-generated profile JSON, or '-' to read JSON from UTF-8-safe stdin.")
    parser.add_argument("--output-dir", required=True, help="Parsed resume output directory.")
    parser.add_argument("--source-resume-md", help="Path to source_resume.md.")
    parser.add_argument("--keep-llm-json", action="store_true", help="Also persist raw LLM JSON to <output-dir>/candidate_profile.llm.json for debugging.")
    parser.add_argument("--delete-input", action="store_true", help="Delete the input JSON file after a successful apply. Ignored when reading from stdin.")
    parser.add_argument("--skip-rewrites", action="store_true", help="Deprecated no-op; rewrite suggestions are generated by the current LLM after interview evidence is available.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    payload = read_profile_payload(args.llm_profile_json)
    outputs = apply_llm_profile(
        payload,
        Path(args.output_dir).resolve(),
        source_resume_md=Path(args.source_resume_md).resolve() if args.source_resume_md else None,
        keep_llm_json=args.keep_llm_json,
    )
    if args.delete_input and args.llm_profile_json != "-":
        input_path = Path(args.llm_profile_json).resolve()
        kept_raw_path = Path(outputs["llm_profile_json"]).resolve() if "llm_profile_json" in outputs else None
        if input_path.exists() and input_path != kept_raw_path:
            input_path.unlink()
    print(json.dumps({"ok": True, "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
