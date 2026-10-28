"""S15 verification and reconciliation (verifier, oracle, A<->B, ledger<->1C, negative controls).

Everything here is machine verified, not accountant attested. The package is not wired into any
gateway, never writes to 1C, and the oracle and verifier modules import nothing from the writer,
preview or normalization code.
"""
