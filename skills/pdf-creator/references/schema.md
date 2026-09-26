# Document spec reference

A document is one JSON object. The renderer reads it, resolves the theme and
geometry, and turns `content` into a PDF. `spec_version` is `1`.

```json
{
  "spec_version": 1,
  "meta": { "title": "...", "author": "...", "subject": "...", "keywords": [], "language": "en" },
  "page": { "size": "A4", "orientation": "portrait", "margins": "20mm", "unit": "mm" },
  "theme": "report",
  "colors": { "accent": "#0F3D6E" },
  "font": { "family": "Helvetica", "mono": "Courier" },
  "styles": { "body": { "font_size": 11, "align": "justify" } },
  "fonts": [ { "name": "Inter", "file": "Inter.ttf", "bold": "Inter-Bold.ttf" } ],
  "header": { "text": "Report", "align": "right", "divider": true },
  "footer": { "text": "{page} / {pages}", "align": "center" },
  "watermark": { "text": "DRAFT", "angle": 32, "opacity": 0.12, "color": "#DDD", "size": 78 },
  "page_numbers": true,
  "toc": { "title": "Contents", "depth": 3, "dot_leader": true },
  "cover": { "title": "Quarterly Report", "subtitle": "...", "author": "...", "date": "..." },
  "security": { "user_password": "open", "can_copy": false },
  "number_headings": false,
  "page_break_headings": 1,
  "content": [ /* blocks */ ]
}
```

All keys except `content` are optional. Unknown block types are a hard error;
unknown style keys are ignored.

## Units and colors

Lengths accept a suffix: `pt`, `px` (`0.75pt`), `in`, `cm`, `mm`, `pc`, `q`, and
`%` where a container is known. A bare number uses `page.unit` (default `mm`)
for block geometry and points for style properties. `auto` is accepted where the
engine has a sensible default.

Colors accept `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(r,g,b)`, `rgba(r,g,b,a)`, a
`[r,g,b]`/`[r,g,b,a]` list, and named colors (`black`, `navy`, `crimson`,
`whitesmoke`, ...; run with an invalid color to see the error). Theme palette
keys can be referenced as `"@accent"`, `"@muted"`, `"@border"`, and so on.

## page

| Key | Values | Notes |
|---|---|---|
| `size` | `A4`, `Letter`, `Legal`, `A3`, `A5`, `Tabloid`, `210x297mm`, `[210, 297]` | named sizes or `WxH` with units |
| `orientation` | `portrait`, `landscape`, `auto` | `auto` keeps the size's own orientation |
| `margins` | length, or `{top,right,bottom,left,horizontal,vertical}` | defaults come from settings |
| `header_reserve` | length | vertical band kept for the header (default `10mm`) |
| `footer_reserve` | length | vertical band kept for the footer (default `10mm`) |
| `columns_gap` | length | gap used by the `two_column`/`three_column` templates and `columns` blocks |

## meta

`title`, `author`, `subject`, `creator`, `keywords` (list), `language`. These
are written into the PDF document information. `{title}` and `{author}` are also
available as header/footer tokens.

## theme, colors, font, styles

`theme` is a name (`default`, `report`, `invoice`, `letter`, `resume`, `book`,
`minimal`, `elegant`) or an inline object `{ "name": "...", "palette": {...},
"styles": {...}, "page": {...}, "header": {...}, "footer": {...} }`.

Every built-in theme is **modern and sans-serif** by default: near-black type,
generous spacing, one restrained accent, light surfaces, and hairline rules
rather than heavy boxes. Serif families are still available — set one
explicitly with `font.family` (`Times`) or in a `styles` override — for a more
formal result.

Merge order, low to high: built-in defaults → named theme → inline theme
object → top-level `colors`/`styles` → per-block overrides.

`font.family` sets the body family and `font.mono` the code family. Families
are built-ins (`Helvetica`, `Times`, `Courier`), a family registered with
`assets.py add-font`, or one declared in `fonts`.

`styles` maps a style name to overrides. Style names: `title`, `subtitle`,
`lead`, `body`, `h1`–`h6`, `caption`, `small`, `code`, `quote`, `table_header`,
`table_cell`, `table_caption`, `toc_title`, `toc1`–`toc3`, `definition_term`,
`definition_body`, `key`, `value`, `callout_title`, `callout_body`, `header`,
`footer`, `watermark`.

Style override keys: `font_family`, `font_size`, `leading`, `line_height`,
`color`, `align` (`left|center|right|justify`), `space_before`, `space_after`,
`left_indent`, `right_indent`, `first_line_indent`, `back_color`,
`border_color`, `border_width`, `border_padding`, `border_radius`,
`keep_with_next`, `word_wrap`.

## fonts

A list of families to embed:

```json
[{ "name": "Inter", "file": "Inter-Regular.ttf",
   "bold": "Inter-Bold.ttf", "italic": "Inter-Italic.ttf",
   "bold_italic": "Inter-BoldItalic.ttf" }]
```

`file` resolves against the spec's folder, then `<home>/fonts`, then
`<home>/assets`. Families registered with `assets.py add-font` are loaded
automatically from the manifest and need no `fonts` entry.

## header, footer, watermark

`header` and `footer` are a string or an object:

```json
{ "text": "{page} of {pages}", "align": "center", "size": 8.5,
  "color": "@muted", "font": "Helvetica", "divider": true,
  "divider_color": "@border", "divider_width": 0.5 }
```

Tokens: `{page}`, `{pages}`, `{date}`, `{title}`, `{author}`, `{doc}`. A footer
containing `{page}`/`{pages}` sets `page_numbers` automatically. When
`page_numbers` is true and the footer has no token, the engine draws `N / M`
centered at the bottom.

`watermark` is `{ "text", "angle", "opacity", "color", "size", "font" }`, drawn
behind the content on body pages (not on `cover`/`title`/`blank` unless the
template overrides it).

## page_templates

Optional per-template overrides keyed by template name (`body`, `cover`,
`title`, `two_column`, `three_column`, `landscape`, `blank`):

```json
{ "body": { "header": {...}, "footer": {...}, "watermark": {...},
            "page_numbers": true, "background": { "color": "#FFFDF7" } } }
```

`background` is a color string or `{ "color": "#..." }` painted full-bleed.

## toc

`{ "title": "Contents", "depth": 3, "dot_leader": true, "page_break": true }`

When present at the top level (or as a `toc` block) the renderer indexes every
heading, emits a table of contents with dot leaders, and adds PDF outline
entries. Rendering is multi-pass so page numbers are correct. Level-1 headings
align with the TOC title and use `toc1`; deeper levels use `toc2`/`toc3` with
their built-in indent.

## page breaks before headings

`page_break_headings` starts every heading of the given level on a fresh page —
the declarative way to give each section its own page. It accepts one level
(`1`), a list (`[1, 2]`), or `true` for level 1. A single heading can also ask
for it directly with `"page_break": true` (or `"break_before": true`). Breaks
collapse when the page is already empty, so a leading heading and the first
heading after the table of contents never produce a blank page.

## cover

A cover object renders on its own page template before the body:

```json
{ "eyebrow": "Acme", "title": "Q3 2026", "subtitle": "...", "author": "...",
  "date": "2026-09-26", "logo": "logo.png", "logo_max_height": "22mm",
  "rule": true, "abstract": "...", "footer": "...", "align": "left",
  "top_space": "42mm" }
```

`logo`/`image` is an asset reference; `rule` draws an accent rule under the
subtitle. Use `cover_header`/`cover_footer` for furniture on the cover.

## security

```json
{ "user_password": "open", "owner_password": "owner",
  "can_print": true, "can_copy": false, "can_modify": true,
  "can_annotate": true, "strength": 128 }
```

## Content blocks

Every block is an object with a `type`. A plain string is shorthand for a
paragraph. `type` defaults to `paragraph` when omitted. See
`references/layout.md` for a worked example of each type; the short table:

| Type | Key options |
|---|---|
| `heading` | `text`, `level` 1–6, `number`, `anchor`, `page_break`, plus style shorthands |
| `paragraph` | `text`, `allow_html`, style shorthands |
| `rich` | `spans` of `{text, bold, italic, underline, strike, code, color, size, font, link, super, sub}` |
| `list` | `ordered`, `items` (strings or `{text, items}`), `start`, `bullet` |
| `table` | `header`, `rows` (or `data`), `widths`/`col_widths`, `grid`, `zebra`, `repeat_header`, `caption`, `numbered`, `spans`, `row_backgrounds`, `number_align`, `padding`, `border_color`, `keep_together` |
| `image` | `src`, `width`, `height`, `max_width`, `max_height`, `fit`, `align`, `caption`, `numbered`, `border` |
| `figure` | `src` or `image`, `caption`, `number` |
| `code` | `text`, `language`, `line_numbers`, `wrap`, `background`, `padding` |
| `callout` | `kind` (`info`/`warning`/`success`/`danger`), `title`, `text` |
| `blockquote` | `text`, `attribution`, `accent` |
| `divider` / `hr` | `thickness`, `color`, `width`, `line_style` (`solid`/`dashed`/`dotted`) |
| `spacer` | `height` |
| `page_break` | `template` (optional) |
| `page_template` | `name`, `break` (`before`/`none`) |
| `columns` | `count`, `content`, or `columns` (a list of column lists), `gap`, `keep_together` |
| `toc` | `title`, `depth`, `dot_leader`, `page_break` |
| `checkbox_list` | `items` of `{text, checked}` |
| `definition_list` | `items` of `{term, definition}` |
| `key_values` | `items` of `{key, value}`, `columns`, `key_ratio` |
| `anchor` | `name` |
| `qr` | `data`, `size`, `align`, `caption` |
| `barcode` | `kind` (`code128`, `code39`, `ean13`, `upca`, ...), `data`, `width`, `height`, `human_readable`, `caption` |

Style shorthands available on text blocks: `align`, `color`, `size`, `font`,
`leading`, `space_before`, `space_after`, `indent`, `first_line_indent`,
`keep_with_next`, `background`, `border_color`, `border_width`, `padding`.
A `style` key takes either a style name or an inline override object.

## Inline markup

Inside `text` and list items: `**bold**`, `__bold__`, `*italic*`, `_italic_`,
`` `code` ``, `~~strike~~`, `[label](url)`, `^superscript^`, `~subscript~`, and
newlines become line breaks. Set `allow_html: true` to pass reportlab markup
through unchanged.
