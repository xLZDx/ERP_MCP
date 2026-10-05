# Snapshot contract

Real-1C integration tests start from a known snapshot.

A snapshot evidence record should contain:

- snapshot ID;
- 1C platform version;
- configuration name/version;
- extensions list/fingerprint;
- seed version;
- creation timestamp;
- database mode (file/server);
- checksum/reference to the restore artifact;
- expected scenario-set version.

Snapshot restore is an operator/test-environment action. The production MCP process has no
restore/delete capability.

Never commit licensed 1C binaries, client data, credentials, or a real `1Cv8.CD` file to this
public repository.
