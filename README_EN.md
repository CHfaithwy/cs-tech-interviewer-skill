# CS Tech Interviewer Skill

> A Chinese CS technical interview simulation, follow-up, scoring, and review tool based on resumes and job descriptions.

It turns a technical interview into a configurable, follow-up-friendly, persistable, and reviewable workflow: from resume parsing, question-bank selection, and project deep dives, to algorithm practice, stage scoring, structured review, and resume rewrite suggestions.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![AgentSkills](https://img.shields.io/badge/AgentSkills-Standard-green)](https://agentskills.io)
[![Language](https://img.shields.io/badge/Language-ZH%20%7C%20EN-lightgrey)](README.md)

[Installation](#installation) · [Quick Start](#quick-start) · [Core Capabilities](#features) · [Interview Modes](#interview-modes) · [Session and Artifacts](#session-artifacts) · [Chinese](README.md)

---

## Applicable Scenarios

This skill is suitable for people who want to prepare for technical interviews systematically, especially:

- candidates targeting backend, AI, RAG, SRE, and similar directions
- people who want high-intensity follow-up questions around resume projects
- people who want JD-oriented mock interviews
- people who want to turn the interview process into scoring, review, and next-round plans
- people who want to turn problems exposed in interviews into resume rewrite suggestions

It is closer to a Chinese technical interview console: based on the resume, JD, role profile, question-bank bias, and session state machine, it organizes a mock interview that feels more like a real technical interview.

The JD is not only a question-filtering condition. The skill remembers the JD as the role context for the whole interview, and uses it to decide what the interviewer should prioritize and what standard to use when judging fit.


<a id="features"></a>

## Core Capabilities

| Capability | Description |
| --- | --- |
| Resume parsing | Supports PDF / DOCX / Markdown / TXT and outputs a structured candidate profile |
| Local question bank | Built-in CS fundamentals cards, algorithm cards, and local knowledge-base metadata |
| JD context memory | Accepts the JD first and turns it into the role context for the whole interview |
| First-class `/role` | Supports role bias such as `backend-java`, `ai-rag`, and `sre-platform` |
| Multi-mode interviews | Supports modes such as full mock, project deep dive, CS fundamentals fast drill, and algorithm practice |
| Session state machine | Each interview is persisted independently, with pause, continue, skip, hint, and mid-session scoring |
| Structured review | Uniformly outputs `interview_evaluation.json / md` |
| Resume rewrite suggestions | Supports static suggestions, and transcript-enhanced suggestions after the interview |

<a id="installation"></a>

## Installation

This is a skill repository, Put it into a skill directory that Codex can load.

```bash
git clone <your-repo-url> cs-tech-interviewer
cd cs-tech-interviewer
pip install -r requirements.txt
```

If you need to parse PDF resumes, it is recommended to install `MinerU` separately. 

```bash
pip install -U "mineru[pipeline]"
```




<a id="quick-start"></a>

## Quick Start

Invoke this skill in Agent:

```text
Use $cs-tech-interviewer to conduct a computer-science mock interview based on a resume and generate a structured feedback report.
```

Typical flow:

```text
Provide a resume or resume text
-> Provide the target JD first, so the interviewer remembers the role context for this session
-> Confirm /role /strength /mode /focus
-> /start
-> /score
-> /report
```

If you paste a full job description directly, you do not need to convert it into command format first. The skill will treat it as `/jd` and remember that JD.

Common commands:

| Command | Purpose |
| --- | --- |
| `/role <value>` | Set a role profile, for example `backend-java` or `ai-rag` |
| `/jd <text>` | Provide the job description so the interviewer builds the role context around it |
| `/mode <value>` | Set the interview mode |
| `/focus <topics>` | Specify the main follow-up direction |
| `/start` | Start the current session |
| `/hint` | Get a hint |
| `/skip` | Skip the current question |
| `/score` | Generate a score snapshot for the current stage |
| `/report` | Generate the final structured review |

<a id="interview-modes"></a>

## Interview Modes

| Mode | Suitable Scenario |
| --- | --- |
| `完整模拟` | Runs the full technical interview chain: self-introduction, projects, CS fundamentals, algorithms, candidate questions, and review |
| `项目深挖` | Specifically drills project ownership, architecture tradeoffs, metrics, and engineering closure |
| `八股快问快答` | Dense drilling of high-frequency CS fundamentals |
| `算法陪练` | Multi-question algorithm practice, focusing on approach, complexity, edge cases, and hint dependency |
| `JD 定向面` | Capability matching and risk follow-up around a target JD |
| `简历拷打` | Focuses on the resume statements most likely to be questioned |
| `复盘教练` | Generates review output from a transcript or structured record |

The source of truth for mode behavior is:

```text
data/interview_mode_profiles.json
```

It centrally maintains stage sequence, question count, selection policy, scoring weights, and report emphasis; free-form answer scoring is led by the current LLM with session context.

<a id="session-artifacts"></a>

## Session and Artifacts

Each interview is written into an independent session directory.

If `--sessions-root` is not provided, it defaults to the user's current working directory:

```text
./sessions/
```

Typical artifacts:

```text
<session_dir>/
  session_state.json
  session_brief.md
  transcript.json
  question_selection.json
  question_selection/
    question_selection.md
    question_selection_interview_mode.md
    question_selection_candidate_mode.md
  score_snapshot.json
  score_snapshot.md
  interview_evaluation.json
  interview_evaluation.md
```

Among them:

- `session_state.json` records the current state-machine runtime state
- `session_state.json.current_question` carries `jd_context`, so the runtime view also remembers the role context
- `session_brief.md` is the opening summary card for the session, so you can quickly inspect `/role`, `/strength`, `/focus`, and the Top 5 selected topics
- `transcript.json` records answer evidence
- `question_selection.json` records the selected questions for this interview
- `question_selection.md` is the default human-readable selection summary and explicitly shows `JD Context`
- `score_snapshot.json / md` are mid-session scoring outputs
- `interview_evaluation.json` is the machine-readable source of truth for the final review
- `interview_evaluation.md` is the review report

## Repository Structure

```text
cs-tech-interviewer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── data/
├── scripts/
├── references/
└── .gitignore
```

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Main skill instructions and interaction rules |
| `agents/` | Skill metadata |
| `data/` | Question banks, role profiles, and mode configuration |
| `scripts/` | Resume parsing, question selection, session control, scoring, and review scripts |
| `references/` | Detailed explanations, schemas, and prompt templates |

## Boundaries and Privacy

This repository does not include real resumes or runtime artifacts by default.

The goal of the skill is to help candidates find problems, organize their answers, and prepare for the next round. It does not promise to "guarantee interview success."

## Data Sources

- The topic organization of the CS fundamentals / knowledge-base layer references [`Snailclimb/JavaGuide`](https://github.com/Snailclimb/JavaGuide)
- The high-frequency distribution of algorithm questions references [`afatcoder/LeetcodeTop`](https://github.com/afatcoder/LeetcodeTop)

If there is any infringement, it will be removed immediately.

## Project Status

Current version V1.0:

```text
Resume parsing -> automatic question selection -> multi-mode interview -> answer recording -> stage scoring -> structured review -> resume rewrite suggestions
```
