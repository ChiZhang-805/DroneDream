# DroneDream manual PDF build

The downloadable English and Simplified Chinese manuals are generated from the
same long-form Markdown files used by the public website. Do not edit the PDF
files by hand.

From the repository root, run:

```powershell
python website\scripts\build_manual_pdf.py --locale all --verify-deterministic
```

The build requires `pandoc`, `xelatex`, and `pdfinfo` on `PATH`. It consumes:

- `frontend/public/docs/downloads/DroneDream-Manual-en.md`
- `frontend/public/docs/downloads/DroneDream-Manual-zh-CN.md`
- the locale-specific cover and screenshots referenced by those Markdown files
- `website/manual-pdf/manual-template.tex`

It writes the two downloadable PDFs in place, requires 19 English pages and 17
Chinese pages, rejects overfull horizontal boxes, and builds each locale twice
in independent temporary directories. The command fails unless both builds are
byte-identical.

The committed Markdown marker `<!-- manual-pdf-pagebreak -->` is replaced with
`\clearpage` only for PDF generation. Browsers do not render the marker.
