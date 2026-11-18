# Design system

## Purpose

Interfaces in this workspace are dense, calm, and operational. A person under time pressure should find the primary action in one scan. Decoration never competes with status, numbers, or errors.

## Tone

- Short labels. Technical nouns are fine when the audience is an operator or engineer.
- Status is always explicit text, not color alone.
- Destructive actions are named (`Delete session`) and sit away from the primary action.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#07080b` | Application background |
| `--bg-elev` | `#101218` | Panels |
| `--bg-elev-2` | `#171b22` | Nested cards, inputs |
| `--line` | `#262b36` | Hairline borders |
| `--text` | `#e7ecf3` | Primary text |
| `--muted` | `#8b95a8` | Secondary text |
| `--accent` | `#d6a15a` | Primary action, brand |
| `--ok` | `#7fd99a` | Pass, healthy |
| `--warn` | `#e6b450` | Waiting, caution |
| `--danger` | `#f07178` | Failure, destructive |
| `--info` | `#7cb7ff` | Running, links |
| `--space-1` | `4px` | Tight stacks |
| `--space-2` | `8px` | Related controls |
| `--space-3` | `12px` | Card padding |
| `--space-4` | `16px` | Section gap |
| `--space-5` | `24px` | Page regions |
| `--radius` | `10px` | Controls and cards |
| `--font-sans` | `Instrument Sans, sans-serif` | UI text |
| `--font-mono` | `IBM Plex Mono, ui-monospace, monospace` | IDs, code, metrics |
| `--motion` | `160ms ease` | Hover and expand |

## Components

- **Button.** Primary (accent fill), quiet (border only), danger (danger text, quiet fill). One primary button per region.
- **Status pill.** Uppercase label plus the semantic color. Always include the word (`RUNNING`, `PASSED`).
- **Text input.** Elevated background, 1px line, focus ring in `--info`.
- **Card.** Elevated background, 1px line, no drop shadow heavier than `0 8px 24px rgb(0 0 0 / 28%)`.
- **Table / metric.** Monospace numbers, muted unit, label above the value.

## Accessibility

- Body text at least 14px. Contrast of `--text` on `--bg` and `--muted` on `--bg-elev` must stay at or above AA for normal text.
- Every interactive element is reachable by keyboard and shows `:focus-visible`.
- Icon-only buttons require `aria-label`.
- Do not start motion that ignores `prefers-reduced-motion`.

## Content

- Empty states name the next action.
- Errors include the failing operation and a next step. Do not show a stack trace as the only message.
- Timers and metrics include their unit.

## Non-patterns

- No gradient hero, no glassmorphism, no novelty illustrations in operational views.
- No new accent colors for a single feature.
- No modal on top of a modal.
