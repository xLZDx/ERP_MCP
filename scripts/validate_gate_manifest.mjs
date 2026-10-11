// Closure validator for governance/GATE_MANIFEST.json (plan section 9). Exits 1 on any violation.
import { readFileSync } from "node:fs";

const path = process.argv[2] ?? "governance/GATE_MANIFEST.json";
const m = JSON.parse(readFileSync(path, "utf8"));
const errors = [];
const gates = new Map(m.gates.map((g) => [g.id, g]));
const known = new Set([...gates.keys(), ...(m.non_gate_nodes ?? [])]);
const FIELDS = ["engineering_status", "gate_status", "external_evidence_status", "production_authorization"];

for (const g of m.gates) {
  for (const f of FIELDS) if (typeof g[f] !== "string" || g[f] === "") errors.push(`${g.id}: missing ${f}`);
  for (const p of g.predecessors) if (!known.has(p)) errors.push(`${g.id}: unknown predecessor ${p}`);
  if (g.gate_status === "PASSED" && !g.evidence) errors.push(`${g.id}: PASSED without an evidence reference`);
  if (g.id === "G4" && g.gate_status !== "PASSED" && !(g.waiver && g.waiver.approved === true)) {
    if (g.gate_status === "NOT_APPLICABLE") errors.push("G4: NOT_APPLICABLE needs an approved waiver");
  }
  if (g.id === "G8" && (g.implies ?? []).length > 0) errors.push("G8 must not imply any other gate");
  if (g.gate_status === "PASSED" && g.production_authorization !== "NONE" && !g.evidence) errors.push(`${g.id}: authorization without evidence`);
}

const state = new Map();
function visit(id, stack) {
  if (!gates.has(id)) return;
  if (state.get(id) === 2) return;
  if (state.get(id) === 1) { errors.push(`cycle: ${[...stack, id].join(" -> ")}`); return; }
  state.set(id, 1);
  for (const p of gates.get(id).predecessors) visit(p, [...stack, id]);
  state.set(id, 2);
}
for (const id of gates.keys()) visit(id, []);

for (const g of m.gates) {
  if (g.gate_status !== "PASSED") continue;
  for (const p of g.predecessors) {
    const pg = gates.get(p);
    if (pg && pg.gate_status !== "PASSED" && !(pg.id === "G4" && pg.waiver && pg.waiver.approved === true)) {
      errors.push(`${g.id}: PASSED while predecessor ${p} is ${pg.gate_status}`);
    }
  }
}

if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`gate manifest ok: ${m.gates.length} gates`);
