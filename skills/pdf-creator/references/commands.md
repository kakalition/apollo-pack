# Command reference

Run every script as `python3 <skill-dir>/scripts/<domain>.py <verb> [flags]`.

Shared flags (accepted by all verbs):

- `--home DIR` — data root (default: `$PDF_CREATOR_HOME` or
  `~/.local/share/pdf-creator`)
- `--format json|table` — output format (default `json`)
- `--tz ZONE` — override the timezone for this call
- `--quiet` — suppress success output; errors still print

Every script auto-creates the data root, directories, and schema on first use.
A run prints exactly one JSON envelope: `{"ok": true, "command": "...", "data":
{...}}` or `{"ok": false, "error": {"code": "...", "message": "..."}}` (exit 1;
argparse errors exit 2).

## init.py

| Verb | Flags |
|---|---|
| `init` | — |

Creates the schema and the `assets/`, `fonts/`, and `output/` directories.
Idempotent. Returns `home`, `db`, `assets`, `fonts`, `output`, `schema_version`,
`already_initialized`, and `dependencies` (`reportlab`, `pillow`, `pypdf`).

## settings.py

| Verb | Flags |
|---|---|
| `show` | — |
| `get` | `--key NAME` (omit for the whole map) |
| `set` | any of the flags below |

`set` flags: `--page-size`, `--orientation portrait\|landscape`,
`--unit mm\|cm\|in\|pt\|pc`, `--margin LEN` (all four), `--theme`, `--font-family`,
`--font-size`, `--line-height`, `--heading-scale`, `--text-color`, `--accent`,
`--author`, `--language`, `--output-dir`, `--allow-remote yes\|no`.

`show` returns `settings` (stored), `env_overrides` (which namespaced
environment variables are in force), and `output_dir`. A set `PDF_CREATOR_*`
variable wins over the stored value for that call.

## documents.py

| Verb | Flags |
|---|---|
| `save` | `--name N` (required), `--spec FILE` or `--stdin`, `--title`, `--tags a,b`, `--force` |
| `list` | `--tag T` |
| `show` | positional `name` |
| `rename` | positional `name`, `new_name` |
| `duplicate` | positional `name`, `new_name`, `--force` |
| `delete` | positional `name`, `--yes` |
| `export` | positional `name`, `--out FILE` (prints the spec when omitted) |

`save` validates the spec before storing it. `show` returns metadata plus the
full `spec`. `delete` requires `--yes`.

## assets.py

| Verb | Flags |
|---|---|
| `add-image` | positional `source`, `--name N`, `--force` |
| `add-font` | positional `file`, `--family N`, `--bold F`, `--italic F`, `--bold-italic F`, `--force` |
| `list` | `--type image\|font` |
| `remove` | positional `name`, `--type image\|font`, `--keep-files` |
| `paths` | — |

Images are copied to `<home>/assets`; fonts to `<home>/fonts` with a
`fonts.json` manifest the renderer reads automatically. Refer to an asset by its
bare file name in a spec.

## templates.py

| Verb | Flags |
|---|---|
| `list` | — |
| `show` | positional `name`, `--kind theme\|demo` |
| `spec` | positional `name`, `--out FILE` |
| `demo` | positional `name`, `--out FILE`, `--allow-remote` |

Themes: `default`, `report`, `invoice`, `letter`, `resume`, `book`, `minimal`,
`elegant`. Demos: `blank`, `report`, `invoice`, `letter`, `resume`. `show` names
a theme by default; pass `--kind demo` to show a demo's spec instead. `spec`
writes a demo's JSON; `demo` renders it.

## render.py

| Verb | Flags |
|---|---|
| `render` | `--doc N` or `--spec FILE`, `--out FILE`, `--var NAME=VALUE` (repeatable), `--force`, `--allow-remote`, `--no-record` |
| `check` | `--doc N` or `--spec FILE`, `--var`, `--strict` |
| `from-markdown` | `--in FILE`, `--out FILE`, `--title`, `--author`, `--theme`, `--header`, `--footer`, `--toc`, `--toc-title`, `--number-headings`, `--force`, `--allow-remote`, `--no-record` |
| `schedule-hint` | `--doc N` or `--spec FILE`, `--out`, `--target`, `--path-mode`, `--at-time`, `--tz`, `--name`, `--action`, `--job` |

`render` writes the PDF, records a render-history row (unless `--no-record`),
and returns `out`, `pages`, `bytes`, `sha256`, `width_pt`, `height_pt`,
`page_size`, `orientation`, `theme`, `warnings`, `document`, `recipe`, and
`render_id`. `check --strict` resolves fonts, images, and every block through
the engine and returns `flowables`.

`--var` substitutes `{{NAME}}` tokens throughout the spec before parsing, which
keeps invoices and letters reusable: `--var number=INV-7 --var client=Acme`.

## reports.py

| Verb | Flags |
|---|---|
| `history` | `--limit N`, `--doc NAME`, `--detail` |
| `show` | positional `render_id` |
| `storage` | — |
| `inspect` | positional `file`, `--password` |
| `stats` | — |

`history`, `show`, `storage`, and `stats` read the local database.
`inspect` reads an existing PDF's page count and metadata when `pypdf` is
installed; encrypted files need `--password`.

## Environment variables

Namespaced overrides, all optional: `PDF_CREATOR_HOME`,
`PDF_CREATOR_PAGE_SIZE`, `PDF_CREATOR_ORIENTATION`, `PDF_CREATOR_UNIT`,
`PDF_CREATOR_THEME`, `PDF_CREATOR_FONT_FAMILY`, `PDF_CREATOR_FONT_SIZE`,
`PDF_CREATOR_LINE_HEIGHT`, `PDF_CREATOR_TEXT_COLOR`, `PDF_CREATOR_ACCENT`,
`PDF_CREATOR_AUTHOR`, `PDF_CREATOR_LANGUAGE`, `PDF_CREATOR_OUTPUT_DIR`,
`PDF_CREATOR_ALLOW_REMOTE`. Key material is never stored; there is nothing
secret in this skill.

## Error codes

`invalid_input`, `invalid_spec`, `invalid_image`, `invalid_pdf`, `not_found`,
`conflict`, `io_error`, `remote_disabled`, `dependency_missing`, `render_error`,
`invalid_state`, `db_error`, `internal_error`.
