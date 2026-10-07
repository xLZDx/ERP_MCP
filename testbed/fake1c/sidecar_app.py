import os  # noqa: I001

from business_ai_gateway.testbed.fake_sidecar import create_sidecar_app


app = create_sidecar_app(os.getenv("FAKE_SIDECAR_TOKEN") or None)
