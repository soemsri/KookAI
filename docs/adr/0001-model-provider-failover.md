# ADR 0001: Automatic Model Provider Failover & Real-Time UI Notifications

* **Status**: Accepted
* **Date**: 2026-08-02

## Context
KookAI relies on multiple AI model backends (Claude, Grok, Kimi, Codex, Muse). Provider outages, rate limiting, or connection drops must not break user interactions.

## Decision
1. Implement automatic failover to the next available configured provider in priority order.
2. Enforce failover priority ordering within `cli_manager.py` and `main.py`.
3. Send real-time status notifications to the UI layer whenever provider switching occurs.

## Consequences
- Enhanced system resilience and seamless fallback.
- Requires backend state tracking in `cli_manager.py` and websocket/event dispatch to UI.
