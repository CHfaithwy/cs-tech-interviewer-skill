# Interview Session Schema

Use this reference as the canonical runtime schema for the V1.0 interview state machine.

`session_state.json` is the live session artifact. It is separate from `transcript.json` on purpose:

- `session_state.json` answers: “Where is the interview right now?”
- `transcript.json` answers: “What evidence has already happened?”

That split keeps runtime control, deferred reconfiguration, and current-question navigation out of the transcript evidence model.

## Top-Level Shape

```json
{
  "schema_version": "1.0",
  "session_id": "ab12cd34ef56",
  "runtime_status": "RUNNING",
  "active_stage": "PROJECT_DEEP_DIVE",
  "stage_sequence": ["SELF_INTRO", "PROJECT_DEEP_DIVE", "CS_FUNDAMENTALS"],
  "config": { ... },
  "artifacts": { ... },
  "question_plan": { ... },
  "current_question": { ... },
  "progress": { ... },
  "pending_reconfiguration": { ... },
  "command_history": [ ... ]
}
```

## `runtime_status`

Supported values:

- `INIT`
- `RESUME_PARSED`
- `CONFIG_READY`
- `RUNNING`
- `PAUSED`
- `REPORT_GENERATION`
- `DONE`

Meaning:

- `INIT`: session folder exists, but no usable resume/profile/config is ready yet.
- `RESUME_PARSED`: structured profile exists; configuration still needs confirmation.
- `CONFIG_READY`: config and question plan are ready; interview has not started.
- `RUNNING`: a live question is active.
- `PAUSED`: interview is suspended, but current question is preserved.
- `REPORT_GENERATION`: questioning is over; the system should produce score/report outputs.
- `DONE`: final report has been generated.

## `config`

Recommended fields:

```json
{
  "role": "ai-rag",
  "strength": "人上人",
  "tone": "默认",
  "level": "中等",
  "mode": "完整模拟",
  "focus": ["RAG 评估", "MySQL 事务"],
  "jd_text": "...",
  "fundamentals_count": 5,
  "algorithms_count": 2,
  "view": "interview_mode"
}
```

These values are the frozen config for the current planning pass.

If the user changes core config mid-session, write those changes into `pending_reconfiguration` first. Apply them only after the current stage finishes.

## `artifacts`

`artifacts` stores file paths that belong to this session:

```json
{
  "candidate_profile_json": ".../candidate_profile.json",
  "question_selection_json": ".../question_selection/question_selection.json",
  "transcript_json": ".../transcript.json",
  "score_snapshot_json": ".../score_snapshot.json",
  "score_snapshot_md": ".../score_snapshot.md",
  "evaluation_json": ".../interview_evaluation.json",
  "evaluation_md": ".../interview_evaluation.md"
}
```

## `question_plan`

`question_plan` is a stage-keyed map of normalized question nodes.

Each node should look like:

```json
{
  "stage": "CS_FUNDAMENTALS",
  "question_id": "redis_cache_consistency_001",
  "question_text": "如果 Redis 缓存和数据库出现不一致，你会如何设计更新策略？",
  "prompt_block": "...",
  "metadata": {
    "kind": "fundamental",
    "topic": "Redis",
    "difficulty": "medium"
  }
}
```

The important rule is: this is a runtime queue, not an evidence record.

## `current_question`

`current_question` is the active node being discussed right now.

It may add runtime-only fields such as:

- `hint_level`

These fields should not be backfilled into the transcript until the question is scored or skipped.

## `progress`

Recommended fields:

```json
{
  "question_counts": {
    "PROJECT_DEEP_DIVE": 2
  },
  "completed_question_ids": [
    "self_intro_001",
    "ai_agent_tool_call_001"
  ],
  "hints_used_total": 3,
  "skipped_total": 1
}
```

## `pending_reconfiguration`

This object stores deferred config edits made during `RUNNING` or `PAUSED`.

Typical examples:

```json
{
  "focus": ["Redis", "MySQL"],
  "mode": "算法陪练"
}
```

When the current stage completes, the controller should:

1. merge `pending_reconfiguration` into `config`
2. rebuild future question selection and question plan
3. clear `pending_reconfiguration`

Already completed transcript evidence must not be rewritten.

## `command_history`

Recommended shape:

```json
[
  {
    "timestamp": "2026-05-11T22:10:00",
    "command": "hint",
    "payload": {
      "question_id": "lc_42_trapping_rain_water",
      "hint_level": 2
    }
  }
]
```

This is useful for debugging session flow and understanding why the runtime state changed.

## Relationship To Transcript Schema

`references/interview-transcript-schema.md` remains the source of truth for scored interview evidence.

Use this split consistently:

- `session_state.json`: runtime control and navigation
- `transcript.json`: scored question records

Future `/score`, `/report`, and evaluation scripts should read transcript evidence, while `/start`, `/pause`, `/continue`, `/next`, and deferred reconfiguration should read session state.
