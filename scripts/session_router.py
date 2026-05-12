"""Route natural Chinese interview messages to session controller actions.

This layer handles two classes of messages:

1. control intent: start / pause / continue / hint / skip / score / report / reconfigure
2. candidate answer: heuristic judge first, optionally enhanced by an LLM semantic judge

The LLM layer is optional and must fail safe:

- if no model configuration is present, use heuristics only
- if LLM judging fails, fall back to heuristics only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
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

POSITIVE_DETAIL_HINTS = [
    "因为",
    "所以",
    "例如",
    "比如",
    "实现",
    "设计",
    "流程",
    "指标",
    "延迟",
    "吞吐",
    "一致性",
    "缓存",
    "降级",
    "重试",
    "幂等",
    "A/B",
    "压测",
    "top-k",
    "rerank",
    "Cypher",
    "Neo4j",
    "LangGraph",
    "GraphRAG",
    "双指针",
    "哈希",
    "堆",
    "动态规划",
    "复杂度",
]

VAGUE_PATTERNS = [
    "不太清楚",
    "不是很懂",
    "忘了",
    "没太想好",
    "大概",
    "差不多",
    "应该是",
    "可能是",
    "我不确定",
]

SELF_INTRO_ROLE_WORDS = [
    "岗位",
    "匹配",
    "后端",
    "ai",
    "agent",
    "rag",
    "项目",
    "技术栈",
    "经历",
]

CANDIDATE_QUESTION_GOOD_HINTS = [
    "团队",
    "评估",
    "上线",
    "协作",
    "稳定性",
    "技术栈",
    "标准",
    "流程",
]

QUALITY_TO_SCORE = {"strong": 4, "partial": 3, "weak": 2, "wrong": 1}
SCORE_TO_QUALITY = {5: "strong", 4: "strong", 3: "partial", 2: "weak", 1: "wrong"}
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SEMANTIC_PROMPT_PATH = SKILL_DIR / "references" / "semantic-judge-prompt.md"
MODE_PROFILES_PATH = SKILL_DIR / "data" / "interview_mode_profiles.json"


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


def load_mode_profiles() -> dict[str, Any]:
    if not MODE_PROFILES_PATH.exists():
        return {"profiles": {}}
    return json.loads(read_text(MODE_PROFILES_PATH))


def get_mode_profile(mode: str | None) -> dict[str, Any]:
    profiles = load_mode_profiles().get("profiles") or {}
    if mode and mode in profiles:
        return profiles[mode]
    return profiles.get("完整模拟", {})


def render_semantic_prompt(current: dict[str, Any], answer: str, heuristic: dict[str, Any]) -> str:
    template = load_semantic_prompt_template()
    mode = ""
    if current.get("_session_dir"):
        try:
            mode = str(controller.load_session_state(Path(current.get("_session_dir", ""))).get("config", {}).get("mode", ""))
        except Exception:
            mode = ""
    replacements = {
        "{{stage}}": str(current.get("stage", "")),
        "{{mode}}": mode,
        "{{question_id}}": str(current.get("question_id", "")),
        "{{question_text}}": str(current.get("question_text", "")),
        "{{hint_level}}": str(current.get("hint_level", 0)),
        "{{question_metadata_json}}": json.dumps(current.get("metadata", {}), ensure_ascii=False, indent=2),
        "{{candidate_answer}}": answer,
        "{{heuristic_judgement_json}}": json.dumps(
            {
                "quality": heuristic.get("quality"),
                "score": heuristic.get("score"),
                "strengths": heuristic.get("strengths", []),
                "issues": heuristic.get("issues", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
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


def contains_any(text: str, words: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for word in words if word.lower() in lowered)


def count_digits(text: str) -> int:
    return len(re.findall(r"\d", text))


def summarize_answer(text: str, limit: int = 120) -> str:
    short = text.strip().replace("\n", " ")
    return short if len(short) <= limit else short[:limit].rstrip() + "..."


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def finalize_judgement(score: int, strengths: list[str], issues: list[str], answer: str, feedback: str) -> dict[str, Any]:
    bounded_score = max(1, min(score, 5))
    quality = SCORE_TO_QUALITY.get(bounded_score, "partial")
    return {
        "quality": quality,
        "score": bounded_score,
        "strengths": unique_keep_order(strengths),
        "issues": unique_keep_order(issues),
        "answer_summary": summarize_answer(answer),
        "feedback": feedback,
        "judge_source": "heuristic",
        "judge_confidence": 0.55,
        "answer_text": answer,
    }


def judge_self_intro(answer: str) -> dict[str, Any]:
    score = 2
    strengths: list[str] = []
    issues: list[str] = []

    if len(answer) >= 40:
        score += 1
        strengths.append("有基本展开")
    else:
        issues.append("回答过短")

    role_hits = contains_any(answer, SELF_INTRO_ROLE_WORDS)
    if role_hits >= 3:
        score += 1
        strengths.append("包含岗位匹配信息")
    else:
        issues.append("岗位匹配点不够聚焦")

    if "项目" in answer and ("技术" in answer or "经历" in answer):
        score += 1
        strengths.append("内容结构较完整")

    if len(answer) > 220:
        score -= 1
        issues.append("回答略长")

    return finalize_judgement(score, strengths, issues, answer, "表达自然，但岗位关键词和个人亮点还可以再收束。")


def judge_project_answer(answer: str, metadata: dict[str, Any]) -> dict[str, Any]:
    score = 2
    strengths: list[str] = []
    issues: list[str] = []

    project_name = str(metadata.get("project", "")).strip()
    risk_area = str(metadata.get("risk_area", "")).strip()

    if len(answer) >= 50:
        score += 1
        strengths.append("有一定展开")
    else:
        issues.append("展开不足")

    detail_hits = contains_any(answer, POSITIVE_DETAIL_HINTS)
    if detail_hits >= 3:
        score += 1
        strengths.append("提到了实现细节或工程动作")
    else:
        issues.append("实现细节不够具体")

    if count_digits(answer) >= 2:
        score += 1
        strengths.append("有一定指标或量化信息")

    if contains_any(answer, VAGUE_PATTERNS) >= 1:
        score -= 1
        issues.append("表达偏模糊")

    if risk_area and risk_area != "个人职责边界" and detail_hits < 2:
        issues.append(f"{risk_area} 回答不够深入")

    feedback = f"和项目【{project_name or '当前项目'}】相关，但还可以把实现链路、取舍和指标讲得更扎实。"
    return finalize_judgement(score, strengths, issues, answer, feedback)


def judge_fundamental_answer(answer: str, metadata: dict[str, Any]) -> dict[str, Any]:
    score = 2
    strengths: list[str] = []
    issues: list[str] = []

    expected_points = [str(item) for item in metadata.get("expected_points", []) or []]
    expected_hits = 0
    for point in expected_points[:4]:
        keywords = [token for token in re.split(r"[，,、；;：:\s]+", point) if len(token) >= 2]
        if any(keyword.lower() in answer.lower() for keyword in keywords[:3]):
            expected_hits += 1

    if len(answer) >= 35:
        score += 1
        strengths.append("回答有基本展开")
    else:
        issues.append("回答偏短")

    if expected_hits >= 2:
        score += 1
        strengths.append("命中了关键知识点")
    else:
        issues.append("关键知识点覆盖不足")

    if contains_any(answer, POSITIVE_DETAIL_HINTS) >= 2:
        score += 1
        strengths.append("带了一些场景或工程细节")

    if contains_any(answer, VAGUE_PATTERNS) >= 1:
        score -= 1
        issues.append("结论有点虚")

    topic = metadata.get("topic", "")
    feedback = f"{topic} 方向基本相关，但可以再把原理、场景和边界讲完整。"
    return finalize_judgement(score, strengths, issues, answer, feedback)


def judge_algorithm_answer(answer: str, metadata: dict[str, Any], current_question: dict[str, Any]) -> dict[str, Any]:
    score = 2
    strengths: list[str] = []
    issues: list[str] = []

    tags = [str(tag) for tag in metadata.get("tags", []) or []]
    tag_hits = sum(1 for tag in tags if tag and tag.lower() in answer.lower())
    complexity_hits = contains_any(answer, ["复杂度", "O(", "时间", "空间"])
    testcase_hits = contains_any(answer, ["边界", "空数组", "重复", "测试", "样例", "奇数", "偶数"])

    if len(answer) >= 40:
        score += 1
        strengths.append("有基本解题展开")
    else:
        issues.append("解题说明偏短")

    if tag_hits >= 1 or contains_any(answer, POSITIVE_DETAIL_HINTS) >= 2:
        score += 1
        strengths.append("提到了核心思路或数据结构")
    else:
        issues.append("核心思路不够明确")

    if complexity_hits >= 1:
        score += 1
        strengths.append("有复杂度意识")
    else:
        issues.append("没有明确复杂度")

    if testcase_hits >= 1:
        strengths.append("考虑了测试或边界")

    if int(current_question.get("hint_level", 0) or 0) >= 2 and score > 1:
        score -= 1
        issues.append("依赖较多提示")

    feedback = "这道算法题方向基本对，但可以把核心思路、复杂度和边界条件说得更稳。"
    return finalize_judgement(score, strengths, issues, answer, feedback)


def judge_candidate_question(answer: str) -> dict[str, Any]:
    score = 2
    strengths: list[str] = []
    issues: list[str] = []

    if len(answer) >= 20:
        score += 1
        strengths.append("有明确反问")
    else:
        issues.append("反问过短")

    good_hits = contains_any(answer, CANDIDATE_QUESTION_GOOD_HINTS)
    if good_hits >= 2:
        score += 1
        strengths.append("反问和真实工作场景较相关")
    else:
        issues.append("反问还可以更具体")

    if "薪资" in answer or "假期" in answer:
        issues.append("更偏通用求职问题，技术相关性有限")

    return finalize_judgement(score, strengths, issues, answer, "方向相关，但还可以更具体、更有信息量。")


def apply_mode_bias(judged: dict[str, Any], current: dict[str, Any], mode: str | None) -> dict[str, Any]:
    biased = dict(judged)
    issues = list(biased.get("issues", []) or [])
    strengths = list(biased.get("strengths", []) or [])
    score = int(biased.get("score", 3))
    answer_text = str(biased.get("answer_text", ""))
    metadata = current.get("metadata", {}) or {}
    stage = current.get("stage")
    mode_profile = get_mode_profile(mode)
    judge_bias = mode_profile.get("auto_judge_bias", {}) or {}

    if mode == "项目深挖" or judge_bias.get("project_detail_weight") == "strict":
        if stage == "PROJECT_DEEP_DIVE":
            if count_digits(answer_text) < 2 and not any("指标" in item or "量化" in item for item in strengths):
                score = max(1, score - 1)
                issues.append("指标或量化信息不足")
            if contains_any(answer_text, ["负责", "独立", "模块", "接口", "链路"]) < 2:
                score = max(1, score - 1)
                issues.append("ownership 边界不够清楚")

    if mode == "八股快问快答" or judge_bias.get("fundamental_accuracy_weight") == "strict":
        if stage == "CS_FUNDAMENTALS":
            expected_points = [str(item) for item in metadata.get("expected_points", []) or []]
            expected_hits = 0
            for point in expected_points[:4]:
                keywords = [token for token in re.split(r"[，,、；;：:\s]+", point) if len(token) >= 2]
                if any(keyword.lower() in answer_text.lower() for keyword in keywords[:3]):
                    expected_hits += 1
            if expected_hits <= 1:
                score = max(1, score - 1)
                issues.append("关键知识点覆盖不足")

    if mode == "算法陪练" or judge_bias.get("algorithm_rigor_weight") == "strict":
        if stage == "CODING_INTERVIEW":
            if contains_any(answer_text, ["复杂度", "O(", "时间", "空间"]) < 1:
                score = max(1, score - 1)
                issues.append("复杂度没有讲清")
            if contains_any(answer_text, ["边界", "空数组", "重复", "样例", "奇数", "偶数"]) < 1:
                score = max(1, score - 1)
                issues.append("边界考虑不足")
            if int(current.get("hint_level", 0) or 0) >= 2:
                score = max(1, score - 1)
                issues.append("对提示依赖较高")

    score = max(1, min(score, 5))
    biased["score"] = score
    biased["quality"] = SCORE_TO_QUALITY.get(score, biased.get("quality", "partial"))
    biased["issues"] = unique_keep_order(issues)
    biased["strengths"] = unique_keep_order(strengths)
    return biased


def heuristic_judge_answer(answer: str, current: dict[str, Any]) -> dict[str, Any]:
    stage = current.get("stage")
    metadata = current.get("metadata", {})

    if stage == "SELF_INTRO":
        judged = judge_self_intro(answer)
    elif stage == "PROJECT_DEEP_DIVE":
        judged = judge_project_answer(answer, metadata)
    elif stage == "CS_FUNDAMENTALS":
        judged = judge_fundamental_answer(answer, metadata)
    elif stage == "CODING_INTERVIEW":
        judged = judge_algorithm_answer(answer, metadata, current)
    elif stage == "CANDIDATE_QUESTIONS":
        judged = judge_candidate_question(answer)
    else:
        judged = finalize_judgement(2, [], ["未识别阶段"], answer, "当前阶段暂未定义自动判定规则。")
    judged["hints_used"] = int(current.get("hint_level", 0) or 0)
    mode = str(controller.load_session_state(Path(current.get("_session_dir", ""))).get("config", {}).get("mode", "")) if current.get("_session_dir") else ""
    judged = apply_mode_bias(judged, current, mode)
    return judged


def llm_semantic_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_OPENAI_API_KEY"))


def llm_endpoint() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def llm_model() -> str:
    return os.getenv("CS_INTERVIEW_JUDGE_MODEL", "gpt-5.5")


def call_llm_semantic_judge(current: dict[str, Any], answer: str, heuristic: dict[str, Any]) -> dict[str, Any] | None:
    if not llm_semantic_enabled():
        return None

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_OPENAI_API_KEY")
    if not api_key:
        return None

    prompt = render_semantic_prompt(current, answer, heuristic)
    payload = {
        "model": llm_model(),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    }
                ],
            }
        ],
    }

    req = urllib.request.Request(
        url=f"{llm_endpoint()}/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    text_parts: list[str] = []
    for item in body.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                text_parts.append(content["text"])
    raw_text = "\n".join(text_parts).strip()
    if not raw_text:
        return None

    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        judged = json.loads(raw_text[start : end + 1] if start >= 0 and end > start else raw_text)
    except (json.JSONDecodeError, ValueError):
        return None

    quality = str(judged.get("quality", "")).strip().lower()
    score = int(judged.get("score", 0) or 0)
    if quality not in {"strong", "partial", "weak", "wrong"}:
        return None
    if score < 1 or score > 5:
        return None

    return {
        "quality": quality,
        "score": score,
        "strengths": unique_keep_order([str(item).strip() for item in judged.get("strengths", []) or []]),
        "issues": unique_keep_order([str(item).strip() for item in judged.get("issues", []) or []]),
        "feedback": str(judged.get("feedback", "")).strip() or heuristic.get("feedback", ""),
        "judge_source": "heuristic+llm",
        "judge_confidence": float(judged.get("confidence", 0.75) or 0.75),
        "answer_text": answer,
        "answer_summary": heuristic.get("answer_summary"),
        "hints_used": heuristic.get("hints_used", 0),
    }


def merge_judgements(heuristic: dict[str, Any], semantic: dict[str, Any] | None) -> dict[str, Any]:
    if not semantic:
        return heuristic

    merged = dict(heuristic)
    merged["quality"] = semantic.get("quality", heuristic.get("quality"))
    merged["score"] = int(semantic.get("score", heuristic.get("score", 3)))
    merged["strengths"] = unique_keep_order((heuristic.get("strengths", []) or []) + (semantic.get("strengths", []) or []))[:4]
    merged["issues"] = unique_keep_order((heuristic.get("issues", []) or []) + (semantic.get("issues", []) or []))[:4]
    merged["feedback"] = semantic.get("feedback", heuristic.get("feedback"))
    merged["judge_source"] = semantic.get("judge_source", "heuristic+llm")
    merged["judge_confidence"] = semantic.get("judge_confidence", 0.75)
    merged["answer_text"] = heuristic.get("answer_text")
    merged["answer_summary"] = heuristic.get("answer_summary")
    merged["hints_used"] = heuristic.get("hints_used", 0)
    return merged


def auto_judge_answer(session_dir: Path, answer: str) -> dict[str, Any]:
    state = controller.load_session_state(session_dir)
    current = state.get("current_question") or {}
    if not current:
        return {
            "ok": False,
            "route": "candidate_answer",
            "error": "当前没有活动题目，无法自动判定作答。",
        }

    current["_session_dir"] = str(session_dir)
    heuristic = heuristic_judge_answer(answer, current)
    semantic = call_llm_semantic_judge(current, answer, heuristic)
    judged = merge_judgements(heuristic, semantic)
    record_result = controller.record_answer_from_dict(session_dir, judged)
    return {
        "ok": True,
        "route": "auto_record_answer",
        "judgement": judged,
        "result": record_result,
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

    return auto_judge_answer(session_dir, text)


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
