# Layout cookbook

Worked examples for every block type. Each snippet is one entry in a spec's
`content` list. Forge the shapes and keys in `references/schema.md`; the numbers
here are only suggestions.

## Text

```json
{ "type": "heading", "level": 1, "text": "Executive summary" }
{ "type": "heading", "level": 2, "text": "Revenue", "anchor": "revenue" }
{ "type": "paragraph", "text": "Revenue grew **12%**, driven by *renewals*. See the [dashboard](https://example.com)." }
{ "type": "paragraph", "text": "A justified lead paragraph.", "align": "justify", "size": 12, "color": "@muted" }
```

Headings are indexed for the table of contents and the PDF outline. Add `anchor`
to link to a section from elsewhere with `[jump](#revenue)`.

To give every section its own page, set `"page_break_headings": 1` at the top
level (or use `[1, 2]` for two levels). A single heading can opt in with
`"page_break": true`. Breaks collapse at the top of a page, so no blank pages
appear.

## Rich text

For precise inline control, list spans instead of a markup string:

```json
{ "type": "rich", "spans": [
  { "text": "Status: " },
  { "text": "On track", "bold": true, "color": "#15803D" },
  { "text": " — see " },
  { "text": "the tracker", "italic": true, "link": "https://example.com" },
  { "text": " (H2O)", "sub": true }
]}
```

## Lists

```json
{ "type": "list", "ordered": false, "items": [
  "Plain item",
  { "text": "Item with children", "items": ["Nested one", "Nested two"] },
  { "text": "Back to the top level" }
]}
```

`ordered` uses `1.` numbering; pass `start` to begin elsewhere and `bullet` to
replace the unordered glyph.

## Tables

```json
{ "type": "table",
  "header": ["Item", "Qty", "Amount"],
  "rows": [
    ["Widgets", "10", "$10.00"],
    ["Gadgets", "3", "$7.50"],
    [{ "text": "Total", "bold": true }, "", { "text": "$17.50", "bold": true, "background": "#E8F0FE" }]
  ],
  "widths": [0.5, 0.2, 0.3],
  "number_align": "first",
  "zebra": true,
  "caption": "Line items",
  "numbered": true,
  "repeat_header": 1,
  "spans": [[2, 2, 2, 2]]
}
```

- `widths` are fractions of the frame (sum ≤ 1), absolute lengths, or
  percentages. Omit them to let the engine size columns.
- `grid`/`style` accepts `modern` (the default: light header, hairline rules, no
  outer box), `grid`, `lines`, `box`, `zebra`, `none`, or a boolean.
- `number_align`: `auto` (auto-detect numbers), `first` (right-align every
  column but the first), `left`, `right`.
- Cells are strings, numbers, or objects with `text`, `align`, `color`,
  `bold`, `size`, `background`, and a nested `style` object.
- `spans` use reportlab coordinates `[c0, r0, c1, r1]` (inclusive), with the
  header row counted as row `0`.
- `row_backgrounds` is a list of `[row_index, color]`; `keep_together` avoids a
  page split for short tables.

## Images

```json
{ "type": "image", "src": "logo.png", "width": "40%", "align": "center",
  "caption": "Company logo", "border": { "width": 0.5, "padding": "2mm", "background": "#FFF" } }
```

`src` is a path (absolute, or relative to the spec file), a `<home>/assets`
name, a `data:` URI, or an `http(s)` URL with `--allow-remote`. With only
`width` or `height` the aspect ratio is preserved; `max_width` (default 100% of
the frame) and `max_height` shrink oversized images. `fit: "stretch"` uses the
exact box. Use `figure` to auto-number the caption.

```json
{ "type": "figure", "src": "chart.png", "caption": "Revenue by quarter", "number": true }
```

## Code

```json
{ "type": "code", "language": "python", "line_numbers": true, "wrap": true,
  "text": "def render(spec):\n    return build(spec)\n" }
```

## Callouts and quotes

```json
{ "type": "callout", "kind": "warning", "title": "Watch item",
  "text": "Hiring is pacing behind plan." }
{ "type": "blockquote", "text": "Growth is a byproduct of keeping promises.",
  "attribution": "Operations review" }
```

`kind` is `info`, `success`, `warning`, or `danger` and picks the tint and the
accent bar.

## Rules and spacing

```json
{ "type": "divider", "thickness": 0.8, "color": "@border", "line_style": "dashed" }
{ "type": "spacer", "height": "6mm" }
{ "type": "page_break" }
```

## Page templates and multi-column

Switch the page template for a section. `two_column` and `three_column` flow
text across frames and pages; `landscape` changes the page size for its pages.

```json
[ { "type": "heading", "level": 1, "text": "Appendix" },
  { "type": "page_template", "name": "two_column" },
  { "type": "paragraph", "text": "Long text flows down column one, then column two, then the next page." } ]
```

For a short, balanced block inside one page, use `columns`:

```json
{ "type": "columns", "count": 2, "gap": "8mm", "keep_together": true, "content": [
  { "type": "paragraph", "text": "Left column." },
  { "type": "paragraph", "text": "Right column." }
]}
```

Or state the columns explicitly: `"columns": [[{...}], [{...}]]`.

## Table of contents

```json
{ "type": "toc", "title": "Contents", "depth": 3, "dot_leader": true, "page_break": true }
```

At the top level, `"toc": { "title": "Contents" }` is inserted before the body
automatically. Level-1 entries sit flush with the title; `toc2`/`toc3` indent
deeper levels.

## Checkboxes, definitions, key/value grids

```json
{ "type": "checkbox_list", "items": [
  { "text": "Draft reviewed", "checked": true },
  { "text": "Sent to client", "checked": false }
]}
{ "type": "definition_list", "items": [
  { "term": "EBITDA", "definition": "Earnings before interest, tax, depreciation, and amortisation." }
]}
{ "type": "key_values", "columns": 2, "items": [
  { "key": "Client", "value": "Northwind" },
  { "key": "Issued", "value": "2026-09-01" }
]}
```

## Anchors, QR codes, barcodes

```json
{ "type": "anchor", "name": "appendix" }
{ "type": "qr", "data": "https://example.com/dashboard", "size": "24mm", "caption": "Dashboard" }
{ "type": "barcode", "kind": "code128", "data": "INV-1042", "width": "60mm", "caption": "Order number" }
```

## Page furniture

`header` and `footer` are drawn in the page margins, not inside the content
frame, following common print/UX guidance (1in margins, with header and footer
text about 0.5in from the trim edge):

- The running header sits roughly 12mm (0.5in) from the top edge, and its
  optional `divider` rule is placed about 9mm above the first line of content,
  so a heading never touches the rule. (`space_before` on a leading heading is
  ignored at the top of a frame, which is why the gap comes from the rule.)
- The footer, including a `{page}`/`{pages}` number, sits about 12mm (0.5in)
  from the bottom edge, so it reads as a footer rather than body copy.
- Keys: `text` (supports `{page}`, `{pages}`, `{date}`, `{title}`, `{author}`),
  `align` (`left`/`center`/`right`), `size`, `color`, `font`. The header also
  accepts `divider`, `divider_color`, and `divider_width`.
- `page_numbers` (bool) adds a centered `n / total` number when the footer text
  does not already include one.

Content margins come from `page.margins`; `page.header_reserve` and
`page.footer_reserve` reserve room for the furniture within the frame.

## A complete small document

```json
{
  "spec_version": 1,
  "theme": "invoice",
  "meta": { "title": "Invoice INV-1042", "author": "Acme Studio" },
  "header": { "text": "Acme Studio", "align": "left", "divider": true },
  "footer": { "text": "Page {page} of {pages}", "align": "center" },
  "content": [
    { "type": "heading", "level": 1, "text": "Invoice {{number}}" },
    { "type": "key_values", "columns": 2, "items": [
      { "key": "Billed to", "value": "{{client}}" },
      { "key": "Due", "value": "2026-09-30" }
    ]},
    { "type": "table", "header": ["Description", "Amount"], "number_align": "first",
      "zebra": true, "rows": [["Design", "$2,400"], ["Retouching", "$270"]] }
  ]
}
```

Render it with `render.py render --spec invoice.json --var number=INV-1042
--var client=Northwind --out invoice.pdf`.
