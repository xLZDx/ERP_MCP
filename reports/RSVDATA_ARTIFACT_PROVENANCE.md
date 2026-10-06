# RSV Data artifact provenance

Verified 2026-10-06 against the official GitHub v1.3.0 release API and downloaded asset.

- Upstream: `prepod2003/mcp-rsv-data`, MIT (pinned source license).
- Release: `v1.3.0`; release tag resolves to `bb98ba48087a0e6b2e8ad494092d773cc8867b4f`.
- Approved source reference remains `76fed8e6e16833fee1514969841b8d9a61c7c152`.
  The tag and approved source SHA are different; binary/source parity is not assumed.
- Asset: [MCP-RSV-Data.zip](https://github.com/prepod2003/mcp-rsv-data/releases/download/v1.3.0/MCP-RSV-Data.zip).
- Size: 5,340,161 bytes.
- Expected, GitHub digest and actual SHA-256 all match:
  `11de9a47cc4d0fc38d0e93e032b3cc69c5641774cb51fd529f930699f12c8a12`.
- Acquisition: `gh release download v1.3.0 --repo prepod2003/mcp-rsv-data --pattern MCP-RSV-Data.zip --dir D:/Temp/ERP_MCP/vendor/rsvdata/v1.3.0 --skip-existing`.
- Cache: `D:/Temp/ERP_MCP/vendor/rsvdata/v1.3.0`; binaries remain outside source control.
- User-supplied root archive independently has the same digest; it remains untouched/untracked.

| File | Bytes | SHA-256 |
|---|---:|---|
| RSVData.cfe | 50,105 | `01055749d44d4b44f941aadb4ea132e4054aa962d6f92019b252a374797f8d4d` |
| rsvdata-bridge.exe | 9,564,160 | `5c14b7db16e5dbf8cd20e2619255fe849edc75ac514bd6a21dedb1599710d728` |
| guide.html | 172,265 | `6908cc12e674841afdb30df933a532ea2f861610031b450dd9161116ac057719` |
| README.txt | 681 | `890b60a6db0a941685882d285239eb05c99586d328a269d4069ace1e4810a7a9` |

Archive contents confirm the built extension exists. Hash verification does not establish
read-only behavior, company isolation, reproducible binary builds, or production approval.
No executable has been launched and no extension has been installed in a customer base.

## Live-use update — 2026-10-06

The artifact was subsequently installed only in a disposable synthetic local 1C 8.3.27.2342 base,
exported to XML/BSL, and exercised through COM. This does not alter the provenance hashes above.
See `RSVDATA_EXTENSION_AUDIT.md` for the live security findings and production disposition.
