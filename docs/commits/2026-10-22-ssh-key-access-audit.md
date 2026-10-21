# Change record: Recheck Ivan SSH keys and trust

## Change

- Added the 2026-10-22 read-only SSH identity/trust recheck to `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md`.
- Recorded the local Ed25519 identity match and ACL state, unavailable SSH agent, absence of the Ivan host from local/global known-hosts files, observed network host-key fingerprint, Tailscale reachability, and strict SSH failures.

## Why

The operator asked to check project SSH keys and access. The repository had a prior host-key blocker, so the current client identity and all relevant trust stores needed to be checked without weakening host verification.

## Affected contracts and paths

- `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md`: append current access evidence and retain the existing `NOT_RUN` source-status outcome.
- No SSH configuration, key file, known-hosts file, remote host, service, connector, or business data was changed.

## Decisions

- Use the matching local `id_ed25519` identity only for the strict SSH attempt; do not offer unrelated local identities to the ERP host.
- Treat `ssh-keyscan` output as untrusted observation. Do not add the observed host key without authenticated out-of-band confirmation.
- Keep `StrictHostKeyChecking=yes`; do not execute remote status or business-read commands while host identity is untrusted.

## Verification state

- `ssh-keygen -lf "$env:USERPROFILE/.ssh/id_ed25519"` and its `.pub` companion returned the same SHA256 fingerprint. The fingerprint is omitted because the record only needs the match result. ACL inspection with `(Get-Acl "$env:USERPROFILE/.ssh/id_ed25519").Access` showed inherited FullControl entries for the current user, SYSTEM, and Administrators. Whether this client identity is authorized for the ERP host remains **NOT_VERIFIED**.
- `ssh-add -l` exited 2: “Error connecting to agent: No such file or directory.” `ssh-keygen -F ivan.tail08f9f9.ts.net -f "$env:USERPROFILE/.ssh/known_hosts"` and the same command for `known_hosts.old` both exited 1 with no match. `Test-Path C:\ProgramData\ssh\ssh_known_hosts` returned `False`.
- `tailscale ping --timeout=8s ivan.tail08f9f9.ts.net` returned a pong from `100.88.71.74` in 2 ms.
- `ssh-keyscan -T 5 -t ed25519 ivan.tail08f9f9.ts.net | ssh-keygen -lf -` observed `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`; repository evidence did not establish that fingerprint as trusted.
- Strict OpenSSH used `ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE/.ssh/id_ed25519" -o "UserKnownHostsFile=$env:USERPROFILE/.ssh/known_hosts" -o ConnectTimeout=8 koros@ivan.tail08f9f9.ts.net exit` and exited 255 before authentication. `IdentitiesOnly=yes` and explicit `-i` constrain the attempt to the one checked identity. `tailscale ssh ivan.tail08f9f9.ts.net whoami` also exited 255 with the unknown-host-key error. No remote command ran.
- No tests, service mutations, or business reads were run.

The commands and essential output are also captured in the linked liveness artifact. No private key material, public key blob, password, token, or credential was added to either record.

## Lesson

A matching client key and a reachable SSH host are not proof of server identity. Compare an observed host fingerprint with an authenticated out-of-band value before recording trust or attempting authenticated remote work.
