import os

from business_ai_gateway.testbed.fake1c import create_app


app = create_app(os.getenv("FAKE1C_PROFILE", "json"))
