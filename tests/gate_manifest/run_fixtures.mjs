// Static-fixture runner for scripts/validate_gate_manifest.mjs.
// Each fixtures/*.json is a manifest plus a "_fixture" block: {expect: accept|reject|probe, match, desc, lines?}.
//  - accept: validator must exit 0 and stdout must match `match`.
//  - reject: validator must exit 1 and stderr must match `match` (a regex tested against the whole stderr;
//            "^...$" patterns are tested per line). If `lines` is set, stderr must have exactly that many lines,
//            so the fixture is proven to violate only the targeted rule.
//  - probe : report-only observation of validator behavior (never fails the run).
// Evidence files are materialized in a temp --root: evidence/ok.txt (digest used by fixtures) and ../outside.txt.
// Usage: node tests/gate_manifest/run_fixtures.mjs
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const validator = resolve(here, "..", "..", "scripts", "validate_gate_manifest.mjs");
const fixtureDir = join(here, "fixtures");
const EVIDENCE = "evidence-fixture-v1\n";

const base = mkdtempSync(join(tmpdir(), "gate-manifest-"));
const root = join(base, "root");
mkdirSync(join(root, "evidence"), { recursive: true });
const evidenceFiles = JSON.parse(readFileSync(join(here, "evidence_files.json"), "utf8"));
for (const [p, content] of Object.entries(evidenceFiles)) writeFileSync(join(root, p), content);
writeFileSync(join(base, "outside.txt"), EVIDENCE);

let failed = 0;
const files = readdirSync(fixtureDir).filter((f) => f.endsWith(".json")).sort();
for (const f of files) {
  const fx = join(fixtureDir, f);
  const meta = JSON.parse(readFileSync(fx, "utf8"))._fixture;
  const r = spawnSync(process.execPath, [validator, fx, "--root", root], { encoding: "utf8" });
  const stderrLines = r.stderr.split(/\r?\n/).filter(Boolean);
  const out = r.stdout.trim();
  let ok = true;
  let why = "";
  if (meta.expect === "accept") {
    ok = r.status === 0 && new RegExp(meta.match).test(out);
    why = ok ? out : `exit=${r.status} stdout=${out} stderr=${stderrLines.join(" | ")}`;
  } else if (meta.expect === "reject") {
    const re = new RegExp(meta.match);
    const hit = stderrLines.find((l) => re.test(l));
    const countOk = meta.lines === undefined || stderrLines.length === meta.lines;
    ok = r.status === 1 && !!hit && countOk;
    why = ok ? hit : `exit=${r.status} lines=${stderrLines.length} (want ${meta.lines ?? "any"}) stderr=${stderrLines.join(" | ") || "<empty>"} stdout=${out}`;
  } else {
    why = `PROBE exit=${r.status} ${r.status === 0 ? out : stderrLines.join(" | ")}`;
  }
  if (!ok) failed++;
  console.log(`${meta.expect === "probe" ? "PROBE" : ok ? "PASS " : "FAIL "} ${f} [${meta.expect}] ${meta.desc}\n      -> ${why}`);
}
rmSync(base, { recursive: true, force: true });
const asserted = files.length - files.filter((f) => JSON.parse(readFileSync(join(fixtureDir, f), "utf8"))._fixture.expect === "probe").length;
console.log(`\nSuite: ${failed ? "FAIL" : "PASS"} (${asserted - failed}/${asserted} asserted fixtures passed, ${files.length - asserted} probes)`);
process.exit(failed ? 1 : 0);
