"""Pure mapping from COM draft executor refusals to change-engine event names.

Conservative rule: any ambiguity stays UNKNOWN. Only a refusal that is proven to have happened before the 1C write
boundary (a known executor code that is raised with ``outcome_unknown`` False) maps to ``REFUSED_BEFORE_WRITE``.
An ``outcome_unknown`` refusal, a known code arriving with an unexpected flag, and every code this table does not
list map to ``CALL_UNKNOWN``; the mapping never fails open to a definite failure.

The values are the names of the change-engine ``Event`` members, so the glue can look them up by name without this
module importing the change package. Stdlib only; no COM access.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

__all__ = ["EXECUTOR_REFUSAL_CODES", "RefusalEvent", "map_executor_refusal"]


class RefusalEvent(str, Enum):
    CALL_UNKNOWN = "CALL_UNKNOWN"
    REFUSED_BEFORE_WRITE = "REFUSED_BEFORE_WRITE"


# Every code ``com_draft_executor`` can raise, with the outcome_unknown flag it is raised with.
# False: raised strictly before the write boundary (validation, reference/enum resolution, in-memory object building).
# True: raised at or after the write boundary (write, read-back, read-back mismatch).
EXECUTOR_REFUSAL_CODES: Final[dict[str, bool]] = {
    "COM_EXECUTOR_DESTINATIONS_INVALID": False,
    "COM_EXECUTOR_DESTINATION_MISMATCH": False,
    "COM_EXECUTOR_VALUE_INVALID": False,
    "COM_EXECUTOR_DOCUMENT_DATE_INVALID": False,
    "COM_MARKER_INVALID": False,
    "COM_REFERENCE_NOT_GUID": False,
    "COM_REFERENCE_LOOKUP_FAILED": False,
    "COM_REFERENCE_NOT_FOUND": False,
    "COM_REFERENCE_DELETION_MARKED": False,
    "COM_ENUM_VALUE_NOT_FOUND": False,
    "COM_DOCUMENT_CREATE_FAILED": False,
    "COM_HEADER_SET_FAILED": False,
    "COM_LINE_SET_FAILED": False,
    "COM_MARKER_SET_FAILED": False,
    "COM_WRITE_MODE_UNAVAILABLE": False,
    "COM_WRITE_OUTCOME_UNKNOWN": True,
    "COM_WRITTEN_READBACK_MISMATCH": True,
}


def map_executor_refusal(code: str, outcome_unknown: bool) -> RefusalEvent:
    """Return the engine event for an executor refusal; anything not provably pre-write is CALL_UNKNOWN."""
    if type(code) is not str or type(outcome_unknown) is not bool:
        return RefusalEvent.CALL_UNKNOWN
    expected_unknown = EXECUTOR_REFUSAL_CODES.get(code)
    if expected_unknown is False and outcome_unknown is False:
        return RefusalEvent.REFUSED_BEFORE_WRITE
    return RefusalEvent.CALL_UNKNOWN
