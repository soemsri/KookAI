---
name: KookAI Workspace Design System
description: Cohesive token system and aesthetic guidelines for KookAI Web Console and Mobile Companion.
colors:
  primary: "#2563eb"
  primary-dark: "#3b82f6"
  surface-light: "#ffffff"
  surface-subtle-light: "#f8f9fa"
  surface-dark: "#181b22"
  surface-subtle-dark: "#0f1115"
  surface-active: "#eaeaea"
  surface-active-dark: "#222630"
  border-light: "#e5e7eb"
  border-dark: "#2e3543"
  text-primary-light: "#1f2937"
  text-primary-dark: "#f3f4f6"
  text-secondary-light: "#4b5563"
  text-secondary-dark: "#9ca3af"
  text-muted: "#6b7280"
  status-success: "#10b981"
  status-error: "#ef4444"
typography:
  display:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.25
  heading:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "Fira Code, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  input-field:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-primary-light}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
---

# KookAI Design System

## Overview

KookAI is a developer-centric AI workspace client. The interface must communicate system state, active CLI agents, model quota, and failover notifications with high visual fidelity, scanability, and zero decorative noise.

## Colors

- **Primary Accent (`#2563eb` light / `#3b82f6` dark):** Reserved for primary interactive controls, active connection badges, and focus rings.
- **Surface Neutrals:** Clean surfaces (`#ffffff` / `#181b22`) paired with subtle contrasting backgrounds (`#f8f9fa` / `#0f1115`) to create depth without relying on heavy box shadows.
- **Status Colors:**
  - Success/Online: `#10b981` (light) / `#34d399` (dark)
  - Error/Offline: `#ef4444` (light) / `#f87171` (dark)
  - Warning/Degraded: `#f59e0b`

## Typography

- **Display & Headings:** `Outfit` provides a modern, geometric tech character for headers, model titles, and brand elements.
- **Body & Controls:** `Inter` handles paragraphs, lists, forms, and message bubbles. Minimum body font size is `14px` (`0.875rem`).
- **Metadata & Badges:** Minimum font size is `11px` (`0.75rem`). Never render interactive or functional labels below 11px.
- **Code & Logs:** `Fira Code` for token streaming, model CLI names, terminal output, and keybindings.

## Layout

- **Desktop Layout:** Two-column split layout with collapsible navigation/history sidebar (260px) and a flexible conversation/dashboard main stage.
- **Mobile Layout:** Single-column fluid view with off-canvas sidebar drawer and sticky bottom prompt composer.
- **Density:** High information density with disciplined rhythm (`8px` / `12px` / `16px`). Avoid sprawling empty space between related form inputs.

## Elevation & Depth

- Rely primarily on subtle border lines (`#e5e7eb` / `#2e3543`) rather than exaggerated shadows.
- Elevation shadows (`--shadow-sm`, `--shadow-md`) are reserved for overlays, dropdowns, and floating toasts.
- **No colored zero-offset glow effects** (`box-shadow: 0 0 15px rgba(...)`).

## Shapes

- Interactive elements use `8px` (`rounded.md`) border radius.
- Badges and status pills use pill/full radius (`9999px`).
- Modal dialogs use `12px` (`rounded.lg`).

## Components

- **Chat Bubbles:** Clear asymmetry between user inputs (accent-tinted or right-aligned) and assistant responses (surface-aligned with markdown styling).
- **Model Selector & Badges:** Distinct tags for provider types (AGY, Codex, Claude, Grok, Kimi, Zai) with active status indicators.
- **Toasts & Notifications:** Floating non-intrusive notifications displaying real-time failover events and token limits.

## Do's and Don'ts

### Do's
- Always maintain WCAG AA contrast ratio (minimum 4.5:1 for normal text).
- Use clear, descriptive labels for model provider status.
- Keep interactive text legible (at least 11px, preferably 12px+).
- Ensure smooth theme transitions (dark/light/system).

### Don'ts
- **No Cardocalypse:** Do not nest card containers inside card containers more than 1 level deep.
- **No Gimmicky Pulse:** Do not use infinite pulsing animation on static indicators; reserve animation strictly for active network streams or live processing.
- **No AI Slop Copy:** Avoid hyperbolic buzzwords like *"world-class next-generation AI experience"*. State clearly what model is running and what it does.
