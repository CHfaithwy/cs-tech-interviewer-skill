# Interview Transcript Schema

Use this reference as the canonical schema for scored interview evidence in V0.5 and V1.0.

This file describes `transcript.json`, not the live runtime controller state.

Read `references/interview-session-schema.md` for `session_state.json`.

## Purpose

The transcript schema answers three stable questions:

1. What happened in each interview stage?
2. How good was each recorded answer?
3. What weaknesses and next-round recommendations follow from the evidence?

This schema is the shared evidence format for:

- interview-time record keeping
- `/score`
- `/report`
- scripted evaluation with `scripts/evaluate_interview.py`

## Top-Level Shape

```json
{
  "schema_version": "0.5",
  "session": { "...": "..." },
  "answers": [ { "...": "..." } ]
}
```

## `session`

`session` captures identity and configuration context for the transcript.

Example:

```json
{
  "strength": "人上人",
  "tone": "默认",
  "mode": "完整模拟",
  "role": "ai-rag",
  "focus": ["RAG 评估", "知识更新", "MySQL 事务"],
  "resume_path": "<resume-file>",
  "selection_json_path": "<question_selection.json>",
  "session_dir": "<session_dir>"
}
```

Recommended fields:

- `strength`
- `tone`
- `mode`
- `role`
- `focus`
- `jd_title`
- `resume_path`
- `selection_json_path`
- `session_dir`
- `candidate_name`

## `answers`

Each item in `answers` is one scored main-question record.

Example:

```json
{
  "stage": "CS_FUNDAMENTALS",
  "question_id": "db_transaction_mvcc_001",
  "question_text": "MySQL 的事务隔离级别分别解决了哪些并发读写问题？",
  "quality": "partial",
  "score": 3,
  "strengths": ["知道隔离级别的核心概念"],
  "issues": ["MVCC 原理回答不清"],
  "candidate_answer_summary": "能说出几个隔离级别，但 read view 和 undo log 讲不清。",
  "interviewer_feedback": "基础方向没错，但底层机制不稳。",
  "hints_used": 1,
  "skipped": false,
  "duration_seconds": 95
}
```

Required fields:

- `stage`
- `question_id`
- `quality`

Supported `stage` values:

- `SELF_INTRO`
- `PROJECT_DEEP_DIVE`
- `CS_FUNDAMENTALS`
- `CODING_INTERVIEW`
- `CANDIDATE_QUESTIONS`

Supported `quality` values:

- `strong`
- `partial`
- `weak`
- `wrong`

Optional fields:

- `score`
- `strengths`
- `issues`
- `hints_used`
- `skipped`
- `question_text`
- `candidate_answer_summary`
- `interviewer_feedback`
- `duration_seconds`

## Field Rules

- `strengths` and `issues` should be short evidence statements, not vague labels.
- Prefer concrete issues such as `事务隔离级别理解不深入` over broad buckets like `数据库弱`.
- If `skipped` is `true`, keep the record and let downstream scoring see that explicitly.
- If `hints_used` is high, keep that in the record rather than hiding it in prose.
- Do not invent transcript evidence after the fact.

## Relationship To Session State

Use this split consistently:

- `session_state.json`
  - current runtime status
  - current question
  - pending reconfiguration
  - command history
- `transcript.json`
  - scored evidence only

That means:

- `/hint` may update runtime state first
- `/record-answer` or `/skip` is what writes durable transcript evidence

## Downstream Outputs

`scripts/evaluate_interview.py` reads this schema and produces:

- `overall_conclusion`
- `module_scores`
- `stage_scores`
- `weakness_tracking`
- `next_round_recommendation`

Any future `/score` or `/report` implementation should either emit this schema directly or be convertible into it without lossy ad hoc parsing.
