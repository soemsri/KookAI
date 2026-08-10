---
trigger: always_on
---

# KookAI Design & Architecture Alignment Rule

- Always inspect [alignment_preferences.json](file:///root/Desktop/KookAI/alignment_preferences.json) when working on model provider orchestration or UI fallback notifications.
- Ensure model provider failover priorities are maintained across `cli_manager.py`, `main.py`, and related backend modules.
