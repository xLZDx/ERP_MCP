"""Deterministic offline documentation embedding with source/content hashes; no CDN/URL fetch."""
from __future__ import annotations

import argparse
import hashlib
import html
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import markdown

DOCUMENTS = {
    'doc-document-index': 'docs/DOCUMENT_INDEX.md', 'doc-tdd': 'docs/TDD.md',
    'doc-master-plan': 'docs/MASTER_PLAN.md', 'doc-data-model': 'docs/DATA_MODEL.md',
    'doc-governance': 'docs/GOVERNANCE.md', 'doc-definition-of-done': 'docs/DEFINITION_OF_DONE.md',
    'doc-architecture': 'docs/ARCHITECTURE.md', 'doc-integration': 'docs/INTEGRATION.md',
    'doc-test-strategy': 'docs/TEST_STRATEGY.md', 'doc-observability-sre': 'docs/OBSERVABILITY_SRE.md',
    'doc-risk-register': 'docs/RISK_REGISTER.md', 'doc-threat-model': 'docs/THREAT_MODEL.md',
    'doc-requirements-traceability': 'docs/REQUIREMENTS_TRACEABILITY.md',
    'doc-compatibility': 'docs/COMPATIBILITY.md', 'doc-adapter-census': 'docs/ADAPTER_CENSUS.md',
    'doc-adapter-intake-plan': 'docs/ADAPTER_INTAKE_PLAN.md', 'doc-security': 'SECURITY.md',
    'doc-production': 'deploy/PRODUCTION.md', 'doc-adr-0001': 'docs/adr/ADR-0001-read-only-mvp.md',
    'doc-adr-0002': 'docs/adr/ADR-0002-control-data-plane.md',
    'doc-adr-0003': 'docs/adr/ADR-0003-reuse-before-rewrite.md',
    'doc-adr-0004': 'docs/adr/ADR-0004-capability-routing.md',
    'doc-adr-0005': 'docs/adr/ADR-0005-no-direct-1c-sql.md',
    'doc-adr-0006': 'docs/adr/ADR-0006-copyleft-isolation.md',
    'doc-mvp-scope': 'docs/MVP_SCOPE.md', 'doc-testbed': 'testbed/real1c/README.md',
    'doc-vendor-upstreams': 'vendor/UPSTREAMS.md', 'doc-package-manifest': 'docs/PACKAGE_MANIFEST.json',
    'doc-scope-freeze': 'docs/SCOPE_FREEZE_BASELINE_2026-10-06.md',
    'doc-dad-coverage': 'docs/DAD_1C_MCP_REQUIREMENTS_COVERAGE.md',
    'doc-ferma-blueprint': 'docs/FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md',
    'doc-rsv-runbook': 'docs/runbooks/RSV_DATA_BRIDGE.md',
    'doc-pilot-evidence': 'docs/PILOT_EVIDENCE_GATE.md', 'doc-vendor-intake': 'vendor/intake.json',
}
COPIES = ('ERP_MCP_ENGINEERING_COMMAND_CENTER.html', 'docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html')
ARTICLES = re.compile(r'(<article\b[^>]*id="(doc-[^"]+)"[^>]*>.*?<div class="md">)(.*?)(</div>\s*</article>)', re.DOTALL)
OVERLAY = re.compile(r'<h2>Phase map</h2>.*?<table id="phase-status-map".*?</table>\s*</div>', re.DOTALL)
BEGIN = '<!-- NORMATIVE_SOURCE_BEGIN -->'
END = '<!-- NORMATIVE_SOURCE_END -->'
TOOL_ANNOTATION = re.compile(r'^\[(?:Reading [0-9]+ lines from start \(total: [0-9]+ lines, [0-9]+ remaining\)|executed on device: [^\r\n]+)\]$')


class SafeHTML(HTMLParser):
    """Narrow presentation policy around the pinned Markdown renderer, not a Markdown parser."""
    TAGS = frozenset({'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'strong',
                      'em', 'blockquote', 'pre', 'code', 'a', 'br', 'hr', 'table', 'thead', 'tbody',
                      'tr', 'td', 'th', 'dl', 'dt', 'dd'})

    def __init__(self, source_path: str):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.source_path = source_path

    def handle_starttag(self, tag, attrs):
        if tag not in self.TAGS:
            return
        attributes = []
        for key, value in attrs:
            if tag == 'a' and key == 'href' and value:
                # Only ordinary relative links/anchors or HTTPS, never javascript/data/file URLs.
                cleaned = html.unescape(value).strip()
                if any(ord(character) < 32 for character in cleaned):
                    continue
                parsed = urlsplit(cleaned)
                if parsed.scheme not in {'', 'https'} or (not parsed.scheme and parsed.netloc):
                    continue
                if not parsed.scheme and parsed.path:
                    local = posixpath.normpath(posixpath.join(str(PurePosixPath(self.source_path).parent), parsed.path))
                    identifier = next((key for key, path in DOCUMENTS.items() if path == local), None)
                    if identifier:
                        cleaned = '#' + identifier  # same offline anchor in both identical copies
                attributes.append(f' href="{html.escape(cleaned, quote=True)}"')
        self.output.append('<' + tag + ''.join(attributes) + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {'br', 'hr'}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.TAGS and tag not in {'br', 'hr'}:
            self.output.append(f'</{tag}>')

    def handle_data(self, data):
        self.output.append(html.escape(data, quote=False))


def normalized_source(root: Path, relative: str) -> str:
    target = root / relative
    if (target.is_symlink() or not target.resolve().is_relative_to(root.resolve())
            or not target.is_file() or target.stat().st_size > 2_000_000):
        raise ValueError('DASHBOARD_DOCUMENT_SOURCE_INVALID')
    with target.open('rb') as stream:
        payload = stream.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError('DASHBOARD_DOCUMENT_SOURCE_INVALID')
    return payload.decode('utf-8').replace('\r\n', '\n')


def embedded(root: Path, relative: str) -> str:
    if markdown.__version__ != '3.11':
        raise ValueError('DASHBOARD_RENDERER_VERSION_UNCONFIRMED')
    source = normalized_source(root, relative)
    # Legacy copied tool envelopes are presentation noise, not normative decisions. Preserve
    # the original source hash (including immutable freeze content), but don't display host IDs.
    visible = '\n'.join(line for line in source.split('\n') if not TOOL_ANNOTATION.fullmatch(line))
    render_source = f'```json\n{visible}\n```' if relative.endswith('.json') else visible
    # Disable raw-HTML handling, not Markdown syntax/code escaping. Pre-escaping the entire
    # input would double-escape operators in code samples and change the displayed document.
    renderer = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
    renderer.preprocessors.deregister('html_block')
    renderer.inlinePatterns.deregister('html')
    converted = renderer.convert(render_source)
    sanitizer = SafeHTML(relative)
    sanitizer.feed(converted)
    rendered = ''.join(sanitizer.output)
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    content_hash = hashlib.sha256(rendered.encode()).hexdigest()
    return (f'<!-- DOC_SOURCE={relative} DOC_SOURCE_SHA256={source_hash} DOC_RENDER_SHA256={content_hash} -->\n'
            + BEGIN + '\n' + rendered + '\n' + END)


def synchronize(page: str, root: Path) -> str:
    page = '\n'.join(line for line in page.split('\n') if not TOOL_ANNOTATION.fullmatch(line))
    seen = set()

    def replace(match):
        identifier = match[2]
        if identifier not in DOCUMENTS or identifier in seen:
            raise ValueError('DASHBOARD_DOCUMENT_INVENTORY_INVALID')
        seen.add(identifier)
        overlay = ''
        if identifier == 'doc-master-plan':
            found = OVERLAY.search(match[3])
            if not found:
                raise ValueError('DASHBOARD_PHASE_OVERLAY_MISSING')
            overlay = found[0] + '\n'
        return match[1] + overlay + embedded(root, DOCUMENTS[identifier]) + match[4]

    updated = ARTICLES.sub(replace, page)
    missing = set(DOCUMENTS) - seen
    if not seen or not {'doc-document-index', 'doc-master-plan'}.issubset(seen):
        raise ValueError('DASHBOARD_DOCUMENT_INVENTORY_INVALID')
    cards, links = [], []
    for identifier, relative in DOCUMENTS.items():
        if identifier not in missing:
            continue
        title = html.escape(Path(relative).stem.replace('_', ' '))
        cards.append(f'<article class="doc-card searchable" id="{identifier}" data-cat="core" data-title="{title}">'
                     f'<div class="doc-head"><h2>{title}</h2></div><div class="md">'
                     + embedded(root, relative) + '</div></article>')
        links.append(f'<button class="doc-link" data-target="{identifier}" data-cat="core">{title}</button>')
    if missing:
        if updated.count('</aside><main>') != 1 or updated.count('</main>') != 1:
            raise ValueError('DASHBOARD_LAYOUT_INVALID')
        updated = updated.replace('</aside><main>', ''.join(links) + '</aside><main>')
        updated = updated.replace('</main>', '\n'.join(cards) + '</main>')
    return updated.rstrip() + '\n'


def check(root: Path) -> None:
    pages = [(root / path).read_text(encoding='utf-8') for path in COPIES]
    if pages[0] != pages[1]:
        raise ValueError('DASHBOARD_COPIES_DIFFER')
    matches = list(ARTICLES.finditer(pages[0]))
    if len(matches) != len(DOCUMENTS) or {match[2] for match in matches} != set(DOCUMENTS):
        raise ValueError('DASHBOARD_DOCUMENT_INVENTORY_INVALID')
    for match in matches:
        expected = embedded(root, DOCUMENTS[match[2]])
        actual = match[3]
        if match[2] == 'doc-master-plan':
            overlay = OVERLAY.search(actual)
            if not overlay:
                raise ValueError('DASHBOARD_PHASE_OVERLAY_MISSING')
            actual = actual[:overlay.start()] + actual[overlay.end():]
        if actual.strip() != expected:
            raise ValueError('STALE_DASHBOARD_DOCUMENT_SOURCE_OR_RENDER')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.check:
        pages = [(root / path).read_text(encoding='utf-8') for path in COPIES]
        if pages[0] != pages[1]:
            raise SystemExit('DASHBOARD_COPIES_DIFFER: preserve and inspect concurrent changes')
        updated = synchronize(pages[0], root)
        for copy in COPIES:
            (root / copy).write_text(updated, encoding='utf-8', newline='\n')
    check(root)
    print(f'Dashboard normative source/render consistency: PASS ({len(DOCUMENTS)} documents)')


if __name__ == '__main__':
    main()
