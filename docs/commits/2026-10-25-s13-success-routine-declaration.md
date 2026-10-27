# S13 success-routine declaration correction

Removed one duplicate local declaration from the candidate PL/pgSQL success-terminal routine.
The duplicate made the function fail to compile. No transition predicates, lock order, authorization,
or business behavior changed. The candidate remains unparsed, uninstalled, ungranted, and unqualified.

Verification: source inspection only; no parser, database operation, tests/checks, stage, commit, or
push ran. See CHANGE_RECORD_253.md for provenance and the next gate.
