# Design system

Direction (from UI UX Pro Max): **Minimalism & Swiss style** for an enterprise identity product — high contrast, geometric, grid-based, one accent colour reserved for the primary action and "verified" states.

## Tokens (`frontend/src/index.css`)

| Token | Light | Dark | Use |
|---|---|---|---|
| `brand-700` `#1E3A5F` | primary buttons, active nav, logo | — | Trust navy |
| `accent-600` `#059669` / `accent-400` `#34D399` | CTA, success, liveness, scan frame | — | Secure green |
| `surface` / `surface-2` / `surface-3` | `#FFFFFF` / `#F7F9FC` / `#EEF2F7` | `#0F172A` / `#131D31` / `#192438` | page, cards, inputs |
| `ink` / `ink-2` / `ink-3` | `#0F172A` / `#475569` / `#64748B` | `#F1F5F9` / `#CBD5E1` / `#94A3B8` | text hierarchy (all ≥ 4.5:1 on their surfaces) |
| `line` / `line-2` | `#E2E8F0` / `#CBD5E1` | 8 % / 14 % white | borders |
| radius | 6 / 10 / 14 / 20 px | | inputs / buttons / cards / kiosk panels |
| shadow | `card` (1–3 px) and `pop` (dialogs/toasts) | | elevation scale of two |
| type | Inter Variable, 15 px body, 1.6 line height, tabular numerals for times and KPIs | | |

The admin console follows the OS colour scheme (`prefers-color-scheme`, override with `data-theme`); the kiosk and landing page are always dark (`.theme-dark`) so the camera stage and scan frame read clearly in a lobby.

## Components (`frontend/src/components/ui`)

Button (6 variants × 5 sizes, loading state, 44 px+ targets on `lg`/`xl`), Card/MotionCard, Input/Select/Textarea/Switch (visible labels, `aria-describedby` errors, 16 px font on mobile), Badge/StatusBadge (colour + dot + text, never colour alone), Dialog/ConfirmDialog (focus trap, Esc, focus restore), Toast (`aria-live=polite`, auto-dismiss 4 s / 7 s), Tabs (layout-animated pill), Table/Th/Td, Pagination, Skeleton, EmptyState, Avatar, Stat + CountUp.

## Motion (`frontend/src/lib/motion.ts`)

- Page transitions: 240 ms fade/translate in, 150 ms out (exit faster than enter).
- Lists and KPI grids: 45 ms stagger with a soft spring (`visualDuration 0.35, bounce 0.12`).
- Dialogs/toasts: `spring.snappy` (stiffness 520, damping 38).
- Sidebar active pill and tabs: `layoutId` shared-element transitions.
- Kiosk: canvas-drawn face frame with corner brackets, scanning sweep (sin-eased), liveness bar, success/failure ring flashes; the identified and recorded screens use scale springs.
- Charts animate on first render only; summaries are rendered as text for screen readers.
- `MotionConfig reducedMotion="user"` plus a global CSS reduced-motion rule disable non-essential motion; the kiosk scan sweep also checks `prefers-reduced-motion`.
- Success states never appear before the API confirms the stored event (`/attendance/events` → 201).

## Accessibility

Skip link, focus moved to `<main>` on route change, visible focus rings (`:focus-visible` 2 px ring), semantic tables, icon-only buttons carry `aria-label`, live regions for kiosk guidance, 375 px layouts verified with device emulation.
