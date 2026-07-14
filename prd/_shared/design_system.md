# ARVIS Design System

Reference document for visual language across all ARVIS screens.

## Theme

- **Dark mode default.** BMS rooms are dim. Operators work overnight shifts.
- **Light mode supported** for exec / printable views.
- **High contrast variant** for colorblind accessibility — must satisfy WCAG AA at minimum, AAA for critical paths.

## Color tokens

```
neutral.bg.0          — page background (dark: #0A0E14, light: #FAFBFC)
neutral.bg.1          — card / panel background
neutral.bg.2          — nested surface (modal, popover)
neutral.border.subtle — divider, faint
neutral.border.strong — focus ring, emphasis
neutral.text.primary  — body text
neutral.text.muted    — labels, timestamps
neutral.text.subtle   — placeholder, disabled

status.success        — verifier passes, advisory approved, on-track GSAS
status.warn           — at-risk, abstention, advisory in question
status.danger         — alarm, verifier fail, deduction
status.info           — neutral state, T1 advisory

accent.primary        — interactive (button, link, focus)
accent.physics        — physics simulator overlays (always distinct)
accent.memory         — memory recall highlights (always distinct)
```

**Color discipline**:
- Red/amber reserved for **problems**. Never decorative.
- Green reserved for **verified passes**. Not nature/environmental imagery.
- Physics overlays use a single, consistent accent (e.g., dotted purple). Never red or green.
- Memory recall highlights are visually distinct from evidence chips.

## Typography

- **Display** — variable sans, used sparingly. Headlines.
- **Body** — variable sans. All prose.
- **Mono** — monospace, used for **all numeric values** (sensor reads, scores, IDs). Alignment matters in dense tables.
- **Recommended families**: Inter (sans), JetBrains Mono (mono). Designer may substitute.

Sizes (web rem):
- xs 0.75 — chip text
- sm 0.875 — labels
- base 1 — body
- lg 1.125 — section heading
- xl 1.5 — page heading
- 2xl 2 — score big number
- 3xl 3 — exec hero

## Spacing scale

4px base. Use multiples: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

## Component primitives

Designer specs the look; engineer wires shadcn/ui or equivalent.

- **Button** — primary, secondary, ghost, danger. Three sizes.
- **Chip** — risk tier, mode, status, evidence source. Color-coded with text label.
- **Card** — has elevation 0 (flat), 1 (subtle), 2 (modal).
- **Toast** — auto-dismiss notification, top-right.
- **Modal** — overlay with backdrop, ESC to close.
- **Tab strip** — for in-screen sub-nav.
- **Empty state** — illustration + headline + body + CTA.
- **Loading skeleton** — never spinner alone, always shape-hint.
- **Tooltip** — on hover, 300ms delay, dismiss on mouseleave.

## Iconography

- Use Lucide React or equivalent open icon set as base.
- **Custom icons required for**: chiller, AHU, pump, valve, damper, coil. None of these exist in standard libraries.
- Icons render at 16/20/24/32 px.
- Equipment icons must be recognizable at 16 px.

## Motion

- Minimum motion. Operators don't want UI sliding around.
- **Acceptable**: confirmation flash (200ms), trace events appending (fast cascade), chart data updating (smooth interpolation).
- **Unacceptable**: hero animations, decorative parallax, scroll-jacking.
- **Reduced motion** must be respected (prefers-reduced-motion).

## Density

- **Default**: dense. Operators are power users on 24" monitors.
- **Presentation mode** (P2, for exec/demo): airier spacing, larger type.
- Designer ships dense as default. Toggleable per user later.

## Accessibility

- WCAG 2.2 AA required, AAA for critical paths.
- All color carries a text label (no color-only encoding).
- Focus states visible, ring at 2px.
- Keyboard nav: every interaction reachable by tab, every action reachable by enter/space.
- ARIA labels on every icon button.
- Live regions announce new advisories.

## Internationalization

- English first.
- **Arabic RTL** must be layout-safe from day 1 (Marina pilot is in Qatar). Component primitives must mirror correctly. Strings externalized.
- Numbers stay LTR even in RTL contexts (sensor reads, scores).

## Print

- All non-interactive screens must print legibly (advisory detail, GSAS audit package, exec KPI).
- Print stylesheet hides chrome, expands collapsibles, drops dark theme.

## Brand

- ARVIS wordmark + monogram (designer to create — current brand placeholder)
- Customer co-branding slot in top-left near mode badge (P1)
