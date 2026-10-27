#!/usr/bin/env node
/**
 * Builds governance/DOCUMENT_REGISTRY.md: every Markdown document of this repository across ALL local
 * and remote branches (git-backed section), plus the repo-relative paths of ordinary untracked Markdown
 * files in the attached worktrees (local-only section).
 *
 * Provenance: adapted from the Personal_Decision_Command_Center generator
 *   scripts/tools/build-document-registry.mjs, commit ebf10414aaa8ef858a3df82652fb2050141adc98,
 *   blob b581feac23e4caea5c056a71dd0587cc7c58eef0 (read only; operator 2026-10-08 allows reusing code
 *   from any project). Changes: ignore-aware untracked discovery without directory walks, symlink and
 *   containment checks, path-only local section, registry excluded from its own inventory, topology-free
 *   aggregate output (sorted distinct title variants instead of per-branch counts), NUL-delimited git
 *   parsing, locale-independent ordering, governance/ created before writing.
 *
 * Inventory contract
 *   - Git-backed rows: one per distinct tracked path whose name ends in the case-sensitive ".md" over all
 *     refs/heads and refs/remotes (symbolic refs and tags excluded; tracked symlinks, mode 120000, excluded).
 *     Each ref is read through the object id captured at scan start. Title cell = sorted, de-duplicated
 *     first-heading variants of that path over all scanned refs, each JSON-quoted and joined by " / " (empty
 *     cell = no heading anywhere), so different variant sets can never render identically. Cyrillic is escaped
 *     only when that heading variant occurs exclusively on archive, rescue, or snapshot refs. The whole blob is
 *     searched for the first heading and a blob that cannot be read aborts generation. Exact scanned ref names
 *     and commit IDs are written as snapshot provenance; per-ref path counts, version counts and absolute
 *     locations are not written.
 *   - Output safety: the registry file and governance/ must be real (non-link) paths inside the repository.
 *   - Local-only rows: repo-relative paths of untracked, non-ignored ".md" files per worktree
 *     (git ls-files --others --exclude-standard). Symlinks/junctions and paths resolving outside their
 *     worktree are skipped; dependency/build directories are never read; headings are never published.
 *   - Excluded: the registry file itself.
 *   - Staleness: adding an alias ref that points at an existing tree does not change the inventory; adding
 *     or removing a distinct path or a distinct title variant does. A document removed from one branch
 *     stays while another scanned ref still contains it.
 *
 * Usage:  node scripts/build_document_registry.mjs [--check] [--exclude-local-only]
 * --check exits 1 when the committed registry differs from the inventory. The scanned ref list with commit
 * ids is printed to stdout for the decision-log record.
 * --exclude-local-only writes a Git-refs-only snapshot without enumerating attached worktree untracked files.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';

const REGISTRY_REL = 'governance/DOCUMENT_REGISTRY.md';
const NEVER_READ_DIRS = new Set(['.git', '.venv', 'venv', 'node_modules', 'var', 'build', 'dist', '__pycache__']);

const gitIn = (cwd, args) =>
  execFileSync('git', args, { cwd, maxBuffer: 512 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }).toString('utf8');

const REPO = resolve(gitIn(process.cwd(), ['rev-parse', '--show-toplevel']).trim());
const OUT = join(REPO, ...REGISTRY_REL.split('/'));
const git = (args) => gitIn(REPO, args);

const KINDS = [
  [/(^|\/)adr\/|ADR-/iu, 'ADR'],
  [/runbooks?\//iu, 'Runbook'],
  [/(^|\/)reports\//iu, 'Report'],
  [/(^|\/)docs\/phase2\/|PHASE_2/u, 'Phase 2 design'],
  [/TDD/u, 'TDD'],
  [/(plan|PLAN|roadmap|ROADMAP|MASTER)/u, 'Plan'],
  [/(design|DESIGN|architecture|ARCHITECTURE|THREAT|MODEL|CONTRACT)/u, 'Design'],
  [/(^|\/)\.claude\//u, 'Agent/skill'],
  [/(^|\/)(governance|core)\//u, 'Governance'],
];
const args = process.argv.slice(2);
const supportedArgs = new Set(['--check', '--exclude-local-only']);
const unsupportedArgs = args.filter((arg) => !supportedArgs.has(arg));
if (unsupportedArgs.length > 0) {
  throw new Error(`unsupported argument(s): ${unsupportedArgs.join(', ')}`);
}
const checkOnly = args.includes('--check');
const excludeLocalOnly = args.includes('--exclude-local-only');
const kindOf = (path) => KINDS.find(([re]) => re.test(path))?.[1] ?? 'Other';
const byCodePoint = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const esc = (text) =>
  text
    .replaceAll('|', '\\|')
    .replaceAll('\n', '\\n')
    .replaceAll('\r', '\\r')
    .replaceAll('\t', '\\t');
const escapeCyrillic = (text) =>
  text.replace(/\p{Script=Cyrillic}/gu, (character) => {
    const codePoint = character.codePointAt(0);
    if (codePoint <= 0xffff) return `\\u${codePoint.toString(16).toUpperCase().padStart(4, '0')}`;
    const adjusted = codePoint - 0x10000;
    const high = 0xd800 + (adjusted >> 10);
    const low = 0xdc00 + (adjusted & 0x3ff);
    return `\\u${high.toString(16).toUpperCase()}\\u${low.toString(16).toUpperCase()}`;
  });
const isHistoricalRef = (ref) => /(?:^|\/)(?:archive|rescue|snapshot)(?:\/|$)/iu.test(ref);
/** Unambiguous title cell; historical-only Cyrillic headings stay escaped, current headings remain readable. */
const titleCell = (variants) => {
  const all = [...variants.entries()].sort(([left], [right]) => byCodePoint(left, right));
  return all.length === 1 && all[0][0] === ''
    ? ''
    : all
        .map(([title, refsForTitle]) => {
          const quoted = esc(JSON.stringify(title));
          return [...refsForTitle].every(isHistoricalRef) ? escapeCyrillic(quoted) : quoted;
        })
        .join(' / ');
};

/** Refuse to read or write through links: the output file and its parent must be real paths inside the repository. */
const isLink = (path) => {
  try {
    return lstatSync(path).isSymbolicLink();
  } catch {
    return false;
  }
};
const assertOutputContained = () => {
  const realRepo = realpathSync(REPO);
  const dir = dirname(OUT);
  if (isLink(dir)) throw new Error('governance/ is a link; refusing to use it');
  if (existsSync(dir)) {
    const realDir = realpathSync(dir);
    if (realDir !== realRepo && !realDir.startsWith(realRepo + sep)) throw new Error('output directory escapes the repository');
  }
  if (isLink(OUT) || (existsSync(OUT) && !lstatSync(OUT).isFile())) {
    throw new Error(`${REGISTRY_REL} is not a regular file; refusing to use it`);
  }
};

// ---- scanned refs (all local and remote branches; tags and symbolic HEADs excluded) ----
const refs = git(['for-each-ref', '--format=%(refname)\t%(objectname)\t%(symref)', 'refs/heads', 'refs/remotes'])
  .split('\n')
  .filter(Boolean)
  .map((line) => line.split('\t'))
  .filter(([, , symref]) => !symref)
  .map(([name, id]) => [name, id])
  .sort((a, b) => byCodePoint(a[0], b[0]));

// ---- git-backed inventory ----
const treeRows = [];
const blobIds = new Set();
for (const [refName, id] of refs) {
  // Each ref is read through the object id captured above, so the printed ref list matches the scanned trees.
  const records = git(['ls-tree', '-r', '-z', '--full-tree', id]).split('\0');
  for (const record of records) {
    const tab = record.indexOf('\t');
    if (tab < 0) continue;
    const [mode, type, blob] = record.slice(0, tab).split(' ');
    const path = record.slice(tab + 1);
    if (type !== 'blob' || mode === '120000' || !path.endsWith('.md') || path === REGISTRY_REL) continue;
    treeRows.push([refName, path, blob]);
    blobIds.add(blob);
  }
}

// Read unique Markdown objects in byte-bounded batches instead of starting one Git process per blob.
const titleByBlob = new Map();
const uniqueBlobIds = [...blobIds];
const BLOB_METADATA_BATCH_SIZE = 256;
const BLOB_BATCH_BYTE_LIMIT = 64 * 1024 * 1024;
const blobSizes = new Map();
for (let start = 0; start < uniqueBlobIds.length; start += BLOB_METADATA_BATCH_SIZE) {
  const batch = uniqueBlobIds.slice(start, start + BLOB_METADATA_BATCH_SIZE);
  const metadata = execFileSync('git', ['cat-file', '--batch-check'], {
    cwd: REPO,
    input: Buffer.from(`${batch.join('\n')}\n`, 'ascii'),
    maxBuffer: 16 * 1024 * 1024,
  }).toString('ascii').split('\n').filter(Boolean);
  if (metadata.length !== batch.length) throw new Error('incomplete Git blob metadata output');
  for (let index = 0; index < batch.length; index += 1) {
    const [actual, type, rawSize] = metadata[index].split(' ');
    if (actual !== batch[index] || type !== 'blob' || !/^\d+$/u.test(rawSize ?? '')) {
      throw new Error(`unreadable Git blob metadata: ${batch[index]}`);
    }
    const size = Number(rawSize);
    if (!Number.isSafeInteger(size) || size < 0) throw new Error(`invalid Git blob size: ${batch[index]}`);
    blobSizes.set(batch[index], size);
  }
}

const blobBatches = [];
let currentBatch = [];
let currentBatchBytes = 0;
for (const blob of uniqueBlobIds) {
  const size = blobSizes.get(blob);
  if (currentBatch.length > 0 && currentBatchBytes + size > BLOB_BATCH_BYTE_LIMIT) {
    blobBatches.push(currentBatch);
    currentBatch = [];
    currentBatchBytes = 0;
  }
  currentBatch.push(blob);
  currentBatchBytes += size;
}
if (currentBatch.length > 0) blobBatches.push(currentBatch);

for (const batch of blobBatches) {
  const output = execFileSync('git', ['cat-file', '--batch'], {
    cwd: REPO,
    input: Buffer.from(`${batch.join('\n')}\n`, 'ascii'),
    maxBuffer: 512 * 1024 * 1024,
  });
  let offset = 0;
  for (const blob of batch) {
    const headerEnd = output.indexOf(0x0a, offset);
    if (headerEnd < 0) throw new Error(`unreadable Git blob header: ${blob}`);
    const [actual, type, rawSize] = output.subarray(offset, headerEnd).toString('ascii').split(' ');
    if (actual !== blob || type !== 'blob' || !/^\d+$/u.test(rawSize ?? '')) {
      throw new Error(`unreadable Git blob: ${blob}`);
    }
    const size = Number(rawSize);
    const contentStart = headerEnd + 1;
    const contentEnd = contentStart + size;
    if (!Number.isSafeInteger(size) || contentEnd >= output.length || output[contentEnd] !== 0x0a) {
      throw new Error(`invalid Git blob length: ${blob}`);
    }
    const text = output.subarray(contentStart, contentEnd).toString('utf8');
    const title = /^#[ \t]+(.+)$/mu.exec(text)?.[1]?.trim() ?? '';
    titleByBlob.set(blob, title);
    offset = contentEnd + 1;
  }
  if (offset !== output.length) throw new Error('unexpected trailing Git batch output');
}

/** @type {Map<string, Map<string, Set<string>>>} path -> title -> refs that contain it */
const tracked = new Map();
for (const [refName, path, blob] of treeRows) {
  const title = titleByBlob.get(blob);
  const variants = tracked.get(path) ?? new Map();
  const titleRefs = variants.get(title) ?? new Set();
  titleRefs.add(refName);
  variants.set(title, titleRefs);
  tracked.set(path, variants);
}

// ---- local-only inventory (ignore-aware, containment-checked, path only) ----
const worktreeRoots = git(['worktree', 'list', '--porcelain'])
  .split('\n')
  .filter((line) => line.startsWith('worktree '))
  .map((line) => resolve(line.slice('worktree '.length)));
const localOnly = new Set();
const unreadable = [];
for (const root of excludeLocalOnly ? [] : worktreeRoots) {
  if (!existsSync(root)) {
    console.warn(`warning: attached worktree root is missing, its untracked Markdown is not inventoried: ${root}`);
    continue;
  }
  const realRoot = realpathSync(root);
  const listed = gitIn(root, ['ls-files', '--others', '--exclude-standard', '-z', '--', '*.md']).split('\0');
  for (const rel of listed) {
    if (!rel || !rel.endsWith('.md') || rel === REGISTRY_REL) continue;
    if (rel.split('/').some((segment) => NEVER_READ_DIRS.has(segment))) continue;
    const full = join(root, ...rel.split('/'));
    try {
      if (lstatSync(full).isSymbolicLink()) {
        console.warn(`warning: symlink skipped: ${full}`);
        continue;
      }
      const real = realpathSync(full);
      if (real !== realRoot && !real.startsWith(realRoot + sep)) {
        console.warn(`warning: path escapes its worktree and is skipped: ${full}`);
        continue;
      }
    } catch (error) {
      unreadable.push(full);
      console.warn(`warning: untracked Markdown could not be inspected and is not inventoried: ${full} (${error.code ?? error.message})`);
      continue;
    }
    localOnly.add(relative(root, full).split(sep).join('/'));
  }
}

// ---- render ----
const rows = [...tracked.entries()].sort(([a], [b]) => byCodePoint(a, b));
const lines = [
  '# Document registry',
  '',
  'Generated by `node scripts/build_document_registry.mjs`. Do not edit by hand. Regenerate and commit whenever a',
  'plan, design, TDD, report, ADR, runbook or any other Markdown file is created, moved, renamed or removed',
  '(operator rule 2026-09-29). `--check` fails when this file is stale.',
  '',
  excludeLocalOnly
    ? 'Scope: every Markdown file (case-sensitive `.md`) on all local and remote branches, as observed at the exact'
    : 'Scope: every Markdown file (case-sensitive `.md`) on all local and remote branches, plus untracked Markdown paths',
  excludeLocalOnly
    ? 'Git refs listed below. Local-only files in attached worktrees are intentionally not inventoried. This is a'
    : 'of attached worktrees, as observed at the exact Git refs listed below. This is a point-in-time snapshot, not a',
  excludeLocalOnly
    ? 'point-in-time snapshot, not a claim about refs created after generation. Excluded are this file, ignored files,'
    : 'claim about refs created after generation. Excluded are this file, ignored files, symlinks and dependency/build',
  excludeLocalOnly
    ? 'symlinks and dependency/build directories. For tracked rows, titles show the first heading of each blob, JSON-quoted;'
    : 'directories. For tracked rows, titles show the first heading of each blob, JSON-quoted; a path with several',
  excludeLocalOnly
    ? 'a path with several heading variants over the scanned refs lists all of them; an empty cell means no heading was found.'
    : 'heading variants over the scanned refs lists all of them; an empty cell means no heading was found.',
  'Cyrillic is escaped only in headings found exclusively on archive, rescue, or snapshot refs.',
  '',
  excludeLocalOnly
    ? `Inventory: ${rows.length} tracked ${rows.length === 1 ? "path" : "paths"}; local-only NOT_ENUMERATED.`
    : `Inventory: ${rows.length} tracked ${rows.length === 1 ? "path" : "paths"}, ${localOnly.size} local-only ${localOnly.size === 1 ? "path" : "paths"}.`,
  '',
  '## Documents in git (scanned refs)',
  '',
  '| Path | Kind | Title |',
  '| --- | --- | --- |',
  ...rows.map(([path, variants]) => `| ${esc(path)} | ${kindOf(path)} | ${titleCell(variants)} |`),
  '',
  '## Scanned refs',
  '',
  '| Ref | Commit |',
  '| --- | --- |',
  ...refs.map(([name, id]) => `| ${esc(name)} | \`${id}\` |`),
  '',
  excludeLocalOnly
    ? '## Local-only Markdown inventory'
    : '## Markdown untracked in at least one attached worktree (paths only)',
  '',
  ...(excludeLocalOnly
    ? ['Local-only Markdown in attached worktrees was not inventoried in this snapshot.']
    : ['| Path |', '| --- |', ...[...localOnly].sort(byCodePoint).map((path) => `| ${esc(path)} |`)]),
  '',
];
const body = lines.join('\n');

console.log(`scanned ${refs.length} refs:`);
for (const [name, id] of refs) console.log(`  ${id} ${name}`);

assertOutputContained();
if (checkOnly) {
  if (unreadable.length > 0) {
    console.log(`${unreadable.length} untracked Markdown path(s) could not be inspected; the local-only inventory is not reliable.`);
    process.exitCode = 1;
  }
  const current = existsSync(OUT) ? readFileSync(OUT, 'utf8').replaceAll('\r\n', '\n') : '';
  if (current !== body) {
    console.log(`${REGISTRY_REL} is stale: regenerate it.`);
    process.exitCode = 1;
  } else {
    console.log(`${REGISTRY_REL} is current.`);
  }
} else if (unreadable.length > 0) {
  console.log(`${unreadable.length} untracked Markdown path(s) could not be inspected; refusing to write an incomplete registry.`);
  process.exitCode = 1;
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  assertOutputContained();
  writeFileSync(OUT, body, 'utf8');
  const localOnlySummary = excludeLocalOnly
    ? 'local-only NOT_ENUMERATED'
    : `${localOnly.size} local-only ${localOnly.size === 1 ? "path" : "paths"}`;
  console.log(`wrote ${REGISTRY_REL}: ${rows.length} tracked ${rows.length === 1 ? "path" : "paths"}; ${localOnlySummary}.`);
}
