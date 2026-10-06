# Daily Report Design System

## Direction

Operational ERP surface: compact, calm, and scan-first. The existing dark glass navigation remains the shell, while report content uses restrained surfaces, compact data rows, and one indigo action accent. The signature interaction is the full-viewport Kingdee line picker with a dense, horizontally scannable row.

## Tokens

- Font: system UI stack already defined by `static/css/app.css`; numeric fields use tabular numbers.
- Base spacing: 4px increments; common gaps are 8px, 12px, 16px, 24px.
- Surfaces: existing `--surface-0`, `--surface-1`, `--surface-2`, `--panel-solid`.
- Borders: existing `--border`, `--line`, `--line-hi`.
- Text: existing `--text`, `--text-secondary`, `--text-tertiary`, `--text-dim`.
- Action: existing `--brand-500` and `--brand-hi`.
- Status: existing semantic warning/error colors; over-allocation uses the existing red warning treatment.

## Layout

- Desktop report forms use two columns: a bounded data-entry column and a flexible linked-line column.
- At 1024px and below, columns collapse to one column.
- Dialogs escape glass cards and use a viewport-level overlay; picker width is capped at 1080px.
- Dense tables may scroll horizontally on narrow screens; data must not be hidden.

## Primitives

- `form-card`: bounded entry surface; default states are idle, validation error, and submitting.
- `links-aside`: persistent selected-line summary; shows count, allocated total, and editable allocation fields.
- `link-picker`: full-viewport dialog; states are closed, loading, empty, results, selected, and error.
- `link-item`: compact ERP row showing document, entry id, material identity, quantities, currency amounts, and allocation state.
- `report-prototype`: standalone offline report page for management, operations, or finance audiences.

## Accessibility

- Use real buttons for actions and `role="dialog" aria-modal="true"` for the picker.
- Escape closes the picker; focus moves to the search field when it opens.
- Preserve visible labels for numeric inputs and never rely on color alone for over-allocation.
- Responsive layouts must remain usable at 375px, 768px, and desktop widths.

## Motion

Use existing Alpine transitions and CSS opacity/transform transitions only for meaningful open/close and focus feedback. Do not animate layout dimensions.
