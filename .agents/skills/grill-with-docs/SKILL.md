---
name: grill-with-docs
description: >-
  Conduct an interactive design & architecture alignment interview (grill-with-docs) that grounds questions in project documentation, updates CONTEXT.md, and generates Architecture Decision Records (ADRs) under docs/adr/.
---

# Grill With Docs (Stateful & Documentation-Driven Interview)

Use this skill when designing a new feature, planning an architectural refactor, or making decisions that need persistent documentation (`CONTEXT.md` and ADRs).

## Core Objectives
1. **Interactive Stress-Testing**: Interview the user step-by-step to expose edge cases, technical trade-offs, and unstated assumptions before code is written.
2. **Context & Glossary Alignment (`CONTEXT.md`)**: Ensure terms and domain models are consistently defined and updated in `CONTEXT.md`.
3. **Architecture Decision Records (`docs/adr/`)**: Document key technical choices, trade-offs, and consequences as numbered ADR files.

## Workflow Protocol

### Step 1: Read & Ground in Existing Documentation
Before asking questions, inspect:
- `CONTEXT.md` (if present)
- Existing ADRs in `docs/adr/`
- `alignment_preferences.json`
- Relevant project specs (`software_spec_th.md`, `software_spec_en.md`, `README.md`)
- Related codebase files (`main.py`, `cli_manager.py`, etc.)

### Step 2: Conduct Iterative Interview ("Grilling")
- Ask targeted questions **one at a time**.
- Present clear architectural trade-offs with recommendations.
- Explore failure modes, provider fallbacks, edge cases, and API contracts.
- Use `ask_question` tool when presenting multi-choice options to the user.

### Step 3: Update & Persist Project Documentation
Once alignment is reached:
1. **Update `CONTEXT.md`**: Record any new domain concepts, terminology, or state rules.
2. **Generate ADR in `docs/adr/`**:
   - Filename format: `docs/adr/NNNN-<short-title>.md` (e.g. `docs/adr/0001-provider-failover-orchestration.md`).
   - Include Status (Accepted/Proposed), Context, Decision, and Consequences.
3. **Update `alignment_preferences.json`**: Sync preference updates if model orchestration rules changed.
