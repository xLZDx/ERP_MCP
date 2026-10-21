# Tailscale SSH access diagnostic — 2026-10-21

## Scope and revision

- Repository: `D:\Repo\ERP_MCP`
- Base revision: `6170d02ce647a815880677d24846f255e7a8fcf8`
- Purpose: test whether the standard Tailscale SSH route supplies a trusted host identity for the authorized read-only WP0 remote checks.

## What changed and why

- Updated `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md` with the follow-up connectivity observations.
- Recorded a command-construction lesson in `core/LESSONS_LOG.md` after a nested PowerShell quote error.
- No SSH host-key policy, remote configuration, task, token, service, or repository runtime state was changed.

## Evidence

- `tailscale ping --c 1 ivan.tail08f9f9.ts.net` returned a direct-path pong from `ivan` at `100.88.71.74`.
- A filtered `tailscale status --json` read showed the peer online; `SSHEnabled` was absent/blank in the returned peer object.
- `tailscale ssh ivan.tail08f9f9.ts.net whoami` failed with `No ED25519 host key is known ...` and `Host key verification failed.`
- An earlier nested PowerShell probe also stopped on the same host-key rejection; its quoting then produced a local PowerShell command error. No remote command ran.
- Strict checking remained enabled; no host key was added or accepted.

## Verification state

Network reachability is observed. Remote authentication, remote status, 1C environment verification, business reads, task start, and token minting are **NOT_RUN**. The missing trusted SSH host identity remains an external dependency.
