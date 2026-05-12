# Semantic Judge Prompt

Use this prompt template for optional LLM-assisted answer judging in `scripts/session_router.py`.

This prompt is designed to sit on top of the heuristic judge, not replace it outright.

## Purpose

The semantic judge receives:

- current stage
- current question text
- question metadata
- hint usage
- candidate answer
- heuristic first-pass judgement

It must return a strict JSON object that is easy for the router to validate and merge.

## Output Contract

The model must return JSON only, with these fields:

```json
{
  "quality": "strong | partial | weak | wrong",
  "score": 1,
  "strengths": ["..."],
  "issues": ["..."],
  "feedback": "...",
  "confidence": 0.0
}
```

Rules:

- `quality` must be one of `strong`, `partial`, `weak`, `wrong`
- `score` must be an integer `1-5`
- `strengths` and `issues` must be short Chinese evidence statements
- `feedback` must be one short Chinese sentence
- `confidence` must be a float `0-1`

## Prompt Template

Use the following as the semantic-judge instruction body. The router fills the runtime variables.

```text
You are judging a Chinese technical mock interview answer.

Your task is to refine, not blindly replace, a heuristic first-pass judgement.

Be conservative:
- do not overpraise vague answers
- do not invent strengths or issues not grounded in the answer
- prefer "partial" over "strong" when evidence is mixed
- prefer "weak" over "wrong" unless the answer is clearly off-topic or fundamentally incorrect

Return strict JSON only with fields:
- quality
- score
- strengths
- issues
- feedback
- confidence

JSON rules:
- quality must be one of: strong, partial, weak, wrong
- score must be an integer from 1 to 5
- strengths/issues must be short Chinese evidence-backed phrases
- feedback must be one short Chinese sentence
- confidence must be a float from 0 to 1

Stage: {{stage}}
Mode: {{mode}}
Question ID: {{question_id}}
Question Text: {{question_text}}
Hint Level: {{hint_level}}

Question Metadata JSON:
{{question_metadata_json}}

Candidate Answer:
{{candidate_answer}}

Heuristic First-Pass Judgement JSON:
{{heuristic_judgement_json}}
```

## Tuning Notes

When tuning this prompt, prefer changing:

- strictness language
- downgrade / upgrade bias
- evidence requirements
- output phrasing guidance

Avoid changing:

- the JSON field contract
- the quality label set
- score range

Those are part of the router validation layer.
