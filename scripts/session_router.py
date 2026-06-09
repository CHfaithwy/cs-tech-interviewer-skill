"""Route natural Chinese interview messages to session controller actions.

This layer handles two classes of messages:

1. control intent: start / pause / continue / hint / skip / score / report / reconfigure
2. candidate answer: build a judgement prompt for the current LLM

Candidate-answer scoring is intentionally model-led. The router does not call a
separate model endpoint or require an API key; it returns the prompt/context that
the current LLM should use, then `apply_llm_answer_judgement.py` persists the
model's JSON judgement.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import interview_session as controller


ROLE_VALUES = {
    "backend-java",
    "backend-python",
    "backend-go",
    "ai-agent",
    "ai-rag",
    "ai-eval",
    "sre-platform",
    "data",
}

MODE_VALUES = {
    "完整模拟",
    "项目深挖",
    "八股快问快答",
    "算法陪练",
    "JD 定向面",
    "简历拷打",
    "复盘教练",
}

STRENGTH_VALUES = {"夯", "顶级", "人上人", "NPC", "拉完了"}
TONE_VALUES = {"温和", "默认", "铁面"}
LEVEL_VALUES = {"简单", "中等", "困难"}
CONFIG_INTENT_HINTS = [
    "改成",
    "改为",
    "切到",
    "切换到",
    "换成",
    "设置",
    "设为",
    "后面改成",
    "后面改为",
    "后续改成",
    "后续改为",
    "重点考",
    "重点放在",
    "侧重",
    "偏向",
    "/role",
    "/mode",
    "/focus",
    "/strength",
    "/tone",
    "/level",
    "/jd",
]

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SEMANTIC_PROMPT_PATH = SKILL_DIR / "references" / "semantic-judge-prompt.md"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_semantic_prompt_template() -> str:
    text = read_text(SEMANTIC_PROMPT_PATH)
    marker = "## Prompt Template"
    start = text.find(marker)
    if start < 0:
        raise ValueError("semantic judge prompt template not found")
    fence_start = text.find("```text", start)
    fence_end = text.find("```", fence_start + len("```text"))
    if fence_start < 0 or fence_end < 0:
        raise ValueError("semantic judge prompt code block not found")
    return text[fence_start + len("```text") : fence_end].strip()


def recent_transcript_context(session_dir: Path, limit: int = 5) -> list[dict[str, Any]]:
    try:
        transcript = controller.load_transcript(session_dir)
    except Exception:
        return []

    answers = transcript.get("answers", []) or []
    context: list[dict[str, Any]] = []
    for item in answers[-limit:]:
        context.append(
            {
                "stage": item.get("stage"),
                "question_id": item.get("question_id"),
                "question_text": item.get("question_text"),
                "quality": item.get("quality"),
                "score": item.get("score"),
                "answer_summary": item.get("candidate_answer_summary"),
                "issues": item.get("issues", []),
                "strengths": item.get("strengths", []),
            }
        )
    return context


def artifact_paths(state: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in (state.get("artifacts") or {}).items() if value}


def render_semantic_prompt(current: dict[str, Any], answer: str, state: dict[str, Any]) -> str:
    template = load_semantic_prompt_template()
    session_dir = Path(current.get("_session_dir", "")) if current.get("_session_dir") else None
    config = state.get("config", {}) or {}
    replacements = {
        "{{stage}}": str(current.get("stage", "")),
        "{{mode}}": str(config.get("mode", "")),
        "{{question_id}}": str(current.get("question_id", "")),
        "{{question_text}}": str(current.get("question_text", "")),
        "{{hint_level}}": str(current.get("hint_level", 0)),
        "{{question_metadata_json}}": json.dumps(current.get("metadata", {}), ensure_ascii=False, indent=2),
        "{{session_config_json}}": json.dumps(config, ensure_ascii=False, indent=2),
        "{{artifact_paths_json}}": json.dumps(artifact_paths(state), ensure_ascii=False, indent=2),
        "{{recent_transcript_json}}": json.dumps(
            recent_transcript_context(session_dir) if session_dir else [],
            ensure_ascii=False,
            indent=2,
        ),
        "{{candidate_answer}}": answer,
    }
    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def split_topics(text: str) -> list[str]:
    raw = text.strip().strip("。；;")
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[,，、/\s]+", raw) if item.strip()]


def first_match(message: str, values: set[str]) -> str | None:
    for value in sorted(values, key=len, reverse=True):
        if value in message:
            return value
    return None


def build_namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def has_configure_intent(message: str) -> bool:
    return any(hint in message for hint in CONFIG_INTENT_HINTS)


def looks_like_jd_payload(message: str) -> bool:
    text = normalize_text(message)
    if len(text) < 24:
        return False
    jd_markers = [
        "岗位职责", "岗位要求", "任职要求", "任职资格", "职位描述", "岗位描述",
        "岗位名称", "工作职责", "加分项", "职位要求", "招聘", "负责", "熟悉",
    ]
    hit_count = sum(1 for marker in jd_markers if marker in text)
    return hit_count >= 2


def configure_from_message(session_dir: Path, message: str) -> dict[str, Any] | None:
    config_patch: dict[str, Any] = {}

    if not has_configure_intent(message):
        return None

    role = first_match(message, ROLE_VALUES)
    if role:
        config_patch["role"] = role

    mode = first_match(message, MODE_VALUES)
    if mode:
        config_patch["mode"] = mode

    strength = first_match(message, STRENGTH_VALUES)
    if strength:
        config_patch["strength"] = strength

    tone = first_match(message, TONE_VALUES)
    if tone:
        config_patch["tone"] = tone

    level = first_match(message, LEVEL_VALUES)
    if level:
        config_patch["level"] = level

    focus_match = re.search(r"(?:focus|方向|重点|侧重|偏向)(?:考|问|一下|一些|为主)?[：:，, ]*(.+)$", message, flags=re.I)
    if focus_match:
        focus_values = split_topics(focus_match.group(1))
        if focus_values:
            config_patch["focus"] = focus_values

    jd_match = re.search(r"(?:jd|岗位描述|岗位要求)[：: ]+(.+)$", message, flags=re.I)
    if jd_match:
        config_patch["jd_text"] = jd_match.group(1).strip()

    if not config_patch:
        return None

    args = build_namespace(
        command="configure",
        session_dir=str(session_dir),
        role=config_patch.get("role"),
        strength=config_patch.get("strength"),
        tone=config_patch.get("tone"),
        level=config_patch.get("level"),
        mode=config_patch.get("mode"),
        focus=",".join(config_patch.get("focus", [])) if "focus" in config_patch else None,
        jd_text=config_patch.get("jd_text"),
        jd_file=None,
        view=None,
        fundamentals_count=None,
        algorithms_count=None,
        defer_if_running=True,
        data_dir=str(controller.DEFAULT_DATA_DIR),
        knowledge_base=str(controller.DEFAULT_KNOWLEDGE_BASE),
        role_profiles=str(controller.DEFAULT_ROLE_PROFILES),
    )
    return controller.command_configure(args)


def set_jd_from_message(session_dir: Path, message: str, defer_if_running: bool = True) -> dict[str, Any]:
    args = build_namespace(
        command="jd",
        session_dir=str(session_dir),
        jd_text=message.strip(),
        jd_file=None,
        defer_if_running=defer_if_running,
    )
    return controller.command_jd(args)


def build_llm_judge_request(session_dir: Path, answer: str) -> dict[str, Any]:
    state = controller.load_session_state(session_dir)
    current = state.get("current_question") or {}
    if not current:
        return {
            "ok": False,
            "route": "candidate_answer",
            "error": "当前没有活动题目，无法构造大模型判分请求。",
        }

    current["_session_dir"] = str(session_dir)
    prompt = render_semantic_prompt(current, answer, state)
    return {
        "ok": True,
        "route": "llm_judge_required",
        "message": "候选人自由回答已识别。请用 judgement_prompt 由当前大模型评分，再用 scripts/apply_llm_answer_judgement.py 写回 transcript。",
        "current_question": controller.summarize_question(current),
        "candidate_answer": answer,
        "judgement_prompt": prompt,
        "apply_command": "python cs-tech-interviewer/scripts/apply_llm_answer_judgement.py <session_dir> <judgement.json>",
    }


def route_message(session_dir: Path, message: str) -> dict[str, Any]:
    text = normalize_text(message)
    lower = text.lower()

    if re.search(r"^/jd\b", lower):
        jd_text = text[3:].strip()
        return set_jd_from_message(session_dir, jd_text)

    jd_inline_match = re.search(r"^(?:这是?我的?jd|这是?岗位描述|岗位要求如下|岗位描述如下|我先发jd|我先给你jd|给你jd|先看jd)[：:，, ]*(.+)$", text, flags=re.I)
    if jd_inline_match:
        return set_jd_from_message(session_dir, jd_inline_match.group(1).strip())

    if looks_like_jd_payload(text):
        return {
            "ok": True,
            "route": "jd_update",
            "result": set_jd_from_message(session_dir, text),
        }

    if re.search(r"^/(start|开始)$", lower) or any(phrase in text for phrase in ("开始吧", "开始面试", "直接开始", "开始模拟")):
        return controller.command_start(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(pause|暂停)$", lower) or "先暂停" in text or "暂停一下" in text:
        return controller.command_pause(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(continue|继续)$", lower) or "继续吧" in text or "恢复面试" in text or "接着来" in text:
        return controller.command_continue(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(hint|提示)$", lower) or "给个提示" in text or "提示一下" in text:
        return controller.command_hint(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(repeat|重复)$", lower) or "重复一下题目" in text or "再说一遍题目" in text:
        return controller.command_repeat(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(explain|解释)$", lower) or "解释一下题意" in text or "帮我解释一下" in text:
        return controller.command_explain(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(skip|跳过)$", lower) or "这题跳过" in text or "先跳过" in text:
        return controller.command_skip(build_namespace(session_dir=str(session_dir), feedback="候选人通过自然语言请求跳过当前问题。"))

    if re.search(r"^/(score|评分)$", lower) or "当前评分" in text or "先打个分" in text:
        return controller.command_score(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(report|复盘)$", lower) or "结束并复盘" in text or "生成复盘" in text or "结束面试" in text:
        return controller.command_report(build_namespace(session_dir=str(session_dir)))

    if re.search(r"^/(reset|重置)$", lower) or "重新开始一场" in text or "重置这场面试" in text:
        return controller.command_reset(build_namespace(session_dir=str(session_dir)))

    configured = configure_from_message(session_dir, text)
    if configured:
        return {
            "ok": True,
            "route": "configure",
            "result": configured,
        }

    return build_llm_judge_request(session_dir, text)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route natural Chinese interview messages to interview_session actions.")
    parser.add_argument("session_dir", help="Path to the live session directory.")
    parser.add_argument("message", nargs="?", help="Natural Chinese control message or candidate answer.")
    parser.add_argument("--message-file", help="Optional text file containing the message.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    session_dir = Path(args.session_dir).resolve()
    if args.message_file:
        message = read_text(Path(args.message_file).resolve()).strip()
    else:
        message = args.message or ""
    if not message:
        print(json.dumps({"ok": False, "error": "请提供一条自然语言消息。"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    try:
        result = route_message(session_dir, message)
    except Exception as exc:
        try:
            state = controller.load_session_state(session_dir)
            payload = controller.error_response(state, str(exc))
        except Exception:
            payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
