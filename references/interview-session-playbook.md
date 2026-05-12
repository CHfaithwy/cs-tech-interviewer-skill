# Interview Session Playbook

Use this playbook when you want practical, copyable examples for `scripts/interview_session.py` and `scripts/session_router.py`.

This file is intentionally operational. It shows what a real user or agent would do in common scenarios without depending on bundled sample resumes or transcripts.

If you do not pass `--sessions-root`, all generated sessions will be written into `./sessions/` under your current working directory.

## 1. Start A Full Mock Interview

### Step 1: Initialize a session

```bash
python cs-tech-interviewer/scripts/interview_session.py init --resume <resume-file>
```

### Step 2: Configure the interview

```bash
python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --mode 完整模拟 --strength 人上人 --tone 默认 --level 中等 --role ai-rag --focus "RAG,MySQL,Redis"
```

### Step 3: Start

```bash
python cs-tech-interviewer/scripts/interview_session.py start <session_dir>
```

### Step 4: Get the current question

```bash
python cs-tech-interviewer/scripts/interview_session.py next <session_dir>
```

### Step 5: Record an answer

```bash
python cs-tech-interviewer/scripts/interview_session.py record-answer <session_dir> --quality partial --score 3 --strengths "表达自然,结构基本清晰" --issues "岗位匹配点不够聚焦,回答略长" --answer-summary "自我介绍结构正常，但岗位匹配点不够集中。" --feedback "表达自然，但还可以更聚焦岗位相关亮点。"
```

### Step 6: Mid-session score

```bash
python cs-tech-interviewer/scripts/interview_session.py score <session_dir>
```

### Step 7: Final report

```bash
python cs-tech-interviewer/scripts/interview_session.py report <session_dir>
```

## 2. Algorithm Drill Mode

```bash
python cs-tech-interviewer/scripts/interview_session.py init --profile-json <candidate_profile.json> --session-name algo_drill
python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --mode 算法陪练 --strength 顶级 --level 困难 --focus "链表,二叉树,DP"
python cs-tech-interviewer/scripts/interview_session.py start <session_dir>
python cs-tech-interviewer/scripts/interview_session.py next <session_dir>
```

In the public repository build, the current question is usually an algorithm card with a locally rewritten prompt. It does not bundle official source HTML, images, or direct problem links.

## 3. Pause / Continue / Skip / Hint

```bash
python cs-tech-interviewer/scripts/interview_session.py pause <session_dir>
python cs-tech-interviewer/scripts/interview_session.py continue <session_dir>
python cs-tech-interviewer/scripts/interview_session.py hint <session_dir>
python cs-tech-interviewer/scripts/interview_session.py skip <session_dir>
```

## 4. Deferred Reconfiguration

```bash
python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --mode 算法陪练 --focus "链表,二叉树" --defer-if-running
```

This keeps the current stage running, writes the change into `pending_reconfiguration`, and rebuilds future stages after the current stage finishes.

## 5. Review Coach Mode

If you already have a transcript:

```bash
python cs-tech-interviewer/scripts/interview_session.py init --transcript-json <transcript.json> --session-name replay
python cs-tech-interviewer/scripts/interview_session.py configure <session_dir> --mode 复盘教练 --role ai-rag
python cs-tech-interviewer/scripts/interview_session.py start <session_dir>
python cs-tech-interviewer/scripts/interview_session.py report <session_dir>
```

## 6. Natural Language Routing

```bash
python cs-tech-interviewer/scripts/session_router.py <session_dir> "开始吧"
python cs-tech-interviewer/scripts/session_router.py <session_dir> "先暂停一下"
python cs-tech-interviewer/scripts/session_router.py <session_dir> "继续吧"
python cs-tech-interviewer/scripts/session_router.py <session_dir> "给个提示"
python cs-tech-interviewer/scripts/session_router.py <session_dir> "后面改成算法陪练，重点考链表 二叉树"
python cs-tech-interviewer/scripts/session_router.py <session_dir> "结束面试并生成复盘"
```

You can also send a free-form candidate answer directly, and the router will try to judge it automatically before calling `record-answer`.
