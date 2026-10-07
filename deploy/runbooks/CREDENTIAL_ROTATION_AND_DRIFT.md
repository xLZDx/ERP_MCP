# Credential rotation and drift remediation

Rotation is a two-person change. Create the replacement secret, validate it with a metadata-only
health call, switch the secret reference, and revoke the old secret. Never print configuration or
connection strings in logs.

For metadata/schema drift: freeze business tools, capture a new live metadata fingerprint, mark
profiles `STALE`, rerun safe capability probes, and require semantic-profile validation before
reenabling operations. Unknown names must not be guessed.
