# ADR 0004: Unified Session History Persistence & Cross-Provider Parameter Abstraction

* **Status**: Accepted
* **Date**: 2026-08-10

## Context
KookAI supports switching between multiple AI model backends (Antigravity/Gemini, Claude, Codex, Kimi, Grok, Meta Muse) and performing dynamic auto-failover during provider errors or rate limits. Previously, history storage formats differed across CLI backends (`.codex`, `.claude_sessions`, `.kimi_history`), leading to context loss during failover. Additionally, provider-specific knobs (Claude Extended Thinking, Codex Ultra Effort, Antigravity Sandbox mode, Grok Reasoning Effort) lacked unified mapping when failover transferred execution to a secondary model backend.

## Decision
1. **Unified Canonical Transcript Store**:
   - Maintain a normalized, provider-agnostic session store (`.data/conversations.json` / SQLite `conversations.db`) capturing roles, multi-turn messages, image attachments, and video analysis context.
   - CLI adapters (`codex_backend.py`, `claude_backend.py`, `kimi_backend.py`, `grok_backend.py`, `muse_backend.py`) dynamically synthesize target CLI context buffers on-the-fly when switching providers or executing auto-failover.
2. **Semantic Parameter Abstraction Matrix**:
   - Map parameters across providers into unified abstraction tiers (e.g., `Effort Level`: `low`, `medium`, `high`, `ultra` mapped to target provider equivalents).
   - If a provider does not support a specific knob (e.g., `sandbox` mode on Antigravity when failing over to Claude), safely degrade by dropping unsupported knobs while emitting a non-intrusive status notification to the UI.

## Consequences
- Preserves full conversation context and attachment history across model switches and failover events.
- Prevents CLI state corruption by isolating canonical storage from native CLI file formats.
- Ensures predictable model behavior across different providers while maintaining UI parameter settings.
