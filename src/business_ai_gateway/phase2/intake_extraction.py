"""Field-level provenance for bounded manual-review intake.

This adapter preserves each nonblank parser value with a one-based source cell
coordinate. It does not infer financial meaning, approve material fields, or
create proposals. Every extracted candidate remains ``REVIEW_REQUIRED``.

The current plan has no broad currency, rounding, discount, credit-note,
mixed-rate, or tolerance rules. Only the explicitly measured single-currency
`includes_vat` arithmetic is cross-checked, exactly and without rounding; every
outcome still requires review and never emits a proposal. Unsupported shapes
are ``UNCOMPUTABLE_REVIEW``. PDF and image inputs stay best-effort/manual-review-
only until H3 qualifies an extractor. No OCR or external I/O is performed here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256

from .safe_parser import ParseLimits, ParseResult, ParseStats, SheetValues, Status, parse_csv, run_isolated


class UploadFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"
    PDF = "pdf"
    IMAGE = "image"
    OTHER = "other"


class ExtractionState(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BEST_EFFORT_REVIEW = "BEST_EFFORT_REVIEW"
    REFUSED = "REFUSED"


class TotalCheckState(StrEnum):
    MATCH_REVIEW = "MATCH_REVIEW"
    MISMATCH_REVIEW = "MISMATCH_REVIEW"
    UNCOMPUTABLE_REVIEW = "UNCOMPUTABLE_REVIEW"


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Stable source identity plus one-based cell coordinates; no local path is retained."""

    source_sha256: str
    source_format: UploadFormat
    sheet_name: str | None
    row_number: int
    column_number: int
    field_key: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    """Untrusted parser text and its exact origin; never an accepted business value."""

    text: str
    provenance: SourceProvenance
    state: ExtractionState = ExtractionState.REVIEW_REQUIRED


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Fail-closed extraction output; this module never authorizes a proposal."""

    state: ExtractionState
    code: str
    source_sha256: str | None
    source_format: UploadFormat
    values: tuple[ExtractedValue, ...] = ()
    total_check: TotalCheckState = TotalCheckState.UNCOMPUTABLE_REVIEW

    @property
    def proposal_allowed(self) -> bool:
        """This extraction slice has no proposal path."""
        return False


@dataclass(frozen=True, slots=True)
class TotalCheckResult:
    """Exact cross-check outcome; even a match remains subject to human review."""

    state: TotalCheckState
    code: str
    computed_total: str | None = None
    difference: str | None = None

    @property
    def proposal_allowed(self) -> bool:
        """A total comparison is diagnostic and cannot authorize a proposal."""
        return False


_FIELD_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}\Z", re.ASCII)
_PLAIN_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,6})?\Z", re.ASCII)
MAX_EXTRACTED_VALUES = 50_000
MAX_TOTAL_COMPONENTS = 50_000
_REFUSED = ExtractionResult(
    state=ExtractionState.REFUSED,
    code="INVALID_INPUT",
    source_sha256=None,
    source_format=UploadFormat.OTHER,
)


def extract_upload(
    data: bytes,
    source_format: UploadFormat,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    column_labels: dict[int, str] | None = None,
) -> ExtractionResult:
    """Parse XLSX/CSV in the existing bounded parser and return review-only cells.

    ``column_labels`` is an optional caller-authored mapping from one-based
    column number to a safe field key. No header or business-field inference is
    performed. PDF/image are not parsed and return an empty manual-review state.
    """
    if type(data) is not bytes or type(source_format) is not UploadFormat or type(limits) is not ParseLimits:
        return _REFUSED
    labels = _validated_labels(column_labels, limits.max_cells)
    if labels is None:
        return _refused(source_format)
    if len(data) > limits.max_input_bytes:
        return _refused(source_format)

    digest = sha256(data).hexdigest()
    if source_format in (UploadFormat.PDF, UploadFormat.IMAGE):
        return ExtractionResult(
            state=ExtractionState.BEST_EFFORT_REVIEW,
            code="MANUAL_REVIEW_ONLY",
            source_sha256=digest,
            source_format=source_format,
        )
    if source_format not in (UploadFormat.XLSX, UploadFormat.CSV):
        return ExtractionResult(
            state=ExtractionState.BEST_EFFORT_REVIEW,
            code="UNSUPPORTED_FORMAT_REVIEW",
            source_sha256=digest,
            source_format=source_format,
        )

    parsed = run_isolated(data, limits=limits) if source_format is UploadFormat.XLSX else parse_csv(data, limits=limits)
    return _extract_parse_result(data, source_format, parsed, limits=limits, column_labels=labels)


def _extract_parse_result(
    data: bytes,
    source_format: UploadFormat,
    parsed: ParseResult,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    column_labels: dict[int, str] | None = None,
) -> ExtractionResult:
    """Strictly adapt a parser result; malformed values fail closed with fixed codes."""
    if (
        type(data) is not bytes
        or type(source_format) is not UploadFormat
        or source_format not in (UploadFormat.XLSX, UploadFormat.CSV)
        or type(limits) is not ParseLimits
    ):
        return _REFUSED
    labels = _validated_labels(column_labels, limits.max_cells)
    if labels is None or len(data) > limits.max_input_bytes:
        return _refused(source_format)
    digest = sha256(data).hexdigest()
    if not _valid_parse_result(parsed, limits):
        return _refused(source_format, digest, "MALFORMED_PARSE_RESULT")
    if parsed.status is not Status.OK or parsed.code != "OK":
        return _refused(source_format, digest, "PARSER_REFUSED")
    if source_format is UploadFormat.CSV and (len(parsed.sheets) != 1 or parsed.sheets[0].name != "csv"):
        return _refused(source_format, digest, "MALFORMED_PARSE_RESULT")

    values: list[ExtractedValue] = []
    for sheet in parsed.sheets:
        for row_index, row in enumerate(sheet.rows, start=1):
            for column_index, value in enumerate(row, start=1):
                if value in (None, ""):
                    continue
                if len(values) >= MAX_EXTRACTED_VALUES:
                    return _refused(source_format, digest, "BOUND_CANDIDATES")
                provenance = SourceProvenance(
                    source_sha256=digest,
                    source_format=source_format,
                    sheet_name=sheet.name if source_format is UploadFormat.XLSX else None,
                    row_number=row_index,
                    column_number=column_index,
                    field_key=labels.get(column_index),
                )
                values.append(ExtractedValue(value, provenance))

    return ExtractionResult(
        state=ExtractionState.REVIEW_REQUIRED,
        code="VALUES_EXTRACTED_REVIEW_REQUIRED",
        source_sha256=digest,
        source_format=source_format,
        values=tuple(values),
    )


def cross_check_explicit_total(
    line_amounts: tuple[str, ...],
    vat_amounts: tuple[str, ...],
    stated_total: str,
    *,
    amount_currency: str,
    vat_currency: str,
    total_currency: str,
    includes_vat: bool,
) -> TotalCheckResult:
    """Apply the measured explicit-VAT arithmetic only; never round or approve.

    The bounded rule comes from `CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json`:
    when `includes_vat` is false, total equals each line amount plus its explicit
    VAT amount; when true, total equals the sum of line amounts. VAT is never
    computed from a rate. The values must already be exact decimal strings in
    the same currency; mixed currencies, negative/credit-note values, unknown
    rounding rules, and any unsupported input return `UNCOMPUTABLE_REVIEW`.
    A match still only means arithmetic agrees under this explicit rule.
    """
    if (
        type(line_amounts) is not tuple
        or type(vat_amounts) is not tuple
        or not line_amounts
        or len(line_amounts) > MAX_TOTAL_COMPONENTS
        or len(vat_amounts) != len(line_amounts)
        or type(stated_total) is not str
        or type(includes_vat) is not bool
        or any(type(value) is not str for value in (*line_amounts, *vat_amounts))
        or not all(type(code) is str and _CURRENCY.fullmatch(code) for code in
                   (amount_currency, vat_currency, total_currency))
        or amount_currency != vat_currency
        or amount_currency != total_currency
    ):
        return TotalCheckResult(TotalCheckState.UNCOMPUTABLE_REVIEW, "TOTAL_INPUT_UNSUPPORTED")

    amount_values = tuple(_parse_exact_amount(value) for value in line_amounts)
    vat_values = tuple(_parse_exact_amount(value) for value in vat_amounts)
    stated_value = _parse_exact_amount(stated_total)
    if stated_value is None or any(value is None for value in (*amount_values, *vat_values)):
        return TotalCheckResult(TotalCheckState.UNCOMPUTABLE_REVIEW, "TOTAL_INPUT_UNSUPPORTED")

    computed = sum((value for value in amount_values if value is not None), Decimal("0"))
    if not includes_vat:
        computed += sum((value for value in vat_values if value is not None), Decimal("0"))
    difference = computed - stated_value
    state = TotalCheckState.MATCH_REVIEW if difference == 0 else TotalCheckState.MISMATCH_REVIEW
    return TotalCheckResult(
        state=state,
        code="TOTAL_MATCH_REQUIRES_REVIEW" if difference == 0 else "TOTAL_MISMATCH_REQUIRES_REVIEW",
        computed_total=format(computed, "f"),
        difference=format(difference, "f"),
    )


def _parse_exact_amount(value: str) -> Decimal | None:
    if len(value) > 26 or not _PLAIN_DECIMAL.fullmatch(value):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _validated_labels(labels: dict[int, str] | None, max_entries: int) -> dict[int, str] | None:
    if labels is None:
        return {}
    if type(labels) is not dict or len(labels) > max_entries:
        return None
    result: dict[int, str] = {}
    for column, key in labels.items():
        if type(column) is not int or column <= 0 or type(key) is not str or not _FIELD_KEY.fullmatch(key):
            return None
        result[column] = key
    return result


def _valid_parse_result(parsed: object, limits: ParseLimits) -> bool:
    if type(parsed) is not ParseResult or type(parsed.status) is not Status or type(parsed.code) is not str:
        return False
    if len(parsed.code) > 80 or not parsed.code.isascii() or not parsed.code.replace("_", "").isalnum():
        return False
    if type(parsed.sheets) is not tuple or type(parsed.stats) is not ParseStats:
        return False
    stats = parsed.stats
    counters = (
        stats.members,
        stats.uncompressed_bytes,
        stats.rows,
        stats.cells,
        stats.formula_cells,
        stats.leading_formula_chars,
    )
    if any(type(value) is not int or value < 0 for value in counters):
        return False
    if len(parsed.sheets) > limits.max_sheets:
        return False
    rows_seen = 0
    cells_seen = 0
    text_seen = 0
    for sheet in parsed.sheets:
        if type(sheet) is not SheetValues or type(sheet.name) is not str or len(sheet.name) > limits.max_cell_chars:
            return False
        if type(sheet.rows) is not tuple:
            return False
        rows_seen += len(sheet.rows)
        if rows_seen > limits.max_rows:
            return False
        for row in sheet.rows:
            if type(row) is not tuple:
                return False
            cells_seen += len(row)
            if cells_seen > limits.max_cells:
                return False
            for value in row:
                if value is not None and type(value) is not str:
                    return False
                if value is not None:
                    if len(value) > limits.max_cell_chars:
                        return False
                    text_seen += len(value)
                    if text_seen > limits.max_total_text_chars:
                        return False
    if parsed.status is Status.OK:
        if (
            parsed.code != "OK"
            or stats.rows != rows_seen
            or stats.cells < cells_seen
            or stats.cells > limits.max_cells
            or stats.members > limits.max_members
            or stats.uncompressed_bytes > limits.max_total_uncompressed
            or stats.formula_cells > stats.cells
            or stats.leading_formula_chars > stats.cells
        ):
            return False
    return True


def _refused(
    source_format: UploadFormat,
    digest: str | None = None,
    code: str = "INVALID_INPUT",
) -> ExtractionResult:
    return ExtractionResult(
        state=ExtractionState.REFUSED,
        code=code,
        source_sha256=digest,
        source_format=source_format,
    )
