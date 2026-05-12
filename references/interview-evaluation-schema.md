# Interview Evaluation Schema

Use this file as the canonical schema for `interview_evaluation.json`.

This schema describes the post-interview structured review artifact, not:

- `session_state.json`
- `transcript.json`

Read together with:

- `references/interview-session-schema.md`
- `references/interview-transcript-schema.md`

## Purpose

`interview_evaluation.json` is the machine-readable source of truth for:

- final `/report`
- structured review exports
- resume rewrite suggestions enhanced by interview evidence
- next-round mock recommendations

## Top-Level Shape

```json
{
  "schema_version": "1.0",
  "kind": "interview_evaluation",
  "generated_at": "...",
  "overall_conclusion": { "...": "..." },
  "module_scores": { "...": "..." },
  "stage_scores": { "...": "..." },
  "highlights": [],
  "issues": [],
  "weakness_tracking": [],
  "review_priorities": [],
  "project_risk_map": [],
  "fundamentals_gap_list": [],
  "algorithm_breakdown": [],
  "jd_fit_gaps": [],
  "resume_risk_map": [],
  "resume_rewrite_suggestions": [],
  "next_round_recommendation": {},
  "report_sections": []
}
```

## Required Stable Blocks

- `overall_conclusion`
- `module_scores`
- `stage_scores`
- `highlights`
- `issues`
- `weakness_tracking`
- `review_priorities`
- `next_round_recommendation`
- `report_sections`

## Mode-Specific Blocks

- `project_risk_map`
- `fundamentals_gap_list`
- `algorithm_breakdown`
- `jd_fit_gaps`
- `resume_risk_map`
- `resume_rewrite_suggestions`

These are populated according to `data/interview_mode_profiles.json`.

## `overall_conclusion`

Example:

```json
{
  "strength": "人上人",
  "tone": "默认",
  "mode": "完整模拟",
  "target_role": "ai-rag",
  "total_score": 65,
  "grade": "C",
  "verdict": "存在明显薄弱点，建议先做针对性训练后再进入更高强度模拟。"
}
```

## `review_priorities`

Machine-readable action items for P0/P1/P2 follow-up work.

Example:

```json
[
  {
    "priority": "P0",
    "topic": "需要较多提示",
    "recommended_action": "优先补基础知识与项目深挖能力",
    "mode_bias": "完整模拟"
  }
]
```

## `resume_rewrite_suggestions`

Each suggestion item uses this shape:

```json
{
  "id": "rewrite_001",
  "scope": "project",
  "target_label": "某智能问答平台项目",
  "target_area": "RAG / GraphRAG 方案深度",
  "original_text": "负责检索、图谱构建和问答接口开发。",
  "source_anchor": {
    "source_kind": "project_claim",
    "path": "candidate_profile.projects[0].claims[2]",
    "claim_index": 2,
    "matched_by": ["keyword:GraphRAG"],
    "match_score": 10
  },
  "problem_types": ["ownership_unclear", "missing_metrics"],
  "why_it_is_weak": "表述容易被追问，但缺少量化结果和职责边界。",
  "evidence": ["指标口径追问", "项目指标不够量化"],
  "rewrite_strategy": "明确职责边界，并补 baseline、指标和评测方式。",
  "suggested_rewrite": "...",
  "placeholders_to_confirm": ["P95 latency", "sample size", "baseline"],
  "priority": "P0",
  "confidence": "high"
}
```

Rules:

- never invent numbers
- use placeholders when exact metrics are unknown
- preserve uncertainty explicitly
- for project-scoped suggestions, prefer binding to the most relevant original `projects[].claims[]` sentence

## `report_sections`

This array determines which markdown sections should be rendered.

Example keys:

- `module_scores`
- `stage_scores`
- `highlights`
- `issues`
- `weakness_tracking`
- `project_risk_map`
- `fundamentals_gap_list`
- `algorithm_breakdown`
- `jd_fit_gaps`
- `resume_risk_map`
- `resume_rewrite`
- `next_round`

## Compatibility

Legacy evaluation consumers may still rely on:

- `module_scores`
- `stage_scores`
- `weakness_tracking`
- `next_round_recommendation`

These remain preserved in V1.0.
