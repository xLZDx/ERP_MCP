# Third-party notices

The sidecar TCP/DNS dispatcher directly reuses Undici 8.10.2 (MIT), locked with npm artifact
integrity in `adapters/odata-sidecar/package-lock.json`. Its original LICENSE is included in the
runtime package. Copyright (c) Matteo Collina and Undici contributors. This runtime dependency is
separate from the older dev-only dispatcher in the unmodified pinned 1C upstream. The full
installed runtime inventory, including direct packages, is audited and scanned in CI.

The runtime integrations remain original wrapper code; selected **candidate preset data** is
adapted from `theYahia/WWmcp/servers/aprovodka/src/presets/` at pinned SHA
`7b62c90e1fe74324605dc28d76f195200bb97252`. Entity names and upstream confidence labels are
retained with repository/SHA/path attribution and are always marked `CANDIDATE_ONLY` for ERP_MCP;
they are not source evidence and do not enable operations.

The adapted preset data is licensed under MIT:

```text
MIT License

Copyright (c) 2026 theYahia

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Other selective intake is governed by `vendor/UPSTREAMS.md`. When more code/data is imported, its
copyright and license notice must also be retained.

GPL-3.0 project `ROCTUP/1c-mcp-toolkit` is reference-only for this repository unless a later
explicit architecture/license decision isolates it as a separate service.
