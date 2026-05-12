#!/usr/bin/env python
"""Parse a CS resume into a structured candidate profile and risk report.

Inputs:
- Markdown (.md/.markdown)
- Text (.txt)
- DOCX (.docx)
- PDF (.pdf) through MinerU Agent API or MinerU CLI
- Public document URL through MinerU Agent API

Outputs:
- source_resume.md
- candidate_profile.json
- candidate_profile.md
- resume_risks.md
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import shutil
import site
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from suggest_resume_rewrites import generate_resume_rewrite_suggestions


MINERU_AGENT_BASE_URL = "https://mineru.net/api/v1/agent"


SECTION_KEYWORDS = {
    "education": ["education", "教育", "教育背景", "学历"],
    "projects": ["projects", "project", "项目", "项目经历", "项目经验"],
    "research": ["research", "research experiences", "科研", "论文", "publication"],
    "experience": ["experience", "work", "intern", "实习", "实习经历", "工作经历", "工作经验"],
    "skills": ["skills", "skill", "llm skills", "code skills", "技术", "技能", "专业技能"],
    "awards": ["awards", "honors", "荣誉", "奖项", "竞赛"],
}

TECH_KEYWORDS = {
    "languages": [
        "Python",
        "Java",
        "C++",
        "C",
        "JavaScript",
        "TypeScript",
        "Go",
        "Rust",
        "SQL",
    ],
    "frameworks": [
        "FastAPI",
        "Django",
        "Flask",
        "Spring",
        "Spring Boot",
        "Vue",
        "React",
        "LangChain",
        "LangGraph",
        "GraphRAG",
        "Microsoft GraphRAG",
        "RestFramework",
        "LitServe",
    ],
    "databases": [
        "MySQL",
        "PostgreSQL",
        "Redis",
        "MongoDB",
        "Neo4j",
        "Elasticsearch",
        "SQLite",
    ],
    "ai_ml": [
        "LLM",
        "RAG",
        "Agent",
        "Multi-Agent",
        "Transformer",
        "PyTorch",
        "TensorFlow",
        "O-CNN",
        "Reinforcement Learning",
        "OCR",
        "MinerU",
    ],
    "tools": [
        "Docker",
        "Git",
        "Linux",
        "Kubernetes",
        "CI/CD",
        "Nginx",
        "Cypher",
        "GraphQL",
        "REST",
        "RESTful",
        "微信小程序",
        "xr-frame",
    ],
}

VAGUE_CLAIMS = [
    "负责",
    "参与",
    "核心",
    "优化",
    "提升",
    "搭建",
    "高性能",
    "高并发",
    "实时",
    "智能",
    "自动化",
    "一键式",
]


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_docx(path: Path) -> str:
    document = docx.Document(str(path))
    blocks: list[str] = []

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if text:
                blocks.append(text)
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    blocks.append(" | ".join(cells))

    return "\n".join(blocks)


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def url_suffix(value: str) -> str:
    return Path(urllib.parse.urlparse(value).path).suffix.lower()


def safe_stem(value: str) -> str:
    stem = Path(urllib.parse.urlparse(value).path).stem if is_http_url(value) else Path(value).stem
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._-")
    return stem or "resume"


def http_json_request(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network request failed for {url}: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from {url}, got: {body[:500]}") from exc


def http_text_request(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network request failed for {url}: {exc.reason}") from exc


def put_file(url: str, path: Path, timeout: int = 120) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid upload URL: {url}")

    body = path.read_bytes()
    request_target = parsed.path or "/"
    if parsed.query:
        request_target += f"?{parsed.query}"

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(parsed.netloc, timeout=timeout)
    try:
        # Signed OSS upload URLs may reject unexpected headers, so do not send Content-Type.
        connection.request("PUT", request_target, body=body, headers={"Content-Length": str(len(body))})
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        if response.status not in {200, 201}:
            raise RuntimeError(f"File upload failed with HTTP {response.status}: {response_body}")
    finally:
        connection.close()


def validate_mineru_response(result: dict[str, Any], action: str) -> dict[str, Any]:
    if result.get("code") != 0:
        raise RuntimeError(f"MinerU Agent API {action} failed: {result.get('msg', result)}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"MinerU Agent API {action} returned invalid data: {result}")
    return data


def mineru_agent_payload(args: argparse.Namespace, source: str | None = None, file_name: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "language": args.mineru_lang,
        "enable_table": args.mineru_enable_table,
        "is_ocr": args.mineru_ocr,
        "enable_formula": args.mineru_enable_formula,
    }
    if source:
        payload["url"] = source
    if file_name:
        payload["file_name"] = file_name
    if args.mineru_page_range:
        payload["page_range"] = args.mineru_page_range
    return payload


def poll_mineru_agent(task_id: str, args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    base_url = args.mineru_api_base.rstrip("/")
    deadline = time.monotonic() + args.mineru_timeout
    last_data: dict[str, Any] = {"task_id": task_id}

    while time.monotonic() < deadline:
        result = http_json_request("GET", f"{base_url}/parse/{urllib.parse.quote(task_id)}", timeout=30)
        data = validate_mineru_response(result, "poll")
        last_data = data
        state = data.get("state")

        if state == "done":
            markdown_url = data.get("markdown_url")
            if not markdown_url:
                raise RuntimeError(f"MinerU Agent API finished without markdown_url: {data}")
            markdown = http_text_request(markdown_url, timeout=60)
            data["markdown_url"] = markdown_url
            return markdown, data

        if state == "failed":
            err_msg = data.get("err_msg", "unknown error")
            err_code = data.get("err_code")
            raise RuntimeError(f"MinerU Agent API parse failed ({err_code}): {err_msg}")

        time.sleep(args.mineru_poll_interval)

    raise RuntimeError(f"MinerU Agent API timed out after {args.mineru_timeout}s. Last state: {last_data}")


def run_mineru_agent_url(source_url: str, output_dir: Path, args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    base_url = args.mineru_api_base.rstrip("/")
    payload = mineru_agent_payload(args, source=source_url)
    result = http_json_request("POST", f"{base_url}/parse/url", payload, timeout=30)
    data = validate_mineru_response(result, "submit URL")
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(f"MinerU Agent API submit URL returned no task_id: {data}")

    markdown, poll_data = poll_mineru_agent(task_id, args)
    agent_md = output_dir / "mineru_agent_output.md"
    write_text(agent_md, normalize_text(markdown))
    return markdown, {
        "engine": "MinerU Agent API",
        "mode": "url",
        "task_id": task_id,
        "language": args.mineru_lang,
        "page_range": args.mineru_page_range,
        "enable_table": args.mineru_enable_table,
        "is_ocr": args.mineru_ocr,
        "enable_formula": args.mineru_enable_formula,
        "markdown_url": poll_data.get("markdown_url"),
        "mineru_markdown": str(agent_md),
    }


def run_mineru_agent_file(pdf_path: Path, output_dir: Path, args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    file_size = pdf_path.stat().st_size
    if file_size > 10 * 1024 * 1024:
        raise RuntimeError("MinerU Agent API only supports files up to 10MB. Use --pdf-converter cli or split the PDF.")

    base_url = args.mineru_api_base.rstrip("/")
    payload = mineru_agent_payload(args, file_name=pdf_path.name)
    result = http_json_request("POST", f"{base_url}/parse/file", payload, timeout=30)
    data = validate_mineru_response(result, "create upload URL")
    task_id = data.get("task_id")
    file_url = data.get("file_url")
    if not task_id or not file_url:
        raise RuntimeError(f"MinerU Agent API create upload URL returned invalid data: {data}")

    put_file(file_url, pdf_path, timeout=120)
    markdown, poll_data = poll_mineru_agent(task_id, args)
    agent_md = output_dir / "mineru_agent_output.md"
    write_text(agent_md, normalize_text(markdown))
    return markdown, {
        "engine": "MinerU Agent API",
        "mode": "file",
        "task_id": task_id,
        "language": args.mineru_lang,
        "page_range": args.mineru_page_range,
        "enable_table": args.mineru_enable_table,
        "is_ocr": args.mineru_ocr,
        "enable_formula": args.mineru_enable_formula,
        "markdown_url": poll_data.get("markdown_url"),
        "mineru_markdown": str(agent_md),
    }


def find_mineru_command() -> list[str] | None:
    cli = shutil.which("mineru")
    if cli:
        return [cli]

    candidates = []
    scripts_name = "mineru.exe" if sys.platform.startswith("win") else "mineru"
    candidates.append(Path(sys.executable).parent / "Scripts" / scripts_name)
    candidates.append(Path(sys.executable).parent / scripts_name)
    try:
        candidates.append(Path(site.USER_BASE) / "Scripts" / scripts_name)
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    return None


def run_mineru(pdf_path: Path, output_dir: Path, backend: str, method: str, lang: str) -> Path:
    mineru_cmd = find_mineru_command()
    if not mineru_cmd:
        raise RuntimeError(
            "MinerU CLI was not found. Install MinerU in a Python 3.10-3.13 environment, "
            "then ensure the `mineru` command is on PATH or in the Python user Scripts directory. "
            "Example: pip install -U \"mineru[pipeline]\""
        )

    mineru_output = output_dir / "mineru_output"
    mineru_output.mkdir(parents=True, exist_ok=True)
    cmd = [*mineru_cmd, "-p", str(pdf_path), "-o", str(mineru_output)]
    if backend:
        cmd.extend(["-b", backend])
    if method:
        cmd.extend(["-m", method])
    if lang:
        cmd.extend(["-l", lang])

    completed = subprocess.run(
        cmd,
        cwd=str(output_dir),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"MinerU conversion failed with exit code {completed.returncode}: {message}")

    md_files = sorted(
        mineru_output.rglob("*.md"),
        key=lambda p: (p.stat().st_size, p.stat().st_mtime),
        reverse=True,
    )
    if not md_files:
        raise RuntimeError(f"MinerU completed but no Markdown file was found under {mineru_output}")
    return md_files[0]


def load_resume_as_markdown(args: argparse.Namespace, output_dir: Path) -> tuple[str, Path, dict[str, Any]]:
    if is_http_url(args.resume):
        suffix = url_suffix(args.resume)
        if args.pdf_converter == "cli":
            raise ValueError("URL input requires --pdf-converter api or auto.")
        text, converter_meta = run_mineru_agent_url(args.resume, output_dir, args)
        text = normalize_text(text)
        md_path = output_dir / "source_resume.md"
        write_text(md_path, text)
        return text, md_path, {
            "source_path": args.resume,
            "source_type": suffix.lstrip(".") or "url",
            "pdf_converter": converter_meta,
        }

    source = Path(args.resume).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Resume file not found: {source}")

    suffix = source.suffix.lower()
    meta: dict[str, Any] = {
        "source_path": str(source),
        "source_type": suffix.lstrip(".") or "unknown",
        "pdf_converter": None,
    }

    if suffix in {".md", ".markdown", ".txt", ".docx"}:
        if suffix == ".docx":
            text = normalize_text(read_docx(source))
        else:
            text = normalize_text(read_text(source))
        md_path = output_dir / "source_resume.md"
        write_text(md_path, text)
        return text, md_path, meta

    if suffix == ".pdf":
        conversion_errors: list[str] = []

        if args.pdf_converter in {"api", "auto"}:
            try:
                text, converter_meta = run_mineru_agent_file(source, output_dir, args)
                text = normalize_text(text)
                md_path = output_dir / "source_resume.md"
                write_text(md_path, text)
                meta["pdf_converter"] = converter_meta
                return text, md_path, meta
            except Exception as exc:
                if args.pdf_converter == "api":
                    raise
                conversion_errors.append(f"MinerU Agent API: {exc}")

        if args.pdf_converter in {"cli", "auto"}:
            try:
                md_from_mineru = run_mineru(source, output_dir, args.mineru_backend, args.mineru_method, args.mineru_lang)
                text = normalize_text(read_text(md_from_mineru))
                md_path = output_dir / "source_resume.md"
                write_text(md_path, text)
                meta["pdf_converter"] = {
                    "engine": "MinerU CLI",
                    "backend": args.mineru_backend,
                    "method": args.mineru_method,
                    "lang": args.mineru_lang,
                    "mineru_markdown": str(md_from_mineru),
                }
                return text, md_path, meta
            except Exception as exc:
                conversion_errors.append(f"MinerU CLI: {exc}")

        raise RuntimeError("PDF conversion failed. " + " | ".join(conversion_errors))

    raise ValueError(f"Unsupported resume format: {source.suffix}. Use .md, .markdown, .txt, .docx, or .pdf.")


def clean_heading(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^\*{1,2}(.+?)\*{1,2}$", r"\1", line)
    return line.strip(" ：:")


def normalize_heading_key(value: str) -> str:
    return re.sub(r"[\s:：_-]+", "", clean_heading(value).lower())


def looks_like_heading(line: str) -> bool:
    raw = line.strip()
    if not raw or len(raw) > 80:
        return False
    if re.match(r"^[^:：]{1,20}[:：]\s*\S", raw):
        return False
    if raw.startswith("#"):
        return True
    cleaned = clean_heading(raw)
    if classify_heading(cleaned):
        return True
    return bool(re.fullmatch(r"[A-Z][A-Z /&_-]{2,}", cleaned))


def classify_heading(line: str) -> str | None:
    heading = normalize_heading_key(line)
    for section, keywords in SECTION_KEYWORDS.items():
        if any(normalize_heading_key(keyword) == heading for keyword in keywords):
            return section
    return None


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"summary": []}
    current = "summary"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if looks_like_heading(line):
            section = classify_heading(line)
            if section:
                current = section
                sections.setdefault(current, [])
                continue
        sections.setdefault(current, []).append(raw_line.rstrip())
    return sections


def find_contact(text: str) -> dict[str, list[str]]:
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)))
    phones = sorted(set(re.findall(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", text)))
    urls = sorted(set(re.findall(r"https?://[^\s)）]+", text)))
    return {"emails": emails, "phones": phones, "urls": urls}


def infer_name(text: str, contact: dict[str, list[str]]) -> str:
    for raw in text.splitlines():
        line = clean_heading(raw)
        if not line:
            continue
        if any(email in line for email in contact["emails"]):
            continue
        if looks_like_heading(line):
            continue
        if len(line) <= 32 and not re.search(r"[|@/\\]", line):
            return line
    return "匿名候选人"


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    found = []
    for keyword in keywords:
        pattern = keyword_pattern(keyword)
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(keyword)
    return sorted(set(found), key=lambda item: item.lower())


def keyword_pattern(keyword: str) -> str:
    escaped = re.escape(keyword)
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return escaped
    if re.fullmatch(r"[A-Za-z0-9_+#./ -]+", keyword):
        return rf"(?<![A-Za-z0-9_+#.-]){escaped}(?![A-Za-z0-9_+#.-])"
    return escaped


def extract_skills(text: str, sections: dict[str, list[str]]) -> dict[str, list[str]]:
    skills_text = "\n".join(sections.get("skills", [])) or text
    skills: dict[str, list[str]] = {}
    for category, keywords in TECH_KEYWORDS.items():
        category_found = set(find_keywords(skills_text, keywords))
        category_found.update(find_keywords(text, keywords))
        skills[category] = sorted(category_found, key=lambda item: item.lower())
    return skills


def section_text(sections: dict[str, list[str]], name: str) -> str:
    return "\n".join(line for line in sections.get(name, []) if line.strip()).strip()


def extract_section_items(sections: dict[str, list[str]], name: str) -> list[str]:
    text = section_text(sections, name)
    if not text:
        return []

    items: list[str] = []
    current: list[str] = []
    marker_pattern = r"^(?:[-*•■]\s*|\d+[.)、]\s*)"

    for raw_line in text.splitlines():
        cleaned = clean_heading(raw_line)
        if not cleaned:
            continue
        starts_new = bool(re.match(marker_pattern, cleaned))
        if name == "awards" and current and re.match(r"^(?:19|20)\d{2}", cleaned):
            starts_new = True
        elif name == "awards" and current:
            starts_new = True
        if name == "research" and current and re.search(r"\b(SIGGRAPH|CVPR|ICCV|ECCV|NeurIPS|ICML|ICLR|IEEE|ACM)\b", cleaned):
            starts_new = bool(re.search(r"\b(SIGGRAPH|CVPR|ICCV|ECCV|NeurIPS|ICML|ICLR|IEEE|ACM)\b", " ".join(current)))

        if starts_new:
            if current:
                items.append(" ".join(current).strip())
            current = [re.sub(marker_pattern, "", cleaned).strip()]
        elif current:
            current.append(cleaned)
        else:
            current = [cleaned]

    if current:
        items.append(" ".join(current).strip())
    return [item for item in items if item]


def extract_experience_items(sections: dict[str, list[str]]) -> list[str]:
    text = section_text(sections, "experience")
    if not text:
        return []

    items: list[str] = []
    current_title = ""
    current_details: list[str] = []

    for raw_line in text.splitlines():
        cleaned = clean_heading(raw_line)
        if not cleaned:
            continue
        starts_new = any(token in cleaned for token in ["实习生", "工程师", "研发", "开发", "某", "公司"]) and bool(
            re.search(r"(19|20)\d{2}", cleaned)
        )
        if starts_new and current_title:
            detail_text = "；".join(item.strip("；") for item in current_details if item.strip())
            items.append(f"{current_title}：{detail_text}" if detail_text else current_title)
            current_title = cleaned
            current_details = []
        elif starts_new:
            current_title = cleaned
            current_details = []
        elif current_title:
            detail = re.sub(r"^(?:[-*•■]\s*|\d+[.)、]\s*)", "", cleaned).strip()
            if detail:
                current_details.append(detail)
        else:
            current_title = cleaned
            current_details = []

    if current_title:
        detail_text = "；".join(item.strip("；") for item in current_details if item.strip())
        items.append(f"{current_title}：{detail_text}" if detail_text else current_title)
    return [item for item in items if item]


def extract_education(sections: dict[str, list[str]]) -> list[dict[str, str]]:
    text = section_text(sections, "education")
    entries = []
    for line in text.splitlines():
        cleaned = clean_heading(line)
        if not cleaned:
            continue
        if any(word in cleaned for word in ["大学", "学院", "University", "College", "Institute"]):
            entries.append({"raw": cleaned})
    if not entries and text:
        entries.append({"raw": text})
    return entries


def is_project_title(line: str, next_line: str | None) -> bool:
    cleaned = clean_heading(line)
    if not cleaned or len(cleaned) > 60:
        return False
    has_title_marker = bool(re.match(r"^(?:[•·*+-]\s*|\d+[)、]\s*|\d+\.\s+)", cleaned))
    title_text = clean_project_title(cleaned)
    if re.search(r"[，。；,;]", cleaned) and not has_title_marker:
        return False
    if re.match(r"^(项目背景|技术栈|功能亮点|项目成果|职责|负责|[-*■])", cleaned):
        return False
    if next_line and re.match(r"^\s*(项目背景|技术栈|功能亮点|项目成果|职责|负责)[:：]", next_line):
        return has_title_marker or len(title_text) <= 36
    if re.search(r"(系统|平台|项目|开发|搭建|工具|服务|知识库|小程序|GraphRAG|Agent)", cleaned):
        return has_title_marker or ("项目" in cleaned and len(title_text) <= 36)
    if has_title_marker and len(title_text) <= 48:
        return True
    return False


def clean_project_title(line: str) -> str:
    return re.sub(r"^(?:[•·*+-]\s*|\d+[)、]\s*|\d+\.\s+)", "", clean_heading(line)).strip()


def parse_field_line(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*([^:：]{2,12})[:：]\s*(.+)$", line)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def extract_metrics(text: str) -> list[str]:
    date_ranges = re.findall(r"\d{4}\.\d{1,2}\s*[-~到至]\s*\d{4}\.\d{1,2}", text)
    patterns = [
        r"\d+(?:\.\d+)?\s*(?:%|倍|万\+?|ms|s|秒|分钟|小时|QPS|TPS|GB|MB|条|个|类|以上|以内)",
        r"\d+\s*[-~到至]\s*\d+\s*(?:%|倍|分钟|小时|ms|s)?",
        r"小时级\s*(?:→|->|到|至)\s*分钟级",
    ]
    metrics: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(0).strip()
            if any(value in date_range for date_range in date_ranges):
                continue
            metrics.add(value)
    return sorted(metrics)


def extract_project_tech(text: str) -> list[str]:
    keywords = [item for values in TECH_KEYWORDS.values() for item in values]
    return find_keywords(text, keywords)


def extract_projects(sections: dict[str, list[str]]) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in sections.get("projects", [])]
    projects: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_field: str | None = None

    for index, line in enumerate(lines):
        cleaned = clean_heading(line)
        if not cleaned:
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else None
        if is_project_title(cleaned, next_line):
            if current:
                projects.append(finalize_project(current))
            current = {
                "name": clean_project_title(cleaned),
                "period": "",
                "background": "",
                "role": "",
                "tech_stack": [],
                "claims": [],
                "results": "",
                "raw_lines": [cleaned],
            }
            last_field = None
            continue

        if current is None:
            current = {
                "name": "未命名项目",
                "period": "",
                "background": "",
                "role": "",
                "tech_stack": [],
                "claims": [],
                "results": "",
                "raw_lines": [],
            }

        current["raw_lines"].append(cleaned)
        if re.fullmatch(r"\d{4}\.\d{1,2}\s*[-~到至]\s*(?:\d{4}\.\d{1,2}|至今|present)", cleaned, flags=re.IGNORECASE):
            current["period"] = cleaned
            last_field = None
            continue

        field = parse_field_line(cleaned)
        if field:
            key, value = field
            if "背景" in key:
                current["background"] = value
                last_field = "background"
            elif "技术" in key:
                current["tech_stack"] = extract_project_tech(value)
                if not current["tech_stack"]:
                    current["tech_stack"] = [item.strip() for item in re.split(r"[+、,，/]", value) if item.strip()]
                last_field = None
            elif "职责" in key or "负责" in key:
                current["role"] = value
                last_field = "role"
            elif "成果" in key:
                current["results"] = value
                last_field = "results"
            else:
                current["claims"].append(cleaned)
                last_field = "claims"
        elif re.match(r"^\s*(?:[-*•■]|[0-9]+[.)、])", line) or cleaned.startswith("■"):
            current["claims"].append(re.sub(r"^\s*(?:[-*•■]|[0-9]+[.)、])\s*", "", cleaned))
            last_field = "claims"
        elif last_field == "background":
            current["background"] = f"{current['background']}{cleaned}"
        elif last_field == "role":
            current["role"] = f"{current['role']}{cleaned}"
        elif last_field == "results":
            current["results"] = f"{current['results']}{cleaned}"
        else:
            current["claims"].append(cleaned)
            last_field = "claims"

    if current:
        projects.append(finalize_project(current))
    return [project for project in projects if project["name"] != "未命名项目" or project["claims"]]


def finalize_project(project: dict[str, Any]) -> dict[str, Any]:
    raw_text = "\n".join(project.get("raw_lines", []))
    tech_stack = set(project.get("tech_stack", []))
    tech_stack.update(extract_project_tech(raw_text))
    project["tech_stack"] = sorted(tech_stack, key=lambda item: item.lower())
    project["metrics"] = extract_metrics(raw_text)
    if not project.get("role"):
        inferred_roles = []
        for claim in project.get("claims", []):
            if any(token in claim for token in ["负责", "设计", "实现", "开发", "搭建", "优化", "构建", "参与"]):
                inferred_roles.append(claim)
        project["role"] = "；".join(inferred_roles[:3])
    project["possible_risks"] = analyze_project_risks(project)
    project.pop("raw_lines", None)
    return project


def has_any(text: str, words: list[str]) -> bool:
    return any(word.lower() in text.lower() for word in words)


def add_risk(
    risks: list[dict[str, str]],
    severity: str,
    area: str,
    evidence: str,
    why: str,
    fix: str,
    followup: str,
) -> None:
    risks.append(
        {
            "severity": severity,
            "area": area,
            "evidence": evidence,
            "why_it_matters": why,
            "suggested_fix": fix,
            "likely_followup": followup,
        }
    )


def analyze_project_risks(project: dict[str, Any]) -> list[dict[str, str]]:
    name = project.get("name", "未命名项目")
    text = "\n".join(
        [
            project.get("background", ""),
            project.get("role", ""),
            " ".join(project.get("tech_stack", [])),
            "\n".join(project.get("claims", [])),
            project.get("results", ""),
        ]
    )
    metrics = project.get("metrics", [])
    risks: list[dict[str, str]] = []

    if not project.get("role"):
        add_risk(
            risks,
            "high",
            "个人职责边界",
            name,
            "项目描述里没有清楚区分本人负责部分和团队/开源/他人完成部分。",
            "补充你独立负责的模块、接口、数据流、代码范围，以及不是你做的部分。",
            "这个项目里哪些模块是你独立完成的？哪些是团队或开源方案已有的？",
        )

    if has_any(text, ["优化", "提升", "高性能", "高并发", "实时", "准确率"]) and not metrics:
        add_risk(
            risks,
            "high",
            "量化指标缺失",
            name,
            "简历出现优化或性能/准确率类表述，但没有看到可验证指标。",
            "补充优化前后指标、数据规模、测试方法、统计口径和环境。",
            "你说提升了性能，优化前后的 P95、吞吐或准确率分别是多少？怎么测的？",
        )

    if metrics and has_any(text, ["提升", "优化", "准确率", "速度"]):
        add_risk(
            risks,
            "medium",
            "指标口径追问",
            "；".join(metrics[:5]),
            "指标本身有价值，但面试官会继续追问统计口径、基线和实验条件。",
            "补充 baseline、样本量、评估集、机器配置、并发量或 A/B 对照。",
            "这个指标是离线评估还是线上统计？样本量和测试环境是什么？",
        )

    if has_any(text, ["GraphRAG", "RAG", "知识库"]):
        add_risk(
            risks,
            "high",
            "RAG/GraphRAG 方案深度",
            name,
            "RAG 类项目容易被追问切分、召回、重排、评估和幻觉控制。",
            "补充 chunk 策略、实体/关系抽取、top-k、评估指标、错误案例和改进方案。",
            "GraphRAG 相比普通向量检索解决了什么问题？你如何评估召回和回答质量？",
        )

    if has_any(text, ["Agent", "Multi-Agent", "LangGraph", "工具调用"]):
        add_risk(
            risks,
            "high",
            "Agent 状态与异常处理",
            name,
            "Agent 项目容易被追问状态管理、工具调用、循环控制、重试和失败恢复。",
            "补充状态图、工具 schema、失败分支、超时控制、日志追踪和人工兜底策略。",
            "如果工具调用失败或模型生成错误参数，LangGraph 的流程如何恢复？",
        )

    if has_any(text, ["Neo4j", "Cypher", "图谱"]):
        add_risk(
            risks,
            "medium",
            "图数据库建模与性能",
            name,
            "Neo4j/Cypher 会被追问图谱 schema、索引约束、批量导入和查询优化。",
            "补充节点/边设计、约束索引、导入批大小、查询 explain/profile 和慢查询处理。",
            "100 万节点/关系导入时如何保证速度和一致性？Cypher 慢查询怎么定位？",
        )

    if has_any(text, ["FastAPI", "Django", "RestFramework", "接口"]):
        add_risk(
            risks,
            "medium",
            "后端工程闭环",
            name,
            "接口封装描述通常还会被追问鉴权、异常、限流、日志、部署和测试。",
            "补充 API 设计、错误码、鉴权、参数校验、单元/接口测试、日志与部署方式。",
            "FastAPI 接口如何做鉴权、异常处理和并发性能保障？",
        )

    if has_any(text, ["MinerU", "PDF", "OCR", "多模态", "表格", "公式"]):
        add_risk(
            risks,
            "medium",
            "文档解析可靠性",
            name,
            "文档解析项目容易被追问版面分析、OCR、表格/公式失败案例和质量评估。",
            "补充解析流程、失败样本、人工校验方式、重试策略和解析质量指标。",
            "PDF 中表格、公式、双栏排版解析失败时你怎么发现和修复？",
        )

    if not has_any(text, ["测试", "单元测试", "监控", "日志", "部署", "CI", "上线"]):
        add_risk(
            risks,
            "low",
            "工程闭环不足",
            name,
            "描述偏功能实现，缺少测试、部署、监控和稳定性信息。",
            "补充测试用例、部署环境、日志监控、异常报警和回滚策略。",
            "这个项目如何测试和上线？线上出错你怎么定位？",
        )

    return risks


def flatten_project_risks(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_risks = []
    for project in projects:
        for idx, risk in enumerate(project.get("possible_risks", []), start=1):
            item = {"project": project.get("name", ""), "id": f"{slugify(project.get('name', 'project'))}_{idx}"}
            item.update(risk)
            all_risks.append(item)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(all_risks, key=lambda risk: severity_order.get(risk.get("severity", "low"), 9))


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_").lower()
    return slug[:40] or "project"


def infer_target_roles(
    skills: dict[str, list[str]],
    projects: list[dict[str, Any]],
    research_items: list[str],
    experience_items: list[str],
) -> list[str]:
    text = "\n".join(
        [
            json.dumps(skills, ensure_ascii=False),
            json.dumps(projects, ensure_ascii=False),
            "\n".join(research_items),
            "\n".join(experience_items),
        ]
    )
    roles: list[str] = []

    if has_any(text, ["Agent", "Multi-Agent", "RAG", "GraphRAG", "LangChain", "LangGraph", "LLM"]):
        roles.append("AI Agent / RAG 工程")
    if has_any(text, ["FastAPI", "Django", "Flask", "Spring", "MySQL", "Redis", "接口"]):
        roles.append("后端开发")
    if has_any(text, ["Vue", "React"]) and has_any(text, ["FastAPI", "Django", "接口", "MySQL"]):
        roles.append("全栈开发")
    if has_any(text, ["SIGGRAPH", "O-CNN", "图形学", "3D", "Reinforcement Learning", "MCTS"]):
        roles.append("计算机图形学 / AI 研究")
    if has_any(text, ["C++", "ICPC", "蓝桥杯", "算法"]):
        roles.append("算法 / C++ 开发")

    return roles[:4] or ["CS 技术候选人"]


def infer_interview_focus(projects: list[dict[str, Any]], risks: list[dict[str, Any]]) -> list[str]:
    focus: list[str] = []
    for risk in risks:
        item = f"{risk.get('project', '项目')}：{risk.get('area', '风险点')}"
        if item not in focus:
            focus.append(item)
        if len(focus) >= 5:
            break

    if not any("CS 基础" in item for item in focus):
        focus.append("CS 基础：数据库、网络、并发、工程测试与部署")

    for project in projects:
        name = project.get("name")
        if name and not any(name in item for item in focus):
            focus.append(f"{name}：技术取舍、实现细节与可验证结果")
        if len(focus) >= 6:
            break

    return focus[:6]


def build_profile(text: str, md_path: Path, source_meta: dict[str, Any]) -> dict[str, Any]:
    sections = split_sections(text)
    contact = find_contact(text)
    projects = extract_projects(sections)
    skills = extract_skills(text, sections)
    research_items = extract_section_items(sections, "research")
    experience_items = extract_experience_items(sections)
    award_items = extract_section_items(sections, "awards")
    risks = flatten_project_risks(projects)
    profile = {
        "schema_version": "0.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source_meta,
        "markdown_path": str(md_path),
        "candidate_profile": {
            "name": infer_name(text, contact),
            "contact": contact,
            "education": extract_education(sections),
            "target_roles": infer_target_roles(skills, projects, research_items, experience_items),
            "skills": skills,
            "projects": projects,
            "research": section_text(sections, "research"),
            "publications": research_items,
            "experience": section_text(sections, "experience"),
            "internships": experience_items,
            "awards": section_text(sections, "awards"),
            "award_items": award_items,
            "interview_focus": infer_interview_focus(projects, risks),
        },
        "resume_risks": risks,
    }
    return profile


def render_profile_md(profile: dict[str, Any]) -> str:
    candidate = profile["candidate_profile"]
    skills = candidate["skills"]
    lines = [
        "# 候选人画像",
        "",
        f"- 姓名：{candidate['name']}",
        f"- 来源：{profile['source']['source_path']}",
        f"- Markdown：{profile['markdown_path']}",
        "",
        "## 联系方式",
    ]
    contact = candidate["contact"]
    lines.append(f"- 邮箱：{', '.join(contact['emails']) or '未识别'}")
    lines.append(f"- 电话：{', '.join(contact['phones']) or '未识别'}")
    if contact["urls"]:
        lines.append(f"- 链接：{', '.join(contact['urls'])}")
    lines.extend(["", "## 目标方向推断"])
    lines.append(f"- {', '.join(candidate.get('target_roles', [])) or '未识别'}")
    if candidate.get("interview_focus"):
        lines.extend(["", "## 建议面试重点"])
        lines.extend(f"- {item}" for item in candidate["interview_focus"])

    lines.extend(["", "## 教育经历"])
    if candidate["education"]:
        lines.extend(f"- {entry.get('raw', '')}" for entry in candidate["education"])
    else:
        lines.append("- 未识别")

    lines.extend(["", "## 技能画像"])
    for category, values in skills.items():
        lines.append(f"- {category}: {', '.join(values) if values else '未识别'}")

    lines.extend(["", "## 项目画像"])
    for project in candidate["projects"]:
        lines.extend(
            [
                f"### {project['name']}",
                f"- 时间：{project.get('period') or '未识别'}",
                f"- 背景：{project.get('background') or '未识别'}",
                f"- 个人职责：{project.get('role') or '未识别'}",
                f"- 技术栈：{', '.join(project.get('tech_stack', [])) or '未识别'}",
                f"- 指标：{', '.join(project.get('metrics', [])) or '未识别'}",
            ]
        )
        claims = project.get("claims", [])
        if claims:
            lines.append("- 关键表述：")
            lines.extend(f"  - {claim}" for claim in claims[:8])
        risks = project.get("possible_risks", [])
        if risks:
            lines.append("- 初步风险：")
            lines.extend(f"  - [{risk['severity']}] {risk['area']}：{risk['why_it_matters']}" for risk in risks)
        lines.append("")

    if candidate.get("publications"):
        lines.extend(["## 科研/论文"])
        lines.extend(f"- {item}" for item in candidate["publications"][:5])
        lines.append("")

    if candidate.get("internships"):
        lines.extend(["## 实习/工作经历"])
        lines.extend(f"- {item}" for item in candidate["internships"][:5])
        lines.append("")

    if candidate.get("award_items"):
        lines.extend(["## 奖项/竞赛"])
        lines.extend(f"- {item}" for item in candidate["award_items"][:8])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_risks_md(profile: dict[str, Any]) -> str:
    risks = profile["resume_risks"]
    lines = ["# 简历风险点", ""]
    if not risks:
        lines.append("未识别到明显风险点。")
        return "\n".join(lines) + "\n"

    for index, risk in enumerate(risks, start=1):
        lines.extend(
            [
                f"## {index}. [{risk['severity']}] {risk['area']}",
                f"- 项目：{risk['project']}",
                f"- 证据：{risk['evidence']}",
                f"- 为什么会被追问：{risk['why_it_matters']}",
                f"- 建议补充：{risk['suggested_fix']}",
                f"- 可能追问：{risk['likely_followup']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(profile: dict[str, Any], output_dir: Path) -> dict[str, str]:
    json_path = output_dir / "candidate_profile.json"
    profile_md_path = output_dir / "candidate_profile.md"
    risks_md_path = output_dir / "resume_risks.md"
    write_text(json_path, json.dumps(profile, ensure_ascii=False, indent=2))
    write_text(profile_md_path, render_profile_md(profile))
    write_text(risks_md_path, render_risks_md(profile))
    _, rewrite_outputs = generate_resume_rewrite_suggestions(json_path, output_dir=output_dir)
    return {
        "profile_json": str(json_path),
        "profile_markdown": str(profile_md_path),
        "risk_report": str(risks_md_path),
        "source_markdown": profile["markdown_path"],
        "rewrite_json": rewrite_outputs["rewrite_json"],
        "rewrite_markdown": rewrite_outputs["rewrite_markdown"],
    }


def parse_resume_to_profile(resume: str, output_dir: Path | None = None, **kwargs: Any) -> tuple[dict[str, Any], dict[str, str]]:
    args_list = [resume]
    if output_dir:
        args_list.extend(["--output-dir", str(output_dir)])

    option_map = {
        "pdf_converter": "--pdf-converter",
        "mineru_api_base": "--mineru-api-base",
        "mineru_page_range": "--mineru-page-range",
        "mineru_timeout": "--mineru-timeout",
        "mineru_poll_interval": "--mineru-poll-interval",
        "mineru_backend": "--mineru-backend",
        "mineru_method": "--mineru-method",
        "mineru_lang": "--mineru-lang",
    }
    bool_flags = {
        "mineru_enable_table": "--mineru-enable-table",
        "mineru_enable_formula": "--mineru-enable-formula",
    }

    for key, flag in option_map.items():
        value = kwargs.get(key)
        if value is not None:
            args_list.extend([flag, str(value)])

    for key, flag in bool_flags.items():
        value = kwargs.get(key)
        if value is not None:
            args_list.append(flag if value else f"--no-{flag[2:]}")

    if kwargs.get("mineru_ocr"):
        args_list.append("--mineru-ocr")

    args = parse_args(args_list)
    resolved_output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir(args.resume)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    text, md_path, source_meta = load_resume_as_markdown(args, resolved_output_dir)
    profile = build_profile(text, md_path, source_meta)
    outputs = write_outputs(profile, resolved_output_dir)
    return profile, outputs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a CS resume into a candidate profile and risk report.")
    parser.add_argument("resume", help="Path to .md, .markdown, .txt, .docx, or .pdf resume, or a public document URL.")
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Output directory. Defaults to <resume stem>_parsed next to the resume.",
    )
    parser.add_argument(
        "--pdf-converter",
        choices=["api", "cli", "auto"],
        default="api",
        help="PDF conversion path. Default: api (MinerU Agent lightweight API).",
    )
    parser.add_argument(
        "--mineru-api-base",
        default=MINERU_AGENT_BASE_URL,
        help=f"MinerU Agent API base URL. Default: {MINERU_AGENT_BASE_URL}",
    )
    parser.add_argument("--mineru-page-range", help='MinerU Agent page range, for example "1-10" or "2,4-6".')
    parser.add_argument(
        "--mineru-enable-table",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable MinerU table parsing for Agent API. Default: enabled.",
    )
    parser.add_argument(
        "--mineru-enable-formula",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable MinerU formula parsing for Agent API. Default: enabled.",
    )
    parser.add_argument("--mineru-ocr", action="store_true", help="Enable OCR in MinerU Agent API. Default: disabled.")
    parser.add_argument("--mineru-timeout", type=int, default=300, help="MinerU Agent poll timeout in seconds.")
    parser.add_argument(
        "--mineru-poll-interval",
        type=float,
        default=3.0,
        help="MinerU Agent poll interval in seconds.",
    )
    parser.add_argument(
        "--mineru-backend",
        default="pipeline",
        help="MinerU CLI backend when --pdf-converter cli or auto uses CLI. Default: pipeline.",
    )
    parser.add_argument("--mineru-method", default="auto", help="MinerU CLI parse method. Default: auto.")
    parser.add_argument("--mineru-lang", default="ch", help="MinerU language hint for API or CLI. Default: ch.")
    return parser.parse_args(argv)


def default_output_dir(resume: str) -> Path:
    if is_http_url(resume):
        return Path.cwd() / f"{safe_stem(resume)}_parsed"
    source = Path(resume).resolve()
    return source.with_name(f"{source.stem}_parsed")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        profile, outputs = parse_resume_to_profile(
            args.resume,
            output_dir=Path(args.output_dir).resolve() if args.output_dir else None,
            pdf_converter=args.pdf_converter,
            mineru_api_base=args.mineru_api_base,
            mineru_page_range=args.mineru_page_range,
            mineru_enable_table=args.mineru_enable_table,
            mineru_enable_formula=args.mineru_enable_formula,
            mineru_ocr=args.mineru_ocr,
            mineru_timeout=args.mineru_timeout,
            mineru_poll_interval=args.mineru_poll_interval,
            mineru_backend=args.mineru_backend,
            mineru_method=args.mineru_method,
            mineru_lang=args.mineru_lang,
        )
    except Exception as exc:
        print(f"parse_resume.py failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
