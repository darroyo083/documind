# DocuMind Stitch design system

This is the design system retrieved from Stitch project `9185568505600455027` through the configured Stitch MCP connection. The rendered Design System asset was not exposed as a downloadable screenshot by the MCP response; the structured design system and its `designMd` are preserved in [assets/design-system.json](assets/design-system.json).

## Identity

| Token | Exact value |
|---|---|
| Display name | The Modern Archivist |
| Color mode | Light |
| Color variant | FIDELITY |
| Headline/body family | Inter |
| Label/metadata family | JetBrains Mono |
| Custom/charcoal ink | `#0D1117` |
| Primary override | `#0D1117` |
| Secondary override | `#0052FF` |
| Neutral override | `#F9F9F8` |

## Typography

| Style | Family | Size | Weight | Line height | Tracking |
|---|---|---:|---:|---:|---:|
| headline-xl | Inter | 40 px | 700 | 48 px | -0.02em |
| headline-lg | Inter | 30 px | 600 | 36 px | -0.01em |
| headline-md | Inter | 24 px | 600 | 32 px | system default |
| body-lg | Inter | 18 px | 400 | 28 px | system default |
| body-md | Inter | 16 px | 400 | 24 px | system default |
| body-sm | Inter | 14 px | 400 | 20 px | system default |
| label-mono | JetBrains Mono | 12 px | 500 | 16 px | 0.05em |
| label-caps | Inter | 11 px | 700 | 16 px | 0.1em |

## Palette

| Group | Token | Value |
|---|---|---|
| Core | archival-paper / background / surface | `#F9F9F8` |
| Core | surface-container-lowest | `#FFFFFF` |
| Core | surface-container-low | `#F3F4F3` |
| Core | surface-container | `#EEEEED` |
| Core | surface-container-high | `#E8E8E7` |
| Core | surface-container-highest / surface-variant | `#E2E2E2` |
| Core | surface-dim | `#DADAD9` |
| Text | on-background / on-surface | `#1A1C1C` |
| Text | on-surface-variant | `#45474B` |
| Structural | charcoal-ink / primary | `#0D1117` / `#000000` |
| Structural | outline | `#76777B` |
| Structural | outline-variant | `#C6C6CB` |
| Structural | border-muted | `#D1D5DB` |
| Accent | technical-blue | `#0052FF` |
| Accent | secondary | `#003EC6` |
| Accent | secondary-container | `#0052FE` |
| Error | error | `#BA1A1A` |
| Error | error-container | `#FFDAD6` |
| Error | on-error-container | `#93000A` |
| Inverse | inverse-surface | `#2F3130` |
| Inverse | inverse-on-surface | `#F1F1F0` |

The remaining named colors are preserved verbatim in the JSON artifact, including fixed/on-fixed variants and tertiary values.

## Layout and spacing

- Rigid 12-column grid; structural wires are visible or implied.
- Baseline unit: 4 px.
- Standard gutter: 24 px.
- Standard outer margin: 32 px.
- Desktop sidebar width: 280 px.
- Functional panes (library, reader, intelligence workspace) use 1 px separators.
- Desktop content commonly offsets by the 280 px sidebar and uses a 64 px top bar; the mobile workspace reference uses a 64 px top bar and a 72 px bottom navigation area.
- Rendered desktop references are primarily 2560 px wide; Intelligence and Ask are 1280 px wide; mobile references are 390 px wide.

## Shape, elevation, and interaction

- The narrative design guidance defines sharp 0 px corners and rejects decorative shadows.
- Level 0: Archival Paper `#F9F9F8`.
- Level 1: white pane/cell with a 1 px charcoal border.
- Active element: 2 px Technical Blue border or charcoal fill with white text.
- Overlay: solid charcoal at 80% opacity; no blur.
- Primary button: charcoal fill with white text.
- Secondary button: 1 px charcoal outline with no fill.
- Inputs: bottom-border or full 1 px border with the label above.
- Cells/cards: separators and tonal layers, not floating cards.
- Status: small square color blocks, not circular dots.
- Scrollbars: 4 px, squared charcoal thumb, visible on hover.
- Intelligence relationships: 1 px Technical Blue connector lines.

### Source inconsistency to resolve before implementation

The structured theme also exposes generic `borderRadius` defaults of 0.25 rem, `lg` 0.5 rem, `xl` 0.75 rem, and `full` 9999 px, while the authored design guidance explicitly says every element is 0 px. The rendered screenshots visually favor the authored sharp-cell rule. Treat this as an acceptance decision for the implementation pass, not as permission to blend both systems.

## Observed component language

Shared patterns visible across the references:

- Persistent desktop SideNavBar: DocuMind wordmark, Intelligence Workspace label, Upload Document CTA, Dashboard/Spaces/Search/Settings navigation, account footer.
- TopAppBar: section tabs Overview/Actions/Compare/Intelligence/Ask, search field, Invite/Upload actions, user avatar.
- Archive cells: document rows, space cells, bento-like metric cells, comparison matrix cells.
- Evidence treatment: monospaced source labels, page references, blue left rules/markers, active-citation panel.
- State treatment: active/processing/error/draft rows, empty-space upload panel, disabled/scope-aware controls, bottom-sheet document detail on mobile.
