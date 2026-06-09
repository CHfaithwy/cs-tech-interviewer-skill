# Structured Resume Parser Reference

Use this reference when running or modifying `scripts/parse_resume.py`.

## Purpose

The parser is now the deterministic front half of the resume workflow:

1. Convert supported resume files into normalized Markdown
2. Emit a draft parser profile if useful
3. Hand normalized Markdown, JD, and user corrections to the current LLM
4. Apply the LLM-generated final profile and risks into fixed files

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
  candidate_profile.llm.json    # created after LLM profile generation
  candidate_profile.json
  candidate_profile.md
  resume_risks.llm.json        # created after LLM risk evaluation
  resume_risks.md
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

The final `candidate_profile.json` should be written from the current LLM's profile output, not treated as the parser's final authority. Its shape is:

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

Before a live interview starts, first generate/apply the LLM profile, then show the user a short checkpoint based on `candidate_profile.md`:

- inferred target roles
- top skills and projects
- top 3-5 resume risks
- parser uncertainty, especially for PDF sources

Ask the user to confirm or correct the profile. Use user corrections as higher-priority evidence than the parser output.

Before showing final resume risks or selecting questions, use the updated LLM-written `candidate_profile.json` as the source of truth.

## LLM Profile Generation

After `source_resume.md` exists, instruct the current LLM to read:

- `<parsed_dir>/source_resume.md`
- optional JD text or JD file
- optional parser draft `<parsed_dir>/candidate_profile.json`
- user corrections or target direction

Use `references/resume-profile-llm-generation.md` as the prompt and workflow reference. Save the model output to `<parsed_dir>/candidate_profile.llm.json`, then apply it:

```bash
python cs-tech-interviewer/scripts/apply_llm_candidate_profile.py <parsed_dir>/candidate_profile.llm.json --output-dir <parsed_dir> --source-resume-md <parsed_dir>/source_resume.md
```

This writes the canonical `candidate_profile.json`, `candidate_profile.md`, and `resume_risks.md`.

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

## LLM Risk Evaluation

`scripts/parse_resume.py` may still emit heuristic draft risks from `analyze_project_risks`, but those rules are not the final assessment. Treat them only as a fallback hint for the current LLM.

If the existing profile is already good and only risks need refreshing, instruct the model to read:

- `<parsed_dir>/source_resume.md`
- `<parsed_dir>/candidate_profile.json`
- optional JD text or JD file

Use `references/resume-risk-llm-evaluation.md` as the prompt and workflow reference. The previous rule list belongs inside that prompt as an interviewer checklist, including:

- missing responsibility boundary
- optimization/performance/accuracy claims without metrics
- metrics without clear baseline or evaluation method
- RAG/GraphRAG projects without retrieval/evaluation/failure details
- Agent/LangGraph/Multi-Agent projects without state, tool, retry, and failure handling details
- Neo4j/Cypher projects without schema, index, import, or query optimization details
- FastAPI/Django/interface projects without auth, exception, test, deployment, or monitoring details
- PDF/OCR/multimodal parsing projects without reliability and quality evaluation details

Save the model output to `<parsed_dir>/resume_risks.llm.json`, then apply it:

```bash
python cs-tech-interviewer/scripts/apply_llm_resume_risks.py <parsed_dir>/candidate_profile.json <parsed_dir>/resume_risks.llm.json
```

This updates `candidate_profile.json` and `resume_risks.md`. Downstream question selection, interview sessions, and reports should use this updated profile.

Treat LLM risk output as interview preparation, not as ground truth. When parsing looks wrong, inspect `source_resume.md` and correct assumptions in the interview setup.

## Resume Rewrite Suggestions

Resume rewrite suggestions are post-interview outputs, not parser outputs. After `/report`, the current LLM must read:

- `<session_dir>/interview_evaluation.json`
- `<session_dir>/transcript.json`
- `<parsed_dir>/candidate_profile.json`
- `<parsed_dir>/resume_risks.md`

Then save `<session_dir>/post_interview_outputs.llm.json` and run `scripts/apply_llm_post_interview_outputs.py` to write `resume_rewrite_suggestions.json` and `resume_rewrite_suggestions.md`.
