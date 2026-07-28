from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

TOKEN_PATTERN = re.compile(r"[a-z0-9_.%/+:-]+")
POINTS_PER_MM = 72.0 / 25.4
BODY_BOTTOM_MARGIN_MM = 16.0
BODY_BOTTOM_TOLERANCE_POINTS = 36.0


def normalize(text: str) -> list[str]:
    text = (
        text.lower()
        .replace("\u00a0", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2019", "'")
    )
    return [cleaned for token in TOKEN_PATTERN.findall(text) if (cleaned := token.strip(".:"))]


def portable_report_path(path: Path) -> str:
    resolved = path.resolve()
    parts = list(resolved.parts)
    for index, part in enumerate(parts):
        if part.lower() == "technical-report":
            return Path(*parts[index:]).as_posix()
    return path.as_posix()


def write_json_lf(path: Path, value: object) -> None:
    """Write canonical UTF-8 JSON without platform newline translation."""
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def pandoc_blocks(source: Path, pandoc: Path) -> list[dict[str, object]]:
    completed = subprocess.run(
        [
            str(pandoc),
            "--from=latex",
            "--to=plain",
            "--wrap=none",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    blocks = re.split(r"\n\s*\n", completed.stdout)
    records: list[dict[str, object]] = []
    in_references = False
    for raw in blocks:
        text = " ".join(line.strip() for line in raw.splitlines()).strip()
        if not text or text == "[image]":
            continue
        if text.upper() == "REFERENCES":
            in_references = True
            continue
        if text.upper().startswith("APPENDIX A."):
            in_references = False
            continue
        if in_references:
            continue
        if re.fullmatch(r"(?:\d+(?:\.\d+)*|A\.\d+)\s+.+", text):
            continue
        if text.lower().startswith("table ") and ":" in text:
            continue
        if text.lower().startswith("github.com/"):
            continue
        if text.startswith("- "):
            style = "bullet"
            text = text[2:].strip()
        elif text.lower().startswith("figure "):
            style = "caption"
        elif not re.search(r"[.!?]$", text):
            continue
        else:
            style = "body"
        tokens = normalize(text)
        if len(tokens) < 5:
            continue
        records.append(
            {
                "index": len(records) + 1,
                "style": style,
                "text": text,
                "tokens": tokens,
            }
        )
    if records:
        records[0]["style"] = "abstract"
    return records


def source_exception_inventory(source: Path) -> dict[str, int]:
    text = source.read_text(encoding="utf-8")
    return {
        "headings": len(
            re.findall(
                r"\\(?:section|subsection|subsubsection)\{",
                text,
            )
        ),
        "list_items": len(re.findall(r"(?m)^\s*\\item(?:\[[^\]]*\])?", text)),
        "display_formulas": len(
            re.findall(
                r"\\begin\{(?:equation\*?|align\*?|gather\*?|"
                r"multline\*?|displaymath)\}|\\\[",
                text,
            )
        ),
        "code_blocks": len(
            re.findall(
                r"\\begin\{(?:verbatim|lstlisting|minted)\}",
                text,
            )
        ),
        "figure_captions": len(re.findall(r"\\emph\{Figure\s+\d+", text)),
        "table_captions": len(re.findall(r"\\caption\{", text)),
        "references": len(re.findall(r"\\hypertarget\{ref_\d+\}", text)),
    }


def page_words(pdf: Path) -> list[list[dict[str, object]]]:
    pages: list[list[dict[str, object]]] = []
    with pdfplumber.open(pdf) as document:
        for page in document.pages:
            words = page.extract_words(
                keep_blank_chars=False,
                use_text_flow=False,
                x_tolerance=1,
                y_tolerance=2,
            )
            expanded: list[dict[str, object]] = []
            for source_word_index, word in enumerate(words):
                for token in normalize(str(word["text"])):
                    item = dict(word)
                    item["source_word_index"] = source_word_index
                    item["source_text"] = str(word["text"])
                    item["normalized"] = token
                    expanded.append(item)
            pages.append(expanded)
    return pages


def find_sequence(
    values: list[str],
    phrase: list[str],
    start: int = 0,
) -> int | None:
    for index in range(start, len(values) - len(phrase) + 1):
        if values[index : index + len(phrase)] == phrase:
            return index
    return None


def geometry_audit(pdf: Path, records: list[dict[str, object]]) -> dict:
    pages = page_words(pdf)
    audited: list[dict[str, object]] = []
    unlocated: list[int] = []
    split: list[int] = []
    page_cursors = [0 for _ in pages]
    current_page = 0

    for record in records:
        tokens = list(record["tokens"])
        match = None
        start_phrase: list[str] = []
        end_phrase: list[str] = []
        for phrase_length in (3, 2, 1):
            phrase_length = min(phrase_length, len(tokens))
            start_phrase = tokens[:phrase_length]
            end_phrase = tokens[-phrase_length:]
            for page_index in range(current_page, len(pages)):
                words = pages[page_index]
                values = [str(word["normalized"]) for word in words]
                start_index = find_sequence(
                    values,
                    start_phrase,
                    page_cursors[page_index],
                )
                if start_index is None:
                    start_index = find_sequence(values, start_phrase)
                if start_index is None:
                    continue
                end_index = find_sequence(
                    values,
                    end_phrase,
                    start_index + phrase_length,
                )
                if end_index is not None:
                    span = end_index + phrase_length - start_index
                    if phrase_length == 1 and not (len(tokens) * 0.55 <= span <= len(tokens) * 1.8):
                        continue
                    match = (
                        page_index,
                        words,
                        start_index,
                        end_index + phrase_length,
                    )
                    page_cursors[page_index] = end_index + phrase_length
                    current_page = page_index
                    break
            if match is not None:
                break
        if match is None:
            start_pages: list[int] = []
            end_pages: list[int] = []
            for page_index, words in enumerate(pages):
                values = [str(word["normalized"]) for word in words]
                if find_sequence(values, start_phrase) is not None:
                    start_pages.append(page_index + 1)
                if find_sequence(values, end_phrase) is not None:
                    end_pages.append(page_index + 1)
            if start_pages and end_pages and not set(start_pages) & set(end_pages):
                split.append(int(record["index"]))
            else:
                unlocated.append(int(record["index"]))
            continue

        page_index, words, start_index, end_index = match
        paragraph_words = words[start_index:end_index]
        lines: list[list[dict[str, object]]] = []
        for word in paragraph_words:
            for line in lines:
                if abs(float(line[0]["top"]) - float(word["top"])) <= 1.5:
                    line.append(word)
                    break
            else:
                lines.append([word])
        lines.sort(key=lambda line: float(line[0]["top"]))
        widths = [
            max(float(word["x1"]) for word in line) - min(float(word["x0"]) for word in line)
            for line in lines
        ]
        widest = max(widths) if widths else 1.0
        ratio = widths[-1] / widest if widths else 1.0
        style = str(record["style"])
        if style in {"body", "abstract"}:
            policy_category = "explanatory_body"
        elif style == "bullet":
            policy_category = "exception_list"
        elif style == "caption":
            policy_category = "exception_caption"
        else:
            policy_category = "exception_other"
        last_line_words: list[str] = []
        seen_source_words: set[int] = set()
        if lines:
            for word in sorted(lines[-1], key=lambda item: float(item["x0"])):
                source_word_index = int(word["source_word_index"])
                if source_word_index in seen_source_words:
                    continue
                seen_source_words.add(source_word_index)
                last_line_words.append(str(word["source_text"]))
        minimum = 6 if style in {"body", "abstract"} else 1
        maximum = 3 if style == "bullet" else None
        audited.append(
            {
                "index": record["index"],
                "page": page_index + 1,
                "style": style,
                "policy_category": policy_category,
                "lines": len(lines),
                "last_line_ratio": round(ratio, 4),
                "last_line_text": " ".join(last_line_words),
                "last_line_pass_50": ratio >= 0.5,
                "last_line_pass_80": ratio >= 0.8,
                "line_policy_passed": (
                    len(lines) >= minimum and (maximum is None or len(lines) <= maximum)
                ),
                "text": record["text"],
            }
        )

    explanatory_body = [item for item in audited if item["policy_category"] == "explanatory_body"]
    explanatory_failures = [
        {
            "index": item["index"],
            "page": item["page"],
            "last_line_ratio": item["last_line_ratio"],
            "last_line_text": item["last_line_text"],
            "text": item["text"],
        }
        for item in explanatory_body
        if not item["last_line_pass_80"]
    ]
    exception_counts = {
        category: sum(item["policy_category"] == category for item in audited)
        for category in (
            "exception_list",
            "exception_caption",
            "exception_other",
        )
    }

    return {
        "records": audited,
        "audited": len(audited),
        "unlocated": unlocated,
        "cross_page_splits": split,
        "last_line_below_50": [item["index"] for item in audited if not item["last_line_pass_50"]],
        "last_line_below_80": [item["index"] for item in audited if not item["last_line_pass_80"]],
        "explanatory_body": {
            "total": len(explanatory_body),
            "passed_80": len(explanatory_body) - len(explanatory_failures),
            "failed_80": len(explanatory_failures),
            "failures": explanatory_failures,
        },
        "exceptions": {
            "categories": exception_counts,
            "definition": {
                "exception_list": (
                    "List items are reported but excluded from the explanatory-body last-line gate."
                ),
                "exception_caption": (
                    "Figure and table captions are reported but excluded "
                    "from the explanatory-body last-line gate."
                ),
                "exception_other": (
                    "Headings, formulas, code, and references are excluded "
                    "before geometry matching or categorized here."
                ),
            },
        },
        "body_below_6_lines": [
            item["index"]
            for item in audited
            if item["policy_category"] == "explanatory_body" and item["lines"] < 6
        ],
        "bullets_above_3_lines": [
            item["index"] for item in audited if item["style"] == "bullet" and item["lines"] > 3
        ],
    }


def gray_text_runs(pdf: Path) -> int:
    count = 0
    with pdfplumber.open(pdf) as document:
        for page in document.pages:
            active = False
            for character in page.chars:
                color = character.get("non_stroking_color")
                is_gray = False
                if isinstance(color, (tuple, list)) and len(color) >= 3:
                    channels = [float(value) for value in color[:3]]
                    if max(channels) <= 1:
                        channels = [value * 255 for value in channels]
                    luminance = sum(channels) / 3
                    is_gray = max(channels) - min(channels) <= 10 and 35 < luminance < 245
                if is_gray and not active:
                    count += 1
                active = is_gray
    return count


def link_audit(pdf: Path) -> dict[str, object]:
    reader = PdfReader(pdf)
    internal = 0
    external: list[str] = []
    for page in reader.pages:
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            action = annotation.get("/A")
            if action and action.get("/URI"):
                external.append(str(action.get("/URI")))
            if annotation.get("/Dest") is not None or (action and action.get("/D") is not None):
                internal += 1
    return {
        "internal": internal,
        "external": len(external),
        "repository_link_present": ("https://github.com/ChiZhang-805/DroneDream" in external),
    }


def bottom_audit(pdf: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with pdfplumber.open(pdf) as document:
        for page_number, page in enumerate(document.pages, 1):
            words = page.extract_words()
            body_bottom_target = page.height - BODY_BOTTOM_MARGIN_MM * POINTS_PER_MM
            body = [
                word
                for word in words
                if float(word["top"]) < body_bottom_target + 6.0
                and not (
                    str(word["text"]) == str(page_number)
                    and float(word["top"]) > body_bottom_target
                )
            ]
            drawable_bottoms = [
                float(item["bottom"])
                for collection in (page.images, page.rects)
                for item in collection
                if float(item.get("top", page.height)) < body_bottom_target + 6.0
                and float(item.get("bottom", 0.0)) <= body_bottom_target + 6.0
            ]
            content_bottom = max([float(word["bottom"]) for word in body] + drawable_bottoms)
            gap_to_body_bottom = max(0.0, body_bottom_target - content_bottom)
            results.append(
                {
                    "page": page_number,
                    "body_bottom_target_points": round(body_bottom_target, 2),
                    "content_bottom_points": round(content_bottom, 2),
                    "gap_to_body_bottom_points": round(gap_to_body_bottom, 2),
                    "gap_to_body_bottom_lines": round(gap_to_body_bottom / 12.0, 3),
                    "passed_bottom_line": (gap_to_body_bottom <= BODY_BOTTOM_TOLERANCE_POINTS),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--pandoc",
        type=Path,
        default=Path(shutil.which("pandoc") or "pandoc"),
    )
    args = parser.parse_args()
    records = pandoc_blocks(args.source, args.pandoc)
    geometry = geometry_audit(args.pdf, records)
    bottoms = bottom_audit(args.pdf)
    exception_inventory = source_exception_inventory(args.source)
    result = {
        "schema_version": "dronedream.latex-technical-report-audit.v2",
        "pdf": portable_report_path(args.pdf),
        "source": portable_report_path(args.source),
        "pages": len(PdfReader(args.pdf).pages),
        "paragraph_geometry": geometry,
        "paragraph_policy": {
            "explanatory_body": {
                "definition": (
                    "Abstract and prose paragraphs that explain a claim, "
                    "method, result, limitation, or evidence boundary."
                ),
                "last_line_target_ratio": 0.8,
                "total": geometry["explanatory_body"]["total"],
                "passed": geometry["explanatory_body"]["passed_80"],
                "failed": geometry["explanatory_body"]["failed_80"],
                "failure_locations": geometry["explanatory_body"]["failures"],
            },
            "reasonable_exceptions": {
                "definition": (
                    "Headings, list items, display formulas, code blocks, "
                    "figure captions, table captions, and references do not "
                    "use the explanatory-body last-line gate."
                ),
                "inventory": exception_inventory,
            },
        },
        "bottoms": bottoms,
        "bottom_failures": [item["page"] for item in bottoms if not item["passed_bottom_line"]],
        "gray_text_run_count": gray_text_runs(args.pdf),
        "links": link_audit(args.pdf),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_lf(args.output, result)
    print(
        json.dumps(
            {
                "pages": result["pages"],
                "audited": geometry["audited"],
                "unlocated": len(geometry["unlocated"]),
                "cross_page_splits": len(geometry["cross_page_splits"]),
                "last_line_below_50": len(geometry["last_line_below_50"]),
                "last_line_below_80": len(geometry["last_line_below_80"]),
                "explanatory_body": {
                    "total": geometry["explanatory_body"]["total"],
                    "passed_80": geometry["explanatory_body"]["passed_80"],
                    "failed_80": geometry["explanatory_body"]["failed_80"],
                },
                "exceptions": geometry["exceptions"]["categories"],
                "source_exception_inventory": exception_inventory,
                "body_below_6_lines": len(geometry["body_below_6_lines"]),
                "bullets_above_3_lines": len(geometry["bullets_above_3_lines"]),
                "bottom_failures": result["bottom_failures"],
                "gray_text_run_count": result["gray_text_run_count"],
                "links": result["links"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
