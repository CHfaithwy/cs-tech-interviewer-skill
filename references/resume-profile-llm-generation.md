# LLM Resume Profile Generation

Use this reference after the resume has been converted into normalized Markdown. The current LLM should generate the candidate profile, project structure, JD fit context, and resume risks. The parser output is a draft aid, not the authority.

## Inputs

Required:

- `<parsed_dir>/source_resume.md`

Recommended:

- target JD text or JD file
- user-provided target role/focus
- user corrections to parser output
- existing parser draft `<parsed_dir>/candidate_profile.json`, if available

Always tell the model the exact local paths it must read.

## Output Targets

1. Validate that the response is parseable JSON.
2. Save it to a temporary UTF-8 JSON file and delete it after a successful apply:

```bash
python cs-tech-interviewer/scripts/apply_llm_candidate_profile.py <temp_profile_json> --output-dir <parsed_dir> --source-resume-md <parsed_dir>/source_resume.md --delete-input
```

If the environment is known to preserve UTF-8 through stdin, piping is also supported:

```bash
python cs-tech-interviewer/scripts/apply_llm_candidate_profile.py - --output-dir <parsed_dir> --source-resume-md <parsed_dir>/source_resume.md
```

The apply script writes:

- `<parsed_dir>/candidate_profile.json`
- `<parsed_dir>/candidate_profile.md`
- `<parsed_dir>/resume_risks.md`

Only add `--keep-llm-json` when debugging requires preserving `<parsed_dir>/candidate_profile.llm.json`.

If only risks need refreshing later, use `references/resume-risk-llm-evaluation.md` and `scripts/apply_llm_resume_risks.py`.

Resume rewrite suggestions are generated after interview evidence exists. Do not generate them from parser/profile rules here.

## Prompt Template

```text
你是资深 CS 技术面试官和简历结构化分析助手。请读取已经解析好的简历 Markdown，并结合 JD 生成候选人画像、项目结构、面试重点和简历风险点。

请读取：
- source_resume.md：{source_resume_md_path}
- 目标 JD（如有）：{jd_path_or_inline_text}
- 用户修正/目标方向（如有）：{user_corrections_or_focus}
- 解析器草稿 candidate_profile.json（如有）：{draft_profile_json_path}

原则：
1. 以 source_resume.md 和用户修正为准，解析器草稿只能参考。
2. 不要编造学历、经历、指标、职责或项目事实。
3. 可以从 JD 和简历语义推断 target_roles、interview_focus 和岗位匹配重点，但要保守。
4. 项目结构必须方便后续项目深挖：每个项目要尽量拆出背景、个人职责、技术栈、指标、关键表述、结果。
5. 风险点必须从面试官视角生成，聚焦最可能被追问的 5-10 个点，不要凑数。
6. 风险点规则清单只是检查表：职责边界、量化指标、指标口径、RAG/Agent/后端/API/Neo4j/PDF-OCR/工程闭环等都要考虑，但不能无证据硬套。
7. 如果 JD 已提供，interview_focus 要体现 JD 匹配和能力缺口。

只输出严格 JSON，不要输出 Markdown 或解释文字。JSON schema：
{
  "source": {
    "source_path": "{source_resume_md_path}",
    "source_type": "md"
  },
  "markdown_path": "{source_resume_md_path}",
  "candidate_profile": {
    "name": "",
    "contact": {
      "emails": [],
      "phones": [],
      "urls": []
    },
    "education": [
      {
        "school": "",
        "degree": "",
        "major": "",
        "period": "",
        "raw": ""
      }
    ],
    "target_roles": [],
    "skills": {
      "languages": [],
      "frameworks": [],
      "databases": [],
      "ai_ml": [],
      "tools": []
    },
    "projects": [
      {
        "name": "",
        "period": "",
        "background": "",
        "role": "",
        "tech_stack": [],
        "metrics": [],
        "claims": [],
        "results": "",
        "possible_risks": []
      }
    ],
    "research": "",
    "publications": [],
    "experience": "",
    "internships": [],
    "awards": "",
    "award_items": [],
    "interview_focus": []
  },
  "resume_risks": [
    {
      "project": "项目名称；跨项目风险用 整体简历",
      "severity": "high|medium|low",
      "area": "风险点名称",
      "evidence": "简历证据，不超过 80 字",
      "why_it_matters": "为什么会被追问",
      "suggested_fix": "应该补充什么事实/指标/边界",
      "likely_followup": "面试官可能追问的问题"
    }
  ]
}
```

## After The Model Responds

- Validate that the response is parseable JSON.
- Remove invented metrics or claims.
- Ensure projects and risks use consistent project names.
- Apply it with `scripts/apply_llm_candidate_profile.py <temp_profile_json> --delete-input`. Use stdin only when the pipe is UTF-8 safe.
