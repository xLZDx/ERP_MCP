"""Shared fixtures for the posted-receipts tests (R2-US-032): scripted in-memory page source."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from business_ai_gateway.phase2.aliases import (
    AliasResolver,
    AliasScope,
    Reference,
    SupplierEntity,
)
from business_ai_gateway.phase2.posted_receipts import (
    Direction,
    Page,
    PostedReceiptsRetriever,
    ReceiptsRequest,
)
from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseDocument,
    PurchaseScope,
)

FROM = datetime(2026, 8, 1, tzinfo=UTC)
UNTIL = datetime(2026, 9, 1, tzinfo=UTC)
INSIDE = datetime(2026, 8, 15, tzinfo=UTC)
COMPANY = "818ha"  # the alias scope key is casefolded: tenant/company must be canonical
VENDOR = "MOLDRETAIL-REF"
SNAP = "snap-1"
REF = Reference("erp_code", VENDOR)


def scope(*, company=COMPANY, vendor=VENDOR, currency="MDL", source="onec-reference"):
    return PurchaseScope("t", source, company, vendor, FROM, UNTIL, currency)


def doc(ref="d-1", *, company=COMPANY, vendor=VENDOR, currency="MDL", posted=True,
        deleted=False, amount="41.20", number="150", at=INSIDE, contract="c-1"):
    return PurchaseDocument(ref, company, vendor, contract, number, at, Decimal(amount),
                            currency, posted, deleted)


def forge(base: PurchaseDocument, **changes) -> PurchaseDocument:
    """A document that bypasses PurchaseDocument validation (hostile source)."""
    out = object.__new__(PurchaseDocument)
    for name in PurchaseDocument.__slots__:
        object.__setattr__(out, name, changes.get(name, getattr(base, name)))
    return out


def forge_scope(base: PurchaseScope, **changes) -> PurchaseScope:
    out = object.__new__(PurchaseScope)
    for name in PurchaseScope.__slots__:
        object.__setattr__(out, name, changes.get(name, getattr(base, name)))
    return out


def resolver(*, extra_entities=()):
    r = AliasResolver(clock=lambda: datetime(2026, 10, 10, tzinfo=UTC))
    r.add_entity(SupplierEntity(VENDOR, AliasScope("t", COMPANY), "Moldretail SRL", (REF,)))
    for ent in extra_entities:
        r.add_entity(ent)
    return r


def request(*, sc=None, direction=Direction.RECEIPT, ref=REF, name=""):
    return ReceiptsRequest(sc or scope(), direction, ref, name)


def page(docs, nxt=None, snap=SNAP, index=None, kinds=None):
    """Kinds default to RECEIPT for every row (the source-native document kind)."""
    docs = tuple(docs)
    return Page(docs, nxt, snap, index, ("RECEIPT",) * len(docs) if kinds is None else kinds)


class UnscriptedTokenError(AssertionError):
    """The retriever asked for a token the test did not script."""


class FakeSource:
    """Serves ``script[token]``; a script value that is an Exception is raised. Records calls
    (``calls``: scope + token, ``directions``: the direction passed to the port). An unscripted
    token fails with a distinct AssertionError (it is a test-script bug, not a source error)."""

    def __init__(self, script):
        self.script = script
        self.calls: list[tuple[PurchaseScope, str | None]] = []
        self.directions: list[object] = []

    def fetch_page(self, sc, direction, continuation_token):
        self.calls.append((sc, continuation_token))
        self.directions.append(direction)
        if continuation_token not in self.script:
            raise UnscriptedTokenError(continuation_token)
        item = self.script[continuation_token]
        if isinstance(item, BaseException):
            raise item
        return item


def three_pages(snap=SNAP):
    return {
        None: page([doc("d-1"), doc("d-2", amount="10")], "tok-1", snap, 0),
        "tok-1": page([doc("d-3", amount="5.5")], "tok-2", snap, 1),
        "tok-2": page([doc("d-4", amount="7")], None, snap, 2),
    }


def retriever(script, **kw):
    src = FakeSource(script)
    return PostedReceiptsRetriever(src, resolver(**kw)), src
