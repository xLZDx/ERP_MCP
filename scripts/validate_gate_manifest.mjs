// Closure validator for governance/GATE_MANIFEST.json (plan section 9). Exits 1 on any violation.
// Usage: node scripts/validate_gate_manifest.mjs [manifest.json] [--root <dir>]
// Evidence references are {path, sha256}; the validator recomputes the digest, so stale evidence is rejected.
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve, relative, isAbsolute } from "node:path";

const args = process.argv.slice(2);
const rootIdx = args.indexOf("--root");
const root = rootIdx >= 0 ? resolve(args[rootIdx + 1]) : process.cwd();
const positional = args.filter((a, i) => !a.startsWith("--") && (rootIdx < 0 || i !== rootIdx + 1));
const path = positional[0] ?? "governance/GATE_MANIFEST.json";
const m = JSON.parse(readFileSync(path, "utf8"));

const GATE_STATUS = new Set(["NOT_PASSED", "PASSED", "NOT_APPLICABLE"]);
const NODE_STATE = new Set(["NOT_STARTED", "IN_PROGRESS", "DONE"]);
const ENG = new Set(["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "NOT_APPLICABLE"]);
const EXT = new Set(["OPEN", "SATISFIED", "NOT_REQUIRED"]);
const AUTH = new Set(["NONE", "TEST_LANE_ONLY", "PRODUCTION_CANARY_SIGNED", "PRODUCTION_GO"]);
const WAIVER_APPROVERS = new Set(["GPT-PM", "operator"]);
const errors = [];
const err = (s) => errors.push(s);

function evidenceOk(label, ev) {
  if (!ev || typeof ev.path !== "string" || typeof ev.sha256 !== "string") {
    err(`${label}: evidence must be {path, sha256}`);
    return false;
  }
  const file = resolve(root, ev.path);
  const rel = relative(root, file);
  if (rel.startsWith("..") || isAbsolute(rel)) { err(`${label}: evidence path escapes the root: ${ev.path}`); return false; }
  if (!existsSync(file)) { err(`${label}: evidence file missing: ${ev.path}`); return false; }
  const actual = createHash("sha256").update(readFileSync(file)).digest("hex");
  if (actual !== ev.sha256) { err(`${label}: stale evidence (sha256 differs): ${ev.path}`); return false; }
  return true;
}

const seen = new Set();
for (const x of [...(m.gates ?? []), ...(m.nodes ?? [])]) {
  if (seen.has(x.id)) err(`${x.id}: duplicate id`);
  seen.add(x.id);
}
const gates = new Map((m.gates ?? []).map((g) => [g.id, g]));
const nodes = new Map((m.nodes ?? []).map((n) => [n.id, n]));
for (const id of nodes.keys()) if (gates.has(id)) err(`${id}: defined as both gate and node`);
const all = new Map([...gates, ...nodes]);

if (![true, false].includes(m.drive_intake_enabled)) err("drive_intake_enabled must be an explicit true or false");

for (const g of gates.values()) {
  if (!GATE_STATUS.has(g.gate_status)) err(`${g.id}: unknown gate_status ${g.gate_status}`);
  if (!ENG.has(g.engineering_status)) err(`${g.id}: unknown engineering_status ${g.engineering_status}`);
  if (!EXT.has(g.external_evidence_status)) err(`${g.id}: unknown external_evidence_status ${g.external_evidence_status}`);
  if (!AUTH.has(g.production_authorization)) err(`${g.id}: unknown production_authorization ${g.production_authorization}`);
  if (g.gate_status === "PASSED") {
    evidenceOk(`${g.id} evidence`, g.evidence);
    if (g.engineering_status !== "COMPLETE") err(`${g.id}: PASSED requires engineering_status COMPLETE`);
    if (g.external_evidence_status === "OPEN") err(`${g.id}: PASSED while external evidence is OPEN`);
  }
  // Production authorizations exist only on the canary gate (signed canary) and the release gate (PRODUCTION_GO).
  const pa = g.production_authorization;
  if (pa === "PRODUCTION_CANARY_SIGNED" && g.id !== "G6") err(`${g.id}: ${pa} is valid only on G6`);
  if (pa === "PRODUCTION_GO" && g.id !== "G7") err(`${g.id}: ${pa} is valid only on G7`);
  if (pa === "PRODUCTION_CANARY_SIGNED" || pa === "PRODUCTION_GO") g._needsClosedPredecessors = true;
  if ((g.implies ?? []).length > 0) err(`${g.id}: a gate must not imply another gate`);
  for (const p of [...(g.predecessors ?? []), ...(g.conditional_predecessors ?? [])]) {
    if (!all.has(p)) err(`${g.id}: unknown predecessor ${p}`);
  }
}
for (const n of nodes.values()) {
  if (!NODE_STATE.has(n.state)) err(`${n.id}: unknown node state ${n.state}`);
  if (n.state === "DONE") evidenceOk(`${n.id} evidence`, n.evidence);
  for (const p of n.predecessors ?? []) if (!all.has(p)) err(`${n.id}: unknown predecessor ${p}`);
}

// G4 applicability is explicit; a waiver is a signed record bound to evidence, not a Boolean.
const g4 = gates.get("G4");
if (g4) {
  if (m.drive_intake_enabled === false) {
    if (g4.gate_status === "NOT_APPLICABLE") {
      const w = g4.waiver;
      if (!w || !WAIVER_APPROVERS.has(w.approved_by) || !w.evidence) err("G4: NOT_APPLICABLE requires a waiver with approved_by (GPT-PM or operator) and evidence");
      else evidenceOk("G4 waiver evidence", w.evidence);
    } else if (g4.gate_status === "PASSED") err("G4 cannot be PASSED while drive intake is disabled");
  } else if (g4.gate_status === "NOT_APPLICABLE") {
    err("G4 is NOT_APPLICABLE while drive intake is enabled");
  }
}
const g4Satisfied = () => g4 && (g4.gate_status === "PASSED" || (m.drive_intake_enabled === false && g4.gate_status === "NOT_APPLICABLE" && g4.waiver && WAIVER_APPROVERS.has(g4.waiver.approved_by)));

const closed = (id) => {
  const x = all.get(id);
  if (!x) return false;
  return gates.has(id) ? (x.gate_status === "PASSED" || (id === "G4" && g4Satisfied())) : x.state === "DONE";
};

// A gate may be PASSED (and a node DONE) only when every predecessor is closed.
for (const x of all.values()) {
  const isGate = gates.has(x.id);
  const complete = isGate ? x.gate_status === "PASSED" : x.state === "DONE";
  if (!complete) continue;
  for (const p of x.predecessors ?? []) if (!closed(p)) err(`${x.id}: closed while predecessor ${p} is not`);
  for (const p of x.conditional_predecessors ?? []) {
    if (p === "G4" && m.drive_intake_enabled === false && !g4Satisfied() && g4?.gate_status !== "PASSED") {
      err(`${x.id}: closed without a valid G4 waiver`);
    } else if (p === "G4" && m.drive_intake_enabled !== false && !closed("G4")) {
      err(`${x.id}: closed while drive intake is enabled and G4 is not PASSED`);
    }
  }
}

// A production authorization may exist only when every predecessor of its gate is closed.
for (const g of gates.values()) {
  if (!g._needsClosedPredecessors) continue;
  for (const p of g.predecessors ?? []) if (!closed(p)) err(`${g.id}: ${g.production_authorization} while predecessor ${p} is not closed`);
  if (g.id === "G7" && (g.conditional_predecessors ?? []).includes("G4") && !closed("G4")) {
    err(m.drive_intake_enabled === false
      ? `G7: PRODUCTION_GO without a valid G4 waiver`
      : `G7: PRODUCTION_GO while drive intake is enabled and G4 is not PASSED`);
  }
}

// Acyclic over all declared predecessors.
const state = new Map();
function visit(id, stack) {
  if (!all.has(id)) return;
  if (state.get(id) === 2) return;
  if (state.get(id) === 1) { err(`cycle: ${[...stack, id].join(" -> ")}`); return; }
  state.set(id, 1);
  const x = all.get(id);
  for (const p of [...(x.predecessors ?? []), ...(x.conditional_predecessors ?? [])]) visit(p, [...stack, id]);
  state.set(id, 2);
}
for (const id of all.keys()) visit(id, []);

if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`gate manifest ok: ${gates.size} gates, ${nodes.size} nodes`);
