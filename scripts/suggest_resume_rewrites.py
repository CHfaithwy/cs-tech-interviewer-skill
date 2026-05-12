#!/usr/bin/env python
"""Generate structured resume rewrite suggestions from parsed profile data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


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


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_output_dir(profile_json: Path) -> Path:
    return profile_json.resolve().parent


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest resume rewrites from candidate profile and interview evidence.")
    parser.add_argument("candidate_profile_json", help="Path to candidate_profile.json.")
    parser.add_argument("--transcript-json", help="Optional transcript.json for interview evidence.")
    parser.add_argument("--evaluation-json", help="Optional interview_evaluation.json for weakness evidence.")
    parser.add_argument("-o", "--output-dir", help="Output directory. Defaults to the candidate profile directory.")
    return parser.parse_args(argv)


def contains_metric_signal(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"\d", text)) or any(token in lowered for token in ["ms", "%", "qps", "p95", "p99", "latency"])


def build_placeholder_list(problem_types: list[str]) -> list[str]:
    placeholders: list[str] = []
    if "missing_metrics" in problem_types:
        placeholders.extend(["P95 latency", "QPS", "sample size", "baseline", "improvement ratio"])
    if "rag_depth" in problem_types:
        placeholders.extend(["chunk strategy", "top-k", "evaluation metric", "failure case"])
    if "agent_reliability" in problem_types:
        placeholders.extend(["state transition", "retry policy", "timeout policy", "fallback path"])
    if "ownership_unclear" in problem_types:
        placeholders.extend(["personal ownership boundary", "upstream/downstream dependency"])
    if "tradeoff_unclear" in problem_types:
        placeholders.extend(["alternative方案", "why chosen", "cost tradeoff"])
    if "engineering_closure" in problem_types:
        placeholders.extend(["test method", "monitoring metric", "deployment guardrail"])
    return unique_keep_order(placeholders)


def rewrite_strategy_for(problem_types: list[str]) -> str:
    strategies: list[str] = []
    if "ownership_unclear" in problem_types:
        strategies.append("明确写出你亲自负责的模块、动作和交付边界")
    if "missing_metrics" in problem_types:
        strategies.append("把优化结果改成 baseline + action + metric + measurement condition")
    if "rag_depth" in problem_types:
        strategies.append("补出检索、评估、失败样例和改进闭环")
    if "agent_reliability" in problem_types:
        strategies.append("补出状态管理、工具失败恢复和兜底链路")
    if "tradeoff_unclear" in problem_types:
        strategies.append("补出方案选择理由和替代方案对比")
    if "engineering_closure" in problem_types:
        strategies.append("补出测试、监控、异常处理和上线保障")
    return "；".join(unique_keep_order(strategies)) or "把表述改成对象、动作、方法、结果四段式"


def classify_problem_types(risk: dict[str, Any], evidence_issues: list[str]) -> list[str]:
    area = normalize_text(risk.get("area"))
    why = normalize_text(risk.get("why_it_matters"))
    combined = " ".join([area, why] + evidence_issues)
    tags: list[str] = []
    if any(token in combined for token in ["指标", "量化", "性能", "baseline", "评估集", "P95", "QPS"]):
        tags.append("missing_metrics")
    if any(token in combined for token in ["RAG", "GraphRAG", "召回", "重排", "幻觉", "评估"]):
        tags.append("rag_depth")
    if any(token in combined for token in ["Agent", "状态", "工具调用", "超时", "重试", "失败恢复"]):
        tags.append("agent_reliability")
    if any(token in combined for token in ["职责", "ownership", "负责"]):
        tags.append("ownership_unclear")
    if any(token in combined for token in ["tradeoff", "取舍", "成本", "方案选择"]):
        tags.append("tradeoff_unclear")
    if any(token in combined for token in ["测试", "监控", "部署", "异常", "工程闭环", "线上"]):
        tags.append("engineering_closure")
    return unique_keep_order(tags) or ["ownership_unclear"]


def collect_evidence_map(transcript: dict[str, Any] | None, evaluation: dict[str, Any] | None) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    if transcript:
        for answer in transcript.get("answers", []) or []:
            question_text = normalize_text(answer.get("question_text"))
            for issue in answer.get("issues", []) or []:
                issue_text = normalize_text(issue)
                if not issue_text:
                    continue
                evidence.setdefault(issue_text, [])
                if question_text:
                    evidence[issue_text].append(question_text)
    if evaluation:
        for item in evaluation.get("weakness_tracking", []) or []:
            issue_text = normalize_text(item.get("issue"))
            focus_hint = normalize_text(item.get("focus_hint"))
            if not issue_text:
                continue
            evidence.setdefault(issue_text, [])
            if focus_hint:
                evidence[issue_text].append(focus_hint)
    return {key: unique_keep_order(values) for key, values in evidence.items()}


def build_project_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    projects = profile.get("candidate_profile", {}).get("projects", []) or []
    lookup: dict[str, dict[str, Any]] = {}
    for project_index, project in enumerate(projects):
        name = normalize_text(project.get("name"))
        if name:
            enriched = dict(project)
            enriched["_project_index"] = project_index
            lookup[name] = enriched
    return lookup


def build_match_keywords(risk: dict[str, Any], problem_types: list[str]) -> list[str]:
    texts = [
        normalize_text(risk.get("area")),
        normalize_text(risk.get("evidence")),
        normalize_text(risk.get("why_it_matters")),
        normalize_text(risk.get("suggested_fix")),
        normalize_text(risk.get("likely_followup")),
    ]
    combined = " ".join(texts)
    keyword_pool = [
        "RAG",
        "GraphRAG",
        "Agent",
        "LangGraph",
        "LangChain",
        "Redis",
        "MySQL",
        "Neo4j",
        "Cypher",
        "FastAPI",
        "日志",
        "超时",
        "重试",
        "降级",
        "状态",
        "异常",
        "trace",
        "监控",
        "测试",
        "部署",
        "索引",
        "SQL",
        "chunk",
        "top-k",
        "评估",
        "召回",
        "重排",
        "幻觉",
        "指标",
        "性能",
        "准确率",
        "成本",
    ]
    keywords = [token for token in keyword_pool if token.lower() in combined.lower()]
    if "missing_metrics" in problem_types:
        keywords.extend(["指标", "性能", "延迟", "准确率"])
    if "rag_depth" in problem_types:
        keywords.extend(["RAG", "GraphRAG", "召回", "评估", "重排"])
    if "agent_reliability" in problem_types:
        keywords.extend(["Agent", "状态", "工具", "超时", "重试", "降级", "日志"])
    if "engineering_closure" in problem_types:
        keywords.extend(["测试", "监控", "部署", "异常"])
    return unique_keep_order(keywords)


def score_claim_match(
    claim_text: str,
    risk: dict[str, Any],
    problem_types: list[str],
    project_metrics: list[str],
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    claim_lower = claim_text.lower()
    keywords = build_match_keywords(risk, problem_types)

    for keyword in keywords:
        if keyword.lower() in claim_lower:
            score += 3
            reasons.append(f"keyword:{keyword}")

    evidence = normalize_text(risk.get("evidence"))
    if evidence and evidence.lower() in claim_lower:
        score += 5
        reasons.append("matched_risk_evidence")

    if "missing_metrics" in problem_types and contains_metric_signal(claim_text):
        score += 5
        reasons.append("metric_signal")

    if any(metric and metric.lower() in claim_lower for metric in project_metrics):
        score += 3
        reasons.append("project_metric")

    if "agent_reliability" in problem_types and any(token in claim_text for token in ["日志", "超时", "重试", "降级", "状态", "异常"]):
        score += 4
        reasons.append("agent_reliability_signal")

    if "rag_depth" in problem_types and any(token in claim_text for token in ["GraphRAG", "RAG", "召回", "评估", "重排"]):
        score += 4
        reasons.append("rag_depth_signal")

    if "engineering_closure" in problem_types and any(token in claim_text for token in ["日志", "测试", "监控", "部署", "异常"]):
        score += 4
        reasons.append("engineering_closure_signal")

    return score, unique_keep_order(reasons)


def find_best_claim_anchor(project: dict[str, Any], risk: dict[str, Any], problem_types: list[str]) -> dict[str, Any]:
    claims = [normalize_text(item) for item in project.get("claims", []) or []]
    metrics = [normalize_text(item) for item in project.get("metrics", []) or []]
    project_index = int(project.get("_project_index", 0))

    best_anchor: dict[str, Any] | None = None
    best_score = -1
    for claim_index, claim_text in enumerate(claims):
        score, reasons = score_claim_match(claim_text, risk, problem_types, metrics)
        if score > best_score:
            best_score = score
            best_anchor = {
                "source_kind": "project_claim",
                "project_name": normalize_text(project.get("name")),
                "project_index": project_index,
                "claim_index": claim_index,
                "path": f"candidate_profile.projects[{project_index}].claims[{claim_index}]",
                "matched_by": reasons,
                "match_score": score,
                "text": claim_text,
            }

    if best_anchor and best_score > 0:
        return best_anchor

    role_text = normalize_text(project.get("role"))
    if role_text:
        return {
            "source_kind": "project_role",
            "project_name": normalize_text(project.get("name")),
            "project_index": project_index,
            "claim_index": None,
            "path": f"candidate_profile.projects[{project_index}].role",
            "matched_by": ["fallback:project_role"],
            "match_score": 0,
            "text": role_text,
        }

    if claims:
        return {
            "source_kind": "project_claim",
            "project_name": normalize_text(project.get("name")),
            "project_index": project_index,
            "claim_index": 0,
            "path": f"candidate_profile.projects[{project_index}].claims[0]",
            "matched_by": ["fallback:first_claim"],
            "match_score": 0,
            "text": claims[0],
        }

    return {
        "source_kind": "project_name",
        "project_name": normalize_text(project.get("name")),
        "project_index": project_index,
        "claim_index": None,
        "path": f"candidate_profile.projects[{project_index}]",
        "matched_by": ["fallback:project_name"],
        "match_score": 0,
        "text": normalize_text(project.get("name")),
    }


def build_suggested_rewrite(
    project_name: str,
    original_text: str,
    problem_types: list[str],
    source_anchor: dict[str, Any] | None,
) -> str:
    subject = project_name or "该段经历"
    anchor_text = normalize_text((source_anchor or {}).get("text")) or original_text

    if "missing_metrics" in problem_types:
        return (
            f"{subject}：负责 {{具体模块/职责边界}}，通过 {{优化动作}} 将 {{指标名}} 从 {{baseline}} 优化到 "
            f"{{目标值}}（统计口径：{{样本量/时间窗口/压测条件}}）。"
        )

    if "rag_depth" in problem_types:
        return (
            f"{subject}：围绕 {{业务场景}} 设计 {{检索/图谱/重排}} 链路，完成 {{chunk 策略/实体关系构建/top-k 检索}}，"
            f"并通过 {{评估指标/失败案例分析}} 持续优化问答效果。"
        )

    if "agent_reliability" in problem_types and "engineering_closure" in problem_types:
        return (
            f"{subject}：负责 {{Agent/工作流模块}} 的状态编排与工具调用治理，补充 {{超时重试/异常回退/降级兜底}} 机制，"
            f"并结合 {{日志/监控/压测}} 提升线上稳定性。"
        )

    if "agent_reliability" in problem_types:
        return (
            f"{subject}：负责 {{Agent/工作流模块}} 的状态流转与工具调用控制，设计 {{失败重试/参数校验/人工兜底}} 机制，"
            f"降低 {{调用失败/脏数据/幻觉输出}} 风险。"
        )

    if "engineering_closure" in problem_types:
        return (
            f"{subject}：负责 {{接口/服务模块}} 的工程落地，补充 {{鉴权/异常处理/测试/监控/部署}} 能力，"
            f"保障 {{线上稳定性/可观测性/发布安全}}。"
        )

    if "tradeoff_unclear" in problem_types:
        return (
            f"{subject}：在 {{候选方案 A}} 与 {{候选方案 B}} 之间做取舍，最终采用 {{当前方案}}，"
            f"原因是 {{性能/成本/复杂度/维护性}} 更符合业务约束。"
        )

    if "ownership_unclear" in problem_types:
        return (
            f"{subject}：我主要负责 {{具体模块/职责边界}}，独立完成 {{关键动作}}，并与 {{上下游团队/依赖模块}} 协作推进交付。"
        )

    if contains_metric_signal(anchor_text):
        return (
            f"{subject}：负责 {{具体模块/职责边界}}，通过 {{优化动作}} 将 {{指标名}} 从 {{baseline}} 优化到 "
            f"{{目标值}}（统计口径：{{样本量/时间窗口/压测条件}}）。"
        )

    return (
        f"{subject}：负责 {{具体模块/职责边界}}，围绕 {{核心问题}} 设计并实现 {{关键方案/模块}}，"
        f"最终支撑 {{业务效果/工程结果}}。"
    )


def build_rewrite_item(
    risk: dict[str, Any],
    project_lookup: dict[str, dict[str, Any]],
    evidence_map: dict[str, list[str]],
    index: int,
) -> dict[str, Any]:
    project_name = normalize_text(risk.get("project"))
    project = project_lookup.get(project_name, {})
    risk_area = normalize_text(risk.get("area"))

    matching_evidence: list[str] = []
    for key, values in evidence_map.items():
        if key.startswith("简历风险：") and risk_area and risk_area in key:
            matching_evidence.extend(values or [key])
        elif any(token in key for token in [risk_area, project_name]) and key:
            matching_evidence.append(key)
            matching_evidence.extend(values)

    problem_types = classify_problem_types(risk, unique_keep_order(matching_evidence))
    anchor = find_best_claim_anchor(project, risk, problem_types) if project else None
    original_text = anchor["text"] if anchor else normalize_text(project.get("role")) or project_name
    placeholders = build_placeholder_list(problem_types)
    strategy = rewrite_strategy_for(problem_types)

    scope = "project" if project_name else "experience"
    if "skills" in risk_area.lower():
        scope = "skills"

    suggested_rewrite = build_suggested_rewrite(project_name, original_text, problem_types, anchor)
    rewrite_diff = {
        "before": original_text,
        "after": suggested_rewrite,
    }

    return {
        "id": f"rewrite_{index:03d}",
        "scope": scope,
        "target_label": project_name or risk_area or f"risk-{index}",
        "target_area": risk_area,
        "original_text": original_text,
        "source_anchor": anchor or {},
        "problem_types": problem_types,
        "why_it_is_weak": normalize_text(risk.get("why_it_matters")) or "当前表述容易在面试中被追问，但缺少足够证据。",
        "evidence": unique_keep_order(
            [normalize_text(risk.get("evidence")), normalize_text(risk.get("likely_followup"))] + matching_evidence
        ),
        "rewrite_strategy": strategy,
        "suggested_rewrite": suggested_rewrite,
        "rewrite_diff": rewrite_diff,
        "placeholders_to_confirm": placeholders,
        "priority": "P0" if normalize_text(risk.get("severity")) == "high" else "P1",
        "confidence": "high" if matching_evidence else "medium",
    }


def build_summary_rewrite(profile: dict[str, Any], evidence_map: dict[str, list[str]], start_index: int) -> list[dict[str, Any]]:
    target_roles = profile.get("candidate_profile", {}).get("target_roles", []) or []
    focus = profile.get("candidate_profile", {}).get("interview_focus", []) or []
    if not target_roles and not focus:
        return []

    issues = [key for key in evidence_map if any(token in key for token in ["岗位匹配", "回答略长", "表达", "模糊"])]
    after = "目标方向：{目标岗位}。具备 {核心技术栈} 项目经验，重点负责 {项目类型/能力主线}，在 {指标/工程闭环} 上有可验证实践。"
    return [
        {
            "id": f"rewrite_{start_index:03d}",
            "scope": "summary",
            "target_label": "简历摘要/自我介绍主线",
            "target_area": "summary_positioning",
            "original_text": "当前简历缺少一段明确的岗位匹配摘要。",
            "source_anchor": {
                "source_kind": "synthetic_summary",
                "path": "candidate_profile.summary",
                "matched_by": ["synthetic:missing_summary"],
                "match_score": 0,
                "text": "当前简历缺少一段明确的岗位匹配摘要。",
            },
            "problem_types": ["ownership_unclear"],
            "why_it_is_weak": "如果简历开头没有清晰主线，面试中的自我介绍和岗位匹配会显得分散。",
            "evidence": unique_keep_order(issues + [", ".join(target_roles), ", ".join(focus)]),
            "rewrite_strategy": "在简历开头增加 2-3 行摘要，明确目标方向、核心项目类型和代表性技术栈",
            "suggested_rewrite": after,
            "rewrite_diff": {
                "before": "当前简历缺少一段明确的岗位匹配摘要。",
                "after": after,
            },
            "placeholders_to_confirm": ["目标岗位", "核心技术栈", "代表项目", "验证指标"],
            "priority": "P1",
            "confidence": "medium",
        }
    ]


def build_rewrite_suggestions(
    profile: dict[str, Any],
    transcript: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_map = collect_evidence_map(transcript, evaluation)
    project_lookup = build_project_lookup(profile)
    risks = profile.get("resume_risks", []) or []

    suggestions: list[dict[str, Any]] = []
    for index, risk in enumerate(risks, start=1):
        suggestions.append(build_rewrite_item(risk, project_lookup, evidence_map, index))

    suggestions.extend(build_summary_rewrite(profile, evidence_map, len(suggestions) + 1))

    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for item in suggestions:
        source_path = normalize_text((item.get("source_anchor") or {}).get("path"))
        key = (item["scope"], item["target_label"], item.get("target_area", ""), source_path)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)

    return {
        "schema_version": "1.0",
        "kind": "resume_rewrite_suggestions",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_profile": normalize_text(profile.get("source", {}).get("source_path")),
        "uses_transcript_evidence": bool(transcript),
        "uses_evaluation_evidence": bool(evaluation),
        "suggestions": deduped,
    }


def render_rewrite_md(result: dict[str, Any]) -> str:
    lines = ["# 简历修改建议", ""]
    suggestions = result.get("suggestions", []) or []
    if not suggestions:
        lines.append("当前没有生成明确的简历修改建议。")
        lines.append("")
        return "\n".join(lines)

    for index, item in enumerate(suggestions, start=1):
        source_anchor = item.get("source_anchor") or {}
        lines.extend(
            [
                f"## {index}. {item['target_label']}",
                f"- 范围：{item['scope']}",
                f"- 优先级：{item['priority']}",
                f"- 原表述：{item['original_text']}",
                f"- 定位：{source_anchor.get('path', 'N/A')}",
                f"- 问题类型：{', '.join(item.get('problem_types', []))}",
                f"- 为什么偏弱：{item['why_it_is_weak']}",
            ]
        )
        matched_by = source_anchor.get("matched_by", []) or []
        if matched_by:
            lines.append("- 命中依据：")
            lines.extend(f"  - {value}" for value in matched_by)
        evidence = item.get("evidence", []) or []
        if evidence:
            lines.append("- 证据：")
            lines.extend(f"  - {value}" for value in evidence[:6])
        lines.append(f"- 改写策略：{item['rewrite_strategy']}")
        lines.append("- 原句 -> 建议改写：")
        lines.append(f"  - 原句：{(item.get('rewrite_diff') or {}).get('before', item['original_text'])}")
        lines.append(f"  - 改写：{(item.get('rewrite_diff') or {}).get('after', item['suggested_rewrite'])}")
        placeholders = item.get("placeholders_to_confirm", []) or []
        if placeholders:
            lines.append("- 待补真实信息：")
            lines.extend(f"  - {value}" for value in placeholders)
        lines.append("")
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], output_dir: Path) -> dict[str, str]:
    json_path = output_dir / "resume_rewrite_suggestions.json"
    md_path = output_dir / "resume_rewrite_suggestions.md"
    write_text(json_path, json.dumps(result, ensure_ascii=False, indent=2))
    write_text(md_path, render_rewrite_md(result))
    return {
        "rewrite_json": str(json_path),
        "rewrite_markdown": str(md_path),
    }


def generate_resume_rewrite_suggestions(
    candidate_profile_json: Path,
    output_dir: Path | None = None,
    transcript_json: Path | None = None,
    evaluation_json: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    profile = load_json(candidate_profile_json)
    if profile is None:
        raise FileNotFoundError(f"Candidate profile not found: {candidate_profile_json}")
    transcript = load_json(transcript_json) if transcript_json else None
    evaluation = load_json(evaluation_json) if evaluation_json else None
    result = build_rewrite_suggestions(profile, transcript=transcript, evaluation=evaluation)
    outputs = write_outputs(result, output_dir or default_output_dir(candidate_profile_json))
    return result, outputs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    profile_json = Path(args.candidate_profile_json).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(profile_json)
    transcript_json = Path(args.transcript_json).resolve() if args.transcript_json else None
    evaluation_json = Path(args.evaluation_json).resolve() if args.evaluation_json else None

    try:
        _, outputs = generate_resume_rewrite_suggestions(
            profile_json,
            output_dir=output_dir,
            transcript_json=transcript_json,
            evaluation_json=evaluation_json,
        )
    except Exception as exc:
        print(f"suggest_resume_rewrites.py failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
