# Semantic Judge Prompt

Use this prompt when a candidate gives a free-form answer during a live interview.

The current LLM is the judge. Do not require a separate API key, model endpoint, or hidden service call. Do not score by keyword heuristics first. Local rules and `expected_points` can be context, especially for `CS_FUNDAMENTALS`, but the final judgement must be a semantic assessment of the answer in context.

## Purpose

The semantic judge receives:

- current stage and mode
- current question text
- question metadata
- hint usage
- target JD and focus, if available
- candidate profile / project context paths or snippets
- recent transcript evidence
- candidate answer

It returns one strict JSON object that can be persisted into `transcript.json`.

## Output Contract

```json
{
  "quality": "strong",
  "score": 4,
  "strengths": ["..."],
  "issues": ["..."],
  "answer_summary": "...",
  "feedback": "...",
  "confidence": 0.85,
  "next_followup": "..."
}
```

Rules:

- `quality` must be one of `strong`, `partial`, `weak`, `wrong`.
- `score` must be an integer from `1` to `5`; use `0` only for skipped answers.
- `strengths` and `issues` must be short Chinese evidence statements grounded in the answer.
- `answer_summary` must summarize what the candidate actually said.
- `feedback` must be one concise Chinese sentence to the candidate.
- `confidence` must be a float from `0` to `1`.
- `next_followup` is optional; use it mainly for `PROJECT_DEEP_DIVE` when the answer exposes a high-value next probe.

## Stage Guidance

- `SELF_INTRO`: judge role fit, structure, project/skill signal, and whether the candidate gives a coherent main line.
- `PROJECT_DEEP_DIVE`: judge ownership, implementation detail, architecture reasoning, tradeoff, metrics, failure handling, testing/deployment/monitoring, and whether the answer resolves the active risk area.
- `CS_FUNDAMENTALS`: use `expected_points` as reference, but judge semantic correctness instead of literal keyword hits.
- `CODING_INTERVIEW`: judge algorithm idea, complexity, edge cases, code/pseudocode correctness, debugging, and hint dependence.
- `CANDIDATE_QUESTIONS`: judge specificity, technical relevance, and whether the question shows mature collaboration/engineering awareness.

## Prompt Template

```text
你是资深 CS 技术面试官，正在给候选人的自由回答做现场语义评分。

重要原则：
- 你就是当前大模型评审器，不要调用外部 API。
- 不要先做关键词/规则式判定；可以参考题目 expected_points，但最终必须看回答语义、上下文和证据。
- 不要因为回答很长就高分；必须有具体、正确、可验证的内容。
- 不要发明候选人没有说过的亮点、指标或职责。
- 如果回答混合好坏，优先给 partial；只有明显充分且可信才给 strong。
- 如果使用了多次提示，要在评分中体现依赖程度。

请基于以下上下文评分：

Stage: {{stage}}
Mode: {{mode}}
Question ID: {{question_id}}
Question Text: {{question_text}}
Hint Level: {{hint_level}}

Question Metadata JSON:
{{question_metadata_json}}

Session Config JSON:
{{session_config_json}}

Artifact Paths JSON:
{{artifact_paths_json}}

Recent Transcript Context JSON:
{{recent_transcript_json}}

Candidate Answer:
{{candidate_answer}}

请只输出严格 JSON，不要输出 Markdown、解释文字或代码块：
{
  "quality": "strong|partial|weak|wrong",
  "score": 1,
  "strengths": ["回答中可以作为正向证据的点"],
  "issues": ["回答中仍然缺失、错误或含糊的点"],
  "answer_summary": "候选人回答摘要",
  "feedback": "一句话现场反馈",
  "confidence": 0.0,
  "next_followup": "可选：下一句追问；没有就用空字符串"
}
```

## Applying The Result

Save the JSON to a file, then apply it with:

```bash
python cs-tech-interviewer/scripts/apply_llm_answer_judgement.py <session_dir> <judgement.json>
```

The apply script records the answer through `interview_session.py record-answer`, advances the state machine, and stores a copy under `<session_dir>/llm_judgements/`.
