"""Local read-only COM bridge for balances by analytics (ADR-0008).

This is a SEPARATE top-level package. The gateway runtime never imports it (it is not under ``src`` and is not
packaged into the gateway image); the gateway only talks to it over loopback HTTP through
``business_ai_gateway.adapters.onec.com_bridge_client``. ``pywin32`` is imported lazily and only on the Windows
host that runs the bridge.
"""
