# DocuMind Stitch design handoff intake

This document records the approved Stitch redesign as a local, reviewable reference. This goal performed design ingestion, inspection, functional mapping, gap analysis, and planning only. No production application code, APIs, database, deployment, or DNS was modified.

## Quick path

- Read the extracted tokens in [design-system.md](design-system.md).
- Use [source-manifest.json](source-manifest.json) to find every Stitch screen, source URL, viewport, and retrieval status.
- Compare the rendered references in [screens/](screens/) before reading the generated HTML in [reference-code/](reference-code/).
- Treat the current product behavior and API contracts in frontend/src and backend/app as authoritative for implementation decisions.

## A. Stitch retrieval

Project: DocuMind UX Redesign  
Project ID: 9185568505600455027  
Visibility: private  
Design system asset ID: assets_6bdaad0638984f33ba6174077c62db6a

### Retrieval result

| Artifact | Result |
|---|---|
| Project metadata | Retrieved from Stitch MCP |
| Screen metadata | All 13 listed screens retrieved through list_screens |
| Direct screen details | 11 screens returned through get_screen; Workspace - Mobile and Actions - Desktop returned an invalid-argument response on direct get_screen |
| Rendered screenshots | 9 downloaded from Stitch-hosted URLs |
| Reference HTML | 13 local files: 9 hosted downloads plus 4 inline MCP payloads |
| Design system | Structured theme and authored designMd retrieved and preserved |
| Rendered Design System asset | Not exposed as a downloadable screenshot or asset URL by the configured MCP |
| Hosted image assets referenced by HTML | 9 JPEGs and the Stitch placeholder SVG downloaded into assets/ |

The two direct get_screen failures do not block the reference set: list_screens returned valid screen metadata and hosted artifacts for Actions - Desktop, and inline reference HTML for Workspace - Mobile. Their exact MCP status is recorded in source-manifest.json.

### Screen inventory

| Stitch screen | ID | Viewport | Screenshot | Reference code |
|---|---|---:|---|---|
| Intelligence - Desktop | 0f92344f4c354043a9842a981a61dd1a | 1280 × 1024 | unavailable from MCP | inline, local |
| Empty Space - Desktop | 17bf944c503e41c1b8bcbae4dba9fdb7 | 2560 × 2048 | local | hosted, local |
| Overview - Desktop | 1a5fb31efc504f1a96dab6eea8144659 | 2560 × 2250 | local | hosted, local |
| Dashboard - Desktop | 81e5cec2c0fc4b0096d835ffac6ac562 | 2560 × 2048 | local | hosted, local |
| Login - Desktop | 84ba77d9d7b44743af53ac697e530973 | 2560 × 2048 | local | hosted, local |
| Landing Page - Desktop | 87d0da6772364d4bbfb4c382e14e2f7f | 2560 × 3640 | local | hosted, local |
| Ask - Mobile | 9bd5bae2c7784d5a9b72b927b21400ad | 390 × 884 | unavailable from MCP | inline, local |
| Space with Documents - Desktop | a0c03fded36143bf9cd3945b112156bd | 2560 × 2048 | local | hosted, local |
| Compare - Desktop | acb73c34c36e49efbef1187de55af9fc | 2570 × 2048 | local | hosted, local |
| Design System | asset-stub-assets_6bdaad0638984f33ba6174077c62db6a | 960 × 540 | unavailable as a rendered asset | structured JSON/MD |
| Workspace - Mobile | b457a41d48db4917a4ec6dc5f8570ab7 | 390 × 884 | unavailable from MCP | inline, local |
| Register - Desktop | ca7be7dfafcf4a498c80ea1a495b1f3e | 2560 × 2048 | local | hosted, local |
| Ask - Desktop | e10fb57b8f4d435aa694b344820396d0 | 1280 × 1024 | unavailable from MCP | inline, local |
| Actions - Desktop | f8dd2844a8e044f988749833da04cec9 | 1280 × 1085 | local | hosted, local |

The generated HTML is intentionally stored as secondary reference only. It contains CDN links, generated sample data, and placeholder assets; it must not be copied into the application.

## B. Design system

The full exact token extraction is in [design-system.md](design-system.md), with the raw structured response in [assets/design-system.json](assets/design-system.json).

### Visual language

The design is The Modern Archivist: high-contrast minimalism with Swiss influence. It uses a paper-toned background, charcoal structural lines, Inter for readable content, and JetBrains Mono for metadata and evidence. Technical Blue is the only chromatic accent and should be used surgically for active states, actions, and evidence.

The rendered screenshots consistently show:

- a fixed 280 px desktop archive sidebar;
- 1 px structural borders and pane separators;
- flat white cells on Archival Paper rather than floating cards;
- upper-case compact labels and monospaced metadata;
- active items marked with charcoal fills or Technical Blue rules;
- square status blocks and blue evidence markers;
- almost no decorative depth.

### Exact tokens

| Area | Values |
|---|---|
| Background | Archival Paper/background/surface #F9F9F8 |
| Primary ink | Charcoal Ink #0D1117; primary metadata also exposes #000000 |
| Text | on-surface #1A1C1C; on-surface-variant #45474B |
| Accent | Technical Blue #0052FF; secondary #003EC6; secondary-container #0052FE |
| Borders | border-muted #D1D5DB; outline #76777B; outline-variant #C6C6CB |
| Error | error #BA1A1A; error-container #FFDAD6; on-error-container #93000A |
| Type families | Inter; JetBrains Mono |
| Type scale | 40/48, 30/36, 24/32, 18/28, 16/24, 14/20, 12/16, 11/16 |
| Spacing | 4 px unit; 24 px gutter; 32 px margin |
| Desktop navigation | 280 px sidebar; approximately 64 px top bar |
| Mobile navigation | approximately 64 px top bar and 72 px bottom navigation |
| Borders | 1 px normal; 2 px active/evidence rule |
| Narrative radii | 0 px / sharp corners |
| Narrative elevation | no shadows; tonal layers and line weight |

### Token conflict to resolve before production implementation

The authored design guidance says every element must be sharp with 0 px corners. The structured Stitch theme also exposes generic radius defaults of 0.25 rem, 0.5 rem, 0.75 rem, and 9999 px, and several generated HTML files use rounded utility classes. The rendered references favor the sharp-cell treatment. The implementation phase needs one explicit acceptance decision; it must not silently mix rounded SaaS controls with sharp archive cells.

### Shared visual primitives inferred

Use only the primitives that are actually shared across screens:

- AppShell / WorkspaceSidebar / TopAppBar
- PublicHeader and AuthFrame
- SpaceHeader and WorkspaceTabs
- Button variants: charcoal primary, outline secondary, quiet text, danger/error
- Field, SearchField, AskComposer
- DocumentRow and SpaceCell
- StatusIndicator with processing/ready/failed/draft variants
- EmptyState, LoadingState, ErrorState
- EvidenceSource, SourcePreview, ActiveCitations
- BriefSection / AnalysisSection
- ActionItem / ActionChecklist
- ComparisonMatrix / ComparisonRow
- IntelligenceSection / ContradictionItem / DateItem / OpenQuestion
- MobileBottomNav and DocumentBottomSheet

These are proposed visual boundaries, not a mandate to create a component for every noun. The current product's data contracts should decide which pieces are reusable.

## C. Component architecture

The current UI is a route-level SPA with a 882-line SpaceDetail orchestrator. The safe architectural direction is to introduce a visual shell and presentational primitives around the existing API calls, then gradually split stateful sections without changing endpoint behavior.

### Proposed ownership

| Layer | Responsibility |
|---|---|
| Shell | Desktop sidebar, top bar, mobile navigation, page canvas, public/auth frames |
| Primitives | Tokens, buttons, fields, tabs, status, cell, empty/loading/error, focus states |
| Evidence | One source model rendered as inline disclosure, active citation panel, or mobile sheet |
| Workspace | Document library, selected document, upload queue, status summary, delete/retry |
| Document sections | Overview, Actions, Compare, Intelligence, Ask |
| API/application hooks | Existing request functions and state transitions; visual rewrite must not move authorization or invent data |
| Route adapters | Map existing routes and SpaceDetail section state into the new shell |

The current components already provide good functional seams: ui.tsx, DocumentUpload, AnalysisOverview, ActionsPanel, ComparePanel, IntelligencePanel, SourceDisclosure, and SearchPage. The first implementation pass should style and compose these seams before creating an independent state model.

## D. Screen mapping

Complexity is relative to the current codebase: S is local styling, M is one existing page/section, L crosses shared components and async states, XL changes the workspace shell or mobile interaction model.

| Stitch screen | Current route | Current main component(s) | Reusable pieces needed | Complexity | Behavior that must remain unchanged |
|---|---|---|---|---|---|
| Intelligence - Desktop | /spaces/:id | SpaceDetail section=intelligence, IntelligencePanel, IntelligenceSources | IntelligenceSection, contradiction/date/question rows, citation panel, stale/error states | L | GET/POST intelligence, ready same-space private documents, stale/processing/failed states, server citations |
| Empty Space - Desktop | /spaces/:id | SpaceDetail empty branch, DocumentUpload, EmptyState | EmptyState, UploadDropzone, upload queue, status summary | M | PDF validation, 10 MB limit, multi-upload, bounded concurrency, upload failures and retry |
| Overview - Desktop | /spaces/:id | SpaceDetail section=overview, AnalysisPanel, AnalysisOverview, AnalysisSources, DocumentTypeBadge | AnalysisSection, fact/date rows, source preview, status states | L | Explicit analysis generation, processing/failed/404 states, source references, no analysis for unready documents |
| Dashboard - Desktop | / | HomeRoute to Dashboard, AppHeader, Button, EmptyState | AppShell, SpaceGrid/SpaceCell, create-space form, destructive-action confirmation | M | Auth guard, list/create/delete spaces, empty dashboard, API errors |
| Login - Desktop | /login | Login, AuthFrame, Button, AuthProvider | Public/auth frame, labeled fields, error state, submit state | M | Token flow, /auth/me, navigation after success, validation and server errors |
| Landing Page - Desktop | / when unauthenticated | Landing, ProductPreview, BrandMark | PublicHeader, hero, capability cells, CTA, evidence sample | M | Public navigation and anchors only; no fake product actions |
| Ask - Mobile | /spaces/:id | SpaceDetail section=ask, SourceDisclosure | AskComposer, scope selector, answer block, mobile citation drawer | L | POST ask, private/reference/combined semantics, disabled Reference/Both when empty, citations |
| Space with Documents - Desktop | /spaces/:id | SpaceDetail, DocumentUpload, document list, selected-document panel | WorkspaceShell, DocumentRow, split library/detail panes, tabs | XL | Upload/delete/retry, processing/ready/failed statuses, query-string selection, all sections |
| Compare - Desktop | /spaces/:id | SpaceDetail section=compare, ComparePanel, ComparisonResult, ComparisonSources | ComparisonMatrix, selection pane, focus field, history, evidence | L | Same-space ready-only 2–4 docs, optional focus <=500 chars, history, processing/failed/retry/idempotence |
| Design System | no application route | Local reference only | Token documentation and acceptance fixtures | S | No runtime behavior |
| Workspace - Mobile | /spaces/:id | SpaceDetail + current responsive CSS | MobileTopBar, BottomNav, DocumentBottomSheet, compact DocumentRow | XL | Current document selection, upload/delete/retry, section access, no invented reader/download APIs |
| Register - Desktop | /register | Register, AuthFrame, Button, AuthProvider | Auth layout, fields, password help/error, submit state | M | Display name/email/password registration, password requirements, token flow |
| Ask - Desktop | /spaces/:id | SpaceDetail section=ask, SourceDisclosure | Two-pane Ask workspace, AskComposer, ActiveCitations | L | Answer grounding, source kind/page/excerpt, scope behavior and failure messages |
| Actions - Desktop | /spaces/:id | SpaceDetail section=actions, ActionsPanel, ActionChecklist, AnalysisSources | ActionItem, grouped deadline sections, source preview, processing/failed states | L | Explicit generation, per-document actions, pending/completed toggle, source evidence, no action execution |

The current sections are tab state inside SpaceDetail rather than separate URLs. Keep that behavior initially; route changes or deep-linking can be a later, explicit product decision.

## E. Functional gaps

The Stitch screens are approved visual references, but their content is generated sample data. The following mismatches are real and must be handled by adaptation rather than invented functionality.

| Stitch assumption | Current product evidence | Safe adaptation |
|---|---|---|
| Project Phoenix, 14 documents, fixed metrics and named files | Dashboard and SpaceDetail render user-owned API data; no fixed project or analytics endpoint | Preserve the same cell hierarchy, but render actual SpaceResponse and DocumentResponse values. Use explicit empty/loading/failed states. |
| Global Settings navigation | App has /, /spaces/:id, /search, /login, /register; no Settings route or settings API | Do not add a fake Settings destination. Omit it, or mark it intentionally out of scope until a product contract exists. |
| Invite/collaboration controls | No invite, sharing, or collaboration API in frontend/src/api.ts | Omit Invite. Do not make a button that cannot perform a real operation. |
| Global Upload Document button | Upload is contextual to a Space and supports multi-file validation/concurrency | Keep the visual CTA in the shell only when a Space context exists; otherwise navigate to create/select a Space or keep the action scoped to the page. |
| Reader thumbnail, Open in reader, Download PDF | Current API exposes document metadata and analysis, not a reader/download endpoint | Reuse the document identity, page count, analysis, and source treatments. Do not show non-functional reader/download controls. |
| Rich timeline and evidence graphs | Intelligence API returns summary, key facts, contradictions, dates, open questions with citations; no analytics graph contract | Use the same grid and connector-line visual treatment around actual arrays. Do not generate extra metrics or relationships. |
| Action Items is a global cross-document index | Current ActionsPanel generates and edits actions for the selected document | Keep the visual grouping but scope it to the selected document. A global action index needs a separate backend/API decision. |
| Reference and Both are always available in Ask | SpaceDetail disables them when the shared reference library is empty; reference documents are application-managed and read-only | Preserve disabled states and explanatory copy. Never pretend reference content exists. |
| Compare includes export report and arbitrary document data | Current comparisons accept 2–4 ready private documents in one Space, with optional focus; no export endpoint; reference documents are excluded | Keep matrix structure, history, and evidence. Omit/disable export and do not include reference documents. |
| Every analysis/intelligence answer is already ready | Current states include 404/not generated, processing, failed, stale, and provider-specific errors | Make every screen state a first-class visual variant. Never replace failures with a blank or fabricated result. |
| Uploads and processing are instant | Upload is synchronous and documents can be processing or failed; scanned PDFs are rejected | Preserve queue, aggregate status, failure code/message, retry, and no-OCR limitation in the redesigned cells. |
| Search is a generic global search with no scope caveat | SearchPage is cross-Space private-document vector search; reference library is not searched | Keep private search semantics, Space filters, page/excerpt display, query-string navigation, and empty/no-match/error states. |
| Mobile has a bottom-sheet reader workflow | Current mobile CSS keeps the selected-document panel in the page flow and has no sheet or bottom navigation | Implement the sheet only as a presentation of existing document metadata/actions, not as a new reader or download workflow. |

## F. Responsive strategy

### Desktop

- Use the 280 px fixed sidebar at the desktop breakpoint, with a 1 px right rule.
- Keep the top bar around 64 px and place section tabs, search, and contextual actions on the same structural line.
- Use the 12-column grid where the reference uses it; do not force every view into a generic card grid.
- For Overview, keep the library/thumbnail/summary relationship separate from the facts/evidence column.
- For Compare, preserve a real matrix with a fixed dimension column and horizontally scrollable document columns if content requires it.
- For Ask, use a conversation pane plus Active Citations pane where the actual answer includes citations.
- Use 1 px borders, tonal surfaces, and blue/charcoal active rules instead of current rounded shadows.

### Mobile

- Hide the desktop sidebar at 390 px.
- Use the reference 64 px top bar and 72 px bottom navigation pattern for Dashboard, Spaces, Search, and any future Settings destination only if it exists.
- Keep document rows full width and use square status blocks.
- Open selected-document detail as a bottom sheet only when it contains existing metadata, analysis, actions, or citations; the sheet must not imply a PDF reader that the API does not provide.
- Convert Ask to one column: conversation first, composer fixed to the workspace bottom, citations as expandable rows or a sheet. Preserve scope controls and server-derived evidence.
- For Overview and Actions, stack sections and keep source labels near their claims.
- Compare has no supplied mobile Stitch screenshot. Use a stacked dimension view or horizontal matrix only after a dedicated acceptance decision; do not infer a final layout from the desktop screenshot alone.
- Landing, Login, and Register need 390 px checks even though the supplied Stitch references are desktop-only. Existing CSS already has mobile behavior that can be used as a baseline, but the visual target remains Stitch's token system.
- The four screenshot gaps (Intelligence Desktop, Ask Mobile, Workspace Mobile, Ask Desktop) require either a new Stitch export or explicit acceptance of HTML-only inspection before those views can be considered pixel-verified.

## G. Implementation phases

| Phase | Scope and likely files | New shared pieces | Risk | Must not regress | Automated tests | Required @Browser checks |
|---|---|---|---|---|---|---|
| 0. Decision gate | Review this intake, choose sharp-radius rule, decide whether missing screenshots are re-exported | None | Medium | No production changes until decisions are recorded | None | Confirm reference inventory and viewport list |
| 1. Tokens and shell | frontend/src/index.css, frontend/src/components/ui.tsx, App.tsx | AppShell, WorkspaceSidebar, TopAppBar, PublicHeader, Button/Input/Status/Cell primitives | High | Route guards, keyboard focus, existing API calls | frontend typecheck/lint; route smoke tests | Compare shell at 2560 and 1280 desktop; 390 mobile |
| 2. Public and auth | Landing.tsx, Login.tsx, Register.tsx, ui.tsx | PublicHeader, AuthFrame, field/error states | Medium | register password rules, login/register token flow, redirects | auth tests and component form tests | Landing, Login, Register at reference desktop sizes and 390 mobile |
| 3. Dashboard and Space library | Dashboard.tsx, SpaceDetail.tsx, DocumentUpload.tsx | SpaceCell, DocumentRow, UploadDropzone, EmptyState, state indicators | High | list/create/delete Spaces, multi-upload, 10 MB/PDF validation, retry, processing/failed | upload queue tests, document retry tests, route/query selection tests | Dashboard, Empty Space, Space with Documents at 2560/1280/390 |
| 4. Overview and Actions | AnalysisOverview.tsx, AnalysisSources.tsx, ActionsPanel.tsx, ActionChecklist.tsx, SpaceDetail.tsx | BriefSection, EvidenceSource, ActionItem | High | analysis/action processing, failed, 404, ready states; action status writes | existing analysis/action tests plus UI state coverage | Overview and Actions with ready, processing, failed, empty evidence fixtures |
| 5. Compare and Intelligence | ComparePanel.tsx, ComparisonResult.tsx, ComparisonSources.tsx, IntelligencePanel.tsx, IntelligenceSources.tsx | ComparisonMatrix, IntelligenceSection, contradiction/date/question rows | High | 2–4 ready docs, focus limit, history, idempotence, stale intelligence, citations | comparison/intelligence API tests; state fixture tests | Compare and Intelligence with real-shaped fixtures at 2560/1280 |
| 6. Ask, Search, evidence | SpaceDetail.tsx, SearchPage.tsx, ui.tsx | AskComposer, ActiveCitations, SourcePreview, scope selector | High | private/reference/combined semantics, disabled scopes, citation metadata, Ctrl/Cmd+K search | search/reference/ask tests; citation rendering tests | Ask desktop/mobile and Search with empty, error, answer, multi-source states |
| 7. Mobile parity | ui.tsx, SpaceDetail.tsx, all responsive CSS | MobileBottomNav, DocumentBottomSheet, stacked matrix strategy | High | current mobile behavior, selected document, upload/retry/delete, accessibility | responsive component tests; keyboard and focus tests | 390 × 884 for Workspace, Ask, Overview, Actions; portrait overflow checks |
| 8. Visual acceptance | docs/design/stitch references plus app fixtures | Screenshot fixture harness; no production dependency on Stitch HTML | Medium | no API or data contract drift | full frontend/backend suites; build; lint/typecheck | Native viewport screenshot comparison for all 14 references, with gaps resolved |

## H. Risks

1. SpaceDetail couples data loading, section selection, uploads, analysis, actions, comparison, intelligence, Ask, and keyboard navigation. A visual rewrite that replaces it wholesale can introduce race conditions or stale selected-document state.
2. The current CSS is materially different from Stitch: rounded cards, shadows, Indigo accent, circular status dots, system sans, and soft gray surfaces. Token migration must be deliberate or the result will be a hybrid instead of the approved system.
3. The radius conflict is an unresolved source-of-truth decision. It affects every primitive and is visible in the screenshots.
4. Generated HTML uses Tailwind CDN, Google Fonts, Material Symbols, placeholder images, and sample content. Treating it as production code would add dependencies and fake product behavior.
5. Evidence is a correctness boundary, not just decoration. Source kind, document name, page number, excerpt, and server validation must remain intact when moved into side panels or bottom sheets.
6. Async state is part of the product contract. Processing and failed documents, stale intelligence, failed generation, 409 conflicts, and empty reference libraries must remain visible.
7. Stitch contains no true mobile references for Overview, Actions, Compare, or Intelligence. Those layouts need explicit decisions and cannot be claimed as pixel-verified from the current intake.
8. The current app has no settings, invite, reader, download, export, or global action-index APIs. Visual affordances for those operations would be misleading.
9. Visual acceptance at native Stitch sizes can expose density and overflow problems that are hidden in a generic 1280 px browser window. Use the recorded viewport sizes and data-shaped fixtures.

## I. Recommended next goal

Implement Phase 1 only: DocuMind visual foundations and shared shell.

Scope:

- Decide and record sharp 0 px corners as the default unless the product owner explicitly overrides the authored design guidance.
- Add the exact Stitch tokens and font strategy to the frontend without changing API behavior.
- Introduce AppShell, WorkspaceSidebar, TopAppBar, PublicHeader, and the minimum primitive set: Button, Field, StatusIndicator, Cell, EmptyState, LoadingState, ErrorState, and EvidenceSource.
- Wire the existing routes into the shell without changing route paths, authentication, SpaceDetail section semantics, or data fetching.
- Keep current page content and functional state transitions intact; no feature additions, no reader/download/invite/settings/export.
- Verify Landing, Login, Dashboard, Empty Space, and Space with Documents at desktop and 390 px using the local Stitch references.

Exit criteria:

- Existing frontend build, lint, and tests pass.
- No backend or API files changed.
- Every shell control either performs an existing action or is omitted.
- Visual comparison uses the local screenshots as the primary reference.
- Missing Stitch screenshots are tracked as explicit acceptance gaps rather than approximated silently.

