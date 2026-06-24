#!/usr/bin/env python
"""Apply a current-LLM answer judgement to a live interview session."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import interview_session as controller


VALID_QUALITIES = {"strong", "partial", "weak", "wrong"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def should_remove_source_judgement(source: Path, session_dir: Path, archive_dir: Path) -> bool:
    source = source.resolve()
    session_dir = session_dir.resolve()
    archive_dir = archive_dir.resolve()
    return source.is_file() and is_relative_to(source, session_dir) and not is_relative_to(source, archive_dir)


def one_line(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [one_line(item) for item in value if one_line(item)]
    text = one_line(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[；;]\s*", text) if item.strip()]


def normalize_judgement(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    quality = one_line(payload.get("quality")).lower()
    if quality not in VALID_QUALITIES:
        raise ValueError(f"quality must be one of {sorted(VALID_QUALITIES)}")

    try:
        score = int(payload.get("score"))
    except (TypeError, ValueError):
        raise ValueError("score must be an integer from 1 to 5") from None
    if score < 1 or score > 5:
        raise ValueError("score must be an integer from 1 to 5")

    try:
        confidence = float(payload.get("confidence", 0.75))
    except (TypeError, ValueError):
        confidence = 0.75
    confidence = max(0.0, min(confidence, 1.0))

    return {
        "quality": quality,
        "score": score,
        "strengths": normalize_list(payload.get("strengths")),
        "issues": normalize_list(payload.get("issues")),
        "answer_summary": one_line(payload.get("answer_summary")),
        "feedback": one_line(payload.get("feedback")),
        "answer_text": str(payload.get("answer_text") or payload.get("candidate_answer") or "").strip(),
        "hints_used": int(current.get("hint_level", 0) or 0),
        "judge_source": "llm",
        "judge_confidence": confidence,
    }


def apply_judgement(session_dir: Path, judgement_json: Path) -> dict[str, Any]:
    state = controller.load_session_state(session_dir)
    current = state.get("current_question") or {}
    if not current:
        raise ValueError("No active question in this session.")

    raw = read_json(judgement_json)
    if not isinstance(raw, dict):
        raise ValueError("Judgement JSON must be an object.")
    payload = normalize_judgement(raw, current)

    archive_dir = session_dir / "llm_judgements"
    archive_dir.mkdir(parents=True, exist_ok=True)
    question_id = one_line(current.get("question_id")) or "question"
    archive_path = archive_dir / f"{question_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_json(
        archive_path,
        {
            "schema_version": "1.0",
            "kind": "llm_answer_judgement",
            "source_judgement_json": str(judgement_json),
            "question": current,
            "judgement": payload,
            "next_followup": one_line(raw.get("next_followup")),
        },
    )

    result = controller.record_answer_from_dict(session_dir, payload)
    source_removed = False
    if should_remove_source_judgement(judgement_json, session_dir, archive_dir):
        judgement_json.unlink()
        source_removed = True
    return {
        "ok": True,
        "session_dir": str(session_dir),
        "archived_judgement": str(archive_path),
        "source_judgement_removed": source_removed,
        "record_result": result,
        "next_followup": one_line(raw.get("next_followup")),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a current-LLM answer judgement to a live interview session.")
    parser.add_argument("session_dir", help="Path to the live session directory.")
    parser.add_argument("judgement_json", help="Path to the LLM judgement JSON file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = apply_judgement(Path(args.session_dir).resolve(), Path(args.judgement_json).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
