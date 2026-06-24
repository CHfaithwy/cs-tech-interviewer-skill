# LLM Session Orchestration

Use this reference whenever a live interview session exists or the user sends a natural-language control message. The current LLM is responsible for interpreting intent and deciding which local script to call. Do not rely on rule-only routing as the sole source of truth.

## Read State Every Turn

Before replying to the user during a live session, inspect:

- `<session_dir>/session_state.json`
- `<session_dir>/transcript.json`
- `<session_dir>/question_selection/question_selection.json`
- `data/interview_mode_profiles.json`

`session_brief.md` is a derived quick view for humans. Read it only for a fast orientation when useful; do not treat it as source of truth.

Use these to determine:

- `runtime_status`
- `config.mode`, `config.tone`, `config.strength`, `config.level`, `config.focus`
- `config.jd_context`
- `active_stage`
- `current_question`
- `pending_reconfiguration`
- completed and skipped questions
- available commands returned by controller responses

Tone and behavior come from `config.tone`, `config.strength`, mode, and stage:

- `tone=温和`: supportive but still concrete.
- `tone=默认`: professional, direct, moderately strict.
- `tone=铁面`: concise, pressure-oriented, asks sharper follow-ups.
- `strength=人上人/顶级/夯`: expect stronger evidence, deeper tradeoffs, and clearer metrics.
- `strength=NPC/拉完了`: reduce depth and give more guidance.

## Natural-Language Intent To Script Calls

The examples below are semantic patterns, not exact string rules. Use the current state to choose the command.

| User intent | Script call |
| --- | --- |
| start / 开始吧 / 直接开始 | `python cs-tech-interviewer/scripts/interview_session.py start <session_dir>` |
| status / 现在到哪了 | `python cs-tech-interviewer/scripts/interview_session.py status <session_dir>` |
| hint / 给个提示 | `python cs-tech-interviewer/scripts/interview_session.py hint <session_dir>` |
| repeat / 再说一遍 | `python cs-tech-interviewer/scripts/interview_session.py repeat <session_dir>` |
| explain / 解释题意 | `python cs-tech-interviewer/scripts/interview_session.py explain <session_dir>` |
| skip / 这题跳过 | `python cs-tech-interviewer/scripts/interview_session.py skip <session_dir>` |
| pause / 暂停一下 | `python cs-tech-interviewer/scripts/interview_session.py pause <session_dir>` |
| continue / 继续 | `python cs-tech-interviewer/scripts/interview_session.py continue <session_dir>` |
| score / 当前评分 | `python cs-tech-interviewer/scripts/interview_session.py score <session_dir>` |
| report / 结束复盘 | `python cs-tech-interviewer/scripts/interview_session.py report <session_dir>` |
| change mode / 后面改成算法陪练 | `python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --mode 算法陪练 --defer-if-running` |
| change focus / 后面重点问 Redis | `python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --focus Redis --defer-if-running` |
| set JD / 这是岗位描述... | `python cs-tech-interviewer/scripts/interview_session.py jd <session_dir> --jd-text "..." --defer-if-running` |

After every script call, read the updated state or use the command output before responding.

## Candidate Answers

If the input is not a control intent and an active question exists, treat it as a candidate answer:

1. Build or use the judgement prompt from `references/semantic-judge-prompt.md`.
2. Current LLM produces strict JSON.
3. Save the JSON and apply it:

```bash
python cs-tech-interviewer/scripts/apply_llm_answer_judgement.py <session_dir> <judgement.json>
```

4. Read the updated `session_state.json`; ask the next question or report that the stage is complete.

## Asking Questions

- For `PROJECT_DEEP_DIVE`, use `references/project-deep-dive-llm-prompt.md`; do not read a static template question to the candidate.
- For `CS_FUNDAMENTALS`, use the selected local question and `expected_points`, but adapt phrasing to tone and JD.
- For `CODING_INTERVIEW`, use the selected algorithm problem statement, then interactively ask for approach, complexity, code/pseudocode, and edge cases.
- For `CANDIDATE_QUESTIONS`, ask for the candidate's questions and score them semantically afterward.

## When State Is Missing Or Inconsistent

- If no session exists, create or initialize one before accepting live answers.
- If no JD exists, ask for JD or explicit confirmation to continue without JD.
- If `runtime_status` is not compatible with the requested action, explain the next valid action and offer the exact command path.
- If parser/LLM profile artifacts look stale after user corrections, regenerate the LLM profile before selecting questions.
