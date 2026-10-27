"""Deterministic synthetic data for simulation scenarios (TEST lane only).

Offline and pure (stdlib only). ``SyntheticGenerator`` draws everything from one seeded ``random.Random`` (same
seed, same call sequence, same data) and produces synthetic organizations, counterparties, contracts, items and
supplier-document payloads (``DraftPayload``) that the real parser ``parse_proposal`` accepts: exact canonical
decimal strings, one line by default (the measured shape), unique (counterparty, number, date) keys. All names are
synthetic identifiers (``SIM-...``); no real names exist here. ``populate`` seeds a ``SimulatedOneC``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from ..change.proposal import DraftPayload, Line, ProposalContext, payload_to_dict
from ..change.types import ChangeKind, Scope
from .clone_1c import SimulatedOneC, encode_payload

__all__ = ["SyntheticGenerator", "SyntheticUniverse", "populate"]

CURRENCIES: Final = ("TSTA", "TSTB")
VAT_CODES: Final = ("VAT0", "VAT10", "VAT20")
_EPOCH_START: Final = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)


def _canon(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


_SYNTHETIC_VAT_PERCENT: Final = {"VAT0": Decimal(0), "VAT10": Decimal(10), "VAT20": Decimal(20)}


def _synthetic_vat_amount(amount: Decimal, vat_code: str) -> Decimal:
    """VAT contained in a VAT-inclusive synthetic amount, rounded to two places; draws no randomness."""
    rate = _SYNTHETIC_VAT_PERCENT[vat_code]
    return (amount * rate / (Decimal(100) + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class SyntheticUniverse:
    organizations: tuple[str, ...]
    counterparties: tuple[str, ...]
    contracts: tuple[tuple[str, str], ...]  # (contract_ref, counterparty_ref)
    items: tuple[str, ...]
    currencies: tuple[str, ...]
    vat_codes: tuple[str, ...]

    def all_refs(self) -> frozenset[str]:
        """Every reference of the universe (suitable as ``ProposalContext.in_scope_refs``)."""
        return frozenset((*self.organizations, *self.counterparties, *(c for c, _ in self.contracts), *self.items))


class SyntheticGenerator:
    def __init__(self, seed: int, organizations: int = 1, counterparties: int = 5, items: int = 8) -> None:
        if type(seed) is not int or min(organizations, counterparties, items) < 1:
            raise ValueError("GENERATOR_ARGUMENTS_INVALID")
        self.seed = seed
        self._rng = random.Random(seed)
        orgs = tuple(f"SIM-ORG-{i:03d}" for i in range(1, organizations + 1))
        cpts = tuple(f"SIM-CPT-{i:03d}" for i in range(1, counterparties + 1))
        contracts = tuple((f"SIM-CTR-{i:03d}-{self._rng.choice('ABC')}", c) for i, c in enumerate(cpts, start=1))
        its = tuple(f"SIM-ITM-{i:03d}" for i in range(1, items + 1))
        self.universe = SyntheticUniverse(orgs, cpts, contracts, its, CURRENCIES, VAT_CODES)
        self._doc_counter = 0
        self._request_counter = 0

    def draft_payload(self, *, organization_ref: str | None = None, lines: int = 1,
                      expected_target_version: str | None = None, counterparty_ref: str | None = None,
                      supplier_document_number: str | None = None, supplier_document_date: str | None = None
                      ) -> DraftPayload:
        """One synthetic supplier-document payload; explicit arguments override the drawn values (for scenarios)."""
        if not 1 <= lines <= 100:
            raise ValueError("GENERATOR_ARGUMENTS_INVALID")
        u, rng = self.universe, self._rng
        organization = organization_ref or rng.choice(u.organizations)
        contract_ref, drawn_cpt = rng.choice(u.contracts)
        counterparty = counterparty_ref or drawn_cpt
        if counterparty_ref is not None:
            contract_ref = next((c for c, cp in u.contracts if cp == counterparty_ref), contract_ref)
        self._doc_counter += 1
        built = []
        for _ in range(lines):
            quantity = Decimal(rng.randint(1, 200)) / Decimal(rng.choice((1, 2, 4)))
            price = Decimal(rng.randint(100, 99999)) / Decimal(100)
            item = rng.choice(u.items)
            vat_code = rng.choice(u.vat_codes)
            amount = quantity * price
            built.append(Line(item, _canon(quantity), _canon(price), vat_code, _canon(amount),
                              _canon(_synthetic_vat_amount(amount, vat_code))))
        document_date = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 280))
        return DraftPayload(
            organization, counterparty, contract_ref,
            supplier_document_number or f"SIM-INV-{self._doc_counter:06d}",
            supplier_document_date or document_date.isoformat(), rng.choice(u.currencies), tuple(built),
            f"Synthetic test document {self._doc_counter:06d}", None, expected_target_version)

    def payloads(self, n: int, **kwargs: object) -> list[DraftPayload]:
        return [self.draft_payload(**kwargs) for _ in range(n)]  # type: ignore[arg-type]

    # ---- helpers to drive the real parser ---------------------------------------------------------------------

    def scope(self, organization_ref: str | None = None) -> Scope:
        return Scope("SIM-TENANT", "SIM-COMPANY", organization_ref or self.universe.organizations[0], "SIM-BASE-0001")

    def context(self, scope: Scope, *, preview_digest: str = "0" * 64, business_state_digest: str | None = None,
                change_id: str = "SIM-CHG-000001", target_refs: tuple[str, ...] = ()) -> ProposalContext:
        """A server-side context for ``parse_proposal`` that admits this universe (every currency qualified).

        ``target_refs`` are clone document references (``SIM-DOC-...``) that are additionally in scope.
        """
        return ProposalContext(
            change_id=change_id, requester_principal="SIM-REQUESTER", requester_person_id="SIM-PERSON-001", scope=scope,
            created_at=_EPOCH_START, expires_at=_EPOCH_START + timedelta(hours=1), auth_epoch_at_proposal=0,
            epoch_dependencies=(), preview_digest=preview_digest, business_state_digest=business_state_digest,
            qualified_currencies=frozenset(self.universe.currencies), in_scope_refs=self.universe.all_refs() | frozenset(target_refs))

    def envelope(self, kind: ChangeKind, payload: DraftPayload | None = None, *, target_ref: str | None = None,
                 target_version: str | None = None, parent_change_id: str | None = None) -> dict[str, object]:
        """The caller-input dict for ``parse_proposal`` (no identity fields, no allowed_effects)."""
        self._request_counter += 1
        raw: dict[str, object] = {"kind": kind.value, "request_id": f"SIM-REQ-{self._request_counter:06d}"}
        if kind in (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT):
            body = payload_to_dict(payload)
            if kind is ChangeKind.CREATE_DRAFT:
                del body["expected_target_version"]
            if body["duplicate_override"] is None:
                del body["duplicate_override"]
            raw["payload"] = body
        if target_ref is not None:
            raw["target_ref"] = target_ref
        if target_version is not None:
            raw["target_version"] = target_version
        if parent_change_id is not None:
            raw["parent_change_id"] = parent_change_id
        return raw


def populate(clone: SimulatedOneC, generator: SyntheticGenerator, n: int, *, post_every: int | None = None
             ) -> tuple[str, ...]:
    """Seed ``clone`` with ``n`` draft documents (optionally posting every ``post_every``-th); returns their refs."""
    if n < 0 or (post_every is not None and post_every < 1):
        raise ValueError("POPULATE_ARGUMENTS_INVALID")
    refs: list[str] = []
    for index in range(1, n + 1):
        result = clone.apply(ChangeKind.CREATE_DRAFT, encode_payload(generator.draft_payload()), None, None)
        if post_every is not None and index % post_every == 0:
            clone.apply(ChangeKind.POST, encode_payload(None), result.target_ref,
                        clone.read_state(result.target_ref)["version"])  # type: ignore[arg-type]
        refs.append(result.target_ref)
    return tuple(refs)
