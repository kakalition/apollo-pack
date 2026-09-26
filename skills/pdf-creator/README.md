# pdf-creator

A portable [Agent Skill](https://skills.sh) that turns a structured JSON
document spec — or a Markdown file — into a production-grade PDF: headings,
lists, tables, images, multi-column sections, a table of contents, running
headers and footers, watermarks, fonts, and optional encryption. It works with
any Agent Skills host (Claude Code, Hermes, Codex, Kilo, nanobot/OpenClaw, and
others).

Source: <https://github.com/kakalition/apollo-pack/tree/main/skills/pdf-creator>

Everything executable lives in focused Python scripts under
`pdf-creator/scripts/`. The agent composes a spec and runs a script; the script
owns layout and prints one JSON envelope per run. State — a document library,
registered assets and fonts, and a render history — lives in a local SQLite
database. There is no server, and no network access unless a spec points at a
remote image and the caller passes `--allow-remote`.

## What it does

- Renders a JSON document spec to PDF with reportlab's flowable layout.
- Blocks: heading, paragraph, rich inline text, list, table, image, figure,
  code, callout, blockquote, divider, spacer, page break, page template,
  columns, table of contents, checkbox list, definition list, key/value grid,
  anchor, QR code, and barcode.
- Page control: named sizes or `WxH`, portrait/landscape, per-side margins,
  headers, footers with `{page}`/`{pages}`, watermarks, page numbers,
  full-bleed background color, and a cover page.
- Data: tables with spans, zebra striping, per-cell styles, repeating headers,
  and automatic numeric alignment.
- Media: PNG/JPEG/GIF/BMP natively, more with Pillow, data URIs, local assets,
  optional remote URLs, EXIF orientation, and aspect-preserving scaling.
- Typesetting: eight built-in themes (modern and sans-serif by default, with
  serif available on request), per-style overrides, embedded TTF/OTF families
  with bold/italic faces, and a table of contents with PDF outline entries.
- Security: user/owner passwords with print/copy/modify permissions.
- Convenience: Markdown to PDF, `{{var}}` substitution, a reusable document
  library, and a render history.
- Emits host-agnostic scheduling artifacts and installs nothing.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill pdf-creator --agent <your-agent> --copy --yes
```

For nanobot specifically, `--agent openclaw` is the marketplace agent id:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill pdf-creator --agent openclaw --copy --yes
```

Manual install: copy the `pdf-creator/` folder into your host's skills
directory so that `pdf-creator/SKILL.md` is discoverable. The folder name must
stay `pdf-creator`.

## Quick start

```bash
SKILL=./pdf-creator
python3 "$SKILL/scripts/init.py" init
python3 "$SKILL/scripts/settings.py" set --theme report --margin 20mm

# render a bundled example
python3 "$SKILL/scripts/templates.py" demo report --out report.pdf

# or a spec of your own
python3 "$SKILL/scripts/render.py" render --spec doc.json --out doc.pdf

# or from Markdown
python3 "$SKILL/scripts/render.py" from-markdown --in notes.md --out notes.pdf --toc
```

A stored document re-renders by name and takes variables:

```bash
python3 "$SKILL/scripts/documents.py" save --name invoice --spec invoice.json
python3 "$SKILL/scripts/render.py" render --doc invoice \
  --var number=INV-7 --var client=Northwind --out invoice.pdf
```

## Requirements

- Python 3.9 or newer.
- `reportlab` for rendering (and optional `Pillow` for extra image formats):
  `pip install -r requirements.txt`.
- Optional `pypdf` for `reports.py inspect`.
- A writable data root (default `~/.local/share/pdf-creator`).

Without reportlab, the state, library, asset, validation, and report verbs still
work; `render` and `templates.py demo` fail fast with `dependency_missing`.

## The document spec

A spec is a JSON object with `meta`, `page`, an optional `theme`, optional
furniture (`header`, `footer`, `watermark`, `toc`, `cover`, `security`), and a
`content` list of blocks. Lengths take unit suffixes (`mm`, `cm`, `in`, `pt`,
`px`, `%`); colors take hex, `rgb()`/`rgba()`, and names. See
`pdf-creator/references/schema.md` for the full reference and
`pdf-creator/references/layout.md` for a worked example of every block.

```json
{
  "spec_version": 1,
  "theme": "report",
  "meta": { "title": "Quarterly Report", "author": "Acme Analytics" },
  "header": { "text": "Quarterly Report", "align": "right", "divider": true },
  "footer": { "text": "Page {page} of {pages}", "align": "center" },
  "toc": { "title": "Contents" },
  "content": [
    { "type": "heading", "level": 1, "text": "Executive summary" },
    { "type": "paragraph", "text": "Revenue grew **12%** quarter over quarter." },
    { "type": "table", "header": ["Region", "Revenue"],
      "rows": [["North America", "$4.1M"], ["Europe", "$2.6M"]], "zebra": true }
  ]
}
```

## Where the data lives

Resolved in order: `--home DIR`, `$PDF_CREATOR_HOME`, then
`~/.local/share/pdf-creator`. The one directory holds:

```
pdf-creator/
├── pdf-creator.db     # document library, settings, render history
├── assets/            # registered images
├── fonts/             # registered fonts + fonts.json manifest
└── output/            # default render destination
```

Back up by copying that directory. No personal data is stored in this
repository.

## Automate a recurring render

```bash
python3 "$SKILL/scripts/render.py" schedule-hint \
  --doc invoice --out ~/invoices/current.pdf \
  --target generic --path-mode abs --tz Asia/Jakarta --name invoice-daily
```

`schedule-hint` is read-only and installs nothing; it emits the commands and
routes for your host to register. See `pdf-creator/references/scheduling.md`.

## Layout

```
skills/pdf-creator/
├── SKILL.md
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── tests/smoke.sh
├── scripts/       # _lib.py + _engine*.py + one script per domain
└── references/    # commands.md, schema.md, layout.md, scheduling.md
```

## Test

```bash
pip install -r requirements.txt   # optional pypdf enables the inspect checks
bash tests/smoke.sh
```

The harness generates its own fixtures, then runs every script and verb against
a throwaway data root and checks the JSON envelope, the library and asset
stores, rendering (pages, files, encryption), Markdown conversion, the
scheduler artifact matrix (executing the emitted report command twice), and
error handling.

## License

MIT. See `LICENSE`.
