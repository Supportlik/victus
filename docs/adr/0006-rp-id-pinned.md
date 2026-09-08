# ADR 0006 — WebAuthn RP_ID is pinned at the first passkey

**Status:** accepted · **Date:** 2026-09-08

## Context

Passkeys are bound to the relying-party identifier (`RP_ID`, effectively the domain). Changing the domain after
users have registered invalidates every credential; there is no migration path. A common failure is to start on a
temporary hostname (VPN-provided name, DynDNS, LAN IP) "for testing" and move to the real domain later. WebAuthn also
requires HTTPS except on `localhost`, so there is no LAN-only trial phase.

## Decision

- `auth.rp_id` and `auth.origin` are mandatory configuration.
- When the **first** passkey of an installation is registered, Victus stores the `RP_ID` in the database
  (`installation.pinned_rp_id`).
- On every start the server compares the configured value with the pinned one and **refuses to start** on mismatch,
  printing both values.
- An explicit `victus auth repin --rp-id <new> --yes` exists for the intentional case; it voids all passkeys and
  requires users to re-enrol via recovery code or admin URL.
- The UI nudges every user until at least two passkeys exist and offers a one-time recovery code.

## Consequences

- Operators must decide the final domain before the first login; DEPLOYMENT.md puts this first.
- Local development uses `rp_id = localhost`, which is a separate installation (separate database) by construction.
- Accidental configuration drift is caught at start-up, not by locked-out users.
