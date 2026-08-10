# KookAI Project Context & Domain Glossary

## Overview
KookAI is an AI orchestration platform supporting multi-provider model routing, automated model failover, video processing, and real-time status dispatch across mobile and web interfaces.

## Domain Terminology & Concepts
- **CLI Manager (`cli_manager.py`)**: Central orchestration component responsible for managing multi-provider model processes and state transitions.
- **Model Provider Failover**: The automated strategy that switches requests to secondary model backends (e.g. Claude, Grok, Kimi, Codex, Muse) upon primary provider errors or rate limits.
- **UI Fallback Notifications**: Real-time status updates dispatched from the backend orchestrator (`main.py` & `cli_manager.py`) to inform the UI of provider switching events.
- **Alignment Preferences (`alignment_preferences.json`)**: Persistent configuration tracking architecture choices and failover priorities aligned via `grill-me` or `grill-with-docs`.
