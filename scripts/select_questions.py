"""Select interview questions from local V0.4 question banks.

The selector reads the V0.3 `candidate_profile.json` output plus optional JD
text/focus/configuration, then emits a deterministic question plan.

Outputs:
- question_selection.json
- question_selection.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = SKILL_DIR / "data"
DEFAULT_KNOWLEDGE_BASE = DEFAULT_DATA_DIR / "fundamental_knowledge_base.json"
DEFAULT_ROLE_PROFILES = DEFAULT_DATA_DIR / "role_profiles.json"

DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}
LEVEL_TO_DIFFICULTY = {
    "简单": "easy",
    "easy": "easy",
    "中等": "medium",
    "medium": "medium",
    "困难": "hard",
    "hard": "hard",
}
STRENGTH_TO_LAYER = {
    "拉完了": "basic",
    "npc": "basic",
    "NPC": "basic",
    "人上人": "standard",
    "顶级": "deep",
    "夯": "deep",
}
LAYER_ORDER = {"basic": 0, "standard": 1, "deep": 2}

ROLE_ALIASES = {
    "backend": ["后端", "服务端", "接口", "java", "spring", "python", "fastapi", "django", "go"],
    "frontend": ["前端", "vue", "react", "浏览器", "小程序", "微信小程序"],
    "fullstack": ["全栈", "前后端", "vue", "react", "fastapi", "django", "spring"],
    "java": ["java", "jvm", "spring", "spring boot"],
    "python": ["python", "fastapi", "django", "flask"],
    "cpp": ["c++", "cpp", "stl", "raii"],
    "algorithm": ["算法", "leetcode", "icpc", "蓝桥杯", "数据结构", "复杂度"],
    "ai": ["ai", "llm", "rag", "agent", "graphrag", "langchain", "langgraph", "模型", "知识库"],
    "data": ["数据", "sql", "etl", "数仓", "neo4j", "mysql"],
    "sre": ["sre", "运维", "linux", "docker", "kubernetes", "监控", "部署"],
    "test": ["测试", "自动化测试", "质量", "ci"],
    "graphics": ["图形学", "几何", "cad", "3d", "siggraph", "toolpath", "mesh"],
}
STOPWORDS = {
    "项目",
    "开发",
    "系统",
    "功能",
    "补充",
    "实现",
    "完成",
    "支持",
    "通过",
    "基于",
    "进行",
    "以及",
    "同时",
    "相关",
    "核心",
    "模块",
    "提升",
    "优化",
}


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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def safe_load_json(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    return load_json(path)


def load_role_profiles(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or DEFAULT_ROLE_PROFILES
    data = safe_load_json(profile_path)
    if not data:
        return {"profiles": {}}
    return data


def normalize_difficulty(value: str | None, default: str = "medium") -> str:
    if not value:
        return default
    return LEVEL_TO_DIFFICULTY.get(value.strip().lower(), LEVEL_TO_DIFFICULTY.get(value.strip(), default))


def trim_text(value: str, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def summarize_jd_text(jd_text: str, jd_counts: Counter[str] | None = None) -> dict[str, Any]:
    text = " ".join(str(jd_text or "").split())
    if not text:
        return {
            "has_jd": False,
            "summary": "",
            "keywords": [],
            "matched_keywords": [],
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

    matched_keywords = [keyword for keyword, _count in (jd_counts or Counter()).most_common(8)]
    summary_parts = []
    if title:
        summary_parts.append(f"目标岗位：{title}")
    if matched_keywords:
        summary_parts.append("重点能力：" + "、".join(matched_keywords[:6]))
    summary = "；".join(summary_parts) if summary_parts else trim_text(text, 120)

    return {
        "has_jd": True,
        "title": title,
        "summary": summary,
        "keywords": matched_keywords[:8],
        "matched_keywords": [{"keyword": keyword, "count": count} for keyword, count in (jd_counts or Counter()).most_common(12)],
        "preview": trim_text(text, 220),
        "source": "user_provided",
    }


def normalize_layer(value: str | None, default: str = "standard") -> str:
    if not value:
        return default
    lowered = value.strip().lower()
    mapping = {
        "basic": "basic",
        "基础": "basic",
        "standard": "standard",
        "标准": "standard",
        "deep": "deep",
        "深挖": "deep",
    }
    return mapping.get(value.strip(), mapping.get(lowered, default))


def normalize_strength_to_layer(value: str | None, default: str = "standard") -> str:
    if not value:
        return default
    return STRENGTH_TO_LAYER.get(value, STRENGTH_TO_LAYER.get(value.strip(), default))


def layer_zh(value: str) -> str:
    return {"basic": "基础", "standard": "标准", "deep": "深挖"}.get(value, value)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def flatten_profile_text(profile: dict[str, Any]) -> str:
    candidate = profile.get("candidate_profile", profile)
    parts: list[str] = []

    for key in ("target_roles", "skills", "projects", "research", "publications", "experience", "internships", "awards", "award_items", "interview_focus"):
        parts.append(normalize_text(candidate.get(key)))
    parts.append(normalize_text(profile.get("resume_risks")))
    return "\n".join(part for part in parts if part)


def extract_profile_keywords(profile: dict[str, Any]) -> Counter[str]:
    candidate = profile.get("candidate_profile", profile)
    keywords: Counter[str] = Counter()

    skills = candidate.get("skills", {})
    if isinstance(skills, dict):
        for values in skills.values():
            if isinstance(values, list):
                keywords.update(str(item) for item in values if str(item).strip())

    for role in candidate.get("target_roles", []) or []:
        keywords[str(role)] += 2

    for focus in candidate.get("interview_focus", []) or []:
        keywords[str(focus)] += 1

    for project in candidate.get("projects", []) or []:
        if not isinstance(project, dict):
            continue
        for value in project.get("tech_stack", []) or []:
            keywords[str(value)] += 2
        for field in ("name", "role", "claims", "metrics"):
            text = normalize_text(project.get(field))
            for token in split_loose_terms(text):
                keywords[token] += 1

    for risk in profile.get("resume_risks", []) or []:
        if not isinstance(risk, dict):
            continue
        for field in ("area", "evidence", "likely_followup", "suggested_fix"):
            for token in split_loose_terms(normalize_text(risk.get(field))):
                keywords[token] += 1

    return Counter({key: value for key, value in keywords.items() if key.strip()})


def split_loose_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_+#./-]{1,}|[\u4e00-\u9fff]{2,}", text):
        value = match.group(0).strip()
        if len(value) > 24 and re.search(r"[\u4e00-\u9fff]", value):
            continue
        if value.lower() in STOPWORDS:
            continue
        terms.append(value)
    return terms


def keyword_pattern(keyword: str) -> str:
    escaped = re.escape(keyword)
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return escaped
    return rf"(?<![A-Za-z0-9_+#./-]){escaped}(?![A-Za-z0-9_+#./-])"


def count_keyword(text: str, keyword: str) -> int:
    if not keyword:
        return 0
    return len(re.findall(keyword_pattern(keyword), text, flags=re.IGNORECASE))


def collect_bank_keywords(fundamental_bank: dict[str, Any], algorithm_bank: dict[str, Any]) -> set[str]:
    keywords: set[str] = set()
    for question in fundamental_bank.get("questions", []):
        keywords.add(str(question.get("topic", "")))
        keywords.add(str(question.get("subtopic", "")))
        keywords.update(str(item) for item in question.get("related_keywords", []) or [])
    for question in algorithm_bank.get("questions", []):
        keywords.update(str(item) for item in question.get("tags", []) or [])
        keywords.update(str(item) for item in question.get("related_keywords", []) or [])
        keywords.add(str(question.get("title", "")))
        keywords.add(str(question.get("title_en", "")))
    for aliases in ROLE_ALIASES.values():
        keywords.update(aliases)
    return {keyword.strip() for keyword in keywords if keyword.strip()}


def extract_known_keyword_counts(text: str, known_keywords: set[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for keyword in known_keywords:
        count = count_keyword(text, keyword)
        if count:
            counts[keyword] = count
    return counts


def infer_roles(profile: dict[str, Any], profile_text: str, jd_text: str, explicit_focus: list[str]) -> set[str]:
    roles: set[str] = set()
    candidate = profile.get("candidate_profile", profile)
    target_role_text = normalize_text(candidate.get("target_roles"))
    primary_haystack = f"{target_role_text}\n{jd_text}\n{' '.join(explicit_focus)}".lower()
    fallback_haystack = profile_text.lower()
    for role, aliases in ROLE_ALIASES.items():
        if any(alias.lower() in primary_haystack for alias in aliases):
            roles.add(role)
            continue
        alias_hits = sum(1 for alias in aliases if alias.lower() in fallback_haystack)
        if alias_hits >= 2:
            roles.add(role)
    return roles


def parse_target_roles(value: str | None, role_profiles: dict[str, Any]) -> list[str]:
    if not value:
        return []
    profiles = role_profiles.get("profiles", {})
    normalized: list[str] = []
    for raw in re.split(r"[,，;；\n]+", value):
        item = raw.strip()
        if not item:
            continue
        lowered = item.lower()
        for profile_name, profile in profiles.items():
            aliases = [alias.lower() for alias in profile.get("aliases", [])]
            if lowered == profile_name or lowered in aliases:
                normalized.append(profile_name)
                break
        else:
            if lowered in ROLE_ALIASES:
                normalized.append(lowered)
                continue
            for role, aliases in ROLE_ALIASES.items():
                if item in aliases or lowered in [alias.lower() for alias in aliases]:
                    normalized.append(role)
                    break
    return unique_keep_order(normalized)


def role_topic_bonus(question: dict[str, Any], roles: list[str], desired_layer: str | None, role_profiles: dict[str, Any]) -> tuple[float, list[str]]:
    if not roles:
        return 0.0, []

    actual_layer = normalize_layer(question.get("layer")) if question.get("layer") else normalize_layer(desired_layer)
    terms = [str(question.get("topic", "")), str(question.get("subtopic", ""))]
    terms.extend(str(item) for item in question.get("related_keywords", []) or [])
    terms.extend(str(item) for item in question.get("role_tags", []) or [])

    score = 0.0
    matched: list[str] = []
    for role in roles:
        weights = role_profiles.get("profiles", {}).get(role, {}).get("layer_priority_terms", {}).get(actual_layer, {})
        for keyword, weight in weights.items():
            if any(term == keyword or count_keyword(term, keyword) or count_keyword(keyword, term) for term in terms):
                score += weight
                matched.append(f"{role}:{keyword}")
    return score, unique_keep_order(matched)


def expand_priority_roles(priority_roles: list[str], role_profiles: dict[str, Any]) -> list[str]:
    expanded: list[str] = []
    for role in priority_roles:
        expanded.append(role)
        profile = role_profiles.get("profiles", {}).get(role)
        if profile:
            expanded.extend(profile.get("base_roles", []))
    return unique_keep_order(expanded)


def parse_focus(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]


def score_question(
    question: dict[str, Any],
    *,
    profile_text: str,
    jd_counts: Counter[str],
    profile_keywords: Counter[str],
    focus_terms: list[str],
    roles: set[str],
    priority_roles: list[str],
    desired_difficulty: str | None,
    desired_layer: str | None,
    role_profiles: dict[str, Any],
    question_kind: str,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    related = [str(item) for item in question.get("related_keywords", []) or []]
    if question_kind == "algorithm":
        related.extend(str(item) for item in question.get("tags", []) or [])
        related.append(str(question.get("title", "")))
        related.append(str(question.get("title_en", "")))
    else:
        related.extend([str(question.get("topic", "")), str(question.get("subtopic", ""))])

    matched_profile: list[str] = []
    for keyword in related:
        if profile_keywords.get(keyword) or count_keyword(profile_text, keyword):
            score += 4.0 + min(profile_keywords.get(keyword, 0), 3) * 0.5
            matched_profile.append(keyword)
    if matched_profile:
        reasons.append("简历匹配：" + "、".join(unique_keep_order(matched_profile)[:5]))

    matched_jd = []
    for keyword in related:
        if jd_counts.get(keyword):
            score += 3.0 + min(jd_counts[keyword], 5) * 0.6
            matched_jd.append(keyword)
    if matched_jd:
        reasons.append("JD 匹配：" + "、".join(unique_keep_order(matched_jd)[:5]))

    matched_focus = []
    for focus in focus_terms:
        if any(count_keyword(focus, keyword) or count_keyword(keyword, focus) for keyword in related):
            score += 6.0
            matched_focus.append(focus)
    if matched_focus:
        reasons.append("命中 /focus：" + "、".join(unique_keep_order(matched_focus)[:3]))

    role_tags = {str(item).lower() for item in question.get("role_tags", []) or []}
    matched_roles = sorted(role_tags & {role.lower() for role in roles})
    if matched_roles:
        score += 2.5 * len(matched_roles)
        reasons.append("方向匹配：" + "、".join(matched_roles[:4]))

    if desired_difficulty:
        actual = normalize_difficulty(str(question.get("difficulty", "")))
        gap = abs(DIFFICULTY_ORDER.get(actual, 1) - DIFFICULTY_ORDER.get(desired_difficulty, 1))
        if gap == 0:
            score += 5.0
            reasons.append(f"难度匹配：{difficulty_zh(actual)}")
        elif gap == 1:
            score -= 2.0
        else:
            score -= 5.0

    if question_kind == "fundamental" and desired_layer:
        actual_layer = normalize_layer(str(question.get("layer", "")))
        gap = abs(LAYER_ORDER.get(actual_layer, 1) - LAYER_ORDER.get(desired_layer, 1))
        if gap == 0:
            score += 5.0
            reasons.append(f"层级匹配：{layer_zh(actual_layer)}")
        elif gap == 1:
            score -= 1.5
        else:
            score -= 4.0

    if question_kind == "fundamental":
        bonus, matched = role_topic_bonus(question, priority_roles, desired_layer, role_profiles)
        if bonus:
            score += bonus
            reasons.append("角色偏置：" + "、".join(matched[:5]))

    if not reasons:
        score += 0.1
        reasons.append("通用默认题")

    return score, reasons


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        clean = item.strip()
        lowered = clean.lower()
        if not clean or lowered in seen:
            continue
        seen.add(lowered)
        result.append(clean)
    return result


def build_knowledge_lookup(knowledge_base: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not knowledge_base:
        return [], []
    return knowledge_base.get("entries", []) or [], knowledge_base.get("topic_packs", []) or []


def score_knowledge_entry(entry: dict[str, Any], question: dict[str, Any]) -> float:
    score = 0.0
    question_terms = [str(question.get("topic", "")), str(question.get("subtopic", ""))]
    question_terms.extend(str(item) for item in question.get("related_keywords", []) or [])
    if "tags" in question:
        question_terms.extend(str(item) for item in question.get("tags", []) or [])
    title_text = str(entry.get("title", ""))
    desc_text = str(entry.get("description", ""))
    headings_text = " ".join(entry.get("headings", []))

    if count_keyword(title_text, str(question.get("subtopic", ""))):
        score += 4.0
    if count_keyword(title_text, str(question.get("topic", ""))):
        score += 3.0
    for term in question_terms:
        if not term:
            continue
        if term in entry.get("keywords", []):
            score += 1.5
        title_hits = count_keyword(title_text, term)
        if title_hits:
            score += 4.0 * title_hits
        if count_keyword(desc_text, term):
            score += 1.5
        if count_keyword(headings_text, term):
            score += 2.0
    if str(entry.get("topic")) == str(question.get("topic")):
        score += 2.0
    if str(entry.get("subtopic")) == str(question.get("subtopic")):
        score += 2.0
    return score


def attach_knowledge_refs(
    selected_items: list[dict[str, Any]],
    knowledge_entries: list[dict[str, Any]],
    topic_packs: list[dict[str, Any]],
) -> None:
    for item in selected_items:
        question = item["question"]
        scored_entries = []
        for entry in knowledge_entries:
            score = score_knowledge_entry(entry, question)
            if score > 0:
                scored_entries.append((score, entry))
        scored_entries.sort(key=lambda pair: (-pair[0], pair[1].get("title", ""), pair[1].get("id", "")))
        refs = [
            {
                "id": entry["id"],
                "title": entry["title"],
                "topic": entry["topic"],
                "subtopic": entry["subtopic"],
            }
            for _, entry in scored_entries[:4]
        ]
        if refs:
            question["knowledge_refs"] = refs

        pack_refs = []
        for pack in topic_packs:
            if pack.get("topic") == question.get("topic") or pack.get("subtopic") == question.get("subtopic"):
                pack_refs.append(pack)
            elif any(keyword in pack.get("keywords", []) for keyword in question.get("related_keywords", []) or []):
                pack_refs.append(pack)
        if pack_refs:
            question["knowledge_packs"] = [
                {
                    "id": pack["id"],
                    "topic": pack["topic"],
                    "subtopic": pack["subtopic"],
                    "entry_count": pack["entry_count"],
                }
                for pack in pack_refs[:3]
            ]


def difficulty_zh(value: str) -> str:
    return {"easy": "简单", "medium": "中等", "hard": "困难"}.get(value, value)


def build_interviewer_fundamental_item(item: dict[str, Any]) -> dict[str, Any]:
    question = item["question"]
    result = {
        "id": question.get("id"),
        "question": question.get("question"),
        "topic": question.get("topic"),
        "subtopic": question.get("subtopic"),
        "layer": normalize_layer(question.get("layer")),
        "layer_zh": layer_zh(normalize_layer(question.get("layer"))),
        "difficulty": normalize_difficulty(question.get("difficulty")),
        "difficulty_zh": difficulty_zh(normalize_difficulty(question.get("difficulty"))),
        "selection_reasons": item.get("reasons", []),
        "expected_points": question.get("expected_points", []),
        "followups": question.get("followups", []),
        "related_keywords": question.get("related_keywords", []),
    }
    refs = question.get("knowledge_refs", []) or []
    if refs:
        result["knowledge_refs"] = refs
    packs = question.get("knowledge_packs", []) or []
    if packs:
        result["knowledge_packs"] = packs
    return result


def build_interviewer_algorithm_item(item: dict[str, Any]) -> dict[str, Any]:
    question = item["question"]
    return {
        "id": question.get("id"),
        "title": question.get("title"),
        "title_en": question.get("title_en"),
        "difficulty": normalize_difficulty(question.get("difficulty")),
        "difficulty_zh": difficulty_zh(normalize_difficulty(question.get("difficulty"))),
        "tags": question.get("tags", []),
        "source": question.get("source", []),
        "selection_reasons": item.get("reasons", []),
        "expected_approaches": question.get("expected_approaches", []),
        "hints": question.get("hints", []),
        "edge_cases": question.get("edge_cases", []),
        "public_release_mode": question.get("public_release_mode", ""),
    }


def build_candidate_algorithm_item(item: dict[str, Any]) -> dict[str, Any]:
    question = item["question"]
    return {
        "id": question.get("id"),
        "title": question.get("title"),
        "title_en": question.get("title_en"),
        "difficulty": normalize_difficulty(question.get("difficulty")),
        "difficulty_zh": difficulty_zh(normalize_difficulty(question.get("difficulty"))),
        "problem_statement_text": question.get("prompt", ""),
        "public_release_mode": question.get("public_release_mode", ""),
        "note": "Public repository build keeps a local rewritten prompt and metadata, without bundling official source HTML, images, or direct links.",
    }


def build_view_payloads(selection: dict[str, Any]) -> dict[str, Any]:
    interviewer_fundamentals = [build_interviewer_fundamental_item(item) for item in selection.get("selected_fundamentals", [])]
    interviewer_algorithms = [build_interviewer_algorithm_item(item) for item in selection.get("selected_algorithms", [])]
    candidate_algorithms = [build_candidate_algorithm_item(item) for item in selection.get("selected_algorithms", [])]

    return {
        "interview_mode": {
            "meta": {
                "generated_at": selection.get("generated_at"),
                "mode": selection.get("config", {}).get("mode"),
                "level": selection.get("config", {}).get("level"),
                "normalized_algorithm_difficulty": selection.get("config", {}).get("normalized_algorithm_difficulty"),
                "jd_context": selection.get("jd_context", {}),
                "focus_terms": selection.get("keyword_summary", {}).get("focus_terms", []),
                "inferred_roles": selection.get("keyword_summary", {}).get("inferred_roles", []),
                "priority_roles": selection.get("keyword_summary", {}).get("priority_roles", []),
                "expanded_priority_roles": selection.get("keyword_summary", {}).get("expanded_priority_roles", []),
            },
            "fundamentals": interviewer_fundamentals,
            "algorithms": interviewer_algorithms,
        },
        "candidate_mode": {
            "meta": {
                "generated_at": selection.get("generated_at"),
                "mode": selection.get("config", {}).get("mode"),
                "level": selection.get("config", {}).get("level"),
                "jd_context": selection.get("jd_context", {}),
            },
            "algorithms": candidate_algorithms,
        },
    }


def build_legacy_selection(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "jd_context": selection.get("jd_context", {}),
        "selected_fundamentals": selection.get("selected_fundamentals", []),
        "selected_algorithms": selection.get("selected_algorithms", []),
        "note": "Legacy compatibility container. Prefer view_payloads for new integrations.",
    }


def finalize_selection(selection: dict[str, Any]) -> dict[str, Any]:
    selection["compatibility"] = {
        "selected_fundamentals": "deprecated_top_level_alias",
        "selected_algorithms": "deprecated_top_level_alias",
        "preferred_machine_readable": "view_payloads",
        "preferred_legacy_group": "legacy_selection",
        "alias_semantics": {
            "selected_fundamentals": "equivalent_to legacy_selection.selected_fundamentals",
            "selected_algorithms": "equivalent_to legacy_selection.selected_algorithms",
        },
        "migration_plan": {
            "target_schema_version": "0.5",
            "planned_change": "top_level selected_* fields may be removed after downstream integrations migrate to view_payloads or legacy_selection",
        },
    }
    selection["legacy_selection"] = build_legacy_selection(selection)
    selection["view_payloads"] = build_view_payloads(selection)
    return selection


def pick_diverse(
    scored: list[dict[str, Any]],
    *,
    limit: int,
    diversity_key: str,
    max_per_key: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for item in scored:
        question = item["question"]
        key = str(question.get(diversity_key, ""))
        if diversity_key == "tags":
            tags = question.get("tags", []) or []
            key = str(tags[0]) if tags else ""
        if key and counts[key] >= max_per_key:
            continue
        selected.append(item)
        if key:
            counts[key] += 1
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        selected_ids = {item["question"].get("id") for item in selected}
        for item in scored:
            if item["question"].get("id") in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
    return selected


def select_questions(
    profile: dict[str, Any],
    jd_text: str,
    focus_terms: list[str],
    level: str,
    mode: str,
    strength: str | None,
    fundamental_layer: str | None,
    target_roles: list[str],
    role_profiles: dict[str, Any],
    fundamental_bank: dict[str, Any],
    algorithm_bank: dict[str, Any],
    knowledge_base: dict[str, Any] | None,
    fundamentals_count: int,
    algorithms_count: int,
) -> dict[str, Any]:
    profile_text = flatten_profile_text(profile)
    profile_keywords = extract_profile_keywords(profile)
    known_keywords = collect_bank_keywords(fundamental_bank, algorithm_bank)
    jd_counts = extract_known_keyword_counts(jd_text, known_keywords)
    roles = infer_roles(profile, profile_text, jd_text, focus_terms)
    desired_difficulty = normalize_difficulty(level)
    desired_layer = normalize_layer(fundamental_layer) if fundamental_layer else normalize_strength_to_layer(strength)
    priority_roles = target_roles or sorted(roles)
    expanded_priority_roles = expand_priority_roles(priority_roles, role_profiles)

    fundamental_scored: list[dict[str, Any]] = []
    for question in fundamental_bank.get("questions", []):
        score, reasons = score_question(
            question,
            profile_text=profile_text,
            jd_counts=jd_counts,
            profile_keywords=profile_keywords,
            focus_terms=focus_terms,
            roles=roles,
            priority_roles=expanded_priority_roles,
            desired_difficulty=None,
            desired_layer=desired_layer,
            role_profiles=role_profiles,
            question_kind="fundamental",
        )
        fundamental_scored.append({"question": question, "score": round(score, 2), "reasons": reasons})

    algorithm_scored: list[dict[str, Any]] = []
    for question in algorithm_bank.get("questions", []):
        score, reasons = score_question(
            question,
            profile_text=profile_text,
            jd_counts=jd_counts,
            profile_keywords=profile_keywords,
            focus_terms=focus_terms,
            roles=roles,
            priority_roles=expanded_priority_roles,
            desired_difficulty=desired_difficulty,
            desired_layer=None,
            role_profiles=role_profiles,
            question_kind="algorithm",
        )
        algorithm_scored.append({"question": question, "score": round(score, 2), "reasons": reasons})

    fundamental_scored.sort(key=lambda item: (-item["score"], item["question"].get("topic", ""), item["question"].get("id", "")))
    algorithm_scored.sort(key=lambda item: (-item["score"], DIFFICULTY_ORDER.get(normalize_difficulty(item["question"].get("difficulty")), 1), item["question"].get("id", "")))

    if mode in ("算法陪练", "algorithm", "coding"):
        fundamentals_count = min(fundamentals_count, 2)
        algorithms_count = max(algorithms_count, 3)
    elif mode in ("八股快问快答", "fundamentals"):
        fundamentals_count = max(fundamentals_count, 8)
        algorithms_count = min(algorithms_count, 1)
    elif mode in ("JD 定向面", "jd"):
        fundamentals_count = max(fundamentals_count, 6)

    selected_fundamentals = pick_diverse(
        fundamental_scored,
        limit=fundamentals_count,
        diversity_key="topic",
        max_per_key=2,
    )
    selected_algorithms = pick_diverse(
        algorithm_scored,
        limit=algorithms_count,
        diversity_key="tags",
        max_per_key=2,
    )

    knowledge_entries, topic_packs = build_knowledge_lookup(knowledge_base)
    attach_knowledge_refs(selected_fundamentals, knowledge_entries, topic_packs)

    keyword_summary = {
        "profile_top_keywords": profile_keywords.most_common(20),
        "jd_matched_keywords": jd_counts.most_common(20),
        "inferred_roles": sorted(roles),
        "priority_roles": priority_roles,
        "expanded_priority_roles": expanded_priority_roles,
        "focus_terms": focus_terms,
    }
    jd_context = summarize_jd_text(jd_text, jd_counts)

    return {
        "schema_version": "0.4",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "level": level,
            "strength": strength,
            "fundamental_layer": desired_layer,
            "normalized_algorithm_difficulty": desired_difficulty,
            "mode": mode,
            "fundamentals_count": fundamentals_count,
            "algorithms_count": algorithms_count,
        },
        "jd_context": jd_context,
        "keyword_summary": keyword_summary,
        "knowledge_base_summary": {
            "enabled": bool(knowledge_entries),
            "entry_count": len(knowledge_entries),
            "topic_pack_count": len(topic_packs),
        },
        "selected_fundamentals": selected_fundamentals,
        "selected_algorithms": selected_algorithms,
    }


def render_question_selection_md(selection: dict[str, Any], view: str) -> str:
    lines = [
        "# V0.4 自动选题结果",
        "",
        f"- 生成时间：{selection.get('generated_at')}",
        f"- 面试模式：{selection.get('config', {}).get('mode')}",
        f"- 算法难度：{selection.get('config', {}).get('level')}",
        f"- 输出视图：{view}",
        "",
    ]

    summary = selection.get("keyword_summary", {})
    jd_context = selection.get("jd_context", {}) or {}
    if jd_context.get("summary"):
        lines.extend(
            [
                "## JD Context",
                f"- JD 语境：{jd_context.get('summary')}",
                f"- 岗位标题：{jd_context.get('title') or '未提取'}",
                "",
            ]
        )

    if view == "interview_mode":
        roles = summary.get("inferred_roles", [])
        focus_terms = summary.get("focus_terms", [])
        jd_keywords = summary.get("jd_matched_keywords", [])
        profile_keywords = summary.get("profile_top_keywords", [])

        lines.extend(["", "## 关键词摘要"])
        lines.append(f"- 推断方向：{', '.join(roles) if roles else '未明确'}")
        lines.append(f"- /focus：{', '.join(focus_terms) if focus_terms else '未指定'}")
        if jd_keywords:
            lines.append("- JD 命中关键词：" + "、".join(f"{key}({count})" for key, count in jd_keywords[:10]))
        if profile_keywords:
            lines.append("- 简历高频关键词：" + "、".join(f"{key}({count})" for key, count in profile_keywords[:10]))

        lines.extend(["", "## 八股 / CS 基础题"])
        for index, item in enumerate(selection.get("selected_fundamentals", []), start=1):
            question = item["question"]
            lines.extend(
                [
                    "",
                    f"### {index}. {question.get('question')}",
                    f"- ID：{question.get('id')}",
                    f"- 主题：{question.get('topic')} / {question.get('subtopic')}",
                    f"- 层级：{layer_zh(normalize_layer(question.get('layer')))}",
                    f"- 难度：{difficulty_zh(normalize_difficulty(question.get('difficulty')))}",
                    f"- 选择原因：{'; '.join(item.get('reasons', []))}",
                    "- 期望要点：" + "；".join(question.get("expected_points", [])[:4]),
                    "- 追问：" + "；".join(question.get("followups", [])[:3]),
                ]
            )
            refs = question.get("knowledge_refs", []) or []
            if refs:
                lines.append("- 本地资料：" + "；".join(f"{ref['title']}（{ref['topic']} / {ref['subtopic']}）" for ref in refs[:3]))

        lines.extend(["", "## 算法题卡片"])
        for index, item in enumerate(selection.get("selected_algorithms", []), start=1):
            question = item["question"]
            lines.extend(
                [
                    "",
                    f"### {index}. {question.get('title')} ({question.get('title_en')})",
                    f"- ID：{question.get('id')}",
                    f"- 难度：{difficulty_zh(normalize_difficulty(question.get('difficulty')))}",
                    f"- 标签：{'、'.join(question.get('tags', []))}",
                    f"- 选择原因：{'; '.join(item.get('reasons', []))}",
                ]
            )
    else:
        lines.extend(["", "## 算法题目"])
        for index, item in enumerate(selection.get("selected_algorithms", []), start=1):
            question = item["question"]
            problem_statement = str(question.get("problem_statement_text") or question.get("prompt") or "").strip()
            lines.extend(
                [
                    "",
                    f"### {index}. {question.get('title')} ({question.get('title_en')})",
                    f"- 难度：{difficulty_zh(normalize_difficulty(question.get('difficulty')))}",
                    f"- 标签：{'、'.join(question.get('tags', []))}",
                ]
            )
            if problem_statement:
                lines.extend(
                    [
                        "",
                        "```text",
                        problem_statement,
                        "```",
                    ]
                )
            else:
                lines.append("- 当前仓库版未附带更长题面，仅保留本地算法题提示与元信息。")

    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select CS interview questions from local V0.4 question banks.")
    parser.add_argument(
        "profile_json",
        nargs="?",
        help="Path to V0.3 candidate_profile.json. If omitted, selects from JD/focus and generic local topics.",
    )
    parser.add_argument("--jd-file", help="Path to target JD text file.")
    parser.add_argument("--jd-text", help="Inline target JD text.")
    parser.add_argument("--focus", help="Comma-separated focus terms, same meaning as /focus.")
    parser.add_argument(
        "--target-role",
        help="Preferred role bias for fundamentals selection, for example backend, ai, java, data, sre.",
    )
    parser.add_argument("--strength", help="Interview strength: 夯, 顶级, 人上人, NPC, 拉完了.")
    parser.add_argument("--level", default="中等", help="Algorithm difficulty: 简单, 中等, 困难. Default: 中等.")
    parser.add_argument("--mode", default="完整模拟", help="Interview mode. Default: 完整模拟.")
    parser.add_argument(
        "--fundamental-layer",
        choices=["basic", "standard", "deep"],
        help="Override fundamentals layering directly. If omitted, infer from --strength.",
    )
    parser.add_argument(
        "--view",
        choices=["interview_mode", "candidate_mode"],
        default="interview_mode",
        help="Output view. interview_mode shows interviewer metadata; candidate_mode shows only candidate-facing algorithm problems.",
    )
    parser.add_argument("--fundamentals-count", type=int, default=5, help="Number of CS fundamentals questions.")
    parser.add_argument("--algorithms-count", type=int, default=2, help="Number of algorithm questions.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Question bank data directory.")
    parser.add_argument(
        "--knowledge-base",
        default=str(DEFAULT_KNOWLEDGE_BASE),
        help="Optional fundamentals knowledge base JSON. Default: data/fundamental_knowledge_base.json",
    )
    parser.add_argument(
        "--role-profiles",
        default=str(DEFAULT_ROLE_PROFILES),
        help="Role profile configuration JSON. Default: data/role_profiles.json",
    )
    parser.add_argument("-o", "--output-dir", help="Output directory. Defaults to <profile dir>/question_selection or ./question_selection.")
    return parser.parse_args(argv)


def default_output_dir(profile_json: str | None) -> Path:
    if profile_json:
        return Path(profile_json).resolve().parent / "question_selection"
    return Path.cwd() / "question_selection"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    data_dir = Path(args.data_dir).resolve()
    fundamental_bank = load_json(data_dir / "fundamental_questions.json")
    algorithm_bank = load_json(data_dir / "algorithm_questions.json")
    knowledge_base = safe_load_json(Path(args.knowledge_base).resolve()) if args.knowledge_base else None
    role_profiles = load_role_profiles(Path(args.role_profiles).resolve()) if args.role_profiles else {"profiles": {}}

    profile: dict[str, Any] = {}
    if args.profile_json:
        profile = load_json(Path(args.profile_json).resolve())

    jd_parts = []
    if args.jd_text:
        jd_parts.append(args.jd_text)
    if args.jd_file:
        jd_parts.append(read_text(Path(args.jd_file).resolve()))
    jd_text = "\n".join(jd_parts)

    selection = select_questions(
        profile,
        jd_text=jd_text,
        focus_terms=parse_focus(args.focus),
        level=args.level,
        mode=args.mode,
        strength=args.strength,
        fundamental_layer=args.fundamental_layer,
        target_roles=parse_target_roles(args.target_role, role_profiles),
        role_profiles=role_profiles,
        fundamental_bank=fundamental_bank,
        algorithm_bank=algorithm_bank,
        knowledge_base=knowledge_base,
        fundamentals_count=max(args.fundamentals_count, 0),
        algorithms_count=max(args.algorithms_count, 0),
    )
    selection = finalize_selection(selection)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.profile_json)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "question_selection.json"
    md_path = output_dir / f"question_selection_{args.view}.md"
    default_md_path = output_dir / "question_selection.md"
    write_text(json_path, json.dumps(selection, ensure_ascii=False, indent=2))
    write_text(md_path, render_question_selection_md(selection, args.view))
    write_text(default_md_path, render_question_selection_md(selection, "interview_mode"))

    print(
        json.dumps(
            {
                "ok": True,
                "outputs": {
                    "question_selection_json": str(json_path),
                    "question_selection_md": str(md_path),
                    "question_selection_md_default": str(default_md_path),
                    "view": args.view,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
