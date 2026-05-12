"""Session controller for the V1.0 CS technical interview state machine.

This script turns the documented interview flow into local session artifacts:

- session_state.json: runtime state, current question, command history
- transcript.json: structured evidence records aligned with V0.5
- question_selection.json: frozen selection artifact for the current plan
- score_snapshot.json / score_snapshot.md: mid-session score outputs
- interview_evaluation.json / interview_evaluation.md: final report outputs
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from evaluate_interview import evaluate_transcript, render_evaluation_md
from parse_resume import parse_resume_to_profile
from select_questions import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_BASE,
    read_text as read_selection_text,
    DEFAULT_ROLE_PROFILES,
    finalize_selection,
    load_json as load_selection_json,
    load_role_profiles,
    parse_focus,
    parse_target_roles,
    render_question_selection_md,
    safe_load_json,
    select_questions,
)


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_SESSIONS_DIR_NAME = "sessions"
SESSION_SCHEMA_VERSION = "1.0"
TRANSCRIPT_SCHEMA_VERSION = "0.5"
DEFAULT_MODE_PROFILES = SKILL_DIR / "data" / "interview_mode_profiles.json"

RUNTIME_STATUSES = {
    "INIT",
    "RESUME_PARSED",
    "CONFIG_READY",
    "RUNNING",
    "PAUSED",
    "REPORT_GENERATION",
    "DONE",
}

STAGES = {
    "SELF_INTRO",
    "PROJECT_DEEP_DIVE",
    "CS_FUNDAMENTALS",
    "CODING_INTERVIEW",
    "CANDIDATE_QUESTIONS",
}

STRENGTH_TO_LAYER = {
    "拉完了": "basic",
    "NPC": "basic",
    "npc": "basic",
    "人上人": "standard",
    "顶级": "deep",
    "夯": "deep",
}

VALID_QUALITIES = {"strong", "partial", "weak", "wrong"}

DEFAULT_CONFIG = {
    "strength": "人上人",
    "tone": "默认",
    "level": "中等",
    "mode": "完整模拟",
    "role": "",
    "focus": [],
    "jd_text": "",
    "jd_context": {},
    "view": "interview_mode",
}


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_mode_profiles(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or DEFAULT_MODE_PROFILES
    if not profile_path.exists():
        return {"profiles": {}}
    return json.loads(read_text(profile_path))


def build_mode_aliases(mode_profiles: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, profile in (mode_profiles.get("profiles") or {}).items():
        aliases[name] = name
        for alias in profile.get("aliases", []) or []:
            aliases[str(alias)] = name
            aliases[str(alias).lower()] = name
    return aliases


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "session"


def normalize_mode(value: str | None) -> str:
    raw = (value or DEFAULT_CONFIG["mode"]).strip()
    mode_profiles = load_mode_profiles()
    mode_aliases = build_mode_aliases(mode_profiles)
    profiles = mode_profiles.get("profiles") or {}
    return mode_aliases.get(raw, mode_aliases.get(raw.lower(), raw if raw in profiles else DEFAULT_CONFIG["mode"]))


def normalize_strength_to_layer(value: str | None) -> str:
    if not value:
        return "standard"
    return STRENGTH_TO_LAYER.get(value.strip(), STRENGTH_TO_LAYER.get(value.strip().lower(), "standard"))


def stage_label(stage: str) -> str:
    return {
        "SELF_INTRO": "自我介绍",
        "PROJECT_DEEP_DIVE": "项目深挖",
        "CS_FUNDAMENTALS": "CS 基础",
        "CODING_INTERVIEW": "算法面试",
        "CANDIDATE_QUESTIONS": "候选人反问",
    }.get(stage, stage)


def question_plan_item(
    stage: str,
    question_id: str,
    question_text: str,
    metadata: dict[str, Any] | None = None,
    prompt_block: str | None = None,
) -> dict[str, Any]:
    merged_metadata = metadata or {}
    return {
        "stage": stage,
        "question_id": question_id,
        "question_text": question_text,
        "metadata": merged_metadata,
        "prompt_block": prompt_block or question_text,
    }


def get_mode_profile(mode: str, mode_profiles: dict[str, Any]) -> dict[str, Any]:
    profiles = mode_profiles.get("profiles") or {}
    return profiles.get(mode, profiles.get(DEFAULT_CONFIG["mode"], {}))


def mode_stage_sequence(mode: str, mode_profiles: dict[str, Any]) -> list[str]:
    return list(get_mode_profile(mode, mode_profiles).get("stage_sequence", []))


def mode_stage_budget(mode_profile: dict[str, Any], stage: str, layer: str, fallback: int) -> int:
    counts = mode_profile.get("default_question_counts", {}).get(stage, {})
    if isinstance(counts, dict):
        if layer in counts:
            return int(counts[layer])
        if "default" in counts:
            return int(counts["default"])
    return fallback


def default_sessions_root(path: str | None = None) -> Path:
    return Path(path).resolve() if path else (Path.cwd() / DEFAULT_SESSIONS_DIR_NAME).resolve()


def create_session_dir(
    sessions_root: Path,
    session_name: str | None,
    resume: str | None,
    profile_json: str | None,
    transcript_json: str | None,
) -> Path:
    stem_source = session_name
    if not stem_source and resume:
        stem_source = Path(resume).stem if not resume.startswith("http") else slugify(resume)
    if not stem_source and profile_json:
        stem_source = Path(profile_json).stem.replace("candidate_profile", "").strip("_") or "profile"
    if not stem_source and transcript_json:
        stem_source = Path(transcript_json).stem
    stem = slugify(stem_source or "interview")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = sessions_root / f"{stem}_session_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def new_stage_status(stage_sequence: list[str]) -> dict[str, str]:
    return {stage: "pending" for stage in stage_sequence}


def transcript_skeleton(config: dict[str, Any], session_dir: Path, profile: dict[str, Any] | None, selection_path: Path | None) -> dict[str, Any]:
    candidate = (profile or {}).get("candidate_profile", {})
    return {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "session": {
            "strength": config.get("strength", DEFAULT_CONFIG["strength"]),
            "tone": config.get("tone", DEFAULT_CONFIG["tone"]),
            "mode": config.get("mode", DEFAULT_CONFIG["mode"]),
            "role": config.get("role", ""),
            "focus": config.get("focus", []),
            "jd_title": config.get("jd_title", ""),
            "resume_path": str((profile or {}).get("source", {}).get("source_path", "")),
            "selection_json_path": str(selection_path) if selection_path else "",
            "session_dir": str(session_dir),
            "candidate_name": candidate.get("name", ""),
        },
        "answers": [],
    }


def session_state_path(session_dir: Path) -> Path:
    return session_dir / "session_state.json"


def transcript_path(session_dir: Path) -> Path:
    return session_dir / "transcript.json"


def load_session_state(session_dir: Path) -> dict[str, Any]:
    return load_json(session_state_path(session_dir))


def save_session_state(session_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    artifacts = state.setdefault("artifacts", {})
    artifacts["session_brief_md"] = str(session_dir / "session_brief.md")
    write_json(session_state_path(session_dir), state)
    write_session_brief(session_dir, state)


def load_transcript(session_dir: Path) -> dict[str, Any]:
    return load_json(transcript_path(session_dir))


def save_transcript(session_dir: Path, transcript: dict[str, Any]) -> None:
    write_json(transcript_path(session_dir), transcript)


def append_command_history(state: dict[str, Any], command: str, payload: dict[str, Any] | None = None) -> None:
    history = state.setdefault("command_history", [])
    history.append(
        {
            "timestamp": now_iso(),
            "command": command,
            "payload": payload or {},
        }
    )


def summarize_question(question: dict[str, Any]) -> dict[str, Any]:
    if not question:
        return {}
    metadata = question.get("metadata", {}) or {}
    return {
        "stage": question.get("stage"),
        "question_id": question.get("question_id"),
        "question_text": question.get("question_text"),
        "hint_level": question.get("hint_level", 0),
        "jd_context": metadata.get("jd_context", {}),
        "jd_summary": metadata.get("jd_summary", ""),
    }


def with_runtime_jd_context(question: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    if not question:
        return None
    current = dict(question)
    metadata = dict(current.get("metadata", {}) or {})
    jd_context = metadata.get("jd_context") or (state.get("config", {}) or {}).get("jd_context", {}) or {}
    metadata["jd_context"] = jd_context
    metadata.setdefault("jd_summary", str(jd_context.get("summary", "") or ""))
    current["metadata"] = metadata
    if "hint_level" not in current:
        current["hint_level"] = 0
    return current


def command_descriptor(command: str, description: str, note: str = "") -> dict[str, str]:
    item = {
        "command": command,
        "description": description,
    }
    if note:
        item["note"] = note
    return item


def trim_text(value: str, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def summarize_jd_text(jd_text: str) -> dict[str, Any]:
    text = " ".join(str(jd_text or "").split())
    if not text:
        return {
            "has_jd": False,
            "summary": "",
            "keywords": [],
            "source": "missing",
        }

    normalized = text.replace("：", ":")
    title = ""
    title_match = (
        re.search(r"(?:职位|岗位|招聘岗位|岗位名称|职位名称)\s*:\s*([^\n。；;，,]{2,36})", normalized, flags=re.I)
        or re.search(r"([A-Za-z0-9+/.-]*(?:后端|前端|Java|Python|Go|算法|AI|RAG|SRE|测试|开发)[A-Za-z0-9+/.-]*(?:工程师|开发|专家|实习生))", normalized, flags=re.I)
    )
    if title_match:
        title = trim_text(title_match.group(1), 48)

    keywords_catalog = [
        "Java", "Python", "Go", "MySQL", "Redis", "Spring", "Spring Boot", "Spring Cloud",
        "JVM", "并发", "操作系统", "网络", "消息队列", "Kafka", "RocketMQ", "分布式",
        "微服务", "系统设计", "Docker", "Kubernetes", "Linux", "Prometheus", "Grafana",
        "Agent", "AI Agent", "RAG", "GraphRAG", "LangChain", "LangGraph", "向量数据库",
        "Embedding", "模型服务化", "推理优化", "评测", "SRE", "DevOps", "可观测性",
    ]
    lowered = text.lower()
    keywords: list[str] = []
    for keyword in keywords_catalog:
        if keyword.lower() in lowered and keyword not in keywords:
            keywords.append(keyword)

    summary_parts = []
    if title:
        summary_parts.append(f"目标岗位：{title}")
    if keywords:
        summary_parts.append("重点能力：" + "、".join(keywords[:8]))
    summary = "；".join(summary_parts) if summary_parts else trim_text(text, 120)

    return {
        "has_jd": True,
        "title": title,
        "summary": summary,
        "keywords": keywords[:12],
        "preview": trim_text(text, 220),
        "source": "user_provided",
    }


def has_jd_context(state: dict[str, Any]) -> bool:
    config = state.get("config", {}) or {}
    jd_text = str(config.get("jd_text", "") or "").strip()
    jd_context = config.get("jd_context", {}) or {}
    return bool(jd_text or jd_context.get("has_jd"))


def available_commands_for_state(state: dict[str, Any]) -> list[dict[str, str]]:
    runtime_status = state.get("runtime_status", "INIT")
    has_current_question = bool(state.get("current_question"))
    answered_count = sum(int(value or 0) for value in (state.get("progress", {}).get("question_counts", {}) or {}).values())
    commands: list[dict[str, str]] = []

    if runtime_status in {"INIT", "RESUME_PARSED"}:
        commands.extend(
            [
                command_descriptor("/jd", "Provide the target JD so the interviewer can bias questions to the role."),
                command_descriptor("/configure", "Set role, strength, mode, focus, and JD context."),
                command_descriptor("/status", "Show the current session state and artifacts."),
                command_descriptor("/reset", "Reset the session if you want to start over."),
            ]
        )
    elif runtime_status == "CONFIG_READY":
        commands.extend(
            [
                command_descriptor("/start", "Start the configured interview session."),
                command_descriptor("/jd", "Update the target JD before starting for better role-specific questioning."),
                command_descriptor("/configure", "Adjust role, strength, mode, focus, or JD before starting."),
                command_descriptor("/status", "Review the current session state and plan."),
                command_descriptor("/reset", "Archive current artifacts and start fresh."),
            ]
        )
    elif runtime_status == "RUNNING":
        commands.extend(
            [
                command_descriptor("/status", "Show current stage, question, and progress."),
                command_descriptor("/next", "Show the current question block or move to the next one."),
                command_descriptor("/jd", "Queue JD updates to reshape follow-up bias after the current stage.", "deferred while running"),
                command_descriptor("/configure", "Queue role/mode/focus changes for the end of the current stage.", "deferred while running"),
            ]
        )
        if has_current_question:
            commands.extend(
                [
                    command_descriptor("/hint", "Increase hint level for the current question."),
                    command_descriptor("/repeat", "Repeat the current question text."),
                    command_descriptor("/explain", "Give a lightweight explanation of the current question."),
                    command_descriptor("/skip", "Skip the current question and record it as skipped."),
                    command_descriptor("/record-answer", "Record a scored answer manually."),
                ]
            )
        commands.extend(
            [
                command_descriptor("/pause", "Pause the interview without losing the current question."),
                command_descriptor("/score", "Generate a mid-session score snapshot."),
                command_descriptor("/report", "End the interview and generate the final report."),
            ]
        )
    elif runtime_status == "PAUSED":
        commands.extend(
            [
                command_descriptor("/status", "Show the current paused state."),
                command_descriptor("/continue", "Resume the paused interview."),
                command_descriptor("/jd", "Queue JD updates before resuming.", "deferred while paused"),
                command_descriptor("/configure", "Queue role/mode/focus changes before resuming.", "deferred while paused"),
                command_descriptor("/score", "Generate a mid-session score snapshot."),
                command_descriptor("/reset", "Archive current artifacts and start fresh."),
            ]
        )
        if answered_count > 0:
            commands.append(command_descriptor("/report", "Finish the interview now and generate the final report."))
    elif runtime_status == "REPORT_GENERATION":
        commands.extend(
            [
                command_descriptor("/status", "Show the current report-generation state."),
                command_descriptor("/report", "Generate the final interview report."),
            ]
        )
    elif runtime_status == "DONE":
        commands.extend(
            [
                command_descriptor("/status", "Show final state and output artifact paths."),
                command_descriptor("/score", "Regenerate a score snapshot from saved transcript data."),
                command_descriptor("/reset", "Archive this session and start a new one."),
            ]
        )

    return commands


def available_inputs_for_state(state: dict[str, Any]) -> list[dict[str, str]]:
    runtime_status = state.get("runtime_status", "INIT")
    current = state.get("current_question") or {}
    if runtime_status == "RUNNING" and current:
        return [
            {
                "type": "free_text_answer",
                "description": "You can also answer the current question directly in natural language.",
                "question_id": str(current.get("question_id", "")),
            }
        ]
    return []


def build_status_message(state: dict[str, Any]) -> str:
    runtime_status = state.get("runtime_status", "INIT")
    current = state.get("current_question") or {}
    active_stage = state.get("active_stage") or ""
    jd_ready = has_jd_context(state)
    if runtime_status == "INIT":
        if not jd_ready:
            return "Session created. Share the target JD first so the interviewer can lock onto the role before the interview starts."
        return "Session created. Configure the interview before starting."
    if runtime_status == "RESUME_PARSED":
        if not jd_ready:
            return "Resume parsed. Before we start, provide the JD so the interviewer can remember the target role and ask more targeted questions."
        return "Resume parsed. Configure role, strength, mode, focus, and JD to build the question plan."
    if runtime_status == "CONFIG_READY":
        if not jd_ready:
            return "Interview configured, but no JD is set yet. Add one if you want stronger role-specific questioning."
        return "Interview configured. You can start now or fine-tune the setup first."
    if runtime_status == "RUNNING":
        if current:
            return f"Interview is running in stage `{active_stage}`. The current question is ready."
        return f"Interview is running in stage `{active_stage}`. Use `/next` to continue."
    if runtime_status == "PAUSED":
        return "Interview is paused. Continue when ready, or score/report/reset from here."
    if runtime_status == "REPORT_GENERATION":
        return "Question flow is complete. Generate the final report now."
    if runtime_status == "DONE":
        return "Interview finished. Review the outputs or reset for a new session."
    return f"Current runtime status: {runtime_status}"


def build_next_step_hint(state: dict[str, Any]) -> str:
    runtime_status = state.get("runtime_status", "INIT")
    current = state.get("current_question") or {}
    jd_ready = has_jd_context(state)
    if runtime_status in {"INIT", "RESUME_PARSED"}:
        if not jd_ready:
            return "Next: send `/jd <岗位描述>` or paste the JD directly, then run `/configure`."
        return "Next: run `/configure` to set role, strength, mode, focus, and optional JD."
    if runtime_status == "CONFIG_READY":
        if not jd_ready:
            return "Next: you can `/start` now, but adding `/jd <岗位描述>` first will make the interviewer's questioning much more targeted."
        return "Next: run `/start` to begin the interview."
    if runtime_status == "RUNNING":
        if current:
            return "Next: answer the current question directly, or use `/hint`, `/repeat`, `/skip`, or `/pause`."
        return "Next: use `/next` to load the current question."
    if runtime_status == "PAUSED":
        return "Next: use `/continue` to resume, or `/score` and `/report` if you want to stop here."
    if runtime_status == "REPORT_GENERATION":
        return "Next: run `/report` to generate `interview_evaluation.json` and `interview_evaluation.md`."
    if runtime_status == "DONE":
        return "Next: review the generated artifacts, or use `/reset` to start a new session."
    return "Next: check `/status` and continue from there."


def enrich_response(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.setdefault("runtime_status", state.get("runtime_status"))
    result["available_commands"] = available_commands_for_state(state)
    available_inputs = available_inputs_for_state(state)
    if available_inputs:
        result["available_inputs"] = available_inputs
    result["status_message"] = build_status_message(state)
    result["next_step_hint"] = build_next_step_hint(state)
    return result


def error_response(state: dict[str, Any], message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {"ok": False, "error": message}
    if payload:
        base.update(payload)
    return enrich_response(state, base)


def write_score_snapshot(session_dir: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    conclusion = result.get("overall_conclusion", {}) or {}
    total_score = conclusion.get("total_score", conclusion.get("score"))
    json_path = session_dir / "score_snapshot.json"
    md_path = session_dir / "score_snapshot.md"

    lines = [
        "# 当前阶段评分",
        "",
        f"- 生成时间：{result.get('generated_at')}",
        f"- 综合评分：{total_score if total_score is not None else '暂无'} / 100",
        "",
        "## 各阶段摘要",
    ]
    stage_scores = result.get("stage_scores", {}) or {}
    if not stage_scores:
        lines.append("- 当前还没有可评分的作答记录。")
    else:
        for stage, stats in stage_scores.items():
            lines.extend(
                [
                    "",
                    f"### {stage_label(stage)}",
                    f"- 平均得分：{stats.get('score_percent', 0)} / 100",
                    f"- 提示次数：{stats.get('hints_used', 0)}",
                    f"- 跳过次数：{stats.get('skipped_count', 0)}",
                ]
            )
            issues = stats.get("issues", []) or []
            strengths = stats.get("strengths", []) or []
            if strengths:
                lines.append("- 亮点：" + "；".join(strengths[:2]))
            if issues:
                lines.append("- 问题：" + "；".join(issues[:2]))
    lines.append("")

    write_json(json_path, result)
    write_text(md_path, "\n".join(lines))
    return json_path, md_path
def empty_score_result(message: str) -> dict[str, Any]:
    return {
        "schema_version": "0.5",
        "generated_at": now_iso(),
        "overall_conclusion": {
            "score": 0,
            "total_score": 0,
            "grade": "N/A",
            "verdict": message,
        },
        "module_scores": {},
        "stage_scores": {},
        "weakness_tracking": [],
        "next_round_recommendation": {},
    }


def write_final_report(session_dir: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    json_path = session_dir / "interview_evaluation.json"
    md_path = session_dir / "interview_evaluation.md"
    write_json(json_path, result)
    write_text(md_path, render_evaluation_md(result))
    return json_path, md_path


def write_session_brief(session_dir: Path, state: dict[str, Any]) -> Path:
    config = state.get("config", {}) or {}
    summary = state.get("selection_summary", {}) or {}
    stage_sequence = state.get("stage_sequence", []) or []
    artifacts = state.get("artifacts", {}) or {}
    available_commands = available_commands_for_state(state)
    status_message = build_status_message(state)
    next_step_hint = build_next_step_hint(state)

    selection_root = artifacts.get("question_selection_json_root")
    selection = load_json(Path(selection_root)) if selection_root and Path(selection_root).exists() else None
    keyword_summary = (selection or {}).get("keyword_summary", {}) or {}
    top_keywords = [item[0] for item in keyword_summary.get("profile_top_keywords", [])[:5] if isinstance(item, list) and item]
    if not top_keywords:
        top_keywords = list(config.get("focus", []) or [])[:5]
    jd_context = config.get("jd_context", {}) or summarize_jd_text(config.get("jd_text", ""))
    jd_keywords = keyword_summary.get("jd_matched_keywords", [])[:5]
    jd_keyword_labels = [item[0] for item in jd_keywords if isinstance(item, list) and item]

    lines = [
        "# Session Brief",
        "",
        "## Opening Card",
        f"- role: `{config.get('role') or 'auto'}`",
        f"- strength: `{config.get('strength', DEFAULT_CONFIG['strength'])}`",
        f"- mode: `{config.get('mode', DEFAULT_CONFIG['mode'])}`",
        f"- focus: {', '.join(config.get('focus', []) or []) or 'auto'}",
        f"- top 5 selected topics: {', '.join(top_keywords) if top_keywords else 'N/A'}",
        f"- JD soul: {jd_context.get('summary') or 'not set yet'}",
        f"- status: `{state.get('runtime_status', 'INIT')}`",
        "",
        "## Config",
        f"- `/role {config.get('role') or 'auto'}`",
        f"- `/strength {config.get('strength', DEFAULT_CONFIG['strength'])}`",
        f"- `/tone {config.get('tone', DEFAULT_CONFIG['tone'])}`",
        f"- `/level {config.get('level', DEFAULT_CONFIG['level'])}`",
        f"- `/mode {config.get('mode', DEFAULT_CONFIG['mode'])}`",
        f"- `/focus {', '.join(config.get('focus', []) or []) or 'auto'}`",
        f"- `/jd {'configured' if jd_context.get('has_jd') else 'missing'}`",
        "",
        "## Why This Bias",
        f"- explicit /role: {summary.get('role') or 'not set explicitly'}",
        f"- strength bias: {summary.get('strength') or config.get('strength', DEFAULT_CONFIG['strength'])}",
        f"- inferred roles: {', '.join(summary.get('inferred_roles', []) or []) or 'N/A'}",
        f"- priority roles: {', '.join(summary.get('priority_roles', []) or []) or 'N/A'}",
        f"- expanded roles: {', '.join(summary.get('expanded_priority_roles', []) or []) or 'N/A'}",
        f"- role bias active: {'yes' if summary.get('role_bias_explained') else 'no'}",
        f"- JD matched keywords: {', '.join(jd_keyword_labels) if jd_keyword_labels else 'N/A'}",
        "",
        "## Flow",
        f"- stage sequence: {' -> '.join(stage_sequence) if stage_sequence else 'not configured'}",
        f"- root question selection: {artifacts.get('question_selection_json_root') or 'not generated'}",
        f"- nested question selection: {artifacts.get('question_selection_json') or 'not generated'}",
        "",
        "## Current State",
        f"- status message: {status_message}",
        f"- next step: {next_step_hint}",
        "",
        "## Available Commands",
    ]
    if available_commands:
        for item in available_commands:
            note = f" ({item['note']})" if item.get('note') else ""
            lines.append(f"- `{item['command']}`: {item['description']}{note}")
    else:
        lines.append("- N/A")

    lines.extend(
        [
            "",
            "## JD",
            f"- configured: {'yes' if jd_context.get('has_jd') else 'no'}",
            f"- title: {jd_context.get('title') or 'N/A'}",
            f"- summary: {jd_context.get('summary') or 'Please provide the JD so the interviewer can keep the target role in mind.'}",
        ]
    )
    if jd_context.get("keywords"):
        lines.append(f"- extracted keywords: {', '.join(jd_context.get('keywords', [])[:8])}")

    brief_path = session_dir / "session_brief.md"
    write_text(brief_path, "\n".join(lines) + "\n")
    return brief_path
def build_self_intro_items(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    jd_context = ((config or {}).get("jd_context") or {}) if config else {}
    base = "请先做一个 2-3 分钟的自我介绍，重点突出与你目标岗位最匹配的经历、项目和技术亮点。"
    if jd_context.get("summary"):
        text = f"{base} 这场面试我会按这个岗位来听：{jd_context.get('summary')}。"
    else:
        text = base
    return [
        question_plan_item(
            "SELF_INTRO",
            "self_intro_001",
            text,
            metadata={"kind": "self_intro", "jd_summary": jd_context.get("summary", "")},
        )
    ]
def build_candidate_question_items(layer: str, mode_profile: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        question_plan_item(
            "CANDIDATE_QUESTIONS",
            "candidate_questions_001",
            "你有什么想问我的？",
            metadata={"kind": "candidate_questions"},
        )
    ]
    budget = mode_stage_budget(mode_profile, "CANDIDATE_QUESTIONS", layer, 1)
    if budget > 1:
        items.append(
            question_plan_item(
                "CANDIDATE_QUESTIONS",
                "candidate_questions_002",
                "如果再补充一个更有价值的问题，你会问什么？",
                metadata={"kind": "candidate_questions"},
            )
        )
    return items
def build_project_items(
    profile: dict[str, Any],
    layer: str,
    mode_profile: dict[str, Any],
    jd_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidate = profile.get("candidate_profile", {})
    projects = candidate.get("projects", []) or []
    risks = profile.get("resume_risks", []) or []
    budget = mode_stage_budget(mode_profile, "PROJECT_DEEP_DIVE", layer, 3)
    items: list[dict[str, Any]] = []
    project_policy = str(mode_profile.get("selection_policy", {}).get("project_policy", "resume_risks_plus_templates"))
    jd_context = jd_context or {}
    jd_summary = str(jd_context.get("summary", "") or "").strip()
    intro_prefix = f"我会按这个岗位语境来追问：{jd_summary}\n\n" if jd_summary else ""

    project_map = {str(project.get("name", "")): project for project in projects}
    used_ids: set[str] = set()

    risk_candidates = list(risks)
    if project_policy == "resume_risks_heavy":
        risk_candidates = list(risks)
    elif project_policy == "jd_match_bias":
        risk_candidates = list(risks)
    elif project_policy == "disabled":
        risk_candidates = []

    for risk in risk_candidates:
        if len(items) >= budget:
            break
        followup = str(risk.get("likely_followup", "")).strip()
        project_name = str(risk.get("project", "")).strip()
        if not followup or not project_name:
            continue
        question_id = str(risk.get("id", "")).strip() or f"{slugify(project_name)}_{len(items)+1}"
        if question_id in used_ids:
            continue
        project = project_map.get(project_name, {})
        items.append(
            question_plan_item(
                "PROJECT_DEEP_DIVE",
                question_id,
                followup,
                metadata={
                    "kind": "project_followup",
                    "project": project_name,
                    "risk_area": risk.get("area", ""),
                    "severity": risk.get("severity", ""),
                    "background": project.get("background", ""),
                    "jd_context": jd_context,
                    "jd_summary": jd_summary,
                },
                prompt_block=(intro_prefix + followup) if not items and intro_prefix else followup,
            )
        )
        used_ids.add(question_id)

    template_questions = [
        "这个项目最核心的业务问题是什么？你为什么要这样设计？",
        "你个人独立负责了哪些模块？边界怎么划分？",
        "这个方案里最难的技术点是什么？你是怎么解决的？",
        "这里最大的 tradeoff 是什么？为什么没有选别的方案？",
        "你怎么评估这个方案的效果，指标从哪里来？",
        "如果线上规模扩大 10 倍，哪里会先成为瓶颈？",
        "线上出了问题你怎么定位、降级和回滚？",
        "如果重做一次，你最想改哪个设计？为什么？",
    ]
    project_index = 0
    if project_policy != "disabled":
        while len(items) < budget and projects:
            project = projects[project_index % len(projects)]
            template = template_questions[len(items) % len(template_questions)]
            question_id = f"{slugify(str(project.get('name', 'project')))}_template_{len(items)+1}"
            if question_id not in used_ids:
                items.append(
                    question_plan_item(
                        "PROJECT_DEEP_DIVE",
                        question_id,
                        template,
                        metadata={
                            "kind": "project_template",
                            "project": project.get("name", ""),
                            "background": project.get("background", ""),
                            "jd_context": jd_context,
                            "jd_summary": jd_summary,
                        },
                        prompt_block=(intro_prefix + template) if not items and intro_prefix else template,
                    )
                )
                used_ids.add(question_id)
            project_index += 1

    return items


def build_fundamental_items(selection: dict[str, Any], layer: str, mode_profile: dict[str, Any]) -> list[dict[str, Any]]:
    budget = mode_stage_budget(mode_profile, "CS_FUNDAMENTALS", layer, 3)
    items: list[dict[str, Any]] = []
    fundamentals = list(selection.get("selected_fundamentals") or [])
    fundamentals_policy = str(mode_profile.get("selection_policy", {}).get("fundamentals_policy", "balanced"))
    if fundamentals_policy == "topic_dense":
        fundamentals.sort(key=lambda item: (item.get("question", {}).get("topic", ""), -float(item.get("score", 0))))
    elif fundamentals_policy == "jd_keyword_bias":
        fundamentals.sort(key=lambda item: (-float(item.get("score", 0)), item.get("question", {}).get("topic", "")))
    elif fundamentals_policy == "resume_claim_bias":
        fundamentals.sort(key=lambda item: (-float(item.get("score", 0)), item.get("question", {}).get("subtopic", "")))
    for item in fundamentals[:budget]:
        question = item.get("question", {})
        items.append(
            question_plan_item(
                "CS_FUNDAMENTALS",
                str(question.get("id", "")),
                str(question.get("question", "")).strip(),
                metadata={
                    "kind": "fundamental",
                    "topic": question.get("topic", ""),
                    "subtopic": question.get("subtopic", ""),
                    "difficulty": question.get("difficulty", ""),
                    "layer": question.get("layer", ""),
                    "followups": question.get("followups", []),
                    "expected_points": question.get("expected_points", []),
                    "selection_reasons": item.get("reasons", []),
                },
            )
        )
    return items


def build_algorithm_items(selection: dict[str, Any], count: int, mode_profile: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    algorithms = list(selection.get("selected_algorithms") or [])
    algorithm_policy = str(mode_profile.get("selection_policy", {}).get("algorithm_policy", "balanced"))
    if algorithm_policy == "dense":
        algorithms.sort(key=lambda item: (-float(item.get("score", 0)), item.get("question", {}).get("difficulty", "")))
    for item in algorithms[:count]:
        question = item.get("question", {})
        statement = str(question.get("problem_statement_text") or question.get("prompt") or "").strip()
        prompt_block = statement or str(question.get("prompt", "")).strip() or f"请直接实现算法题《{str(question.get('title', '')).strip()}》。"
        items.append(
            question_plan_item(
                "CODING_INTERVIEW",
                str(question.get("id", "")),
                str(question.get("title", "")).strip(),
                metadata={
                    "kind": "algorithm",
                    "title_en": question.get("title_en", ""),
                    "difficulty": question.get("difficulty", ""),
                    "tags": question.get("tags", []),
                    "selection_reasons": item.get("reasons", []),
                    "public_release_mode": question.get("public_release_mode", ""),
                },
                prompt_block=prompt_block,
            )
        )
    return items


def build_question_plan(profile: dict[str, Any] | None, selection: dict[str, Any] | None, config: dict[str, Any]) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    mode = normalize_mode(config.get("mode"))
    layer = normalize_strength_to_layer(config.get("strength"))
    mode_profiles = load_mode_profiles()
    mode_profile = get_mode_profile(mode, mode_profiles)
    stage_sequence = mode_stage_sequence(mode, mode_profiles)

    if mode == "复盘教练":
        return [], {}

    if not profile and "PROJECT_DEEP_DIVE" in stage_sequence:
        stage_sequence = [stage for stage in stage_sequence if stage != "PROJECT_DEEP_DIVE"]

    plan: dict[str, list[dict[str, Any]]] = {}
    if "SELF_INTRO" in stage_sequence and mode_profile.get("selection_policy", {}).get("include_self_intro", True):
        plan["SELF_INTRO"] = build_self_intro_items(config)
    if "PROJECT_DEEP_DIVE" in stage_sequence:
        plan["PROJECT_DEEP_DIVE"] = build_project_items(
            profile or {},
            layer,
            mode_profile,
            (selection or {}).get("jd_context") or config.get("jd_context") or {},
        )
    if "CS_FUNDAMENTALS" in stage_sequence:
        plan["CS_FUNDAMENTALS"] = build_fundamental_items(selection or {}, layer, mode_profile)
    if "CODING_INTERVIEW" in stage_sequence:
        algorithm_count = int((selection or {}).get("config", {}).get("algorithms_count", 1) or 1)
        algorithm_required = bool(mode_profile.get("selection_policy", {}).get("algorithm_required", False))
        default_count = mode_stage_budget(mode_profile, "CODING_INTERVIEW", layer, algorithm_count)
        plan["CODING_INTERVIEW"] = build_algorithm_items(selection or {}, max(default_count, 1 if algorithm_required else 0), mode_profile)
    if "CANDIDATE_QUESTIONS" in stage_sequence:
        plan["CANDIDATE_QUESTIONS"] = build_candidate_question_items(layer, mode_profile)

    stage_sequence = [stage for stage in stage_sequence if plan.get(stage)]
    return stage_sequence, plan


def next_pending_stage(state: dict[str, Any]) -> str | None:
    for stage in state.get("stage_sequence", []):
        status = state.get("stage_status", {}).get(stage)
        if status in {"pending", "in_progress"}:
            return stage
    return None


def current_stage_remaining_items(state: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    completed = set(state.get("progress", {}).get("completed_question_ids", []))
    return [item for item in state.get("question_plan", {}).get(stage, []) if item.get("question_id") not in completed]


def update_current_question(state: dict[str, Any]) -> dict[str, Any] | None:
    stage = state.get("active_stage")
    if not stage:
        return None
    remaining = current_stage_remaining_items(state, stage)
    if not remaining:
        return None
    current = with_runtime_jd_context(remaining[0], state)
    state["current_question"] = current
    return current


def apply_pending_reconfiguration(session_dir: Path, state: dict[str, Any]) -> None:
    pending = state.get("pending_reconfiguration") or {}
    if not pending:
        return

    config = dict(state.get("config", {}))
    config.update(pending)
    state["config"] = config
    state["pending_reconfiguration"] = {}

    profile = load_json(Path(state["artifacts"]["candidate_profile_json"])) if state["artifacts"].get("candidate_profile_json") else None
    selection = generate_selection_for_session(session_dir, state, profile)
    stage_sequence, plan = build_question_plan(profile, selection, config)

    completed_stages = {stage for stage, status in state.get("stage_status", {}).items() if status == "completed"}
    new_stage_sequence = []
    for stage in stage_sequence:
        if stage in completed_stages:
            new_stage_sequence.append(stage)
        else:
            new_stage_sequence.append(stage)
    state["stage_sequence"] = new_stage_sequence
    state["question_plan"] = plan
    state["stage_status"] = {
        stage: ("completed" if stage in completed_stages else "pending") for stage in new_stage_sequence
    }
    state["active_stage"] = next_pending_stage(state)
    if state["active_stage"]:
        state["stage_status"][state["active_stage"]] = "in_progress"
        update_current_question(state)
    else:
        state["current_question"] = None


def generate_selection_for_session(session_dir: Path, state: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    config = state.get("config", {})
    data_dir = Path(state.get("data_dir", DEFAULT_DATA_DIR)).resolve()
    fundamental_bank = load_selection_json(data_dir / "fundamental_questions.json")
    algorithm_bank = load_selection_json(data_dir / "algorithm_questions.json")
    knowledge_base = safe_load_json(Path(state.get("knowledge_base", DEFAULT_KNOWLEDGE_BASE)).resolve())
    role_profiles = load_role_profiles(Path(state.get("role_profiles", DEFAULT_ROLE_PROFILES)).resolve())

    selection = select_questions(
        profile or {},
        jd_text=str(config.get("jd_text", "") or ""),
        focus_terms=config.get("focus", []) or [],
        level=str(config.get("level", DEFAULT_CONFIG["level"])),
        mode=str(config.get("mode", DEFAULT_CONFIG["mode"])),
        strength=str(config.get("strength", DEFAULT_CONFIG["strength"])),
        fundamental_layer=None,
        target_roles=parse_target_roles(config.get("role"), role_profiles),
        role_profiles=role_profiles,
        fundamental_bank=fundamental_bank,
        algorithm_bank=algorithm_bank,
        knowledge_base=knowledge_base,
        fundamentals_count=int(config.get("fundamentals_count", 5) or 5),
        algorithms_count=int(config.get("algorithms_count", 2) or 2),
    )
    selection = finalize_selection(selection)
    output_dir = session_dir / "question_selection"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "question_selection.json"
    root_json_path = session_dir / "question_selection.json"
    default_md_path = output_dir / "question_selection.md"
    write_json(json_path, selection)
    write_json(root_json_path, selection)
    write_text(default_md_path, render_question_selection_md(selection, "interview_mode"))
    write_text(output_dir / "question_selection_interview_mode.md", render_question_selection_md(selection, "interview_mode"))
    write_text(output_dir / "question_selection_candidate_mode.md", render_question_selection_md(selection, "candidate_mode"))
    state["artifacts"]["question_selection_json"] = str(json_path)
    state["artifacts"]["question_selection_json_root"] = str(root_json_path)
    state["artifacts"]["question_selection_md"] = str(default_md_path)
    state["selection_summary"] = {
        "role": config.get("role", ""),
        "strength": config.get("strength", DEFAULT_CONFIG["strength"]),
        "mode": config.get("mode", DEFAULT_CONFIG["mode"]),
        "focus": config.get("focus", []) or [],
        "jd_context": config.get("jd_context", {}),
        "inferred_roles": selection.get("keyword_summary", {}).get("inferred_roles", []),
        "priority_roles": selection.get("keyword_summary", {}).get("priority_roles", []),
        "expanded_priority_roles": selection.get("keyword_summary", {}).get("expanded_priority_roles", []),
        "role_bias_explained": bool(config.get("role")),
    }
    return selection


def bootstrap_state(
    session_dir: Path,
    profile: dict[str, Any] | None,
    profile_outputs: dict[str, str] | None,
    transcript_seed: dict[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    stage_sequence = []
    status = "INIT"
    artifacts = {
        "candidate_profile_json": profile_outputs.get("profile_json", "") if profile_outputs else (args.profile_json or ""),
        "question_selection_json": "",
        "question_selection_json_root": "",
        "transcript_json": str(transcript_path(session_dir)),
        "score_snapshot_json": "",
        "score_snapshot_md": "",
        "evaluation_json": "",
        "evaluation_md": "",
    }

    if profile:
        status = "RESUME_PARSED"

    transcript = transcript_seed or transcript_skeleton(config, session_dir, profile, None)
    save_transcript(session_dir, transcript)

    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": uuid4().hex[:12],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "runtime_status": status,
        "active_stage": None,
        "stage_sequence": stage_sequence,
        "stage_status": {},
        "config": config,
        "artifacts": artifacts,
        "selection_summary": {},
        "question_plan": {},
        "current_question": None,
        "progress": {
            "question_counts": {},
            "completed_question_ids": [],
            "hints_used_total": 0,
            "skipped_total": 0,
        },
        "pending_reconfiguration": {},
        "command_history": [],
        "data_dir": str(Path(args.data_dir).resolve()),
        "knowledge_base": str(Path(args.knowledge_base).resolve()),
        "role_profiles": str(Path(args.role_profiles).resolve()),
    }


def ensure_runtime(state: dict[str, Any], allowed: set[str], command: str) -> None:
    runtime_status = state.get("runtime_status")
    if runtime_status not in allowed:
        raise ValueError(f"`{command}` 当前不能在状态 {runtime_status} 下执行")


def infer_next_quality(score: int, skipped: bool) -> str:
    if skipped:
        return "wrong"
    if score >= 4:
        return "strong"
    if score >= 3:
        return "partial"
    if score >= 1:
        return "weak"
    return "wrong"


def build_replay_transcript(transcript_json: str, session_dir: Path) -> dict[str, Any]:
    transcript = load_json(Path(transcript_json).resolve())
    transcript.setdefault("session", {})
    transcript["session"]["session_dir"] = str(session_dir)
    return transcript


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    sessions_root = default_sessions_root(args.sessions_root)
    session_dir = create_session_dir(sessions_root, args.session_name, args.resume, args.profile_json, args.transcript_json)

    profile = None
    profile_outputs = None
    transcript_seed = None

    if args.profile_json:
        profile = load_json(Path(args.profile_json).resolve())
    elif args.resume:
        profile_output_dir = session_dir / "resume_parsed"
        profile, profile_outputs = parse_resume_to_profile(
            args.resume,
            output_dir=profile_output_dir,
            pdf_converter=args.pdf_converter,
            mineru_api_base=args.mineru_api_base,
            mineru_page_range=args.mineru_page_range,
            mineru_enable_table=args.mineru_enable_table,
            mineru_enable_formula=args.mineru_enable_formula,
            mineru_ocr=args.mineru_ocr,
            mineru_timeout=args.mineru_timeout,
            mineru_poll_interval=args.mineru_poll_interval,
            mineru_backend=args.mineru_backend,
            mineru_method=args.mineru_method,
            mineru_lang=args.mineru_lang,
        )

    if args.transcript_json:
        transcript_seed = build_replay_transcript(args.transcript_json, session_dir)

    state = bootstrap_state(session_dir, profile, profile_outputs, transcript_seed, args)
    append_command_history(state, "init", {"resume": args.resume or "", "profile_json": args.profile_json or "", "transcript_json": args.transcript_json or ""})
    save_session_state(session_dir, state)

    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "outputs": state["artifacts"],
    })


def command_configure(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)

    config_patch: dict[str, Any] = {}
    if args.role is not None:
        config_patch["role"] = args.role.strip()
    if args.strength is not None:
        config_patch["strength"] = args.strength.strip()
    if args.tone is not None:
        config_patch["tone"] = args.tone.strip()
    if args.level is not None:
        config_patch["level"] = args.level.strip()
    if args.mode is not None:
        config_patch["mode"] = normalize_mode(args.mode)
    if args.focus is not None:
        config_patch["focus"] = parse_focus(args.focus)
    if args.jd_text is not None:
        config_patch["jd_text"] = args.jd_text
    if args.jd_file:
        config_patch["jd_text"] = read_text(Path(args.jd_file).resolve())
    if args.view is not None:
        config_patch["view"] = args.view
    if args.fundamentals_count is not None:
        config_patch["fundamentals_count"] = args.fundamentals_count
    if args.algorithms_count is not None:
        config_patch["algorithms_count"] = args.algorithms_count

    if state["runtime_status"] in {"RUNNING", "PAUSED"} and args.defer_if_running:
        pending = state.setdefault("pending_reconfiguration", {})
        pending.update(config_patch)
        append_command_history(state, "configure_deferred", config_patch)
        save_session_state(session_dir, state)
        return enrich_response(state, {
            "ok": True,
            "session_dir": str(session_dir),
            "deferred": True,
            "pending_reconfiguration": pending,
        })

    config = dict(state.get("config", {}))
    config.update(config_patch)
    config["mode"] = normalize_mode(config.get("mode"))
    config["jd_context"] = summarize_jd_text(config.get("jd_text", ""))
    state["config"] = config

    profile = load_json(Path(state["artifacts"]["candidate_profile_json"])) if state["artifacts"].get("candidate_profile_json") else None
    if config["mode"] == "复盘教练":
        state["stage_sequence"] = []
        state["question_plan"] = {}
        state["stage_status"] = {}
        state["runtime_status"] = "CONFIG_READY"
        transcript = load_transcript(session_dir)
        transcript["session"].update(
            {
                "strength": config.get("strength"),
                "tone": config.get("tone"),
                "mode": config.get("mode"),
                "role": config.get("role"),
                "focus": config.get("focus", []),
                "jd_title": (config.get("jd_context", {}) or {}).get("title", ""),
                "jd_summary": (config.get("jd_context", {}) or {}).get("summary", ""),
            }
        )
        save_transcript(session_dir, transcript)
    else:
        selection = generate_selection_for_session(session_dir, state, profile)
        stage_sequence, plan = build_question_plan(profile, selection, config)
        state["stage_sequence"] = stage_sequence
        state["question_plan"] = plan
        state["stage_status"] = new_stage_status(stage_sequence)
        state["runtime_status"] = "CONFIG_READY"
        transcript = load_transcript(session_dir)
        transcript["session"].update(
            {
                "strength": config.get("strength"),
                "tone": config.get("tone"),
                "mode": config.get("mode"),
                "role": config.get("role"),
                "focus": config.get("focus", []),
                "jd_title": (config.get("jd_context", {}) or {}).get("title", ""),
                "jd_summary": (config.get("jd_context", {}) or {}).get("summary", ""),
                "selection_json_path": state["artifacts"].get("question_selection_json", ""),
            }
        )
        save_transcript(session_dir, transcript)

    brief_path = write_session_brief(session_dir, state)
    state["artifacts"]["session_brief_md"] = str(brief_path)
    append_command_history(state, "configure", config_patch)
    save_session_state(session_dir, state)
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "config": state["config"],
        "stage_sequence": state.get("stage_sequence", []),
    })


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    runtime_status = state.get("runtime_status")

    if runtime_status == "RUNNING":
        current = state.get("current_question") or {}
        return enrich_response(state, {
            "ok": True,
            "session_dir": str(session_dir),
            "runtime_status": runtime_status,
            "current_question": summarize_question(current),
        })
    if runtime_status == "PAUSED":
        raise ValueError("当前会话已暂停，请使用 `/continue` 恢复。")
    if runtime_status == "DONE":
        raise ValueError("当前会话已经结束，请先 `/reset` 后再重新开始。")
    if runtime_status not in {"CONFIG_READY", "RESUME_PARSED", "INIT"}:
        raise ValueError(f"当前状态 {runtime_status} 不能启动。")
    if runtime_status != "CONFIG_READY":
        raise ValueError("请先完成 `/configure` 再启动面试。")

    if state["config"]["mode"] == "复盘教练":
        state["runtime_status"] = "REPORT_GENERATION"
        append_command_history(state, "start", {"mode": state['config']['mode']})
        save_session_state(session_dir, state)
        return {
            "ok": True,
            "session_dir": str(session_dir),
            "runtime_status": state["runtime_status"],
            "message": "复盘教练模式已准备好，直接执行 `/report` 生成复盘。",
        }

    active_stage = next_pending_stage(state)
    if not active_stage:
        raise ValueError("当前没有可执行的阶段，请检查 question_plan。")
    state["active_stage"] = active_stage
    state["stage_status"][active_stage] = "in_progress"
    current = update_current_question(state)
    state["runtime_status"] = "RUNNING"
    append_command_history(state, "start", {"active_stage": active_stage})
    save_session_state(session_dir, state)
    jd_context = state.get("config", {}).get("jd_context", {}) or {}
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "active_stage": active_stage,
        "current_question": summarize_question(current or {}),
        "jd_context": jd_context,
        "opening_guidance": (
            f"已按该 JD 建立面试偏置：{jd_context.get('summary')}"
            if jd_context.get("summary")
            else "当前未提供 JD，本场面试会更多依赖简历和 /role 推断。"
        ),
    })


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state.get("runtime_status"),
        "active_stage": state.get("active_stage"),
        "current_question": summarize_question(state.get("current_question") or {}),
        "pending_reconfiguration": state.get("pending_reconfiguration", {}),
        "progress": state.get("progress", {}),
        "jd_context": state.get("config", {}).get("jd_context", {}) or {},
        "artifacts": state.get("artifacts", {}),
    })


def command_jd(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    jd_text = args.jd_text if args.jd_text is not None else ""
    if args.jd_file:
        jd_text = read_text(Path(args.jd_file).resolve())

    configure_args = argparse.Namespace(
        session_dir=str(session_dir),
        role=None,
        strength=None,
        tone=None,
        level=None,
        mode=None,
        focus=None,
        jd_text=jd_text,
        jd_file=None,
        view=None,
        fundamentals_count=None,
        algorithms_count=None,
        defer_if_running=bool(getattr(args, "defer_if_running", True)),
    )
    result = command_configure(configure_args)
    refreshed_state = load_session_state(session_dir)
    jd_context = refreshed_state.get("config", {}).get("jd_context", {}) or {}
    result["jd_context"] = jd_context
    result["message"] = (
        f"JD 已更新，后续面试将按这个岗位语境追问：{jd_context.get('summary')}"
        if jd_context.get("summary")
        else "JD 已清空，后续面试将回退为以简历和 /role 为主。"
    )
    return result


def command_next(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    ensure_runtime(state, {"RUNNING", "PAUSED"}, "next")

    if state["runtime_status"] == "PAUSED":
        raise ValueError("当前会话已暂停，请先 `/continue`。")

    current = state.get("current_question")
    if not current:
        active_stage = state.get("active_stage") or next_pending_stage(state)
        state["active_stage"] = active_stage
        if not active_stage:
            state["runtime_status"] = "REPORT_GENERATION"
            save_session_state(session_dir, state)
            return {
                "ok": True,
                "session_dir": str(session_dir),
                "runtime_status": state["runtime_status"],
                "message": "所有问答阶段都完成了，可以执行 `/report`。",
            }
        state["stage_status"][active_stage] = "in_progress"
        current = update_current_question(state)
        save_session_state(session_dir, state)

    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "active_stage": state.get("active_stage"),
        "current_question": summarize_question(current or {}),
        "prompt_block": (current or {}).get("prompt_block", ""),
    })


def command_hint(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    ensure_runtime(state, {"RUNNING"}, "hint")
    current = state.get("current_question")
    if not current:
        raise ValueError("当前没有活动题目，无法提供提示。")

    current["hint_level"] = int(current.get("hint_level", 0) or 0) + 1
    state["current_question"] = current
    state["progress"]["hints_used_total"] = int(state["progress"].get("hints_used_total", 0) or 0) + 1
    append_command_history(state, "hint", {"question_id": current.get("question_id"), "hint_level": current["hint_level"]})
    save_session_state(session_dir, state)

    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "question_id": current.get("question_id"),
        "hint_level": current["hint_level"],
    })


def command_repeat(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    current = state.get("current_question")
    if not current:
        raise ValueError("当前没有活动题目。")
    append_command_history(state, "repeat", {"question_id": current.get("question_id")})
    save_session_state(session_dir, state)
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "current_question": summarize_question(current),
        "prompt_block": current.get("prompt_block", ""),
    })


def command_explain(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    current = state.get("current_question")
    if not current:
        raise ValueError("当前没有活动题目。")
    append_command_history(state, "explain", {"question_id": current.get("question_id")})
    save_session_state(session_dir, state)
    metadata = current.get("metadata", {})
    explanation = metadata.get("topic") or metadata.get("kind") or current.get("question_text")
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "question_id": current.get("question_id"),
        "explanation": explanation,
    })


def advance_after_record(session_dir: Path, state: dict[str, Any]) -> None:
    current_stage = state.get("active_stage")
    if not current_stage:
        return

    remaining = current_stage_remaining_items(state, current_stage)
    if remaining:
        state["current_question"] = dict(remaining[0])
        state["current_question"]["hint_level"] = 0
        return

    state["stage_status"][current_stage] = "completed"
    apply_pending_reconfiguration(session_dir, state)
    next_stage = next_pending_stage(state)
    if not next_stage:
        state["active_stage"] = None
        state["current_question"] = None
        state["runtime_status"] = "REPORT_GENERATION"
        return
    state["active_stage"] = next_stage
    state["stage_status"][next_stage] = "in_progress"
    state["current_question"] = None
    update_current_question(state)


def command_record_answer(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    ensure_runtime(state, {"RUNNING"}, "record-answer")
    current = state.get("current_question")
    if not current:
        raise ValueError("当前没有活动题目。")

    quality = (args.quality or "").strip().lower()
    if quality not in VALID_QUALITIES:
        raise ValueError(f"quality 必须是 {sorted(VALID_QUALITIES)} 之一。")

    transcript = load_transcript(session_dir)
    hints_used = int(args.hints_used) if args.hints_used is not None else int(current.get("hint_level", 0) or 0)
    skipped = bool(args.skipped)
    score = int(args.score) if args.score is not None else (0 if skipped else {"strong": 4, "partial": 3, "weak": 2, "wrong": 1}[quality])
    issues = parse_focus(args.issues) if args.issues else []
    strengths = parse_focus(args.strengths) if args.strengths else []
    if skipped and "跳过问题" not in issues:
        issues.append("跳过问题")

    answer = {
        "stage": current.get("stage"),
        "question_id": current.get("question_id"),
        "question_text": current.get("question_text"),
        "quality": quality,
        "score": score,
        "strengths": strengths,
        "issues": issues,
        "candidate_answer_summary": args.answer_summary or "",
        "interviewer_feedback": args.feedback or "",
        "hints_used": hints_used,
        "skipped": skipped,
    }
    if getattr(args, "answer_text", None):
        answer["candidate_answer_text"] = args.answer_text
    if getattr(args, "judge_source", None):
        answer["judge_source"] = args.judge_source
    if getattr(args, "judge_confidence", None) is not None:
        answer["judge_confidence"] = args.judge_confidence
    if args.duration_seconds is not None:
        answer["duration_seconds"] = args.duration_seconds

    transcript.setdefault("answers", []).append(answer)
    save_transcript(session_dir, transcript)

    progress = state.setdefault("progress", {})
    completed = progress.setdefault("completed_question_ids", [])
    completed.append(current.get("question_id"))
    counts = progress.setdefault("question_counts", {})
    counts[current.get("stage")] = int(counts.get(current.get("stage"), 0) or 0) + 1
    if skipped:
        progress["skipped_total"] = int(progress.get("skipped_total", 0) or 0) + 1

    append_command_history(
        state,
        "record-answer",
        {
            "question_id": current.get("question_id"),
            "quality": quality,
            "score": score,
            "skipped": skipped,
        },
    )
    advance_after_record(session_dir, state)
    save_session_state(session_dir, state)

    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "recorded": {
            "question_id": answer["question_id"],
            "stage": answer["stage"],
            "quality": answer["quality"],
            "score": answer["score"],
        },
        "runtime_status": state["runtime_status"],
        "next_question": summarize_question(state.get("current_question") or {}),
        "next_stage": state.get("active_stage"),
    })


def record_answer_from_dict(session_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    args = argparse.Namespace(
        session_dir=str(session_dir),
        quality=payload.get("quality"),
        score=payload.get("score"),
        strengths=",".join(payload.get("strengths", [])) if payload.get("strengths") else None,
        issues=",".join(payload.get("issues", [])) if payload.get("issues") else None,
        answer_summary=payload.get("answer_summary"),
        feedback=payload.get("feedback"),
        duration_seconds=payload.get("duration_seconds"),
        hints_used=payload.get("hints_used"),
        skipped=bool(payload.get("skipped", False)),
        answer_text=payload.get("answer_text"),
        judge_source=payload.get("judge_source"),
        judge_confidence=payload.get("judge_confidence"),
    )
    return command_record_answer(args)


def command_skip(args: argparse.Namespace) -> dict[str, Any]:
    args.quality = "wrong"
    args.score = 0
    args.skipped = True
    if not args.feedback:
        args.feedback = "候选人选择跳过当前问题。"
    return command_record_answer(args)


def command_pause(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    ensure_runtime(state, {"RUNNING"}, "pause")
    state["runtime_status"] = "PAUSED"
    append_command_history(state, "pause")
    save_session_state(session_dir, state)
    return enrich_response(state, {"ok": True, "session_dir": str(session_dir), "runtime_status": state["runtime_status"]})


def command_continue(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    ensure_runtime(state, {"PAUSED"}, "continue")
    state["runtime_status"] = "RUNNING"
    append_command_history(state, "continue")
    save_session_state(session_dir, state)
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "current_question": summarize_question(state.get("current_question") or {}),
    })


def command_score(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    transcript = load_transcript(session_dir)
    profile = load_json(Path(state["artifacts"]["candidate_profile_json"])) if state["artifacts"].get("candidate_profile_json") else None
    selection = load_json(Path(state["artifacts"]["question_selection_json"])) if state["artifacts"].get("question_selection_json") else None

    answers = transcript.get("answers", []) or []
    result = (
        evaluate_transcript(transcript, profile=profile, selection=selection)
        if answers
        else empty_score_result("当前还没有可评分的作答记录。")
    )
    json_path, md_path = write_score_snapshot(session_dir, result)
    state["artifacts"]["score_snapshot_json"] = str(json_path)
    state["artifacts"]["score_snapshot_md"] = str(md_path)
    append_command_history(state, "score")
    save_session_state(session_dir, state)
    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "outputs": {
            "score_snapshot_json": str(json_path),
            "score_snapshot_md": str(md_path),
        },
        "overall_score": result.get("overall_conclusion", {}).get("total_score", result.get("overall_conclusion", {}).get("score")),
    })


def command_report(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    transcript = load_transcript(session_dir)
    if not (transcript.get("answers", []) or []):
        raise ValueError("当前还没有作答记录，暂时不能生成复盘报告。")
    profile = load_json(Path(state["artifacts"]["candidate_profile_json"])) if state["artifacts"].get("candidate_profile_json") else None
    selection = load_json(Path(state["artifacts"]["question_selection_json"])) if state["artifacts"].get("question_selection_json") else None

    state["runtime_status"] = "REPORT_GENERATION"
    save_session_state(session_dir, state)

    result = evaluate_transcript(transcript, profile=profile, selection=selection)
    json_path, md_path = write_final_report(session_dir, result)
    state["artifacts"]["evaluation_json"] = str(json_path)
    state["artifacts"]["evaluation_md"] = str(md_path)
    state["runtime_status"] = "DONE"
    append_command_history(state, "report")
    save_session_state(session_dir, state)

    return enrich_response(state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": state["runtime_status"],
        "outputs": {
            "evaluation_json": str(json_path),
            "evaluation_md": str(md_path),
        },
    })


def command_reset(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).resolve()
    state = load_session_state(session_dir)
    archive_dir = session_dir / f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    archive_dir.mkdir(parents=True, exist_ok=False)

    for name in (
        "session_state.json",
        "session_brief.md",
        "transcript.json",
        "question_selection.json",
        "score_snapshot.json",
        "score_snapshot.md",
        "interview_evaluation.json",
        "interview_evaluation.md",
    ):
        path = session_dir / name
        if path.exists():
            shutil.move(str(path), str(archive_dir / name))

    question_selection_dir = session_dir / "question_selection"
    if question_selection_dir.exists():
        shutil.move(str(question_selection_dir), str(archive_dir / "question_selection"))

    artifacts = state.get("artifacts", {})
    transcript = transcript_skeleton(state.get("config", {}), session_dir, None, None)
    save_transcript(session_dir, transcript)
    reset_state = {
        **state,
        "runtime_status": "INIT",
        "active_stage": None,
        "stage_sequence": [],
        "stage_status": {},
        "question_plan": {},
        "current_question": None,
        "progress": {
            "question_counts": {},
            "completed_question_ids": [],
            "hints_used_total": 0,
            "skipped_total": 0,
        },
        "pending_reconfiguration": {},
        "artifacts": {
            **artifacts,
            "question_selection_json": "",
            "question_selection_json_root": "",
            "session_brief_md": "",
            "score_snapshot_json": "",
            "score_snapshot_md": "",
            "evaluation_json": "",
            "evaluation_md": "",
            "transcript_json": str(transcript_path(session_dir)),
        },
        "selection_summary": {},
    }
    append_command_history(reset_state, "reset", {"archive_dir": str(archive_dir)})
    save_session_state(session_dir, reset_state)

    return enrich_response(reset_state, {
        "ok": True,
        "session_dir": str(session_dir),
        "runtime_status": reset_state["runtime_status"],
        "archive_dir": str(archive_dir),
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a local CS interview session state machine.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Question bank data directory.")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE), help="Knowledge base JSON path.")
    parser.add_argument("--role-profiles", default=str(DEFAULT_ROLE_PROFILES), help="Role profile JSON path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new interview session.")
    init_parser.add_argument("--resume", help="Path or URL to a resume file.")
    init_parser.add_argument("--profile-json", help="Existing candidate_profile.json.")
    init_parser.add_argument("--transcript-json", help="Existing transcript.json for 复盘教练 mode.")
    init_parser.add_argument("--session-name", help="Optional session name prefix.")
    init_parser.add_argument("--sessions-root", help="Directory that stores session folders.")
    init_parser.add_argument("--pdf-converter", choices=["api", "cli", "auto"], default="api")
    init_parser.add_argument("--mineru-api-base")
    init_parser.add_argument("--mineru-page-range")
    init_parser.add_argument("--mineru-enable-table", action=argparse.BooleanOptionalAction, default=True)
    init_parser.add_argument("--mineru-enable-formula", action=argparse.BooleanOptionalAction, default=True)
    init_parser.add_argument("--mineru-ocr", action="store_true")
    init_parser.add_argument("--mineru-timeout", type=int, default=300)
    init_parser.add_argument("--mineru-poll-interval", type=float, default=3.0)
    init_parser.add_argument("--mineru-backend", default="pipeline")
    init_parser.add_argument("--mineru-method", default="auto")
    init_parser.add_argument("--mineru-lang", default="ch")

    configure_parser = subparsers.add_parser("configure", help="Set or update session config and question plan.")
    configure_parser.add_argument("session_dir")
    configure_parser.add_argument("--role")
    configure_parser.add_argument("--strength")
    configure_parser.add_argument("--tone")
    configure_parser.add_argument("--level")
    configure_parser.add_argument("--mode")
    configure_parser.add_argument("--focus")
    configure_parser.add_argument("--jd-text")
    configure_parser.add_argument("--jd-file")
    configure_parser.add_argument("--view", choices=["interview_mode", "candidate_mode"])
    configure_parser.add_argument("--fundamentals-count", type=int)
    configure_parser.add_argument("--algorithms-count", type=int)
    configure_parser.add_argument("--defer-if-running", action="store_true", default=True)

    jd_parser = subparsers.add_parser("jd", help="Set or update JD context for this session.")
    jd_parser.add_argument("session_dir")
    jd_parser.add_argument("--jd-text")
    jd_parser.add_argument("--jd-file")
    jd_parser.add_argument("--defer-if-running", action="store_true", default=True)

    for name, help_text in (
        ("start", "Start the configured interview."),
        ("status", "Show current session status."),
        ("next", "Show the current or next question."),
        ("hint", "Increase hint level for the current question."),
        ("repeat", "Repeat the current question."),
        ("explain", "Explain the current question without ending it."),
        ("pause", "Pause the running interview."),
        ("continue", "Resume a paused interview."),
        ("score", "Generate a mid-session score snapshot."),
        ("report", "Finish the interview and generate the final report."),
        ("reset", "Archive current artifacts and reset the session."),
    ):
        cmd = subparsers.add_parser(name, help=help_text)
        cmd.add_argument("session_dir")

    record_parser = subparsers.add_parser("record-answer", help="Record a scored answer for the current question.")
    record_parser.add_argument("session_dir")
    record_parser.add_argument("--quality", required=True, choices=sorted(VALID_QUALITIES))
    record_parser.add_argument("--score", type=int)
    record_parser.add_argument("--strengths", help="Comma-separated evidence strengths.")
    record_parser.add_argument("--issues", help="Comma-separated concrete issues.")
    record_parser.add_argument("--answer-summary")
    record_parser.add_argument("--feedback")
    record_parser.add_argument("--duration-seconds", type=int)
    record_parser.add_argument("--hints-used", type=int)
    record_parser.add_argument("--skipped", action="store_true")

    skip_parser = subparsers.add_parser("skip", help="Skip the current question and move on.")
    skip_parser.add_argument("session_dir")
    skip_parser.add_argument("--feedback")

    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    handlers = {
        "init": command_init,
        "configure": command_configure,
        "jd": command_jd,
        "start": command_start,
        "status": command_status,
        "next": command_next,
        "hint": command_hint,
        "repeat": command_repeat,
        "explain": command_explain,
        "record-answer": command_record_answer,
        "skip": command_skip,
        "pause": command_pause,
        "continue": command_continue,
        "score": command_score,
        "report": command_report,
        "reset": command_reset,
    }
    return handlers[args.command](args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv or sys.argv[1:])
    try:
        result = dispatch(args)
    except Exception as exc:
        state = None
        session_dir = getattr(args, "session_dir", None)
        if session_dir:
            try:
                state = load_session_state(Path(session_dir).resolve())
            except Exception:
                state = None
        error_payload = error_response(state, str(exc)) if state else {"ok": False, "error": str(exc)}
        print(json.dumps(error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
