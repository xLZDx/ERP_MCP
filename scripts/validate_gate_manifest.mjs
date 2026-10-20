// Closure validator for governance/GATE_MANIFEST.json (plan section 9). Exits 1 on any violation.
// Usage: node scripts/validate_gate_manifest.mjs [manifest.json] [--root <dir>]
// Evidence references are {path, sha256}; the validator recomputes the digest, so stale evidence is rejected.
import { readFileSync, existsSync } from "node:fs";
import { createHash, createPublicKey, verify } from "node:crypto";
import { resolve, relative, isAbsolute } from "node:path";

const args = process.argv.slice(2);
const rootIdx = args.indexOf("--root");
const root = rootIdx >= 0 ? resolve(args[rootIdx + 1]) : process.cwd();
const signersIdx = args.indexOf("--signers");
const positional = args.filter((a, i) => !a.startsWith("--") && (rootIdx < 0 || i !== rootIdx + 1) && (signersIdx < 0 || i !== signersIdx + 1));
const signersPath = signersIdx >= 0 ? resolve(args[signersIdx + 1]) : resolve("governance/WAIVER_SIGNERS.json");
const path = positional[0] ?? "governance/GATE_MANIFEST.json";
const m = JSON.parse(readFileSync(path, "utf8"));

// Canonical mandatory graph for manifest schema 2 (plan section 9 and section 8 sprint dependencies).
// It lives in the validator on purpose: the manifest is the mutable status record and must not be its own
// source of truth for which gates, nodes and edges are mandatory. A legitimate graph amendment is a reviewed
// change to this constant together with a new schema number, never an edit of the manifest alone.
const SCHEMA = 2;
const CANONICAL_GATES = {
  G0: [], G1: ["G0"], G2: ["G0"], G3: ["G2"], G4: ["G0"], G5: ["S16", "S17"], "G6-pre": ["G1", "G8"],
  G6: ["G3", "G5", "G6-pre", "G8"], G7: ["G0", "G1", "G2", "G3", "G5", "G6", "G8"],
  G8: ["G0", "CT14", "S12", "S13", "S14", "S15", "S16", "S17", "S18"],
};
const CANONICAL_CONDITIONAL = { G7: ["G4"] };
const CANONICAL_NODES = {
  CT14: [], S11: [], S12: ["S11"], S13: ["S12"], S14: ["S12", "CT14"], S15: ["S13", "S14"],
  S16: ["S12", "S15"], S17: ["S16"], S18: ["S13", "S14", "S15", "S16"], S19: ["S17", "S18"],
};
const sameSet = (a, b) => a.length === b.length && [...a].sort().every((x, i) => x === [...b].sort()[i]);

const GATE_STATUS = new Set(["NOT_PASSED", "PASSED", "NOT_APPLICABLE"]);
const NODE_STATE = new Set(["NOT_STARTED", "IN_PROGRESS", "DONE"]);
const ENG = new Set(["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "NOT_APPLICABLE"]);
const EXT = new Set(["OPEN", "SATISFIED", "NOT_REQUIRED"]);
const AUTH = new Set(["NONE", "TEST_LANE_ONLY", "PRODUCTION_CANARY_SIGNED", "PRODUCTION_GO"]);
// Waiver approver is the operator only; the signature check below is the authority.
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
if (m.schema !== SCHEMA) err(`unsupported manifest schema ${m.schema}; this validator enforces schema ${SCHEMA}`);
{
  const gotGates = (m.gates ?? []).map((g) => g.id);
  const gotNodes = (m.nodes ?? []).map((n) => n.id);
  for (const id of Object.keys(CANONICAL_GATES)) if (!gotGates.includes(id)) err(`mandatory gate missing: ${id}`);
  for (const id of Object.keys(CANONICAL_NODES)) if (!gotNodes.includes(id)) err(`mandatory node missing: ${id}`);
  for (const id of gotGates) if (!(id in CANONICAL_GATES)) err(`unexpected gate not in the canonical graph: ${id}`);
  for (const id of gotNodes) if (!(id in CANONICAL_NODES)) err(`unexpected node not in the canonical graph: ${id}`);
  for (const g of m.gates ?? []) {
    if (!(g.id in CANONICAL_GATES)) continue;
    if (!sameSet(g.predecessors ?? [], CANONICAL_GATES[g.id])) err(`${g.id}: predecessors differ from the canonical graph`);
    if (!sameSet(g.conditional_predecessors ?? [], CANONICAL_CONDITIONAL[g.id] ?? [])) err(`${g.id}: conditional predecessors differ from the canonical graph`);
  }
  for (const n of m.nodes ?? []) {
    if (!(n.id in CANONICAL_NODES)) continue;
    if (!sameSet(n.predecessors ?? [], CANONICAL_NODES[n.id])) err(`${n.id}: predecessors differ from the canonical graph`);
  }
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
      // A waiver is authorized only by a detached Ed25519 signature of a registered operator key. A file that merely
      // quotes an approval is not authority. With no registered signer no waiver can be valid (fail closed).
      const w = g4.waiver;
      const WAIVER_MSG = (sha) => `G4-WAIVER|baseline=${m.baseline}|drive_intake_enabled=false|evidence_sha256=${sha}`;
      if (!w || w.approved_by !== "operator" || !w.evidence || typeof w.signer_id !== "string" || typeof w.signature !== "string") {
        err("G4: NOT_APPLICABLE requires an operator waiver with signer_id, signature and evidence");
      } else if (evidenceOk("G4 waiver evidence", w.evidence)) {
        let signers = [];
        try { signers = JSON.parse(readFileSync(signersPath, "utf8")).signers ?? []; } catch { signers = []; }
        const signer = signers.find((x) => x.id === w.signer_id && x.role === "operator");
        if (!signer) err(`G4 waiver: signer ${w.signer_id} is not a registered operator signer`);
        else {
          let ok = false;
          try {
            ok = verify(null, Buffer.from(WAIVER_MSG(w.evidence.sha256), "utf8"), createPublicKey(signer.public_key_pem), Buffer.from(w.signature, "base64"));
          } catch { ok = false; }
          if (!ok) err("G4 waiver: signature does not verify against the registered operator key");
        }
      }
    } else if (g4.gate_status === "PASSED") err("G4 cannot be PASSED while drive intake is disabled");
  } else if (g4.gate_status === "NOT_APPLICABLE") {
    err("G4 is NOT_APPLICABLE while drive intake is enabled");
  }
}
const g4Satisfied = () => g4 && (g4.gate_status === "PASSED" || (m.drive_intake_enabled === false && g4.gate_status === "NOT_APPLICABLE" && g4.waiver && g4.waiver.approved_by === "operator" && !errors.some((e) => e.startsWith("G4"))));

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
