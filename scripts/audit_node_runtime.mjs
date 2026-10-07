// Audit the exact installed sidecar dependency inventory, not unused upstream MCP/CLI packages.
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

const root = process.argv[2] ?? '/app/node_modules';
const inventory = new Map();
for (const entry of await readdir(join(root, '.pnpm'), { withFileTypes: true })) {
  if (!entry.isDirectory() || entry.name === 'node_modules') continue;
  const modules = join(root, '.pnpm', entry.name, 'node_modules');
  for (const name of await readdir(modules)) {
    if (name.startsWith('.')) continue;
    const names = name.startsWith('@')
      ? (await readdir(join(modules, name))).map(n => `${name}/${n}`)
      : [name];
    for (const packageName of names) {
      const manifest = JSON.parse(await readFile(join(modules, packageName, 'package.json'), 'utf8'));
      if (!manifest.name || !manifest.version) throw new Error('Invalid installed manifest');
      const versions = inventory.get(manifest.name) ?? new Set();
      versions.add(manifest.version);
      inventory.set(manifest.name, versions);
    }
  }
}
if (!inventory.has('fast-xml-parser')) throw new Error('Missing expected runtime dependency');
// Include direct runtime packages copied alongside the pnpm store (e.g. the pinned dispatcher).
for (const entry of await readdir(root, { withFileTypes: true })) {
  if (entry.name.startsWith('.') || (!entry.isDirectory() && !entry.isSymbolicLink())) continue;
  const names = entry.name.startsWith('@')
    ? (await readdir(join(root, entry.name))).map(name => `${entry.name}/${name}`)
    : [entry.name];
  for (const packageName of names) {
    const manifest = JSON.parse(await readFile(join(root, packageName, 'package.json'), 'utf8'));
    if (!manifest.name || !manifest.version) throw new Error('Invalid direct installed manifest');
    const versions = inventory.get(manifest.name) ?? new Set();
    versions.add(manifest.version);
    inventory.set(manifest.name, versions);
  }
}
if (!inventory.has('undici') || !inventory.get('undici').has('8.10.2')) {
  throw new Error('Missing pinned runtime dispatcher');
}
const packages = Object.fromEntries([...inventory].sort().map(([name, versions]) =>
  [name, [...versions].sort()]));
// The source-pinned workspace client is verified with upstream parity tests, not npm resolution.
const registryPackages = Object.fromEntries(Object.entries(packages).filter(([name]) =>
  !name.startsWith('@1c-odata/')));
const response = await fetch('https://registry.npmjs.org/-/npm/v1/security/advisories/bulk', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(registryPackages),
  signal: AbortSignal.timeout(30000),
});
if (!response.ok) throw new Error(`Registry audit unavailable: ${response.status}`);
const advisories = await response.json();
if (!advisories || typeof advisories !== 'object' || Array.isArray(advisories)) {
  throw new Error('Invalid registry advisory response');
}
let count = 0;
for (const [name, items] of Object.entries(advisories)) {
  if (!(name in registryPackages) || !Array.isArray(items)) throw new Error('Invalid advisories');
  count += items.length;
}
console.log(JSON.stringify({ upstream_sha: 'cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5',
  packages, advisories, vulnerability_count: count }, null, 2));
if (count) process.exitCode = 1;
