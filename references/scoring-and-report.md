# Scoring And Report Reference

Use this reference for `/score`, `/report`, resume rewrite suggestions, and post-interview coaching.

Read these files together:

- `references/interview-session-schema.md`
- `references/interview-transcript-schema.md`
- `references/interview-evaluation-schema.md`

Mode-specific scoring and report emphasis come from:

- `data/interview_mode_profiles.json`

## V1.0 Session-Aware Flow

For a live V1.0 session, prefer using `scripts/interview_session.py`:

```bash
python cs-tech-interviewer/scripts/interview_session.py score <session_dir>
python cs-tech-interviewer/scripts/interview_session.py report <session_dir>
```

This writes outputs into the same session directory:

```text
<session_dir>/
  score_snapshot.json
  score_snapshot.md
  interview_evaluation.json
  interview_evaluation.md
```

## Standalone Evaluation

Use `scripts/evaluate_interview.py` when you already have a structured transcript and want:

- stage-level scoring
- weakness tracking
- next-round mock recommendations
- a compact machine-readable evaluation artifact

Examples:

```bash
python cs-tech-interviewer/scripts/evaluate_interview.py <transcript.json>
python cs-tech-interviewer/scripts/evaluate_interview.py <transcript.json> --profile-json <candidate_profile.json>
python cs-tech-interviewer/scripts/evaluate_interview.py <transcript.json> --profile-json <candidate_profile.json> --selection-json <question_selection.json>
```

The standalone script outputs:

```text
<transcript stem>_evaluation/
  interview_evaluation.json
  interview_evaluation.md
```

`interview_evaluation.json` is the machine-readable source of truth for the final structured review output.

## Score Bands

| Score | Grade | Meaning |
|---:|---|---|
| 90-100 | A | Excellent; ready for high-intensity interviews. |
| 80-89 | B+ | Strong foundation with a few gaps. |
| 70-79 | B | Can handle ordinary technical interviews, but project depth or fundamentals need work. |
| 60-69 | C | Obvious weaknesses; needs systematic review. |
| 0-59 | D | Not recommended to enter formal interviews yet. |

## Module Weights

| Module | Weight | Evaluate |
|---|---:|---|
| Self Introduction | 10 | Clarity, concision, role fit, highlights |
| Project Depth | 30 | Architecture, hard points, tradeoffs, metrics, ownership |
| CS Fundamentals | 20 | OS, networking, database, language, engineering basics |
| Algorithm Ability | 25 | Understanding, approach, code, complexity, edge cases |
| Communication | 10 | Structure, interaction, pressure handling |
| Candidate Questions | 5 | Specificity, relevance, seniority awareness |

## Mode-Specific Weighting

- `项目深挖`
  - project-heavy weighting
  - report emphasizes project risk, ownership, metrics, and resume rewrite
- `八股快问快答`
  - fundamentals-heavy weighting
  - report emphasizes topic gap list and review priority
- `算法陪练`
  - algorithm-heavy weighting
  - report emphasizes complexity, edge cases, and recommended next questions

## Current Score Output

For `/score`, keep it compact:

```markdown
# 当前阶段评分
- 阶段：...
- 暂评得分：...
- 证据：...
- 主要问题：...
- 下一问我会继续追问：...
```

## Final Report Shape

Use this shape for `/report`:

```markdown
# 技术面模拟复盘报告

## 1. 总体结论
- 本场面试强度：...
- 面试语气：...
- 面试模式：...
- 目标岗位：...
- 综合评分：... / 100
- 面试结论：...

## 2. 各模块评分

## 3. 主要亮点

## 4. 主要问题

## 5. 项目与简历风险点

## 6. 简历修改建议

## 7. 后续复习建议

## 8. 下一次模拟建议
```

## Resume Rewrite Outputs

You can generate static rewrite suggestions directly from parsed resume artifacts:

```bash
python cs-tech-interviewer/scripts/suggest_resume_rewrites.py <candidate_profile.json>
```

This writes:

```text
<parsed_dir>/
  resume_rewrite_suggestions.json
  resume_rewrite_suggestions.md
```

When `/report` runs with both profile and transcript evidence, the final `interview_evaluation.json` also includes:

- `resume_rewrite_suggestions`

and the markdown report adds a dedicated resume-rewrite section when the current mode requires it.
