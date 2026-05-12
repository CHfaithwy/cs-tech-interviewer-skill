# Interview Flow Reference

Use this reference for V1.0 session control, command transitions, stage routing, and runtime adjustment behavior.

The live controller is:

- `scripts/interview_session.py`

For natural-language routing on top of the controller, use:

- `scripts/session_router.py`

Mode-specific runtime behavior is defined in:

- `data/interview_mode_profiles.json`

## Runtime Artifacts

Each interview session writes to its own directory, for example:

```text
<name>_session_<timestamp>/
  session_state.json
  transcript.json
  question_selection.json
  question_selection/
    question_selection.json
    question_selection_interview_mode.md
    question_selection_candidate_mode.md
  score_snapshot.json
  score_snapshot.md
  interview_evaluation.json
  interview_evaluation.md
  session_brief.md
```

如果不传 `--sessions-root`，session 默认写到：

- 当前工作目录下的 `./sessions/`

## State Machine

```text
INIT
  -> RESUME_PARSED
  -> CONFIG_READY
  -> RUNNING
  -> PAUSED
  -> REPORT_GENERATION
  -> DONE
```

在 `RUNNING` 状态内，还会按阶段推进：

```text
SELF_INTRO
  -> PROJECT_DEEP_DIVE
  -> CS_FUNDAMENTALS
  -> CODING_INTERVIEW
  -> CANDIDATE_QUESTIONS
```

并不是每种 mode 都会走完整阶段链路。

## Command Semantics

### Session setup

- `init`
- `configure`
- `start`

### Live runtime

- `next`
- `record-answer`
- `hint`
- `skip`
- `repeat`
- `explain`
- `pause`
- `continue`

### Review outputs

- `score`
- `report`
- `reset`

## Mode-Specific Stage Routing

### `完整模拟`

```text
SELF_INTRO -> PROJECT_DEEP_DIVE -> CS_FUNDAMENTALS -> CODING_INTERVIEW -> CANDIDATE_QUESTIONS
```

### `项目深挖`

```text
PROJECT_DEEP_DIVE
```

### `八股快问快答`

```text
CS_FUNDAMENTALS
```

### `算法陪练`

```text
CODING_INTERVIEW
```

### `JD 定向面`

```text
SELF_INTRO -> PROJECT_DEEP_DIVE -> CS_FUNDAMENTALS -> CANDIDATE_QUESTIONS
```

### `简历拷打`

```text
PROJECT_DEEP_DIVE -> CS_FUNDAMENTALS
```

### `复盘教练`

```text
REPORT_GENERATION -> DONE
```

## Strength And Question Budget

强度主要映射到追问深度：

- `拉完了` -> `basic`
- `NPC` -> `basic`
- `人上人` -> `standard`
- `顶级` -> `deep`
- `夯` -> `deep`

## Dynamic Adjustment

当前实现主要在“下一题”这个粒度上做动态调整：

- strong answer
  - 可以继续同主题深挖
- partial answer
  - 当前深度收住，再继续原计划
- weak / wrong answer
  - 不再继续加深当前线程
- skipped answer
  - 记入 transcript，并直接推进

高 hint 使用和 skipped 都会保留在 transcript 里，供 `/score` 和 `/report` 读取。

## Mid-Session Reconfiguration

如果用户在面试进行中改配置，不要立刻重建 question plan。

先把这些改动写进：

- `pending_reconfiguration`

当前阶段结束后再应用。

典型的 deferred keys：

- `/mode`
- `/role`
- `/focus`
- `/strength`
- `/level`
- `/jd`

## No-Resume Degradation

如果没有简历或 candidate profile：

- 跳过 `PROJECT_DEEP_DIVE`
- 保留通用的 `SELF_INTRO`
- 保留 `CS_FUNDAMENTALS`
- 保留 `CODING_INTERVIEW`
- 保留 `CANDIDATE_QUESTIONS`
