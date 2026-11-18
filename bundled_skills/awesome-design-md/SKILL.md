---
name: awesome-design-md
description: Enforce a structured design system, component hierarchy, design tokens, accessibility, and frontend consistency through DESIGN.md.
---

# Awesome Design MD

`DESIGN.md` at the workspace root is the source of truth for product UI. Read it before adding a screen, component, or style. Update it when you introduce a token, a component, or an interaction pattern that does not fit.

## Hierarchy

1. **Foundations** — color, type, space, radius, elevation, motion.
2. **Components** — buttons, inputs, navigation, feedback, data display.
3. **Patterns** — forms, empty states, loading, errors, destructive confirmation.
4. **Product surfaces** — the actual screens and their primary action.

Build screens out of components. Build components out of tokens. Do not invent a one-off color or spacing value in a feature file.

## Required sections in DESIGN.md

- Purpose and product tone (one paragraph).
- Tokens with concrete values.
- Component inventory and when to use each.
- Accessibility: contrast, focus, keyboard, names for icon-only controls, motion.
- Content rules: labels, errors, empty states.
- Explicit non-patterns (what not to add).

## Implementation rules

- Interactive controls have a visible focus state and an accessible name.
- Text meets WCAG AA contrast against its background.
- Do not convey state by color alone.
- Respect `prefers-reduced-motion` when adding animation.
- Errors tell the user what to do next.
- Loading and empty states are designed, not accidental.

## When the PRD has no UI

Say so, leave `DESIGN.md` unchanged, and do not restyle unrelated files.
