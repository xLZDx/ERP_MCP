import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const sourceGenerator = join(dirname(fileURLToPath(import.meta.url)), 'build_document_registry.mjs');

function git(cwd, ...args) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

test('registry snapshot keeps current Cyrillic readable and excludes local-only Markdown', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'erp-mcp-document-registry-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));

  const generator = join(root, 'scripts', 'build_document_registry.mjs');
  mkdirSync(dirname(generator), { recursive: true });
  mkdirSync(join(root, 'docs'), { recursive: true });
  writeFileSync(generator, readFileSync(sourceGenerator));

  git(root, 'init', '-b', 'main');
  git(root, 'config', 'user.name', 'Registry E2E');
  git(root, 'config', 'user.email', 'registry-e2e@example.invalid');
  writeFileSync(join(root, 'docs', 'current.md'), '# \u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a\n');
  writeFileSync(join(root, 'docs', 'mixed.md'), '# \u0421\u0442\u0430\u0440\u043e\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435\n');
  git(root, 'add', 'scripts/build_document_registry.mjs', 'docs/current.md', 'docs/mixed.md');
  git(root, 'commit', '-m', 'fixture: seed current registry documents');

  git(root, 'branch', 'archive/legacy');
  git(root, 'switch', 'archive/legacy');
  writeFileSync(join(root, 'docs', 'historical.md'), '# \u0418\u0441\u0442\u043e\u0440\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a\n');
  git(root, 'add', 'docs/historical.md');
  git(root, 'commit', '-m', 'fixture: add historical-only document');

  git(root, 'switch', 'main');
  writeFileSync(join(root, 'docs', 'mixed.md'), '# \u041d\u043e\u0432\u043e\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435\n');
  git(root, 'add', 'docs/mixed.md');
  git(root, 'commit', '-m', 'fixture: update current title variant');

  mkdirSync(join(root, 'private'), { recursive: true });
  writeFileSync(join(root, 'private', 'untracked-secret.md'), '# MUST_NOT_BE_INVENTORIED\n');

  const output = execFileSync(process.execPath, [generator, '--exclude-local-only'], {
    cwd: root,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const registry = readFileSync(join(root, 'governance', 'DOCUMENT_REGISTRY.md'), 'utf8');
  const row = (path) => registry.split('\n').find((line) => line.startsWith(`| ${path} |`));

  assert.match(output, /wrote governance\/DOCUMENT_REGISTRY\.md: 3 tracked paths; local-only NOT_ENUMERATED\./);
  assert.match(row('docs/current.md') ?? '', /\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a/);
  assert.match(row('docs/historical.md') ?? '', /\\u0418\\u0441\\u0442\\u043E\\u0440\\u0438\\u0447\\u0435\\u0441\\u043A\\u0438\\u0439/);
  assert.match(row('docs/mixed.md') ?? '', /\\u0421\\u0442\\u0430\\u0440\\u043E\\u0435/);
  assert.match(row('docs/mixed.md') ?? '', /\u041d\u043e\u0432\u043e\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435/);
  assert.match(registry, /Inventory: 3 tracked paths; local-only NOT_ENUMERATED\./);
  assert.doesNotMatch(registry, /untracked-secret\.md|MUST_NOT_BE_INVENTORIED/);
});
