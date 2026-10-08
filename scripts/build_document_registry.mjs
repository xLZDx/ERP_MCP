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
 *     refs/heads and refs/remotes (symbolic HEAD refs and tags excluded). Title = sorted, de-duplicated
 *     first-heading variants of that path over all scanned refs, joined by " / ". No ref names, counts per
 *     ref, version counts or absolute locations are written.
 *   - Local-only rows: repo-relative paths of untracked, non-ignored ".md" files per worktree
 *     (git ls-files --others --exclude-standard). Symlinks/junctions and paths resolving outside their
 *     worktree are skipped; dependency/build directories are never read; headings are never published.
 *   - Excluded: the registry file itself.
 *   - Staleness: adding an alias ref that points at an existing tree does not change the inventory; adding
 *     or removing a distinct path or a distinct title variant does. A document removed from one branch
 *     stays while another scanned ref still contains it.
 *
 * Usage:  node scripts/build_document_registry.mjs [--check]
 * --check exits 1 when the committed registry differs from the inventory. The scanned ref list with commit
 * ids is printed to stdout for the decision-log record.
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
const kindOf = (path) => KINDS.find(([re]) => re.test(path))?.[1] ?? 'Other';
const byCodePoint = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const esc = (text) => text.replaceAll('|', '\\|');

// ---- scanned refs (all local and remote branches; tags and symbolic HEADs excluded) ----
const refs = git(['for-each-ref', '--format=%(refname)\t%(objectname)', 'refs/heads', 'refs/remotes'])
  .split('\n')
  .filter(Boolean)
  .map((line) => line.split('\t'))
  .filter(([name]) => !name.endsWith('/HEAD'))
  .sort((a, b) => byCodePoint(a[0], b[0]));

// ---- git-backed inventory ----
const titleByBlob = new Map();
const titleOf = (blob) => {
  if (titleByBlob.has(blob)) return titleByBlob.get(blob);
  let title = '';
  try {
    const head = execFileSync('git', ['cat-file', 'blob', blob], { cwd: REPO, maxBuffer: 64 * 1024 * 1024 })
      .subarray(0, 4000)
      .toString('utf8');
    title = /^#[ \t]+(.+)$/mu.exec(head)?.[1]?.trim() ?? '';
  } catch {
    title = '';
  }
  titleByBlob.set(blob, title);
  return title;
};

/** @type {Map<string, Set<string>>} path -> distinct title variants */
const tracked = new Map();
for (const [ref] of refs) {
  const records = git(['ls-tree', '-r', '-z', '--full-tree', ref]).split('\0');
  for (const record of records) {
    const tab = record.indexOf('\t');
    if (tab < 0) continue;
    const [, type, blob] = record.slice(0, tab).split(' ');
    const path = record.slice(tab + 1);
    if (type !== 'blob' || !path.endsWith('.md') || path === REGISTRY_REL) continue;
    const variants = tracked.get(path) ?? new Set();
    variants.add(titleOf(blob));
    tracked.set(path, variants);
  }
}

// ---- local-only inventory (ignore-aware, containment-checked, path only) ----
const worktreeRoots = git(['worktree', 'list', '--porcelain'])
  .split('\n')
  .filter((line) => line.startsWith('worktree '))
  .map((line) => resolve(line.slice('worktree '.length)));
const localOnly = new Set();
for (const root of worktreeRoots) {
  if (!existsSync(root)) continue;
  const realRoot = realpathSync(root);
  const listed = gitIn(root, ['ls-files', '--others', '--exclude-standard', '-z', '--', '*.md']).split('\0');
  for (const rel of listed) {
    if (!rel || !rel.endsWith('.md') || rel === REGISTRY_REL) continue;
    if (rel.split('/').some((segment) => NEVER_READ_DIRS.has(segment))) continue;
    const full = join(root, ...rel.split('/'));
    try {
      if (lstatSync(full).isSymbolicLink()) continue;
      const real = realpathSync(full);
      if (real !== realRoot && !real.startsWith(realRoot + sep)) continue;
    } catch {
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
  'Scope: every Markdown file (case-sensitive `.md`) on all local and remote branches, plus untracked Markdown paths',
  'of attached worktrees. Excluded: this file, ignored files, symlinks, dependency/build directories. Titles are',
  'the first heading of tracked blobs; a path with several heading variants over the scanned refs lists all of them.',
  '',
  `Inventory: ${rows.length} tracked paths, ${localOnly.size} local-only paths.`,
  '',
  '## Documents in git (all branches)',
  '',
  '| Path | Kind | Title |',
  '| --- | --- | --- |',
  ...rows.map(([path, variants]) => {
    const titles = [...variants].filter(Boolean).sort(byCodePoint).join(' / ');
    return `| ${esc(path)} | ${kindOf(path)} | ${esc(titles)} |`;
  }),
  '',
  '## Markdown outside git history (untracked in an attached worktree; paths only)',
  '',
  '| Path |',
  '| --- |',
  ...[...localOnly].sort(byCodePoint).map((path) => `| ${esc(path)} |`),
  '',
];
const body = lines.join('\n');

console.log(`scanned ${refs.length} refs:`);
for (const [name, id] of refs) console.log(`  ${id} ${name}`);

if (process.argv.includes('--check')) {
  const current = existsSync(OUT) ? readFileSync(OUT, 'utf8').replaceAll('\r\n', '\n') : '';
  if (current !== body) {
    console.log(`${REGISTRY_REL} is stale: regenerate it.`);
    process.exitCode = 1;
  } else {
    console.log(`${REGISTRY_REL} is current.`);
  }
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, body, 'utf8');
  console.log(`wrote ${REGISTRY_REL}: ${rows.length} tracked paths, ${localOnly.size} local-only.`);
}
