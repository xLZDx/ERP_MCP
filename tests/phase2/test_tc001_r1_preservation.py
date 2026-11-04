"""Targeted offline predicates for the TC001 R1 preservation procedure.

The Gherkin product scenario remains @not_implemented. These tests exercise two
specific static/transport predicates that were not covered by the prior selected
R1 helper matrix; they do not claim that the catalog scenario ran.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from business_ai_gateway.adapters.onec.client import OneCReadClient, OneCTransportError
from business_ai_gateway.models import Source


ROOT = Path(__file__).resolve().parents[2]
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "tc001_preservation_runner", ROOT / "tests/phase2/run_tc001_r1_preservation.py"
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
TC001_RUNNER = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(TC001_RUNNER)


def _p12_case(**overrides):
    case = {
        "candidate": "candidate-sha",
        "head_after_run": "candidate-sha",
        "source_worktree_clean": True,
        "dependency_hashes_match_candidate": True,
        "image_undici_version": "8.12.3",
        "candidate_undici_version": "8.12.3",
        "selected_test_hashes_match_candidate": True,
        "tested_image_id": "sha256:built-image",
        "image_build": {
            "build_exit_code": 0,
            "candidate_head": "candidate-sha",
            "build_inputs_clean": True,
            "candidate_label": "candidate-sha",
            "image_id": "sha256:built-image",
            "submodule_clean_at_candidate_gitlink": True,
            "candidate_submodule_gitlink_sha": "vendor-sha",
            "submodule_worktree_head": "vendor-sha",
        },
    }
    case.update(overrides)
    return TC001_RUNNER.p12_gate_checks(**case)


def test_p12_accepts_fully_candidate_bound_provenance():
    checks = _p12_case()
    assert all(checks.values())


def test_p12_rejects_modified_selected_test_outside_tc001_module():
    selected = TC001_RUNNER.selected_pytest_support_paths()
    unrelated_selected_test = "tests/test_auth.py"
    assert unrelated_selected_test in selected
    assert unrelated_selected_test != "tests/phase2/test_tc001_r1_preservation.py"
    identities = {
        path: {
            "working_file_git_clean_blob_oid": "same-oid",
            "candidate_head_blob_oid": "same-oid",
        }
        for path in selected
    }
    identities[unrelated_selected_test]["working_file_git_clean_blob_oid"] = "modified-oid"
    matches = TC001_RUNNER.candidate_blob_inventory_matches(identities)
    assert not matches
    checks = _p12_case(selected_test_hashes_match_candidate=matches)
    assert not checks["selected_test_and_support_hashes_match_candidate"]
    assert not all(checks.values())


def test_p12_git_clean_blob_identity_normalizes_crlf_but_rejects_content_changes():
    path = "testbed/fake1c/fixtures/synthetic_profiles.json"
    candidate = TC001_RUNNER.git("rev-parse", "HEAD").strip()
    candidate_content = TC001_RUNNER.git_blob(candidate, path)
    assert candidate_content is not None
    lf_checkout = candidate_content.replace(b"\r\n", b"\n")
    crlf_checkout = lf_checkout.replace(b"\n", b"\r\n")
    edited_content = crlf_checkout + b"changed"

    candidate_oid = TC001_RUNNER.candidate_blob_oid(candidate, path)
    lf_oid = TC001_RUNNER.git_clean_blob_oid(path, lf_checkout)
    crlf_oid = TC001_RUNNER.git_clean_blob_oid(path, crlf_checkout)
    edited_oid = TC001_RUNNER.git_clean_blob_oid(path, edited_content)

    assert candidate_oid is not None
    assert lf_oid == candidate_oid
    assert crlf_oid == candidate_oid
    assert edited_oid is not None and edited_oid != candidate_oid
    assert TC001_RUNNER.candidate_blob_inventory_matches({
        path: {
            "working_file_git_clean_blob_oid": crlf_oid,
            "candidate_head_blob_oid": candidate_oid,
        },
    })
    assert not TC001_RUNNER.candidate_blob_inventory_matches({
        path: {
            "working_file_git_clean_blob_oid": edited_oid,
            "candidate_head_blob_oid": candidate_oid,
        },
    })


def test_p12_sidecar_manifest_and_lock_identity_normalizes_crlf_and_rejects_content_changes():
    candidate = TC001_RUNNER.git("rev-parse", "HEAD").strip()
    paths = (
        "adapters/odata-sidecar/package.json",
        "adapters/odata-sidecar/package-lock.json",
    )

    actual_provenance = TC001_RUNNER.sidecar_dependency_provenance(candidate)
    assert actual_provenance["working_tree_matches_candidate_head"]
    assert actual_provenance["working_tree_manifest_git_clean_blob_oid"] == actual_provenance[
        "candidate_head_manifest_blob_oid"
    ]
    assert actual_provenance["working_tree_lockfile_git_clean_blob_oid"] == actual_provenance[
        "candidate_head_lockfile_blob_oid"
    ]

    for path in paths:
        candidate_content = TC001_RUNNER.git_blob(candidate, path)
        assert candidate_content is not None
        assert b"8.12.3" in candidate_content
        lf_checkout = candidate_content.replace(b"\r\n", b"\n")
        crlf_checkout = lf_checkout.replace(b"\n", b"\r\n")
        changed_content = crlf_checkout.replace(b"8.12.3", b"8.12.4", 1)

        unchanged_identity = TC001_RUNNER.candidate_path_blob_identity(
            candidate, path, crlf_checkout,
        )
        changed_identity = TC001_RUNNER.candidate_path_blob_identity(
            candidate, path, changed_content,
        )

        assert TC001_RUNNER.candidate_blob_inventory_matches({path: unchanged_identity})
        assert not TC001_RUNNER.candidate_blob_inventory_matches({path: changed_identity})


@pytest.mark.parametrize(
    "relative_path",
    (
        "adapters/odata-sidecar/package.json",
        "adapters/odata-sidecar/package-lock.json",
    ),
)
def test_p12_sidecar_provenance_rejects_changed_dependency_file(monkeypatch, relative_path):
    candidate = TC001_RUNNER.git("rev-parse", "HEAD").strip()
    target_path = TC001_RUNNER.ROOT / relative_path
    original_read_bytes = TC001_RUNNER.Path.read_bytes

    def read_bytes(path):
        content = original_read_bytes(path)
        if path == target_path:
            assert b"8.12.3" in content
            return content.replace(b"8.12.3", b"8.12.4", 1)
        return content

    monkeypatch.setattr(TC001_RUNNER.Path, "read_bytes", read_bytes)
    provenance = TC001_RUNNER.sidecar_dependency_provenance(candidate)

    assert not provenance["working_tree_matches_candidate_head"]


def test_p12_rejects_matching_image_version_without_candidate_build_provenance():
    checks = _p12_case(image_build={})
    assert checks["image_installed_undici_matches_candidate"]
    assert not checks["fresh_image_build_succeeded_this_run"]
    assert not all(checks.values())

    mismatched_build = {
        "build_exit_code": 0,
        "candidate_head": "another-sha",
        "build_inputs_clean": True,
        "candidate_label": "another-sha",
        "image_id": "sha256:built-image",
        "submodule_clean_at_candidate_gitlink": True,
        "candidate_submodule_gitlink_sha": "vendor-sha",
        "submodule_worktree_head": "vendor-sha",
    }
    checks = _p12_case(image_build=mismatched_build)
    assert checks["image_installed_undici_matches_candidate"]
    assert not checks["image_build_candidate_head_matches"]
    assert not checks["image_candidate_label_matches"]
    assert not all(checks.values())


def test_p12_rejects_executable_or_dependency_worktree_delta():
    executable_delta = _p12_case(source_worktree_clean=False)
    dependency_delta = _p12_case(dependency_hashes_match_candidate=False)
    assert not executable_delta["source_worktree_clean_against_candidate"]
    assert not all(executable_delta.values())
    assert not dependency_delta["manifest_and_lock_hashes_match_candidate"]
    assert not all(dependency_delta.values())


def test_p01_rejects_unexplained_affected_path():
    unexplained = {
        "path": "src/business_ai_gateway/unmapped_runtime.py",
        "class": "unclassified",
        "rationale": "",
        "surface_applicability": "runtime_python_module",
        "surface_parse_error": None,
        "exports_before": [],
        "exports_after": [],
        "exports_added": [],
        "exports_removed": [],
        "entrypoints_before": [],
        "entrypoints_after": [],
        "entrypoints_added": [],
        "entrypoints_removed": [],
        "dependency_propagation": {},
    }
    assert not TC001_RUNNER.affected_path_inventory_complete([unexplained])


def test_p01_rejects_empty_runtime_surface_or_dependency_propagation():
    runtime_row = {
        "path": "src/business_ai_gateway/known_runtime.py",
        "class": "R1_shared_adapter",
        "rationale": "Known runtime module; candidate import graph and module surface are required.",
        "surface_applicability": "runtime_python_module",
        "surface_inventory_complete": True,
        "surface_completeness_basis": "AST enumeration completed for baseline and candidate.",
        "surface_parse_error": None,
        "exports_before": [],
        "exports_after": [],
        "exports_added": [],
        "exports_removed": [],
        "entrypoints_before": [],
        "entrypoints_after": [],
        "entrypoints_added": [],
        "entrypoints_removed": [],
        "dependency_propagation": {},
    }
    assert not TC001_RUNNER.affected_path_inventory_complete([runtime_row])

    # Match the producer output shape: propagation_for() returns the graph
    # fields directly, and the record helper adds the consumer envelope.
    runtime_row["dependency_propagation"] = TC001_RUNNER.python_dependency_propagation_record({
        "module_present_in_candidate": True,
        "direct_importers": [],
        "transitive_importers": [],
        "named_r1_roots_reaching_module": [],
    })
    runtime_row["surface_inventory_complete"] = False
    assert not TC001_RUNNER.affected_path_inventory_complete([runtime_row])

    runtime_row["surface_inventory_complete"] = True
    assert TC001_RUNNER.affected_path_inventory_complete([runtime_row])


def test_p01_accepts_explicit_non_runtime_dependency_exclusion():
    non_runtime_row = {
        "path": "docs/contract.md",
        "class": "documentation_or_governance",
        "rationale": "Documentation-only acceptance context.",
        "surface_applicability": "not_applicable_non_runtime_python_module",
        "exports_before": [],
        "exports_after": [],
        "exports_added": [],
        "exports_removed": [],
        "entrypoints_before": [],
        "entrypoints_after": [],
        "entrypoints_added": [],
        "entrypoints_removed": [],
        "dependency_propagation": {
            "applicability": "no Python runtime import edge; explicit path classification rationale applies",
            "rationale": "Documentation is not imported as runtime code.",
        },
    }
    assert TC001_RUNNER.affected_path_inventory_complete([non_runtime_row])


def test_p01_accepts_runtime_dependency_manifest_with_javascript_importers_and_image_copy():
    propagation = {
        "candidate_head_package_dependency": {
            "package": "undici",
            "javascript_importers": [
                "adapters/odata-sidecar/egress.mjs",
                "adapters/odata-sidecar/server.mjs",
            ],
            "dockerfile_copies_runtime_package": True,
            "dockerfile_inputs": ["adapters/odata-sidecar/Dockerfile"],
        },
    }
    rows = [
        {
            "path": path,
            "class": "R1_shared_adapter",
            "rationale": "Sidecar dependency manifest is reconciled with its importers and runtime image.",
            "surface_applicability": "not_applicable_non_runtime_python_module",
            "exports_before": [],
            "exports_after": [],
            "exports_added": [],
            "exports_removed": [],
            "entrypoints_before": [],
            "entrypoints_after": [],
            "entrypoints_added": [],
            "entrypoints_removed": [],
            "dependency_propagation": propagation,
        }
        for path in (
            "adapters/odata-sidecar/package.json",
            "adapters/odata-sidecar/package-lock.json",
        )
    ]
    assert TC001_RUNNER.affected_path_inventory_complete(rows)

    rows[0]["dependency_propagation"]["candidate_head_package_dependency"][
        "dockerfile_copies_runtime_package"
    ] = False
    assert not TC001_RUNNER.affected_path_inventory_complete(rows)


def test_evidence_output_rejects_path_outside_project_root():
    outside_path = ROOT.parent / "tc001-outside-project.json"
    with pytest.raises(ValueError, match="must stay within project root"):
        TC001_RUNNER.resolve_output_path(outside_path)


def _source() -> Source:
    return Source(
        id="tc001-source",
        project="onec",
        kind="onec_odata",
        display_name="TC001 fixture",
        base_url="https://registered.example.test/odata/standard.odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=("synthetic",),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


@pytest.mark.asyncio
async def test_tc001_onec_redirect_is_not_followed_or_leaked():
    seen: list[httpx.Request] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://unregistered.example.test/escape"},
            request=request,
        )

    client = OneCReadClient(
        timeout_seconds=2,
        max_response_bytes=1024,
        transport=httpx.MockTransport(upstream),
    )
    try:
        with pytest.raises(OneCTransportError, match="1C_UPSTREAM_HTTP_302") as failure:
            await client.get_bytes(
                _source(),
                "$metadata",
                username="synthetic-user",
                password="synthetic-secret",
            )
        assert len(seen) == 1
        assert str(seen[0].url) == (
            "https://registered.example.test/odata/standard.odata/$metadata"
        )
        rendered = str(failure.value)
        assert "unregistered.example.test" not in rendered
        assert "synthetic-secret" not in rendered
    finally:
        await client.close()


def test_tc001_phase2_does_not_enable_r1_writes_or_production():
    """Check public R1 MCP and HTTP route declarations plus the release authority."""
    server_tree = ast.parse(
        (ROOT / "src/business_ai_gateway/server.py").read_text(encoding="utf-8")
    )
    tool_functions = []
    for node in ast.walk(server_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            tool_functions.append(node)
            assert any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                and any(
                    keyword.arg == "annotations"
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "CHATGPT_READ_ONLY_ANNOTATIONS"
                    for keyword in decorator.keywords
                )
                for decorator in node.decorator_list
            ), f"MCP tool {node.name} is not declared read-only"
    assert tool_functions, "no MCP tools were found for the R1 route audit"

    app_tree = ast.parse(
        (ROOT / "src/business_ai_gateway/app.py").read_text(encoding="utf-8")
    )
    route_count = 0
    for node in ast.walk(app_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "custom_route"
            ):
                continue
            route_count += 1
            methods = next(
                (
                    keyword.value
                    for keyword in decorator.keywords
                    if keyword.arg == "methods"
                ),
                None,
            )
            assert isinstance(methods, (ast.List, ast.Tuple))
            assert all(
                isinstance(method, ast.Constant) and method.value == "GET"
                for method in methods.elts
            ), f"non-GET public route declared by {node.name}"
    assert route_count, "no public custom routes were found for the R1 route audit"

    gate = json.loads(
        (ROOT / "governance/GATE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert gate.get("release_2") == "NO_GO"
    assert all(
        row.get("production_authorization") == "NONE"
        for row in gate.get("gates", [])
    )

    public_client_methods = {
        name for name in dir(OneCReadClient) if not name.startswith("_")
    }
    assert not public_client_methods.intersection({"post", "put", "patch", "delete"})


def test_tc001_admin_dynamic_routes_are_classified_and_guarded():
    """Admin POST/PATCH routes are authorized control-plane routes, not R1 writers."""
    source = (ROOT / "src/business_ai_gateway/admin_api.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_admin_routes"
    )
    routes_assignment = next(
        node for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "routes" for target in node.targets)
    )
    actual_routes = {}
    for row in routes_assignment.value.elts:
        path = ast.literal_eval(row.elts[0])
        methods = tuple(ast.literal_eval(row.elts[1]))
        handler = ast.unparse(row.elts[2])
        actual_routes[(path, methods)] = handler
    expected_routes = {
        ("/admin/v1/me", ("GET",)): "api.me",
        ("/admin/v1/overview", ("GET",)): "api.overview_view",
        ("/admin/v1/sources", ("GET",)): "api.sources",
        ("/admin/v1/sources/{source_id}", ("GET",)): "api.source_detail_view",
        ("/admin/v1/companies", ("GET",)): "api.companies",
        ("/admin/v1/companies/{company_id}", ("GET",)): "api.company_detail_view",
        ("/admin/v1/capabilities", ("GET",)): "api.capabilities",
        ("/admin/v1/grants", ("GET",)): "api.grants",
        ("/admin/v1/platform-role-bindings", ("GET",)): "api.platform_role_bindings",
        ("/admin/v1/principals/resolve", ("GET",)): "api.principal_resolve",
        ("/admin/v1/effective-access", ("GET",)): "api.effective_access",
        ("/admin/v1/business-roles", ("GET",)): "api.business_roles",
        ("/admin/v1/business-role-assignments", ("GET",)): "api.business_role_assignments",
        ("/admin/v1/capability-overrides", ("GET",)): "api.capability_overrides",
        ("/admin/v1/company-scope-mappings", ("GET",)): "api.company_scope_mappings",
        ("/admin/v1/semantic-profiles", ("GET",)): "api.profiles",
        ("/admin/v1/semantic-profiles/{profile_id}", ("GET",)): "api.profile_detail",
        ("/admin/v1/audit", ("GET",)): "api.audit",
        ("/admin/v1/semantic-profiles", ("POST",)): "api.semantic_profile_create",
        ("/admin/v1/semantic-profiles/{profile_id}/mappings", ("POST",)): "api.semantic_mapping_create",
        ("/admin/v1/semantic-profiles/{profile_id}/validate", ("POST",)): "api.semantic_profile_validate",
        ("/admin/v1/semantic-profiles/{profile_id}/retire", ("POST",)): "api.semantic_profile_retire",
        ("/admin/v1/source-probes", ("POST",)): "api.source_probe",
        ("/admin/v1/sources", ("POST",)): "api.source_create",
        ("/admin/v1/sources/{source_id}", ("PATCH",)): "api.source_update",
        ("/admin/v1/sources/{source_id}/capability-refresh", ("POST",)): "api.capability_refresh",
        ("/admin/v1/companies", ("POST",)): "api.company_create",
        ("/admin/v1/companies/{company_id}", ("PATCH",)): "api.company_update",
        ("/admin/v1/grants", ("POST",)): "api.grant_create",
        ("/admin/v1/grants/{grant_id}/revoke", ("POST",)): "api.grant_revoke",
        ("/admin/v1/platform-role-bindings", ("POST",)): "api.platform_role_create",
        ("/admin/v1/platform-role-bindings/{binding_id}/revoke", ("POST",)): "api.platform_role_revoke",
        ("/admin/v1/business-role-assignments", ("POST",)): "api.business_role_assign",
        ("/admin/v1/business-role-assignments/{assignment_id}/revoke", ("POST",)): "api.business_role_revoke",
        ("/admin/v1/capability-overrides", ("POST",)): "api.capability_override_create",
        ("/admin/v1/capability-overrides/{override_id}/revoke", ("POST",)): "api.capability_override_revoke",
        ("/admin/v1/company-scope-mappings", ("POST",)): "api.company_scope_mapping_create",
        ("/admin/v1/sources/{source_id}/drift-acknowledgements", ("POST",)): "api.drift_ack",
    }
    assert actual_routes == expected_routes

    api_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AdminAPI"
    )
    serve = next(
        node for node in api_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "serve"
    )
    serve_handler = next(
        node for node in serve.body
        if isinstance(node, ast.Try)
    )
    guard_assignment = next(
        node for node in serve_handler.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "guard" for target in node.targets)
    )
    guard_expr = guard_assignment.value
    assert isinstance(guard_expr, ast.IfExp), "CSRF check must be conditional on request method"
    assert isinstance(guard_expr.test, ast.Compare)
    assert isinstance(guard_expr.test.left, ast.Attribute)
    assert isinstance(guard_expr.test.left.value, ast.Name)
    assert guard_expr.test.left.value.id == "request"
    assert guard_expr.test.left.attr == "method"
    assert len(guard_expr.test.ops) == 1 and isinstance(guard_expr.test.ops[0], ast.In)
    mutation_methods = ast.literal_eval(guard_expr.test.comparators[0])
    assert mutation_methods == {"POST", "PUT", "PATCH", "DELETE"}
    assert isinstance(guard_expr.body, ast.Await)
    assert isinstance(guard_expr.body.value, ast.Call)
    assert isinstance(guard_expr.body.value.func, ast.Attribute)
    assert guard_expr.body.value.func.attr == "csrf_guard"
    assert ast.unparse(guard_expr.body.value.args[0]) == "request"
    assert isinstance(guard_expr.orelse, ast.Constant) and guard_expr.orelse.value is None
    guarded_response = next(
        node for node in serve_handler.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "response" for target in node.targets)
    )
    response_expr = guarded_response.value
    assert isinstance(response_expr, ast.IfExp), "CSRF denial must prevent handler execution"
    assert isinstance(response_expr.test, ast.Compare)
    assert ast.unparse(response_expr.test) == "guard is not None"
    assert isinstance(response_expr.body, ast.Name) and response_expr.body.id == "guard"
    assert isinstance(response_expr.orelse, ast.Await)
    assert ast.unparse(response_expr.orelse.value) == "handler(request)"

    # Prove the route table loop registers exactly its handler variable, and that
    # the handler closure forwards its captured route handler through api.serve.
    api_loop = next(
        node for node in function.body
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "routes"
    )
    assert ast.unparse(api_loop.target) == "(path, methods, handler)"
    api_registration = next(
        node for node in ast.walk(api_loop)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Attribute)
        and node.func.func.attr == "custom_route"
    )
    assert ast.unparse(api_registration) == "mcp.custom_route(path, methods=methods)(guarded)"
    api_wrapper = next(
        node for node in api_loop.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "guarded"
    )
    api_return = next(node for node in api_wrapper.body if isinstance(node, ast.Return))
    assert isinstance(api_return.value, ast.Await)
    assert ast.unparse(api_return.value.value) == "api.serve(request, _handler)"
    assert api_wrapper.args.args[-1].arg == "_handler"
    handler_default = next(
        node for node in api_wrapper.args.defaults
        if isinstance(node, ast.Name) and node.id == "handler"
    )
    assert isinstance(handler_default, ast.Name) and handler_default.id == "handler"

    literal_registrations = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Call):
            continue
        registrar = node.func
        if not isinstance(registrar.func, ast.Attribute) or registrar.func.attr != "custom_route":
            continue
        if not registrar.args or not isinstance(registrar.args[0], ast.Constant) or not isinstance(registrar.args[0].value, str):
            continue
        methods = next((kw.value for kw in registrar.keywords if kw.arg == "methods"), None)
        literal_registrations[(registrar.args[0].value, tuple(ast.literal_eval(methods)))] = ast.unparse(node.args[0])
    expected_literal_registrations = {
        ("/admin", ("GET",)): "api.admin_root",
        ("/admin/", ("GET",)): "api.admin_ui",
        ("/admin/static/admin.js", ("GET",)): "api.admin_js",
    }
    assert literal_registrations == expected_literal_registrations

    # Browser auth routes are dynamically looped, including the POST logout endpoint.
    browser_gate = next(
        node for node in function.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Attribute)
        and node.test.attr == "admin_ui_enabled"
    )
    browser_loop = next(
        node for node in browser_gate.body
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
    )
    browser_routes = browser_loop.iter
    actual_browser_routes = {
        (ast.literal_eval(item.elts[0]), tuple(ast.literal_eval(item.elts[1]))): ast.unparse(item.elts[2])
        for item in browser_routes.elts
    }
    assert actual_browser_routes == {
        ("/admin/login", ("GET",)): "api.login",
        ("/admin/callback", ("GET",)): "api.callback",
        ("/admin/logout", ("POST",)): "api.logout",
    }
    browser_registration = next(
        node for node in ast.walk(browser_loop)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Attribute)
        and node.func.func.attr == "custom_route"
    )
    assert ast.unparse(browser_registration) == "mcp.custom_route(path, methods=methods)(browser_route)"
    browser_wrapper = next(
        node for node in browser_loop.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "browser_route"
    )
    browser_return = next(node for node in browser_wrapper.body if isinstance(node, ast.Return))
    assert isinstance(browser_return.value, ast.Await)
    assert ast.unparse(browser_return.value.value) == "api.serve(request, _handler)"
    assert browser_wrapper.args.args[-1].arg == "_handler"
    browser_handler_default = next(
        node for node in browser_wrapper.args.defaults
        if isinstance(node, ast.Name) and node.id == "handler"
    )
    assert isinstance(browser_handler_default, ast.Name) and browser_handler_default.id == "handler"

    # The frozen baseline has no admin_api module; the candidate adds an admin
    # control-plane surface. Its POST/PATCH routes are explicitly scoped by P10
    # role/scope tests and are not R1 OneC document/register write routes.


def test_tc001_r1_evidence_path_does_not_reach_r2_native_parser_or_vault():
    """R2 parser/vault modules are excluded only while absent from the R1 import graph."""
    runtime_root = ROOT / "src/business_ai_gateway"
    forbidden = ("business_ai_gateway.phase2.safe_parser", "business_ai_gateway.phase2.artifact_vault")
    violations = []
    for path in runtime_root.rglob("*.py"):
        if "phase2" in path.relative_to(runtime_root).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            pytest.fail(f"R1 runtime source could not be inspected: {path}: {type(exc).__name__}")
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module
            if module and any(name in module for name in forbidden):
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}:{module}")
    assert not violations, "R1 imports R2 parser/vault: " + ", ".join(violations)
