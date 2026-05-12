# Structured Resume Parser Reference

Use this reference when running or modifying `scripts/parse_resume.py`.

## Purpose

The parser implements V0.3 structured resume parsing:

1. Convert supported resume files into normalized Markdown
2. Extract a candidate profile: contact, education, skills, projects, research/experience, awards
3. Generate resume risk points for interview follow-up
4. Emit both machine-readable JSON and human-readable Markdown reports

## Supported Inputs

- `.md` / `.markdown`
- `.txt`
- `.docx`
- `.pdf`
- public document URL

## Commands

```bash
python cs-tech-interviewer/scripts/parse_resume.py <resume.txt>
python cs-tech-interviewer/scripts/parse_resume.py <resume.docx>
python cs-tech-interviewer/scripts/parse_resume.py <resume.pdf>
python cs-tech-interviewer/scripts/parse_resume.py <resume.pdf> --mineru-page-range 1-10
python cs-tech-interviewer/scripts/parse_resume.py https://example.com/resume.pdf --mineru-page-range 1-10
python cs-tech-interviewer/scripts/parse_resume.py <resume.pdf> --pdf-converter cli --mineru-backend pipeline
```

Default output directory:

```text
<resume stem>_parsed/
  source_resume.md
  candidate_profile.json
  candidate_profile.md
  resume_risks.md
  resume_rewrite_suggestions.json
  resume_rewrite_suggestions.md
  mineru_agent_output.md
  mineru_output/
```

## MinerU PDF Path

MinerU supports two useful paths for this parser.

### Agent lightweight API

Use this by default:

```bash
python cs-tech-interviewer/scripts/parse_resume.py <resume.pdf>
```

Useful options:

```bash
--mineru-page-range 1-10
--mineru-ocr
--no-mineru-enable-table
--no-mineru-enable-formula
--mineru-timeout 300
```

### Local CLI fallback

When `--pdf-converter cli` is set, the parser calls:

```bash
mineru -p <resume.pdf> -o <resume_stem>_parsed/mineru_output -b pipeline -m auto -l ch
```

## JSON Shape

`candidate_profile.json` contains:

```json
{
  "schema_version": "0.3",
  "generated_at": "...",
  "source": {
    "source_path": "...",
    "source_type": "txt|md|pdf",
    "pdf_converter": null
  },
  "markdown_path": ".../source_resume.md",
  "candidate_profile": {
    "name": "...",
    "contact": {
      "emails": [],
      "phones": [],
      "urls": []
    },
    "education": [],
    "target_roles": [],
    "skills": {
      "languages": [],
      "frameworks": [],
      "databases": [],
      "ai_ml": [],
      "tools": []
    },
    "projects": [],
    "research": "",
    "publications": [],
    "experience": "",
    "internships": [],
    "awards": "",
    "award_items": [],
    "interview_focus": []
  },
  "resume_risks": []
}
```

## Profile Confirmation

Before a live interview starts, show the user a short checkpoint based on `candidate_profile.md`:

- inferred target roles
- top skills and projects
- top 3-5 resume risks
- parser uncertainty, especially for PDF sources

Ask the user to confirm or correct the profile. Use user corrections as higher-priority evidence than the parser output.

## Question Selection

After `candidate_profile.json` is produced and the user confirms the profile, run the selector when a resume/JD-driven question plan is useful:

```bash
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --jd-file jd.txt --focus "Redis, MySQL, FastAPI" --level 中等
```

The selector writes:

```text
<parsed_dir>/question_selection/
  question_selection.json
  question_selection.md
```

## Risk Generation Rules

The parser flags risks when it sees:

- missing responsibility boundary
- optimization/performance/accuracy claims without metrics
- metrics without clear baseline or evaluation method
- RAG/GraphRAG projects without retrieval/evaluation/failure details
- Agent/LangGraph/Multi-Agent projects without state, tool, retry, and failure handling details
- Neo4j/Cypher projects without schema, index, import, or query optimization details
- FastAPI/Django/interface projects without auth, exception, test, deployment, or monitoring details
- PDF/OCR/multimodal parsing projects without reliability and quality evaluation details

Treat parser output as an interview preparation aid, not as ground truth. When parsing looks wrong, inspect `source_resume.md` and correct assumptions in the interview setup.

## Resume Rewrite Suggestions

`parse_resume.py` also emits:

- `resume_rewrite_suggestions.json`
- `resume_rewrite_suggestions.md`

These suggestions are generated only from parsed profile and resume risk evidence. They do not invent metrics. When exact values are unknown, they use placeholders that the candidate must replace with real numbers or verified context.
