"""Recording wrapper in front of the unchanged Fake1C OData app (test harness only)."""

from __future__ import annotations

import os

from business_ai_gateway.testbed.fake1c import create_app
from tests.functional.support.recording import wrap

app = wrap(create_app(os.getenv("FAKE1C_PROFILE", "json")))
