# LLM Resume Risk Evaluation

Use this reference after `scripts/parse_resume.py` has produced a parsed resume directory. The goal is to let the current LLM assess the parsed resume as a CS interviewer, rather than treating deterministic parser rules as the final risk source.

## Inputs

Required files:

- `<parsed_dir>/source_resume.md`
- `<parsed_dir>/candidate_profile.json`

Optional context:

- target JD text or a saved JD file
- user corrections to parser output
- target role, interview mode, focus, or strength

Always tell the model the exact local paths it must read. Prefer the parsed Markdown and profile JSON over the original PDF/DOCX because they are the normalized artifacts the rest of the skill uses.

## Output Targets

Persist the LLM assessment before continuing with question selection:

1. Save the raw model JSON as `<parsed_dir>/resume_risks.llm.json`.
2. Apply it with:

```bash
python cs-tech-interviewer/scripts/apply_llm_resume_risks.py <parsed_dir>/candidate_profile.json <parsed_dir>/resume_risks.llm.json
```

The apply script writes or refreshes:

- `<parsed_dir>/candidate_profile.json` (`resume_risks`, project `possible_risks`, and `risk_evaluation`)
- `<parsed_dir>/resume_risks.llm.json`
- `<parsed_dir>/resume_risks.md`
- `<parsed_dir>/resume_rewrite_suggestions.json`
- `<parsed_dir>/resume_rewrite_suggestions.md`

If file writes are not possible, return the JSON and Markdown risk summary directly to the user and state clearly that the result was not persisted.

## Evaluation Principles

- Evaluate the parsed resume, not just the parser's rule output.
- Use the source resume text as evidence. Cite short evidence snippets or profile fields; do not invent facts or metrics.
- Treat user corrections and JD context as higher-priority context than parser guesses.
- Prefer interview-relevant risks: claims likely to trigger follow-up, unclear ownership, unsupported metrics, missing engineering closure, or suspiciously broad claims.
- Keep 5-10 high-signal risks by default. Use fewer if the resume is clean; do not pad.
- Sort by severity: `high`, then `medium`, then `low`.
- Project names should match `candidate_profile.projects[].name` when possible. Use `整体简历` only for cross-resume risks.
- A risk is not a moral judgment. Phrase it as "what an interviewer will probe" and how the candidate can make the claim verifiable.

## Interviewer Checklist

Use this checklist inside the prompt, but do not blindly emit every item:

- If personal responsibility is unclear, flag `个人职责边界`.
- If the resume says optimization, improvement, high performance, high concurrency, real-time, or accuracy without numbers, flag `量化指标缺失`.
- If metrics exist without baseline, sample size, environment, or evaluation method, flag `指标口径追问`.
- For RAG/GraphRAG projects, probe chunking, retrieval, reranking, evaluation, failure cases, and hallucination control.
- For Agent/LangGraph/Multi-Agent projects, probe state management, tool schema, tool-call errors, retries, loop control, timeout, logging, and failure recovery.
- For backend/API projects, probe auth, validation, exceptions, rate limiting, logging, deployment, monitoring, testing, and rollback.
- For Neo4j/Cypher projects, probe schema design, indexes, constraints, import consistency, query plan, and slow query optimization.
- For PDF/OCR/multimodal parsing projects, probe layout analysis, table/formula failures, quality evaluation, retries, and manual validation.
- For any production-sounding project, probe testing, deployment, observability, incident handling, and tradeoffs.

## Prompt Template

```text
你是资深 CS 技术面试官，目标是评估一份已经解析好的简历中哪些表述最容易在技术面试里被追问或质疑。

请先读取以下本地文件：
- 解析后简历 Markdown：{source_resume_md_path}
- 候选人结构化画像 JSON：{candidate_profile_json_path}
- 目标 JD（如有）：{jd_path_or_inline_text}

任务：
1. 基于 source_resume.md 和 candidate_profile.json 评估简历风险点；不要只复述已有的规则风险。
2. 如果 candidate_profile.json 里的解析结果和 source_resume.md 冲突，以 source_resume.md 和用户修正为准。
3. 从面试官视角找出最可能被追问的 5-10 个风险点。不要为了凑数输出低价值风险。
4. 每个风险必须有简历证据，不能编造指标、项目事实或候选人职责。
5. 将以下规则作为检查表一起考虑：
   - 没有个人职责或职责边界不清：个人职责边界。
   - 有“优化/提升/高性能/高并发/实时/准确率”等表述但没有数字：量化指标缺失。
   - 有数字但缺 baseline、样本量、环境、统计口径或评估方法：指标口径追问。
   - RAG/GraphRAG：切分、召回、重排、评估、错误案例、幻觉控制。
   - Agent/LangGraph/Multi-Agent：状态、工具 schema、工具调用失败、重试、循环控制、超时、日志、失败恢复。
   - 后端/API：鉴权、参数校验、异常、限流、日志、部署、监控、测试、回滚。
   - Neo4j/Cypher：schema、索引、约束、导入一致性、查询计划、慢查询优化。
   - PDF/OCR/多模态解析：版面分析、表格/公式失败、质量评估、重试、人工校验。
6. 如果 JD 已提供，请额外指出风险为何影响岗位匹配；如果和 JD 无关，不要强行关联。

只输出严格 JSON，不要输出 Markdown、解释文字或代码块。JSON schema：
{
  "schema_version": "1.0",
  "kind": "llm_resume_risk_evaluation",
  "source_resume_path": "{source_resume_md_path}",
  "candidate_profile_json_path": "{candidate_profile_json_path}",
  "jd_context": "{none_or_short_summary}",
  "resume_risks": [
    {
      "project": "必须尽量匹配 candidate_profile.projects[].name；跨项目问题用 整体简历",
      "severity": "high|medium|low",
      "area": "简短风险点名称",
      "evidence": "简历中的短证据或结构化字段，不超过 80 字",
      "why_it_matters": "为什么面试官会追问，不超过 120 字",
      "suggested_fix": "建议候选人补充什么事实、指标、边界或验证方式，不超过 120 字",
      "likely_followup": "面试官可能追问的问题",
      "confidence": "high|medium|low",
      "source_quote": "可选：source_resume.md 中的短摘录，不超过 80 字",
      "jd_relevance": "可选：和 JD 的关系，不超过 80 字"
    }
  ]
}
```

## After The Model Responds

Validate the model output before applying it:

- The response must be parseable JSON.
- `resume_risks` must be an array.
- Each item must include `project`, `severity`, `area`, `evidence`, `why_it_matters`, `suggested_fix`, and `likely_followup`.
- Remove duplicated risks. Merge overlapping "指标缺失" items for the same project.
- Downgrade or remove risks with weak evidence.

Then save the JSON to `<parsed_dir>/resume_risks.llm.json` and run `scripts/apply_llm_resume_risks.py`.
