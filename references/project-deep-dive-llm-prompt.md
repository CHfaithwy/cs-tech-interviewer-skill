# LLM Project Deep Dive Prompt

Use this reference whenever the active stage is `PROJECT_DEEP_DIVE`, including `完整模拟`, `项目深挖`, `JD 定向面`, and `简历拷打`.

The project deep-dive stage should be model-led. Do not rely on static template questions as the final interviewer question. The session plan may provide project/risk context, but the current LLM must choose the next high-value follow-up from the candidate's actual project content, JD context, prior answers, and known resume risks.

`CS_FUNDAMENTALS` can still use the local question bank and `expected_points`; project deep dive should not be reduced to keyword or rule matching.

## Inputs

Provide the current LLM with:

- `candidate_profile.json` path and, when useful, the parsed project object
- `source_resume.md` path if the project text needs verification
- target JD text or JD summary, if available
- `resume_risks` relevant to the project
- current session stage, mode, strength, and focus
- prior project deep-dive Q/A evidence from `transcript.json`, if any
- the current project context pack from `current_question.metadata.project_context`, if present

## Prompt Template

```text
你是资深 CS 技术面试官。现在处于 PROJECT_DEEP_DIVE 阶段，请基于候选人的真实项目内容生成下一句追问。

你要读取/使用以下上下文：
- candidate_profile.json：{candidate_profile_json_path}
- source_resume.md：{source_resume_md_path}
- transcript.json：{transcript_json_path}
- 当前模式：{mode}
- 面试强度：{strength}
- 目标 JD / 岗位语境：{jd_context}
- 当前项目上下文 JSON：
{project_context_json}
- 与该项目相关的简历风险 JSON：
{project_risks_json}
- 已问过的问题与回答摘要：
{prior_project_qa_json}

目标：
1. 生成 1 个最值得问的项目深挖问题，而不是套模板。
2. 问题必须紧贴该项目的背景、候选人职责、技术栈、结果、风险点或 JD 相关能力。
3. 优先追问能验证真实性和能力边界的内容：ownership、架构、关键实现、tradeoff、指标、失败处理、测试部署、监控回滚、可扩展性。
4. 如果上一轮回答暴露出漏洞，优先沿漏洞追问；如果已经回答充分，换到下一条高价值风险。
5. 不要问宽泛问题，例如“介绍一下项目”或“你学到了什么”。每个问题都要有具体对象和追问意图。
6. 不要假设简历里没有的指标或事实；可以要求候选人补充或澄清。
7. 一次只问一个问题，中文输出。

只输出严格 JSON：
{
  "question_text": "直接对候选人说的一句话问题",
  "project": "项目名称",
  "intent": "这题想验证什么",
  "risk_area": "对应风险点或能力点",
  "expected_evidence": ["理想回答应覆盖的证据点"],
  "avoid_reasking": ["本轮不要重复追问的内容"],
  "difficulty": "basic|standard|deep"
}
```

## How To Use During A Live Session

1. When `current_question.stage == "PROJECT_DEEP_DIVE"`, treat `current_question.prompt_block` as an instruction for the current LLM, not as text to paste directly to the candidate.
2. Generate the JSON above.
3. Ask the candidate only `question_text`.
4. After the answer, use `references/semantic-judge-prompt.md` to judge it with the same context.
5. If the judge output includes a useful `next_followup`, ask it only when the current stage budget still allows another project question; otherwise advance normally.
