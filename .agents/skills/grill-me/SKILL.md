---
name: grill-me
description: >-
  Use this skill to conduct an interactive design & architecture alignment interview (grill-me session) for the KookAI project.
  It helps align decisions on model provider failover, UI behavior, and backend orchestration before implementation.
---

# KookAI Design & Architecture Alignment (Grill-Me)

Use this skill when initiating new major features, architecture changes, or refactoring in the KookAI project.

## Alignment Objectives
1. **Interactive Requirements Gathering**: Ask targeted, focused questions to resolve design choices and architecture decisions.
2. **Provider Failover & Fallback Compliance**: Ensure any backend model routing aligns with KookAI's model fallback rules (`alignment_preferences.json`).
3. **UI/UX & Notification Alignment**: Verify real-time status dispatch and UI notification requirements.

## Protocol Steps
1. **Check Existing Preferences**: Read [alignment_preferences.json](file:///root/Desktop/KookAI/alignment_preferences.json) in the project root to inspect active constraints.
2. **Conduct Grill-Me Interview**:
   - Present architectural trade-offs and design options clearly.
   - Resolve ambiguity before writing code.
3. **Persist Alignment**:
   - Save updated decisions to [alignment_preferences.json](file:///root/Desktop/KookAI/alignment_preferences.json).
   - Enforce updated constraints in `cli_manager.py` and `main.py`.
