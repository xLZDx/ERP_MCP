# Change Record 304 — reduce bounded trust-payload preflight overhead

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP WP5 trust-snapshot decoder.
- Acceptance: `WP5-JSON-DECODER-01`.
- State: implemented in the working tree; the updated decoder suite and five performance samples passed. The complete WP5 acceptance coverage audit is still in progress, so this is not story closure.

## Change and reason

The preflight now caches the input length instead of invoking `len(payload)` during every scanner
iteration. The bounded value/string helpers cache their lengths as well. ASCII payloads use the
exact identity between character count and UTF-8 byte count after a C-level `isascii()` scan;
non-ASCII text is counted with strict UTF-8 encoding in 65,536-character chunks. This keeps
temporary encoding memory bounded, preserves the exact 8 MiB byte boundary, and rejects raw lone
surrogates before JSON parsing.

The change follows a cProfile observation on a prebuilt, exactly 8 MiB ASCII trust payload. The
reported earlier profile contained 8,388,641 calls to `len`; the later profile of the working-tree
scanner contained 47. The earlier untracked source hash was not captured, so this is a measured
profile difference with unresolved source identity, not a fully reproducible attribution claim.

## Verification evidence

At Git HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`, the E2E test role ran
`uv run pytest -q -s tests/phase2/test_wp5_json_decoder_contracts.py`: exit 0, 14 tests and 24
subtests passed. It then ran five separate invocations of
`uv run pytest -q -s tests/phase2/test_wp5_json_decoder_contracts.py -k maximum_payload_decode_duration_and_peak_allocation`;
each exited 0 with 1 passed and 13 deselected.

| Workload | Earlier five-run observations (source hash unavailable) | Updated five-run observations (working-tree hashes recorded) |
|---|---|---|
| Trust snapshot, 8 MiB | Median 2.454574 s; range 2.102123–2.803708 s; traced peak 4,103–4,161 B | Median 1.414163 s; range 1.183709–1.873672 s; traced peak 4,161 B each run |
| Evidence envelope, 2 MiB | Median 0.269218 s; range 0.233783–0.348919 s; traced peak 9,444,614 B each run | Median 0.498974 s; range 0.369962–0.538454 s; traced peak 9,444,614 B each run |

Updated trust-snapshot samples are below the acceptance's 3-second source budget, and their
median is lower than the earlier observation. The evidence-envelope path was not changed in this
work and its observed timing range shifted upward; the difference is not attributed to this code
and needs a stable remeasurement after the acceptance-test additions finish. These five local
samples are not an SLO or platform-wide percentile.

The updated files' exact SHA-256 values and commands are in
`docs/phase2/artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md`. A separate cProfile run on the
exact 8,388,608-byte ASCII trust payload completed in 1.143 s with 259 calls; `_check_json_text_limits`
accounted for 1.126 s and `json.loads` for 0.017 s. A bounded source reviewer found no correctness
issue in byte counting, strict surrogate handling, temporary allocation, or scanner termination.
This source review and offline Python run do not prove the production adapter, S13 SQL, effective
grants, or operational COM behavior.

## Affected paths

- `src/erp_mcp_private_writer/postgres_evidence_trust.py` — bounded exact byte-count fast path and cached scan lengths.
- `tests/phase2/test_wp5_json_decoder_contracts.py` — exact multibyte byte-limit and raw-surrogate cases, authored by the functional-test-reviewer.
- `docs/phase2/artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md` — exact commands, results, hashes and limitations.

## Expanded acceptance run — 2026-10-26

After the functional-test-reviewer added the full schema, malformed-input, structural-limit, and
zero-trust-lookup matrix, the authorized functional-test-reviewer ran:

```text
uv run pytest -q tests/phase2/test_wp5_json_decoder_contracts.py
```

Result: exit 0; 20 tests and 54 subtests passed in 35.07 seconds. The first expanded run had 19
tests pass and one fixture failure because the test supplied a non-numeric emoji revision where
the production contract requires canonical positive decimal text. The test role corrected only
that fixture to place the non-BMP scalar in a valid signer service ID; the exact command then
passed. No production source was changed by that correction.

The run was on the dirty working tree at Git revision
`3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; the untracked/modified source contents are identified
by their hashes, not by Git HEAD alone:

- `test_wp5_json_decoder_contracts.py`: `398D188242DAD3A8E8909A4D6628507AF47E55F3B4AACFEA26C9AC3ADFE72CA1`
- `postgres_evidence_trust.py`: `E13EF0D8C99C3E67F4ED87C1A6AAD2869318B15EC38E81F0E71BA79CA35E9C18`
- `production_evidence_verifier.py`: `9E513570862BC118135005D294287DEC7FC927D62BA4368C48AA6A19221717E5`
- `json_preflight.py`: `C88EA5922637F6DFBC45C4F55746AF71FFB7A85A929DDFA4A9383E49F775E774`
- `evidence.py`: `C20D7496B54777573EF7024CB26E13BA5D4FFC92BF7CD33573A834052C61FDC9`

This run closes only the mapped offline decoder acceptance file. It does not close WP5 signer
provisioning, installed S13 trust/ACL state, SQL qualification, real-lane evidence, or the full
WP5 release gate.
