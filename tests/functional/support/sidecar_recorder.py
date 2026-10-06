"""Recording wrapper in front of the TEST-ONLY fake OData sidecar (testbed.fake1c.sidecar_app)."""

from __future__ import annotations

from testbed.fake1c.sidecar_app import app as _inner
from tests.functional.support.recording import wrap

app = wrap(_inner)
