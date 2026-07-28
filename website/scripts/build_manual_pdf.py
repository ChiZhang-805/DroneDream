from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / "frontend" / "public" / "docs" / "downloads"
TEMPLATE = ROOT / "website" / "manual-pdf" / "manual-template.tex"
SOURCE_DATE_EPOCH = "1785211535"
PAGE_BREAK_MARKER = "<!-- manual-pdf-pagebreak -->"
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

MANUALS = {
    "en": {
        "source": DOWNLOADS / "DroneDream-Manual-en.md",
        "cover": "DroneDream-Manual-en-cover.png",
        "output": DOWNLOADS / "DroneDream-Manual-en.pdf",
        "expected_pages": 19,
    },
    "zh-CN": {
        "source": DOWNLOADS / "DroneDream-Manual-zh-CN.md",
        "cover": "DroneDream-Manual-zh-CN-cover.png",
        "output": DOWNLOADS / "DroneDream-Manual-zh-CN.pdf",
        "expected_pages": 17,
    },
}


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Required executable is unavailable: {name}")
    return path


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        tail = "\n".join(output.splitlines()[-80:])
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: "
            f"{' '.join(command)}\n{tail}"
        )
    return output


def pdf_page_count(pdfinfo: str, pdf_path: Path, *, env: dict[str, str]) -> int:
    output = run([pdfinfo, str(pdf_path)], cwd=DOWNLOADS, env=env)
    match = re.search(r"^Pages:\s+(\d+)\s*$", output, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"pdfinfo did not report a page count for {pdf_path}")
    return int(match.group(1))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manual_trailer_id(
    source: Path,
    source_text: str,
    *,
    cover_name: str,
) -> str:
    input_paths = [source, TEMPLATE, DOWNLOADS / cover_name]
    for relative_path in MARKDOWN_IMAGE_PATTERN.findall(source_text):
        input_paths.append(DOWNLOADS / relative_path)

    digest = hashlib.sha256()
    for input_path in input_paths:
        if not input_path.is_file():
            raise RuntimeError(f"Manual input is missing: {input_path}")
        relative_name = input_path.relative_to(ROOT).as_posix()
        if input_path.suffix.lower() in {".md", ".tex"}:
            payload = (
                input_path.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .encode("utf-8")
            )
        else:
            payload = input_path.read_bytes()
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def compile_manual(
    locale: str,
    *,
    build_root: Path,
    pandoc: str,
    xelatex: str,
    pdfinfo: str,
    env: dict[str, str],
) -> tuple[Path, int, str]:
    config = MANUALS[locale]
    source = Path(config["source"])
    build_dir = build_root / locale
    build_dir.mkdir(parents=True, exist_ok=True)
    tex_path = build_dir / f"DroneDream-Manual-{locale}.tex"
    source_text = source.read_text(encoding="utf-8")
    trailer_id = manual_trailer_id(
        source,
        source_text,
        cover_name=str(config["cover"]),
    )
    marker_count = source_text.count(PAGE_BREAK_MARKER)
    if marker_count != 1:
        raise RuntimeError(
            f"{source.name} must contain exactly one {PAGE_BREAK_MARKER!r}; "
            f"found {marker_count}"
        )
    pandoc_source = build_dir / source.name
    pandoc_source.write_text(
        source_text.replace(PAGE_BREAK_MARKER, r"\clearpage"),
        encoding="utf-8",
        newline="\n",
    )

    run(
        [
            pandoc,
            "--standalone",
            "--from=markdown+yaml_metadata_block",
            "--to=latex",
            "--no-highlight",
            "--columns=12",
            f"--template={TEMPLATE}",
            f"--variable=coverimage:{config['cover']}",
            f"--variable=trailerid:{trailer_id}",
            f"--output={tex_path}",
            str(pandoc_source),
        ],
        cwd=DOWNLOADS,
        env=env,
    )

    latex_command = [
        xelatex,
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-output-directory={build_dir}",
        str(tex_path),
    ]
    run(latex_command, cwd=DOWNLOADS, env=env)
    run(latex_command, cwd=DOWNLOADS, env=env)

    pdf_path = tex_path.with_suffix(".pdf")
    log_path = tex_path.with_suffix(".log")
    log = log_path.read_text(encoding="utf-8", errors="replace")
    overfull = [line for line in log.splitlines() if "Overfull \\hbox" in line]
    if overfull:
        raise RuntimeError(
            f"{locale} manual contains overfull boxes:\n" + "\n".join(overfull)
        )

    pages = pdf_page_count(pdfinfo, pdf_path, env=env)
    expected_pages = int(config["expected_pages"])
    if pages != expected_pages:
        raise RuntimeError(
            f"{locale} manual has {pages} pages; expected {expected_pages}"
        )
    return pdf_path, pages, sha256(pdf_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the complete English and Simplified Chinese DroneDream manuals "
            "from their committed Markdown sources with the committed XeLaTeX template."
        )
    )
    parser.add_argument("--locale", choices=["en", "zh-CN", "all"], default="all")
    parser.add_argument(
        "--verify-deterministic",
        action="store_true",
        help="Build twice and require byte-identical PDFs before updating downloads.",
    )
    args = parser.parse_args()

    pandoc = require_tool("pandoc")
    xelatex = require_tool("xelatex")
    pdfinfo = require_tool("pdfinfo")
    if not TEMPLATE.is_file():
        raise RuntimeError(f"Manual template is missing: {TEMPLATE}")

    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    env["FORCE_SOURCE_DATE"] = "1"
    env["TZ"] = "UTC"

    locales = list(MANUALS) if args.locale == "all" else [args.locale]
    with tempfile.TemporaryDirectory(prefix="dronedream-manual-build-") as first_temp:
        first_root = Path(first_temp)
        first_results = {
            locale: compile_manual(
                locale,
                build_root=first_root,
                pandoc=pandoc,
                xelatex=xelatex,
                pdfinfo=pdfinfo,
                env=env,
            )
            for locale in locales
        }

        if args.verify_deterministic:
            with tempfile.TemporaryDirectory(
                prefix="dronedream-manual-rebuild-"
            ) as second_temp:
                second_root = Path(second_temp)
                second_results = {
                    locale: compile_manual(
                        locale,
                        build_root=second_root,
                        pandoc=pandoc,
                        xelatex=xelatex,
                        pdfinfo=pdfinfo,
                        env=env,
                    )
                    for locale in locales
                }
                for locale in locales:
                    if first_results[locale][2] != second_results[locale][2]:
                        raise RuntimeError(
                            f"{locale} PDF is not deterministic: "
                            f"{first_results[locale][2]} != "
                            f"{second_results[locale][2]}"
                        )

        for locale in locales:
            built_pdf, pages, digest = first_results[locale]
            output = Path(MANUALS[locale]["output"])
            shutil.copyfile(built_pdf, output)
            print(
                f"{locale}: {output} | pages={pages} | "
                f"sha256={digest} | deterministic={args.verify_deterministic}"
            )


if __name__ == "__main__":
    main()
