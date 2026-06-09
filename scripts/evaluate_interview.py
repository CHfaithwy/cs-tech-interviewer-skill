"""Evaluate a structured interview transcript and render a structured review report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_MODE_PROFILES = SKILL_DIR / "data" / "interview_mode_profiles.json"

MODULE_WEIGHTS = {
    "self_introduction": 10,
    "project_depth": 30,
    "cs_fundamentals": 20,
    "algorithm_ability": 25,
    "communication": 10,
    "candidate_questions": 5,
}

MODULE_LABELS = {
    "self_introduction": "自我介绍",
    "project_depth": "项目深度",
    "cs_fundamentals": "CS 基础",
    "algorithm_ability": "算法能力",
    "communication": "沟通表达",
    "candidate_questions": "反问质量",
}

STAGE_TO_MODULE = {
    "SELF_INTRO": "self_introduction",
    "PROJECT_DEEP_DIVE": "project_depth",
    "CS_FUNDAMENTALS": "cs_fundamentals",
    "CODING_INTERVIEW": "algorithm_ability",
    "CANDIDATE_QUESTIONS": "candidate_questions",
}
VALID_STAGES = set(STAGE_TO_MODULE)
VALID_QUALITIES = {"strong", "partial", "weak", "wrong"}

def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    return json.loads(read_text(path))


def load_mode_profiles(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or DEFAULT_MODE_PROFILES
    if not profile_path.exists():
        return {"profiles": {}}
    return json.loads(read_text(profile_path))


def get_mode_profile(mode: str | None, mode_profiles: dict[str, Any]) -> dict[str, Any]:
    profiles = mode_profiles.get("profiles") or {}
    if mode and mode in profiles:
        return profiles[mode]
    return profiles.get("完整模拟", {})


def get_mode_weights(mode: str | None, mode_profiles: dict[str, Any]) -> dict[str, int]:
    profile = get_mode_profile(mode, mode_profiles)
    configured = profile.get("scoring_policy", {}).get("weights", {}) or {}
    merged = dict(MODULE_WEIGHTS)
    for key, value in configured.items():
        merged[str(key)] = int(value)
    return merged


def get_report_sections(mode: str | None, mode_profiles: dict[str, Any]) -> list[str]:
    profile = get_mode_profile(mode, mode_profiles)
    return list(profile.get("report_sections", []))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a structured interview transcript.")
    parser.add_argument("transcript_json", help="Structured interview transcript JSON.")
    parser.add_argument("--profile-json", help="Optional candidate_profile.json from parse_resume.py.")
    parser.add_argument("--selection-json", help="Optional question_selection.json from select_questions.py.")
    parser.add_argument("-o", "--output-dir", help="Output directory. Defaults to <transcript stem>_evaluation.")
    return parser.parse_args(argv)


def default_output_dir(transcript_path: str) -> Path:
    source = Path(transcript_path).resolve()
    return source.with_name(f"{source.stem}_evaluation")


def validate_transcript_schema(transcript: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(transcript.get("schema_version", "")).strip() != "0.5":
        errors.append("schema_version 必须是 0.5")

    session = transcript.get("session")
    if not isinstance(session, dict):
        errors.append("session 必须存在且为对象")

    answers = transcript.get("answers")
    if not isinstance(answers, list) or not answers:
        errors.append("answers 必须存在且至少包含一条记录")
        return errors

    for index, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            errors.append(f"answers[{index}] 必须为对象")
            continue
        stage = str(answer.get("stage", "")).strip()
        quality = str(answer.get("quality", "")).strip().lower()
        question_id = str(answer.get("question_id", "")).strip()
        if stage not in VALID_STAGES:
            errors.append(f"answers[{index}].stage 非法：{stage}")
        if quality not in VALID_QUALITIES:
            errors.append(f"answers[{index}].quality 非法：{quality}")
        if not question_id:
            errors.append(f"answers[{index}].question_id 不能为空")
    return errors


def grade_from_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def summarize_module(score: int, weight: int, evidence: list[str], weaknesses: list[str]) -> str:
    if weight <= 0:
        return "本模式不考查该模块"
    if score >= int(weight * 0.85):
        tone = "表现较强"
    elif score >= int(weight * 0.65):
        tone = "表现中等"
    else:
        tone = "存在明显短板"

    parts = [tone]
    if evidence:
        parts.append("亮点：" + "；".join(evidence[:2]))
    if weaknesses:
        parts.append("问题：" + "；".join(weaknesses[:2]))
    return "。".join(parts)


def evaluate_answer(answer: dict[str, Any]) -> dict[str, Any]:
    score = int(answer.get("score", 0))
    quality = str(answer.get("quality", "")).strip().lower()
    hints_used = int(answer.get("hints_used", 0) or 0)
    skipped = bool(answer.get("skipped", False))
    issues = [str(item) for item in answer.get("issues", []) or []]
    strengths = [str(item) for item in answer.get("strengths", []) or []]

    if quality == "strong":
        score = max(score, 4)
    elif quality == "partial":
        score = max(score, 3)
    elif quality == "weak":
        score = min(score or 2, 2)
    elif quality == "wrong":
        score = min(score or 1, 1)

    if hints_used >= 2 and score > 1:
        score -= 1
        issues.append("需要较多提示")
    if skipped:
        score = 0
        issues.append("跳过问题")

    return {
        "score_5": max(0, min(score, 5)),
        "issues": issues,
        "strengths": strengths,
        "hints_used": hints_used,
        "skipped": skipped,
    }


def aggregate_stages(transcript: dict[str, Any]) -> dict[str, Any]:
    answers = transcript.get("answers", []) or []
    stage_stats: dict[str, dict[str, Any]] = {}
    module_strengths: dict[str, list[str]] = defaultdict(list)
    module_issues: dict[str, list[str]] = defaultdict(list)
    weakness_counter: Counter[str] = Counter()

    for answer in answers:
        stage = str(answer.get("stage", "UNKNOWN"))
        module = STAGE_TO_MODULE.get(stage)
        if not module:
            continue

        evaluated = evaluate_answer(answer)
        stats = stage_stats.setdefault(
            stage,
            {
                "module": module,
                "question_count": 0,
                "score_5_total": 0,
                "hints_used": 0,
                "skipped_count": 0,
                "strengths": [],
                "issues": [],
            },
        )
        stats["question_count"] += 1
        stats["score_5_total"] += evaluated["score_5"]
        stats["hints_used"] += evaluated["hints_used"]
        stats["skipped_count"] += 1 if evaluated["skipped"] else 0
        stats["strengths"].extend(evaluated["strengths"])
        stats["issues"].extend(evaluated["issues"])
        module_strengths[module].extend(evaluated["strengths"])
        module_issues[module].extend(evaluated["issues"])
        weakness_counter.update(issue for issue in evaluated["issues"] if issue)

    for stats in stage_stats.values():
        question_count = max(stats["question_count"], 1)
        avg_score_5 = stats["score_5_total"] / question_count
        stats["avg_score_5"] = round(avg_score_5, 2)
        stats["score_percent"] = round(avg_score_5 / 5 * 100)
        stats["strengths"] = unique_keep_order(stats["strengths"])
        stats["issues"] = unique_keep_order(stats["issues"])

    return {
        "stage_stats": stage_stats,
        "module_strengths": {key: unique_keep_order(value) for key, value in module_strengths.items()},
        "module_issues": {key: unique_keep_order(value) for key, value in module_issues.items()},
        "weakness_counter": weakness_counter,
    }


def estimate_communication_score(
    stage_stats: dict[str, Any],
    module_strengths: dict[str, list[str]],
    module_issues: dict[str, list[str]],
    weights: dict[str, int],
) -> dict[str, Any]:
    weight = weights["communication"]
    strengths: list[str] = []
    issues: list[str] = []

    long_answer_count = 0
    hint_heavy_count = 0
    skipped_count = 0
    for stats in stage_stats.values():
        long_answer_count += sum(1 for issue in stats.get("issues", []) if "回答略长" in issue or "回答过长" in issue)
        hint_heavy_count += stats.get("hints_used", 0)
        skipped_count += stats.get("skipped_count", 0)
    for values in module_strengths.values():
        strengths.extend([item for item in values if any(token in item for token in ["表达", "结构", "条理", "逻辑"])])
    for values in module_issues.values():
        issues.extend([item for item in values if any(token in item for token in ["表达", "结构", "过长", "模糊", "跑题"])])

    score = weight
    if long_answer_count >= 2:
        score -= 2
    if hint_heavy_count >= 4:
        score -= 1
    if skipped_count >= 2:
        score -= 1
    if issues:
        score -= 1
    score = max(0, min(weight, score))

    return {
        "score": score,
        "weight": weight,
        "stage": "MULTI_STAGE",
        "strengths": unique_keep_order(strengths),
        "issues": unique_keep_order(issues),
        "summary": summarize_module(score, weight, unique_keep_order(strengths), unique_keep_order(issues)),
    }


def compute_module_scores(aggregated: dict[str, Any], weights: dict[str, int]) -> dict[str, Any]:
    stage_stats = aggregated["stage_stats"]
    module_scores: dict[str, dict[str, Any]] = {}

    for stage, stats in stage_stats.items():
        module = stats["module"]
        weight = weights[module]
        normalized = stats["avg_score_5"] / 5
        adjusted = min(1.0, max(0.0, normalized * 0.8 + 0.2))
        base_score = round(adjusted * weight)
        module_scores[module] = {
            "score": base_score,
            "weight": weight,
            "stage": stage,
            "strengths": aggregated["module_strengths"].get(module, []),
            "issues": aggregated["module_issues"].get(module, []),
            "summary": summarize_module(
                base_score,
                weight,
                aggregated["module_strengths"].get(module, []),
                aggregated["module_issues"].get(module, []),
            ),
        }

    for module, weight in weights.items():
        module_scores.setdefault(
            module,
            {
                "score": 0,
                "weight": weight,
                "stage": "",
                "strengths": [],
                "issues": ["本轮未覆盖该模块"] if weight > 0 else [],
                "summary": "本轮未覆盖该模块" if weight > 0 else "本模式不考查该模块",
            },
        )

    module_scores["communication"] = estimate_communication_score(
        stage_stats,
        aggregated["module_strengths"],
        aggregated["module_issues"],
        weights,
    )
    return module_scores


def map_issue_to_focus(issue: str) -> str:
    mapping = {
        "指标": "项目指标与量化结果",
        "事务": "MySQL 事务 / MVCC",
        "索引": "MySQL 索引 / 执行计划",
        "缓存": "Redis 缓存一致性与热点问题",
        "边界": "算法边界情况与测试用例",
        "复杂度": "算法复杂度分析",
        "表达": "结构化表达与回答压缩",
        "工具": "Agent 工具调用与错误恢复",
        "召回": "RAG 评估与检索质量",
    }
    for keyword, focus in mapping.items():
        if keyword in issue:
            return focus
    return "基础知识与项目追问补强"


def build_weakness_tracking(aggregated: dict[str, Any], profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    weakness_counter: Counter[str] = aggregated["weakness_counter"]
    risks = profile.get("resume_risks", []) if profile else []
    weakness_items: list[dict[str, Any]] = []

    for issue, count in weakness_counter.most_common():
        if not issue or issue == "本轮未覆盖该模块":
            continue
        weakness_items.append(
            {
                "issue": issue,
                "count": count,
                "focus_hint": map_issue_to_focus(issue),
                "priority": "P0" if count >= 2 else "P1",
            }
        )

    for risk in risks[:5]:
        area = str(risk.get("area", "")).strip()
        if not area:
            continue
        weakness_items.append(
            {
                "issue": f"简历风险：{area}",
                "count": 1,
                "focus_hint": str(risk.get("likely_followup", "")),
                "priority": "P1",
            }
        )

    deduped = []
    seen = set()
    for item in weakness_items:
        key = item["issue"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:12]


def build_llm_required_next_round_placeholder(transcript: dict[str, Any]) -> dict[str, Any]:
    session = transcript.get("session", {}) or {}
    return {
        "status": "llm_required",
        "reason": "下一轮配置需要由当前大模型读取完整复盘、作答证据、候选人画像和简历风险后生成。",
        "current_context": {
            "strength": session.get("strength"),
            "tone": session.get("tone"),
            "mode": session.get("mode"),
            "focus": session.get("focus", []) or [],
        },
        "required_inputs": [
            "interview_evaluation.json",
            "transcript.json",
            "candidate_profile.json",
            "resume_risks.md",
        ],
        "apply_script": "scripts/apply_llm_post_interview_outputs.py",
    }


def build_overall_conclusion(module_scores: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    total_score = sum(value["score"] for value in module_scores.values())
    grade = grade_from_score(total_score)
    strength = transcript.get("session", {}).get("strength", "")
    tone = transcript.get("session", {}).get("tone", "")
    mode = transcript.get("session", {}).get("mode", "")
    target_role = transcript.get("session", {}).get("role", "") or transcript.get("session", {}).get("target_role", "")

    if mode == "项目深挖":
        if total_score >= 80:
            verdict = "项目深挖表现较强，ownership、实现细节和工程思路具备较好的说服力。"
        elif total_score >= 65:
            verdict = "项目主线能讲清，但指标、tradeoff 或工程闭环仍需补强。"
        else:
            verdict = "项目深挖暴露出明显风险，建议优先补 ownership、指标和线上工程细节。"
    elif mode == "八股快问快答":
        if total_score >= 80:
            verdict = "基础知识覆盖较稳，已经具备较好的八股快问快答能力。"
        elif total_score >= 65:
            verdict = "核心概念基本在线，但仍有一批知识点需要系统化回炉。"
        else:
            verdict = "基础知识短板较明显，建议先按 topic gap list 分批补强。"
    elif mode == "算法陪练":
        if total_score >= 80:
            verdict = "算法思路、复杂度和边界意识整体较稳，可以继续提高题目强度。"
        elif total_score >= 65:
            verdict = "算法主思路基本可用，但复杂度分析或边界处理还有明显提升空间。"
        else:
            verdict = "算法专项短板较明显，建议先回到更稳的题型分层练习。"
    else:
        if total_score >= 85:
            verdict = "具备较强的正式面试竞争力，可以继续提高强度和深挖深度。"
        elif total_score >= 70:
            verdict = "具备普通技术面通过潜力，但仍有若干短板需要针对性补齐。"
        elif total_score >= 60:
            verdict = "存在明显薄弱点，建议先做针对性训练后再进入更高强度模拟。"
        else:
            verdict = "当前不建议直接进入高强度正式面试，先补基础和表达。"

    return {
        "strength": strength,
        "tone": tone,
        "mode": mode,
        "target_role": target_role,
        "total_score": total_score,
        "grade": grade,
        "verdict": verdict,
    }


def section_enabled(report_sections: list[str], key: str, default: bool = True) -> bool:
    if not report_sections:
        return default
    return key in report_sections


def extract_highlights(module_scores: dict[str, Any]) -> list[str]:
    return unique_keep_order([text for module in module_scores.values() for text in module.get("strengths", [])])[:6]


def extract_issues(module_scores: dict[str, Any]) -> list[str]:
    return unique_keep_order(
        [text for module in module_scores.values() for text in module.get("issues", []) if text != "本轮未覆盖该模块"]
    )[:8]


def build_review_priorities(weakness_items: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    priorities: list[dict[str, Any]] = []
    for item in weakness_items[:8]:
        action = item.get("focus_hint") or "补充可验证证据"
        priorities.append(
            {
                "priority": item.get("priority", "P1"),
                "topic": item.get("issue"),
                "recommended_action": action,
                "mode_bias": mode,
            }
        )
    return priorities


def build_project_risk_map(profile: dict[str, Any] | None, transcript: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if not profile or mode not in {"项目深挖", "完整模拟", "JD 定向面", "简历拷打"}:
        return []
    project_answers = [answer for answer in transcript.get("answers", []) or [] if answer.get("stage") == "PROJECT_DEEP_DIVE"]
    issue_pool = unique_keep_order([issue for answer in project_answers for issue in answer.get("issues", []) or []])
    result = []
    for risk in profile.get("resume_risks", []) or []:
        if not risk.get("project"):
            continue
        result.append(
            {
                "project": risk.get("project"),
                "area": risk.get("area"),
                "severity": risk.get("severity"),
                "why_it_matters": risk.get("why_it_matters"),
                "suggested_fix": risk.get("suggested_fix"),
                "interview_evidence": [issue for issue in issue_pool if any(token in issue for token in [str(risk.get("area")), "指标", "状态", "恢复", "tradeoff", "成本"])][:3],
            }
        )
    return result[:10]


def build_resume_risk_map(profile: dict[str, Any] | None, transcript: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if not profile or mode not in {"简历拷打", "项目深挖", "JD 定向面", "完整模拟"}:
        return []
    all_issues = unique_keep_order([issue for answer in transcript.get("answers", []) or [] for issue in answer.get("issues", []) or []])
    items = []
    for risk in profile.get("resume_risks", []) or []:
        items.append(
            {
                "project": risk.get("project"),
                "area": risk.get("area"),
                "severity": risk.get("severity"),
                "evidence": risk.get("evidence"),
                "why_it_matters": risk.get("why_it_matters"),
                "likely_followup": risk.get("likely_followup"),
                "interview_evidence": [issue for issue in all_issues if any(token in issue for token in [str(risk.get("area")), "指标", "细节", "实现", "恢复"])][:3],
            }
        )
    return items[:10]


def build_fundamentals_gap_list(transcript: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode not in {"八股快问快答", "JD 定向面", "完整模拟", "简历拷打"}:
        return []
    items = []
    for answer in transcript.get("answers", []) or []:
        if answer.get("stage") != "CS_FUNDAMENTALS":
            continue
        if str(answer.get("quality", "")).lower() == "strong":
            continue
        items.append(
            {
                "question_id": answer.get("question_id"),
                "question_text": answer.get("question_text"),
                "issues": unique_keep_order([str(item) for item in answer.get("issues", []) or []])[:4],
                "priority": "P0" if str(answer.get("quality", "")).lower() in {"weak", "wrong"} else "P1",
            }
        )
    return items[:10]


def build_algorithm_breakdown(transcript: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode not in {"算法陪练", "完整模拟"}:
        return []
    items = []
    for answer in transcript.get("answers", []) or []:
        if answer.get("stage") != "CODING_INTERVIEW":
            continue
        issues = [str(item) for item in answer.get("issues", []) or []]
        strengths = [str(item) for item in answer.get("strengths", []) or []]
        items.append(
            {
                "question_id": answer.get("question_id"),
                "question_text": answer.get("question_text"),
                "quality": answer.get("quality"),
                "score": answer.get("score"),
                "hint_dependency": int(answer.get("hints_used", 0) or 0),
                "edge_case_gaps": [item for item in issues if "边界" in item][:3],
                "complexity_gaps": [item for item in issues if "复杂度" in item][:3],
                "strengths": strengths[:3],
                "issues": unique_keep_order(issues)[:4],
            }
        )
    return items[:8]


def build_jd_fit_gaps(
    transcript: dict[str, Any],
    profile: dict[str, Any] | None,
    selection: dict[str, Any] | None,
    mode: str,
) -> list[dict[str, Any]]:
    if mode != "JD 定向面":
        return []
    focus = transcript.get("session", {}).get("focus", []) or []
    issues = unique_keep_order([issue for answer in transcript.get("answers", []) or [] for issue in answer.get("issues", []) or []])
    highlights = unique_keep_order([item for answer in transcript.get("answers", []) or [] for item in answer.get("strengths", []) or []])
    return [
        {
            "jd_signal": item,
            "strength_evidence": [text for text in highlights if any(token in text for token in [item, "RAG", "评估", "MySQL", "Redis"])][:2],
            "gap_evidence": [text for text in issues if any(token in text for token in [item, "指标", "事务", "恢复", "表达"])][:3],
        }
        for item in list(focus)[:6]
    ]


def render_table(lines: list[str], headers: list[str], rows: list[list[str]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")


def render_evaluation_md(result: dict[str, Any]) -> str:
    conclusion = result["overall_conclusion"]
    module_scores = result["module_scores"]
    weakness_items = result["weakness_tracking"]
    next_round = result.get("next_round_recommendation") or {}
    stage_scores = result["stage_scores"]
    report_sections = result.get("report_sections", []) or []

    lines = [
        "# 技术面模拟复盘报告",
        "",
        "## 1. 总体结论",
        f"- 本场面试强度：{conclusion.get('strength')}",
        f"- 面试语气：{conclusion.get('tone')}",
        f"- 面试模式：{conclusion.get('mode')}",
        f"- 目标岗位：{conclusion.get('target_role') or '未指定'}",
        f"- 综合评分：{conclusion.get('total_score')} / 100",
        f"- 等级：{conclusion.get('grade')}",
        f"- 面试结论：{conclusion.get('verdict')}",
    ]

    if section_enabled(report_sections, "module_scores"):
        lines.extend(["", "## 2. 各模块评分"])
        rows = []
        for key, label in MODULE_LABELS.items():
            module = module_scores[key]
            if module["weight"] <= 0:
                continue
            rows.append([label, f"{module['score']}/{module['weight']}", module["summary"]])
        render_table(lines, ["模块", "分数", "评价"], rows)

    if section_enabled(report_sections, "stage_scores"):
        lines.extend(["", "## 3. 阶段评分"])
        rows = []
        for stage, item in stage_scores.items():
            rows.append(
                [
                    stage,
                    item["module"],
                    str(item["score_percent"]),
                    str(item["hints_used"]),
                    str(item["skipped_count"]),
                ]
            )
        render_table(lines, ["阶段", "模块", "暂评分", "提示使用", "跳过"], rows)

    if section_enabled(report_sections, "highlights"):
        lines.extend(["", "## 4. 主要亮点"])
        for index, item in enumerate(result.get("highlights", []) or [], start=1):
            lines.append(f"{index}. {item}")

    if section_enabled(report_sections, "issues"):
        lines.extend(["", "## 5. 主要问题"])
        for index, item in enumerate(result.get("issues", []) or [], start=1):
            lines.append(f"{index}. {item}")

    if section_enabled(report_sections, "weakness_tracking"):
        lines.extend(["", "## 6. 薄弱点追踪"])
        rows = [[item["issue"], str(item["count"]), item["priority"], item["focus_hint"]] for item in weakness_items]
        render_table(lines, ["问题", "次数", "优先级", "建议方向"], rows)

    if section_enabled(report_sections, "project_risk_map"):
        items = result.get("project_risk_map", []) or []
        if items:
            lines.extend(["", "## 7. 项目深度风险图"])
            rows = [[str(item.get("project", "")), str(item.get("area", "")), str(item.get("severity", "")), str(item.get("suggested_fix", ""))] for item in items]
            render_table(lines, ["项目", "风险点", "等级", "补强建议"], rows)

    if section_enabled(report_sections, "fundamentals_gap_list") or section_enabled(report_sections, "gap_list"):
        items = result.get("fundamentals_gap_list", []) or []
        if items:
            lines.extend(["", "## 8. 八股知识缺口"])
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. {item.get('question_text') or item.get('question_id')}")
                lines.append(f"   - 优先级：{item.get('priority')}")
                issue_list = item.get("issues", []) or []
                if issue_list:
                    lines.append("   - 问题：" + "；".join(issue_list))

    if section_enabled(report_sections, "algorithm_breakdown"):
        items = result.get("algorithm_breakdown", []) or []
        if items:
            lines.extend(["", "## 9. 算法专项拆解"])
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. {item.get('question_text') or item.get('question_id')}")
                lines.append(f"   - 质量：{item.get('quality')} / score={item.get('score')}")
                lines.append(f"   - 提示依赖：{item.get('hint_dependency')}")
                if item.get("edge_case_gaps"):
                    lines.append("   - 边界问题：" + "；".join(item["edge_case_gaps"]))
                if item.get("complexity_gaps"):
                    lines.append("   - 复杂度问题：" + "；".join(item["complexity_gaps"]))
                if item.get("issues"):
                    lines.append("   - 其他问题：" + "；".join(item["issues"]))

    if section_enabled(report_sections, "jd_fit_gaps"):
        items = result.get("jd_fit_gaps", []) or []
        if items:
            lines.extend(["", "## 10. JD 匹配缺口"])
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. JD 信号：{item.get('jd_signal')}")
                if item.get("strength_evidence"):
                    lines.append("   - 已体现：" + "；".join(item["strength_evidence"]))
                if item.get("gap_evidence"):
                    lines.append("   - 缺口：" + "；".join(item["gap_evidence"]))

    if section_enabled(report_sections, "resume_risk_map") or section_enabled(report_sections, "resume_risks"):
        items = result.get("resume_risk_map", []) or []
        if items:
            lines.extend(["", "## 11. 简历高风险表述地图"])
            rows = [[str(item.get("project", "")), str(item.get("area", "")), str(item.get("severity", "")), str(item.get("why_it_matters", ""))] for item in items]
            render_table(lines, ["对象", "风险点", "等级", "为什么会被追问"], rows)

    if section_enabled(report_sections, "resume_rewrite"):
        items = result.get("resume_rewrite_suggestions", []) or []
        if items:
            lines.extend(["", "## 12. 简历修改建议"])
            for index, item in enumerate(items, start=1):
                lines.append(f"{index}. {item.get('target_label')}")
                lines.append(f"   - 原表述：{item.get('original_text')}")
                lines.append(f"   - 问题类型：{', '.join(item.get('problem_types', []))}")
                lines.append(f"   - 改写策略：{item.get('rewrite_strategy')}")
                rewrite_diff = item.get("rewrite_diff") or {}
                lines.append("   - 原句 -> 建议改写：")
                lines.append(f"     - 原句：{rewrite_diff.get('before', item.get('original_text'))}")
                lines.append(f"     - 改写：{rewrite_diff.get('after', item.get('suggested_rewrite'))}")
                placeholders = item.get("placeholders_to_confirm", []) or []
                if placeholders:
                    lines.append("   - 待补真实信息：" + "；".join(placeholders))

    if section_enabled(report_sections, "review_priority") or section_enabled(report_sections, "review_priorities"):
        items = result.get("review_priorities", []) or []
        if items:
            lines.extend(["", "## 13. 复习优先级"])
            rows = [[str(item.get("priority", "")), str(item.get("topic", "")), str(item.get("recommended_action", ""))] for item in items]
            render_table(lines, ["优先级", "主题", "建议动作"], rows)

    if section_enabled(report_sections, "next_round"):
        lines.extend(["", "## 14. 下一轮模拟建议"])
        if next_round.get("status") == "llm_required":
            lines.append("- 待当前大模型读取 `interview_evaluation.json`、`transcript.json`、`candidate_profile.json` 和 `resume_risks.md` 后生成。")
            lines.append("- 生成后运行 `scripts/apply_llm_post_interview_outputs.py` 写回固定文件。")
        else:
            lines.append(f"- `/strength {next_round.get('strength')}`")
            lines.append(f"- `/tone {next_round.get('tone')}`")
            lines.append(f"- `/mode {next_round.get('mode')}`")
            if next_round.get("focus"):
                lines.append(f"- `/focus {', '.join(next_round.get('focus', []))}`")
            if next_round.get("recommended_questions"):
                lines.append("- 推荐算法题：" + "、".join(next_round.get("recommended_questions", [])))

    lines.append("")
    return "\n".join(lines)


def evaluate_transcript(
    transcript: dict[str, Any],
    profile: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_errors = validate_transcript_schema(transcript)
    if schema_errors:
        raise ValueError("；".join(schema_errors))

    current_mode = str(transcript.get("session", {}).get("mode", "完整模拟"))
    mode_profiles = load_mode_profiles()
    weights = get_mode_weights(current_mode, mode_profiles)
    report_sections = get_report_sections(current_mode, mode_profiles)
    aggregated = aggregate_stages(transcript)
    module_scores = compute_module_scores(aggregated, weights)
    weakness_items = build_weakness_tracking(aggregated, profile)
    next_round = build_llm_required_next_round_placeholder(transcript)
    conclusion = build_overall_conclusion(module_scores, transcript)
    highlights = extract_highlights(module_scores)
    issues = extract_issues(module_scores)
    review_priorities = build_review_priorities(weakness_items, current_mode)

    project_risk_map = build_project_risk_map(profile, transcript, current_mode)
    fundamentals_gap_list = build_fundamentals_gap_list(transcript, current_mode)
    algorithm_breakdown = build_algorithm_breakdown(transcript, current_mode)
    jd_fit_gaps = build_jd_fit_gaps(transcript, profile, selection, current_mode)
    resume_risk_map = build_resume_risk_map(profile, transcript, current_mode)
    resume_rewrite_suggestions: list[dict[str, Any]] = []

    return {
        "schema_version": "1.0",
        "kind": "interview_evaluation",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall_conclusion": conclusion,
        "module_scores": module_scores,
        "stage_scores": aggregated["stage_stats"],
        "highlights": highlights,
        "issues": issues,
        "weakness_tracking": weakness_items,
        "review_priorities": review_priorities,
        "project_risk_map": project_risk_map,
        "fundamentals_gap_list": fundamentals_gap_list,
        "algorithm_breakdown": algorithm_breakdown,
        "jd_fit_gaps": jd_fit_gaps,
        "resume_risk_map": resume_risk_map,
        "resume_rewrite_suggestions": resume_rewrite_suggestions,
        "next_round_recommendation": next_round,
        "report_sections": report_sections,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    transcript_path = Path(args.transcript_json).resolve()
    transcript = load_json(transcript_path)
    if transcript is None:
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    schema_errors = validate_transcript_schema(transcript)
    if schema_errors:
        print("evaluate_interview.py failed schema validation:", file=sys.stderr)
        for error in schema_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    profile = load_json(Path(args.profile_json).resolve()) if args.profile_json else None
    selection = load_json(Path(args.selection_json).resolve()) if args.selection_json else None
    result = evaluate_transcript(transcript, profile=profile, selection=selection)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.transcript_json)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "interview_evaluation.json"
    md_path = output_dir / "interview_evaluation.md"
    write_text(json_path, json.dumps(result, ensure_ascii=False, indent=2))
    write_text(md_path, render_evaluation_md(result))

    print(
        json.dumps(
            {
                "ok": True,
                "outputs": {
                    "evaluation_json": str(json_path),
                    "evaluation_md": str(md_path),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
