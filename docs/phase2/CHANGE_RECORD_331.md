# Change record 331 — source-only validator build attestation verifier

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation owner: Codex; architecture adjudication: GPT-PM.
- Canonical project binding verified through PM Bridge as `erp_mcp`, repository
  `https://github.com/xLZDx/ERP_MCP.git`, local path `D:\Repo\ERP_MCP`.
- PM Bridge request `31d04c5c-7a8e-4bf4-8a46-7c8dcf7374c3` received an exact `REQUEST_ID`-matched
  recommendation: implement the verifier source-only, keep production composition disabled until
  externally authorized root/policy/deployment identity and measured artifact evidence exist.
  This was architecture advice, not commit, push, deployment or gate approval.
- The registrar, runtime-composition and qualification-prerequisite files were pre-existing
  untracked/dirty shared-worktree artifacts; their original authorship is not established. This
  turn made the validator-provenance changes described below. The package export file was dirty in
  the shared worktree; only the new exports are attributable to this turn.
- No tests, checks, build, SQL migration, database mutation, COM call, key provisioning, staging,
  commit or push was performed for this change.

## Defect and implementation

The prior registrar accepted any object with `load_current_approved_build()` that returned a
shape-valid 64-character `build_id` and matching configured `policy_id`. That shape did not
authenticate the signing root, approved policy, running artifact or deployment.

Added `validator_build_attestation.py` with a bounded canonical v1 envelope, duplicate/unknown-key
rejection, strict UTF-8/JSON/timestamp constraints, a separate Ed25519 domain, key/policy/build/
attestation revocation checks, derived build identity, artifact/source/provenance/component/
deployment/environment binding, authenticated-time expiry checks, and a three-second trust-snapshot
and runtime-measurement freshness ceiling. Verified results carry an internal verifier seal; a
caller-provided build ID or policy string cannot construct a result accepted by the registrar.

The registrar now requires the concrete verifier and re-loads/re-verifies the build authority
immediately before every evidence transaction. If policy revision, attestation or measured identity
changed between evidence verification and registration, it refuses before acquiring a database
connection. The runtime composition root accepts only the abstract production host-source type;
there is no concrete host provider in this repository, so test input sources cannot enter production
composition and the gate remains unavailable. Synthetic trust roots are suitable only for isolated
verifier tests, not production composition.

Acceptance `S13-VALIDATOR-BUILD-ATTESTATION-01` was added to
`S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.

## Verification state

- Source module SHA-256: `6A9B806E86168CEF0774A619BB599E69C72A19AA40D37620500CC3AFAF257909`.
- Registrar SHA-256: `26778EB190A6FC1AB79860FD92E1FF1F50FE193CFF21EFBB26814EDCBCC581DB`.
- Runtime-composition SHA-256: `72E6EAB4949526988075EF1FC6F9B781F417D8F9942213779DAFA617A84056A8`.
- Package exports SHA-256: `E2DF91B7297014460F049C36B2E222C439B0CA5E75ED447EA5449228B2953197`.
- Runtime behavior, canonical golden vectors, invalid/signature/revocation/time/policy/artifact
  mismatch cases, provider-change-before-insert behavior and production-gate rejection remain
  `NOT_RUN`. No source review has yet inspected this new code.
- External authority remains `NOT_ESTABLISHED`: authorized root/key lifecycle, issuer, policy and
  revocation owner, CI provenance authority, host artifact measurement, deployment identity,
  certificate mapping, authenticated clock, and effective evidence-ingest privileges.

## Next steps

1. Codex: complete source review/fix pass and reconcile this contract with existing S13 interfaces.
2. After in-scope coding closes, `functional-test-reviewer` and `e2e-runner` implement and run the
   mapped cases in `S13-VALIDATOR-BUILD-ATTESTATION-01` using disposable synthetic roots only.
3. Fresh security/Python/database reviews inspect the exact final source hashes and test evidence.
4. Keep production evidence registration unavailable until the operator-authorized external trust
   and deployment sources are present and independently qualified.
