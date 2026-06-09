#!/usr/bin/env python
"""Validate and persist current-LLM post-interview outputs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_STRENGTHS = {"NPC", "人上人", "顶级", "夯", "拉完了"}
VALID_TONES = {"温和", "默认", "铁面"}
VALID_MODES = {"完整模拟", "项目深挖", "八股快问快答", "算法陪练", "JD 定向面", "简历拷打", "复盘教练"}
VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_SCOPES = {"project", "experience", "skills", "summary", "education", "other"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def one_line(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def normalize_list(value: Any, *, max_items: int | None = None) -> list[str]:
    if value is None:
        items: list[str] = []
    elif isinstance(value, list):
        items = [one_line(item) for item in value if one_line(item)]
    else:
        items = [item.strip() for item in re.split(r"[；;,\n]", one_line(value)) if item.strip()]
    return items[:max_items] if max_items else items


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def require_text(payload: dict[str, Any], key: str, label: str) -> str:
    text = one_line(payload.get(key))
    if not text:
        raise ValueError(f"{label}.{key} is required.")
    return text


def normalize_next_round(value: Any) -> dict[str, Any]:
    payload = require_object(value, "next_round_recommendation")
    strength = require_text(payload, "strength", "next_round_recommendation")
    tone = require_text(payload, "tone", "next_round_recommendation")
    mode = require_text(payload, "mode", "next_round_recommendation")
    if strength not in VALID_STRENGTHS:
        raise ValueError(f"next_round_recommendation.strength must be one of {sorted(VALID_STRENGTHS)}.")
    if tone not in VALID_TONES:
        raise ValueError(f"next_round_recommendation.tone must be one of {sorted(VALID_TONES)}.")
    if mode not in VALID_MODES:
        raise ValueError(f"next_round_recommendation.mode must be one of {sorted(VALID_MODES)}.")
    focus = normalize_list(payload.get("focus"), max_items=8)
    recommended_questions = normalize_list(payload.get("recommended_questions"), max_items=8)
    commands = payload.get("commands")
    if commands is None:
        commands = [
            f"/strength {strength}",
            f"/tone {tone}",
            f"/mode {mode}",
        ]
        if focus:
            commands.append("/focus " + ", ".join(focus))
    else:
        commands = normalize_list(commands, max_items=8)

    return {
        "strength": strength,
        "tone": tone,
        "mode": mode,
        "focus": focus,
        "recommended_questions": recommended_questions,
        "rationale": one_line(payload.get("rationale")),
        "commands": commands,
        "evidence": normalize_list(payload.get("evidence"), max_items=8),
    }


def normalize_anchor(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    payload = require_object(value, "source_anchor")
    anchor = {
        "source_kind": one_line(payload.get("source_kind")),
        "path": one_line(payload.get("path")),
        "claim_index": payload.get("claim_index"),
        "matched_by": normalize_list(payload.get("matched_by"), max_items=8),
        "match_score": payload.get("match_score", 0),
    }
    return {key: val for key, val in anchor.items() if val not in ("", [], None)}


def normalize_rewrite_item(value: Any, index: int) -> dict[str, Any]:
    payload = require_object(value, f"resume_rewrite_suggestions[{index}]")
    scope = one_line(payload.get("scope") or "project")
    if scope not in VALID_SCOPES:
        raise ValueError(f"resume_rewrite_suggestions[{index}].scope must be one of {sorted(VALID_SCOPES)}.")

    priority = one_line(payload.get("priority") or "P1")
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"resume_rewrite_suggestions[{index}].priority must be one of {sorted(VALID_PRIORITIES)}.")

    confidence = one_line(payload.get("confidence") or "medium").lower()
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"resume_rewrite_suggestions[{index}].confidence must be one of {sorted(VALID_CONFIDENCE)}.")

    problem_types = normalize_list(payload.get("problem_types"), max_items=8)
    if not problem_types:
        raise ValueError(f"resume_rewrite_suggestions[{index}].problem_types is required.")

    original_text = require_text(payload, "original_text", f"resume_rewrite_suggestions[{index}]")
    suggested_rewrite = require_text(payload, "suggested_rewrite", f"resume_rewrite_suggestions[{index}]")
    rewrite_diff = payload.get("rewrite_diff")
    if isinstance(rewrite_diff, dict):
        before = one_line(rewrite_diff.get("before")) or original_text
        after = one_line(rewrite_diff.get("after")) or suggested_rewrite
    else:
        before = original_text
        after = suggested_rewrite

    return {
        "id": one_line(payload.get("id")) or f"rewrite_{index:03d}",
        "scope": scope,
        "target_label": require_text(payload, "target_label", f"resume_rewrite_suggestions[{index}]"),
        "target_area": require_text(payload, "target_area", f"resume_rewrite_suggestions[{index}]"),
        "original_text": original_text,
        "source_anchor": normalize_anchor(payload.get("source_anchor")),
        "problem_types": problem_types,
        "why_it_is_weak": require_text(payload, "why_it_is_weak", f"resume_rewrite_suggestions[{index}]"),
        "evidence": normalize_list(payload.get("evidence"), max_items=12),
        "rewrite_strategy": require_text(payload, "rewrite_strategy", f"resume_rewrite_suggestions[{index}]"),
        "suggested_rewrite": suggested_rewrite,
        "rewrite_diff": {
            "before": before,
            "after": after,
        },
        "placeholders_to_confirm": normalize_list(payload.get("placeholders_to_confirm"), max_items=12),
        "priority": priority,
        "confidence": confidence,
    }


def extract_payload(raw: Any) -> dict[str, Any]:
    payload = require_object(raw, "LLM post-interview output")
    nested = payload.get("post_interview_outputs")
    if nested is not None:
        payload = require_object(nested, "post_interview_outputs")
    return payload


def normalize_payload(raw: Any) -> dict[str, Any]:
    payload = extract_payload(raw)
    next_round = normalize_next_round(payload.get("next_round_recommendation"))
    rewrites_raw = payload.get("resume_rewrite_suggestions")
    if rewrites_raw is None:
        rewrites_raw = payload.get("rewrite_suggestions")
    if not isinstance(rewrites_raw, list):
        raise ValueError("resume_rewrite_suggestions must be a list.")
    rewrites = [normalize_rewrite_item(item, index) for index, item in enumerate(rewrites_raw, start=1)]
    return {
        "next_round_recommendation": next_round,
        "resume_rewrite_suggestions": rewrites,
    }


def render_next_round_md(next_round: dict[str, Any]) -> str:
    lines = [
        "# 下一轮模拟建议",
        "",
        f"- 强度：`{next_round['strength']}`",
        f"- 语气：`{next_round['tone']}`",
        f"- 模式：`{next_round['mode']}`",
    ]
    if next_round.get("focus"):
        lines.append("- 重点：" + "、".join(next_round["focus"]))
    if next_round.get("recommended_questions"):
        lines.append("- 推荐题目：" + "、".join(next_round["recommended_questions"]))
    if next_round.get("rationale"):
        lines.append(f"- 理由：{next_round['rationale']}")
    if next_round.get("commands"):
        lines.extend(["", "## 可直接执行"])
        lines.extend(f"- `{command}`" for command in next_round["commands"])
    return "\n".join(lines)


def render_rewrites_md(items: list[dict[str, Any]]) -> str:
    lines = ["# 简历修改建议", ""]
    if not items:
        lines.append("当前没有生成明确的简历修改建议。")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item['target_label']}",
                f"- 作用范围：{item['scope']}",
                f"- 风险区域：{item['target_area']}",
                f"- 优先级：{item['priority']}",
                f"- 原表述：{item['original_text']}",
                f"- 问题类型：{', '.join(item['problem_types'])}",
                f"- 为什么弱：{item['why_it_is_weak']}",
                f"- 改写策略：{item['rewrite_strategy']}",
                f"- 建议改写：{item['suggested_rewrite']}",
            ]
        )
        if item.get("evidence"):
            lines.append("- 面试证据：" + "；".join(item["evidence"]))
        if item.get("placeholders_to_confirm"):
            lines.append("- 待补真实信息：" + "；".join(item["placeholders_to_confirm"]))
        lines.append("")
    return "\n".join(lines).rstrip()


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def infer_paths(session_dir: Path, args: argparse.Namespace) -> dict[str, Path | None]:
    state = load_optional_json(session_dir / "session_state.json") or {}
    artifacts = state.get("artifacts", {}) if isinstance(state, dict) else {}
    evaluation_json = Path(args.evaluation_json).resolve() if args.evaluation_json else None
    transcript_json = Path(args.transcript_json).resolve() if args.transcript_json else None
    profile_json = Path(args.profile_json).resolve() if args.profile_json else None
    risks_md = Path(args.risks_md).resolve() if args.risks_md else None

    if evaluation_json is None:
        value = artifacts.get("evaluation_json") or str(session_dir / "interview_evaluation.json")
        evaluation_json = Path(value).resolve()
    if transcript_json is None:
        value = artifacts.get("transcript_json") or str(session_dir / "transcript.json")
        transcript_json = Path(value).resolve()
    if profile_json is None and artifacts.get("candidate_profile_json"):
        profile_json = Path(artifacts["candidate_profile_json"]).resolve()
    if risks_md is None and profile_json:
        risks_md = (profile_json.parent / "resume_risks.md").resolve()

    return {
        "evaluation_json": evaluation_json,
        "transcript_json": transcript_json,
        "profile_json": profile_json,
        "risks_md": risks_md,
    }


def ensure_report_sections(evaluation: dict[str, Any]) -> None:
    sections = evaluation.get("report_sections")
    if not isinstance(sections, list):
        sections = []
    for section in ("resume_rewrite", "next_round"):
        if section not in sections:
            sections.append(section)
    evaluation["report_sections"] = sections


def refresh_evaluation_md(evaluation_json: Path, evaluation: dict[str, Any]) -> Path | None:
    md_path = evaluation_json.with_suffix(".md")
    try:
        import evaluate_interview

        write_text(md_path, evaluate_interview.render_evaluation_md(evaluation))
        return md_path
    except Exception:
        return None


def update_session_state(session_dir: Path, outputs: dict[str, str]) -> None:
    state_path = session_dir / "session_state.json"
    if not state_path.exists():
        return
    state = read_json(state_path)
    if not isinstance(state, dict):
        return
    artifacts = state.setdefault("artifacts", {})
    artifacts.update(outputs)
    write_json(state_path, state)


def apply_outputs(session_dir: Path, llm_outputs_json: Path, args: argparse.Namespace) -> dict[str, Any]:
    session_dir.mkdir(parents=True, exist_ok=True)
    normalized = normalize_payload(read_json(llm_outputs_json))
    generated_at = datetime.now().isoformat(timespec="seconds")
    paths = infer_paths(session_dir, args)

    canonical_path = session_dir / "post_interview_outputs.llm.json"
    next_json = session_dir / "next_round_recommendation.json"
    next_md = session_dir / "next_round_recommendation.md"
    rewrite_json = session_dir / "resume_rewrite_suggestions.json"
    rewrite_md = session_dir / "resume_rewrite_suggestions.md"

    canonical = {
        "schema_version": "1.0",
        "kind": "llm_post_interview_outputs",
        "generated_at": generated_at,
        "source_llm_json": str(llm_outputs_json),
        "inputs": {key: str(value) for key, value in paths.items() if value},
        **normalized,
    }
    write_json(canonical_path, canonical)
    write_json(
        next_json,
        {
            "schema_version": "1.0",
            "kind": "next_round_recommendation",
            "generated_at": generated_at,
            "source_llm_json": str(llm_outputs_json),
            "next_round_recommendation": normalized["next_round_recommendation"],
        },
    )
    write_text(next_md, render_next_round_md(normalized["next_round_recommendation"]))
    write_json(
        rewrite_json,
        {
            "schema_version": "1.0",
            "kind": "resume_rewrite_suggestions",
            "generated_at": generated_at,
            "source_llm_json": str(llm_outputs_json),
            "suggestions": normalized["resume_rewrite_suggestions"],
        },
    )
    write_text(rewrite_md, render_rewrites_md(normalized["resume_rewrite_suggestions"]))

    evaluation_json = paths["evaluation_json"]
    evaluation_md = None
    if evaluation_json and evaluation_json.exists():
        evaluation = read_json(evaluation_json)
        if isinstance(evaluation, dict):
            evaluation["next_round_recommendation"] = normalized["next_round_recommendation"]
            evaluation["resume_rewrite_suggestions"] = normalized["resume_rewrite_suggestions"]
            evaluation["post_interview_outputs"] = {
                "method": "llm",
                "updated_at": generated_at,
                "source_llm_json": str(llm_outputs_json),
                "canonical_json": str(canonical_path),
            }
            ensure_report_sections(evaluation)
            write_json(evaluation_json, evaluation)
            evaluation_md = refresh_evaluation_md(evaluation_json, evaluation)

    artifact_outputs = {
        "llm_post_interview_outputs_json": str(canonical_path),
        "next_round_recommendation_json": str(next_json),
        "next_round_recommendation_md": str(next_md),
        "resume_rewrite_suggestions_json": str(rewrite_json),
        "resume_rewrite_suggestions_md": str(rewrite_md),
    }
    if evaluation_md:
        artifact_outputs["evaluation_md"] = str(evaluation_md)
    update_session_state(session_dir, artifact_outputs)

    return {
        "ok": True,
        "session_dir": str(session_dir),
        "outputs": {
            **artifact_outputs,
            "evaluation_json": str(evaluation_json) if evaluation_json and evaluation_json.exists() else "",
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and persist current-LLM post-interview outputs.")
    parser.add_argument("session_dir", help="Path to the session directory.")
    parser.add_argument("llm_outputs_json", help="Path to current-LLM JSON with next-round and resume-rewrite outputs.")
    parser.add_argument("--evaluation-json", help="Path to interview_evaluation.json. Default: infer from session.")
    parser.add_argument("--transcript-json", help="Path to transcript.json. Default: infer from session.")
    parser.add_argument("--profile-json", help="Path to candidate_profile.json. Default: infer from session artifacts.")
    parser.add_argument("--risks-md", help="Path to resume_risks.md. Default: next to candidate_profile.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = apply_outputs(Path(args.session_dir).resolve(), Path(args.llm_outputs_json).resolve(), args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
