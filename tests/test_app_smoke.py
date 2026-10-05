def test_production_app_imports_and_builds():
    from business_ai_gateway.app import app

    assert app is not None
