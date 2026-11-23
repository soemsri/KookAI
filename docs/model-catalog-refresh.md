# Automatic model catalog refresh

Already-installed mobile apps call `GET /api/models` at startup. The server now
waits up to 8 seconds for shared discovery before returning the refreshed catalog.
No mobile rebuild is required for this startup path. Requests within 60 seconds
of a completed refresh reuse the catalog; concurrent clients share one discovery.
Server boot, the 30-minute background timer, and `POST /api/models/sync` also use
that shared worker. The manual POST bypasses the 60-second cooldown.

If discovery fails or exceeds the wait budget, GET returns the last good catalog.
The worker continues after an HTTP timeout/disconnect. Older mobile clients will
see its completed results on their next catalog request (model picker, reconnect,
server switch, or the existing 10-minute timer), not immediately via push.

## Sources and limits

| Provider | Discovery source |
| --- | --- |
| AGY / Gemini | Installed `agy models`, then existing seeds |
| Codex / OpenAI | Read-only app-server `model/list`, local model cache, seeds |
| Claude | Public `models.dev` registry and seeds |
| Grok / xAI | Installed `grok models`, public registry, seeds |
| Kimi | Actual configured aliases in `$KIMI_CODE_HOME/config.toml` (default `~/.kimi-code/config.toml`) and seeds |
| Muse | Public registry and seeds |
| DeepSeek | Public registry and seeds |
| Z.ai | Public registry, using the existing `zai-coding-plan/` route, and seeds |

The public registry request contains no account credentials. Only non-deprecated,
text-output, tool-capable models with supported routes are imported. Registry
membership is **not** proof of account entitlement or successful generation.
Kimi requires CLI-configured aliases: the server does not invent aliases or modify
native CLI configuration. Python 3.10 without `tomllib` retains Kimi seeds only.

Discovery adds models without changing existing entries, disabled flags, the
selected/default model, or provider failover order. The catalog limit is now 1000
entries, retaining a bounded validation limit while allowing multi-provider growth.
The response body remains schema version 1. `Cache-Control: no-store` prevents
HTTP cache reuse; `X-KookAI-Model-Sync` reports `complete`, `cached`, `pending`, or
`failed`. `complete` means the discovery cycle completed, not that every source
or account was available.

## Verification and rollback

Run `venv\Scripts\python.exe -m pytest -q`. Startup HTTP tests cover first-response
freshness, concurrent requests, forced refresh, timeout/cancellation, authorization,
and preservation of default/disabled models. Discovery tests mock remote sources;
also rehearse live discovery against a temporary copy of the catalog before deploy.

Before rollback, restore both the previous source and the previous **runtime model
catalog**. Old server code rejects catalogs larger than 100 entries. Restart using
the established `run_server.bat` launcher; a 200 alone does not prove the new build
is running—check its process creation time and `X-KookAI-Model-Sync` header.
