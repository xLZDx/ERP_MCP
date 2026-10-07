import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.sync_dashboard_documents import COPIES, DOCUMENTS, check, embedded, synchronize


def prepare(root: Path):
    for relative in DOCUMENTS.values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Fixture baseline v1.1\n\nCurrent authoritative source.\n', encoding='utf-8')
    overlay = '<h2>Phase map</h2><div><table id="phase-status-map"><tr><td>current-status-fixture</td></tr></table></div>'
    cards = ''.join(f'<article id="{identifier}"><div class="md">'
                    + (overlay if identifier == 'doc-master-plan' else 'historical v1.0')
                    + '</div></article>' for identifier in list(DOCUMENTS)[:28])
    page = '<aside></aside><main>' + cards + '</main><script>preserved-UI-shell</script>'
    updated = synchronize(page, root)
    for copy in COPIES:
        path = root / copy
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding='utf-8')
    return updated


def test_all_34_sources_are_embedded_and_idempotent_without_losing_phase_overlay(tmp_path):
    page = prepare(tmp_path)
    check(tmp_path)
    assert synchronize(page, tmp_path) == page
    assert 'historical v1.0' not in page and 'preserved-UI-shell' in page
    assert page.count('current-status-fixture') == 1
    assert page.count('DOC_SOURCE=') == 34


def test_source_change_requires_actual_html_refresh_not_just_latest_marker(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'docs/TDD.md').write_text('# Changed authoritative text\n', encoding='utf-8')
    with pytest.raises(ValueError, match='STALE_DASHBOARD'):
        check(tmp_path)


def test_refreshing_hash_marker_without_render_cannot_hide_stale_body(tmp_path):
    page = prepare(tmp_path)
    old = embedded(tmp_path, 'docs/TDD.md')
    (tmp_path / 'docs/TDD.md').write_text('# Changed authoritative text\n', encoding='utf-8')
    new = embedded(tmp_path, 'docs/TDD.md')
    forged = page.replace(old.splitlines()[0], new.splitlines()[0])
    for copy in COPIES:
        (tmp_path / copy).write_text(forged, encoding='utf-8')
    with pytest.raises(ValueError, match='STALE_DASHBOARD'):
        check(tmp_path)


@pytest.mark.parametrize('kind', ['changed-render', 'missing-card', 'duplicate-card', 'missing-overlay', 'divergent-copy'])
def test_changed_missing_or_duplicate_embedded_data_fails_closed(tmp_path, kind):
    page = prepare(tmp_path)
    if kind == 'changed-render':
        changed = page.replace('Current authoritative source.', 'wrong body', 1)
    elif kind == 'missing-card':
        changed = re.sub(r'<article id="doc-tdd">.*?</article>', '', page, count=1, flags=re.DOTALL)
    elif kind == 'duplicate-card':
        changed = page.replace('</main>', '<article id="doc-tdd"><div class="md">duplicate</div></article></main>')
    elif kind == 'missing-overlay':
        changed = page.replace('id="phase-status-map"', 'id="wrong-table"')
    else:
        changed = page + 'different-copy'
    (tmp_path / COPIES[0]).write_text(changed, encoding='utf-8')
    if kind != 'divergent-copy':
        (tmp_path / COPIES[1]).write_text(changed, encoding='utf-8')
    with pytest.raises(ValueError):
        check(tmp_path)


def test_untrusted_html_urls_and_images_cannot_activate_script_or_network_loads(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'docs/TDD.md').write_text(
        '# XSS negative\n\n<script>alert(1)</script>\n\n[x](javascript:alert%281%29)\n\n'
        '[x](data:text/html,evil)\n\n![pixel](https://tracking.invalid/pixel)\n\n'
        '[safe](https://example.invalid/docs)\n', encoding='utf-8')
    body = embedded(tmp_path, 'docs/TDD.md')
    assert '<script>' not in body and '<img' not in body
    assert 'href="javascript' not in body and 'href="data' not in body
    assert 'href="https://example.invalid/docs"' in body
    assert '&lt;script&gt;' in body


def test_source_line_endings_are_portable(tmp_path):
    prepare(tmp_path)
    path = tmp_path / 'docs/TDD.md'
    expected = embedded(tmp_path, 'docs/TDD.md')
    path.write_bytes(path.read_text(encoding='utf-8').replace('\n', '\r\n').encode('utf-8'))
    assert embedded(tmp_path, 'docs/TDD.md') == expected


def test_code_operators_are_not_double_escaped_or_changed(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'docs/TDD.md').write_text('```python\nif x < 2 and x > 0:\n    print("a&b")\n```\n', encoding='utf-8')
    body = embedded(tmp_path, 'docs/TDD.md')
    assert 'x &lt; 2' in body and 'x &gt; 0' in body and 'a&amp;b' in body
    assert '&amp;lt;' not in body and '&amp;gt;' not in body


def test_embedding_inventory_covers_the_entire_frozen_required_package():
    package = json.loads(Path('docs/PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    assert set(package['required_documents']).issubset(set(DOCUMENTS.values()))


def test_known_normative_source_links_work_offline_in_both_copies(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'docs/TDD.md').write_text('[Master Plan](MASTER_PLAN.md)\n', encoding='utf-8')
    assert 'href="#doc-master-plan"' in embedded(tmp_path, 'docs/TDD.md')


def test_legacy_tool_envelopes_are_not_displayed_but_immutable_source_hash_is_preserved(tmp_path):
    prepare(tmp_path)
    source = '[Reading 2 lines from start (total: 2 lines, 0 remaining)]\n# Normative rule\n[executed on device: private-host (private-device-id)]\n'
    path = tmp_path / 'docs/SCOPE_FREEZE_BASELINE_2026-10-06.md'
    path.write_text(source, encoding='utf-8', newline='\n')
    body = embedded(tmp_path, 'docs/SCOPE_FREEZE_BASELINE_2026-10-06.md')
    assert 'private-host' not in body and 'Reading 2 lines' not in body
    assert 'Normative rule' in body and hashlib.sha256(source.encode()).hexdigest() in body
    assert path.read_text(encoding='utf-8') == source  # no mutation of the freeze source
