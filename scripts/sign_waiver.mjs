// Operator tool: sign a G4 waiver. Usage: node scripts/sign_waiver.mjs <private_key.pem> <evidence_file> <baseline>
// Prints the evidence sha256 and the base64 signature to put in the manifest waiver record. Never commit the private key.
import { readFileSync } from "node:fs";
import { createHash, createPrivateKey, sign } from "node:crypto";

const [keyPath, evidencePath, baseline] = process.argv.slice(2);
if (!keyPath || !evidencePath || !baseline) { console.error("usage: sign_waiver.mjs <private_key.pem> <evidence_file> <baseline>"); process.exit(2); }
const sha = createHash("sha256").update(readFileSync(evidencePath)).digest("hex");
const msg = `G4-WAIVER|baseline=${baseline}|drive_intake_enabled=false|evidence_sha256=${sha}`;
const signature = sign(null, Buffer.from(msg, "utf8"), createPrivateKey(readFileSync(keyPath, "utf8"))).toString("base64");
console.log(JSON.stringify({ evidence_sha256: sha, signature }, null, 2));
