# ADR 0002: Multi-Host Server Pairing, Token Lifecycle & Fallback Protocol

* **Status**: Accepted
* **Date**: 2026-08-10

## Context
KookAI mobile client allows users to connect to multiple computer host instances (e.g. Home PC, Work PC) via 6-digit PINs or QR code scanning. We need clear strategies for token expiration, server heartbeat tracking, and setup fallback when the Cloudflare Worker registry is unreachable.

## Decision
1. **Token Lifecycle**: Use persistent device auth tokens generated upon successful pairing. Tokens remain valid until explicitly un-paired/revoked by the server host. Periodic heartbeat requests validate session status.
2. **Multi-Server Management**: The mobile app executes background ping checks (every 15s) against all registered servers. Visual status pills indicate server health, and auto-switch prompts are presented if the active server goes offline.
3. **Registry Fallback Strategy**: If the host computer cannot register its PIN on the remote Cloudflare Worker Registry, the server falls back to generating a local LAN IP QR code and serving direct local PIN validation.

## Consequences
- Reliable pairing UX even in offline or firewalled local network environments.
- Active multi-server tracking in mobile client with minimal battery/network overhead (15s lightweight ping).
- Server backend maintains device authorization lists in `authorized_devices.json`.
