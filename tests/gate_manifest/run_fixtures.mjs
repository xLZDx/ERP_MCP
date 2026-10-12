// Static-fixture runner for scripts/validate_gate_manifest.mjs.
// Each fixtures/*.json is a manifest plus a "_fixture" block: {expect: accept|reject|probe, match, desc, lines?, signers?}.
//  - accept: validator must exit 0 and stdout must match `match`.
//  - reject: validator must exit 1 and stderr must match `match` (a regex tested per stderr line). If `lines` is set,
//            stderr must have exactly that many lines, so the fixture is proven to violate only the targeted rule.
//  - probe : report-only observation of validator behavior (never fails the run).
// G4 waiver signatures cannot be static: the runner generates TEST Ed25519 keypairs in memory (the private keys are never
// written to disk), writes a temp signers file holding only the public key, and materializes "@SIGN*" placeholders:
//   @SIGN                 valid signature over the canonical waiver message
//   @SIGN_OTHER_BASELINE  valid signature over a different baseline
//   @SIGN_OTHER_EVIDENCE  valid signature over a different evidence hash
//   @SIGN_TAMPERED        valid signature with one byte flipped
//   @SIGN_IMPOSTOR       signature by a different (unregistered) private key
// `_fixture.signers`: "empty" (no registered signer) or "badrole" (signer registered with a non-operator role).
// Evidence files come from evidence_files.json and are written into a temp --root, together with ../outside.txt.
// Usage: node tests/gate_manifest/run_fixtures.mjs
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { generateKeyPairSync, sign } from "node:crypto";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const validator = process.env.GATE_VALIDATOR ? resolve(process.env.GATE_VALIDATOR) : resolve(here, "..", "..", "scripts", "validate_gate_manifest.mjs");
const fixtureDir = join(here, "fixtures");

const base = mkdtempSync(join(tmpdir(), "gate-manifest-"));
const root = join(base, "root");
mkdirSync(join(root, "evidence"), { recursive: true });
const evidenceFiles = JSON.parse(readFileSync(join(here, "evidence_files.json"), "utf8"));
for (const [p, content] of Object.entries(evidenceFiles)) writeFileSync(join(root, p), content);
writeFileSync(join(base, "outside.txt"), evidenceFiles["evidence/ok.txt"]);

const SIGNER_ID = "op-test";
const keys = generateKeyPairSync("ed25519");
const impostor = generateKeyPairSync("ed25519");
const pem = keys.publicKey.export({ type: "spki", format: "pem" });
const signersFiles = {
  registered: { schema: 1, signers: [{ id: SIGNER_ID, role: "operator", public_key_pem: pem }] },
  empty: { schema: 1, signers: [] },
  badrole: { schema: 1, signers: [{ id: SIGNER_ID, role: "reader", public_key_pem: pem }] },
};
const signersPath = {};
for (const [k, v] of Object.entries(signersFiles)) { signersPath[k] = join(base, `signers_${k}.json`); writeFileSync(signersPath[k], JSON.stringify(v)); }

const msg = (baseline, sha) => `G4-WAIVER|baseline=${baseline}|drive_intake_enabled=false|evidence_sha256=${sha}`;
function materialize(m) {
  const g4 = (m.gates ?? []).find((g) => g.id === "G4");
  const w = g4 && g4.waiver;
  if (!w || typeof w.signature !== "string" || !w.signature.startsWith("@SIGN")) return m;
  const sha = (w.evidence && w.evidence.sha256) ?? "";
  const sig = (text, key = keys.privateKey) => sign(null, Buffer.from(text, "utf8"), key);
  const v = w.signature;
  let out;
  if (v === "@SIGN") out = sig(msg(m.baseline, sha));
  else if (v === "@SIGN_OTHER_BASELINE") out = sig(msg("some/other/BASELINE.md revision 9", sha));
  else if (v === "@SIGN_OTHER_EVIDENCE") out = sig(msg(m.baseline, "a".repeat(64)));
  else if (v === "@SIGN_TAMPERED") { out = sig(msg(m.baseline, sha)); out[out.length - 1] ^= 0x01; }
  else if (v === "@SIGN_IMPOSTOR") out = sig(msg(m.baseline, sha), impostor.privateKey);
  else throw new Error("unknown signature directive " + v);
  w.signature = out.toString("base64");
  return m;
}

let failed = 0;
const files = readdirSync(fixtureDir).filter((f) => f.endsWith(".json")).sort();
let probes = 0;
for (const f of files) {
  const fx = join(fixtureDir, f);
  const raw = JSON.parse(readFileSync(fx, "utf8"));
  const meta = raw._fixture;
  const manifestPath = join(base, "m_" + f);
  writeFileSync(manifestPath, JSON.stringify(materialize(raw)));
  const sp = signersPath[meta.signers ?? "registered"];
  const r = spawnSync(process.execPath, [validator, manifestPath, "--root", root, "--signers", sp], { encoding: "utf8" });
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
    probes++;
    why = `PROBE exit=${r.status} ${r.status === 0 ? out : stderrLines.join(" | ")}`;
  }
  if (!ok) failed++;
  console.log(`${meta.expect === "probe" ? "PROBE" : ok ? "PASS " : "FAIL "} ${f} [${meta.expect}] ${meta.desc}\n      -> ${why}`);
}
rmSync(base, { recursive: true, force: true });
const asserted = files.length - probes;
console.log(`\nSuite: ${failed ? "FAIL" : "PASS"} (${asserted - failed}/${asserted} asserted fixtures passed, ${probes} probes)`);
process.exit(failed ? 1 : 0);
