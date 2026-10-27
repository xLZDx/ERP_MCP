"""Acceptance tests for disposable Windows DPAPI signer provisioning.

All key generation and DPAPI calls are replaced by deterministic test doubles. The tests exercise
only temporary files under the test runner's temporary directory and never create real key bytes.
"""
from __future__ import annotations

import builtins
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import erp_mcp_private_writer.signer_provisioning as provisioning


_SEED = b"test-private-seed-material-00000"
_PUBLIC = b"P" * 32
_CIPHERTEXT = b"mocked-dpapi-ciphertext"


def _mock_windows_crypto(
        protected_result: object,
        unprotected_result: object = ("ERP_MCP private writer Ed25519 seed", _SEED),
        *,
        unprotect_side_effect: Exception | None = None):
    """Patch platform imports so no real Ed25519 generation or DPAPI API can run."""
    raw_encoding = object()
    raw_format = object()
    no_encryption = object()
    public_key = SimpleNamespace(public_bytes=Mock(return_value=_PUBLIC))
    private_key = SimpleNamespace(
        private_bytes=Mock(return_value=_SEED), public_key=Mock(return_value=public_key),
    )
    key_type = SimpleNamespace(generate=Mock(return_value=private_key))
    serialization = SimpleNamespace(
        Encoding=SimpleNamespace(Raw=raw_encoding),
        PrivateFormat=SimpleNamespace(Raw=raw_format),
        PublicFormat=SimpleNamespace(Raw=raw_format),
        NoEncryption=Mock(return_value=no_encryption),
    )
    crypto_primitives = SimpleNamespace(serialization=serialization)
    crypto_ed25519 = SimpleNamespace(Ed25519PrivateKey=key_type)
    win32crypt = SimpleNamespace(
        CryptProtectData=Mock(return_value=protected_result),
        CryptUnprotectData=Mock(
            return_value=unprotected_result,
            side_effect=unprotect_side_effect,
        ),
    )
    original_import = builtins.__import__

    def mocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "win32crypt":
            return win32crypt
        if name == "cryptography.hazmat.primitives":
            return crypto_primitives
        if name == "cryptography.hazmat.primitives.asymmetric.ed25519":
            return crypto_ed25519
        return original_import(name, globals, locals, fromlist, level)

    return SimpleNamespace(
        raw_encoding=raw_encoding,
        raw_format=raw_format,
        no_encryption=no_encryption,
        public_key=public_key,
        private_key=private_key,
        key_type=key_type,
        serialization=serialization,
        win32crypt=win32crypt,
        importer=mocked_import,
    )


class _SafeProvisioningDiagnostics:
    """Capture only provisioning-frame line/type pairs and mock call counts."""

    def __init__(self, doubles) -> None:
        self._doubles = doubles
        self.exceptions: list[tuple[int, str]] = []
        self._previous_trace = None
        self._function_code = provisioning.provision_windows_dpapi_ed25519_key.__code__

    def __enter__(self):
        self._previous_trace = sys.gettrace()
        sys.settrace(self._trace)
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        sys.settrace(self._previous_trace)
        return False

    def _trace(self, frame, event, argument):
        if frame.f_code is self._function_code and event == "exception":
            exception_type = argument[0]
            self.exceptions.append((frame.f_lineno, exception_type.__name__))
        return self._trace

    def safe_summary(self) -> str:
        d = self._doubles
        calls = {
            "generate": d.key_type.generate.call_count,
            "private_bytes": d.private_key.private_bytes.call_count,
            "public_key": d.private_key.public_key.call_count,
            "public_bytes": d.public_key.public_bytes.call_count,
            "protect_data": d.win32crypt.CryptProtectData.call_count,
            "unprotect_data": d.win32crypt.CryptUnprotectData.call_count,
        }
        return f"mock_stage_calls={calls}; provisioning_frame_exceptions={self.exceptions}"


class WindowsDpapiSignerProvisioningAcceptance(unittest.TestCase):
    """Contract: create a protected seed file and return only its public identity."""

    def _invoke_with_mocks(self, path: Path, protected_result: object):
        doubles = _mock_windows_crypto(protected_result)
        diagnostics = _SafeProvisioningDiagnostics(doubles)
        with diagnostics, patch.object(provisioning.sys, "platform", "win32"), \
                patch.object(builtins, "__import__", side_effect=doubles.importer):
            try:
                result = provisioning.provision_windows_dpapi_ed25519_key(path)
            except provisioning.SignerProvisioningError as error:
                self.fail(
                    f"provisioning refused with {error.code}; {diagnostics.safe_summary()}"
                )
        return result, doubles

    def test_non_windows_refuses_before_crypto_import_or_file_creation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            root = Path(directory)
            destination = root / "signer.dpapi"
            with patch.object(provisioning.sys, "platform", "linux"):
                with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                    provisioning.provision_windows_dpapi_ed25519_key(destination)
            self.assertEqual(caught.exception.code, "SIGNER_PROVISIONING_PLATFORM_UNSUPPORTED")
            self.assertEqual(tuple(root.iterdir()), ())

    def test_success_publishes_only_mocked_ciphertext_and_returns_public_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            destination = Path(directory) / "signer.dpapi"
            result, doubles = self._invoke_with_mocks(
                destination, _CIPHERTEXT,
            )

            doubles.key_type.generate.assert_called_once_with()
            doubles.private_key.private_bytes.assert_called_once_with(
                encoding=doubles.raw_encoding,
                format=doubles.raw_format,
                encryption_algorithm=doubles.no_encryption,
            )
            doubles.private_key.public_key.assert_called_once_with()
            doubles.public_key.public_bytes.assert_called_once_with(
                encoding=doubles.raw_encoding,
                format=doubles.raw_format,
            )
            doubles.win32crypt.CryptProtectData.assert_called_once_with(
                _SEED, "ERP_MCP private writer Ed25519 seed", None, None, None, 0x1,
            )
            doubles.win32crypt.CryptUnprotectData.assert_called_once_with(
                _CIPHERTEXT, None, None, None, 0,
            )
            self.assertEqual(destination.read_bytes(), _CIPHERTEXT)
            self.assertNotEqual(destination.read_bytes(), _SEED)
            self.assertEqual(result.protected_seed_path, destination)
            self.assertEqual(result.public_key_bytes, _PUBLIC)
            self.assertEqual(result.public_key_sha256, hashlib.sha256(_PUBLIC).hexdigest())
            self.assertEqual(
                {field.name for field in provisioning.ProvisionedEd25519PublicKey.__dataclass_fields__.values()},
                {"protected_seed_path", "public_key_bytes", "public_key_sha256"},
            )
            self.assertFalse(hasattr(result, "seed"))
            self.assertNotIn(_SEED.decode("ascii"), repr(result))

    def test_unprotect_refusal_never_creates_or_publishes_a_blob(self) -> None:
        cases = (
            ("raises", ("description", _SEED), RuntimeError("sensitive detail")),
            ("malformed-tuple", ("description",), None),
            ("non-tuple-result", _SEED, None),
            ("wrong-type", ("description", bytearray(_SEED)), None),
            ("wrong-length", ("description", _SEED[:-1]), None),
            ("wrong-seed", ("description", b"X" * len(_SEED)), None),
        )
        for name, unprotected_result, side_effect in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory(
                    prefix="signer-provisioning-") as directory:
                root = Path(directory)
                destination = root / "signer.dpapi"
                doubles = _mock_windows_crypto(
                    _CIPHERTEXT,
                    unprotected_result,
                    unprotect_side_effect=side_effect,
                )
                diagnostics = _SafeProvisioningDiagnostics(doubles)
                with patch.object(provisioning.sys, "platform", "win32"), \
                        patch.object(builtins, "__import__", side_effect=doubles.importer), \
                        patch.object(provisioning.tempfile, "mkstemp") as create_temp, \
                        diagnostics:
                    with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                        provisioning.provision_windows_dpapi_ed25519_key(destination)

                self.assertEqual(
                    caught.exception.code, "SIGNER_PROVISIONING_ROUNDTRIP_FAILED",
                    msg=diagnostics.safe_summary(),
                )
                doubles.win32crypt.CryptProtectData.assert_called_once()
                doubles.win32crypt.CryptUnprotectData.assert_called_once_with(
                    _CIPHERTEXT, None, None, None, 0,
                )
                create_temp.assert_not_called()
                self.assertFalse(destination.exists())
                self.assertEqual(tuple(root.iterdir()), ())

    def test_existing_destination_is_refused_without_changing_its_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            root = Path(directory)
            destination = root / "signer.dpapi"
            existing = b"pre-existing protected blob"
            destination.write_bytes(existing)
            doubles = _mock_windows_crypto(_CIPHERTEXT)
            diagnostics = _SafeProvisioningDiagnostics(doubles)
            with patch.object(provisioning.sys, "platform", "win32"), \
                    patch.object(builtins, "__import__", side_effect=doubles.importer), \
                    diagnostics:
                with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                    provisioning.provision_windows_dpapi_ed25519_key(destination)

            self.assertEqual(
                caught.exception.code, "SIGNER_PROVISIONING_DESTINATION_EXISTS",
                msg=diagnostics.safe_summary(),
            )
            self.assertEqual(destination.read_bytes(), existing)
            self.assertEqual(tuple(root.iterdir()), (destination,))

    def test_invalid_dpapi_results_refuse_without_publishing_or_leaking_temp_files(self) -> None:
        invalid_results = (None, b"", b"C" * (64 * 1024 + 1))
        for protected_result in invalid_results:
            with self.subTest(result_type=type(protected_result).__name__):
                with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
                    root = Path(directory)
                    destination = root / "signer.dpapi"
                    doubles = _mock_windows_crypto(protected_result)
                    diagnostics = _SafeProvisioningDiagnostics(doubles)
                    with patch.object(provisioning.sys, "platform", "win32"), \
                            patch.object(builtins, "__import__", side_effect=doubles.importer), \
                            diagnostics:
                        with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                            provisioning.provision_windows_dpapi_ed25519_key(destination)
                    self.assertEqual(
                        caught.exception.code, "SIGNER_PROVISIONING_OUTPUT_INVALID",
                        msg=diagnostics.safe_summary(),
                    )
                    self.assertFalse(destination.exists())
                    self.assertEqual(tuple(root.iterdir()), ())

    def test_write_failure_cleans_invocation_temp_and_preserves_sibling_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            root = Path(directory)
            destination = root / "signer.dpapi"
            sibling = root / "operator-owned.marker"
            sibling.write_bytes(b"preserve")
            doubles = _mock_windows_crypto(_CIPHERTEXT)
            diagnostics = _SafeProvisioningDiagnostics(doubles)
            with patch.object(provisioning.sys, "platform", "win32"), \
                    patch.object(builtins, "__import__", side_effect=doubles.importer), \
                    patch.object(provisioning.os, "fsync", side_effect=OSError("injected write failure")) as fsync_spy, \
                    diagnostics:
                with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                    provisioning.provision_windows_dpapi_ed25519_key(destination)

            self.assertEqual(
                caught.exception.code, "SIGNER_PROVISIONING_FAILED",
                msg=diagnostics.safe_summary(),
            )
            fsync_spy.assert_called_once()
            self.assertEqual(doubles.win32crypt.CryptProtectData.call_count, 1)
            self.assertFalse(destination.exists())
            self.assertEqual(sibling.read_bytes(), b"preserve")
            self.assertEqual(tuple(root.iterdir()), (sibling,))

    def test_post_publication_failure_cleans_only_created_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            root = Path(directory)
            destination = root / "signer.dpapi"
            sibling = root / "operator-owned.marker"
            sibling.write_bytes(b"preserve")
            doubles = _mock_windows_crypto(_CIPHERTEXT)
            result_constructor = Mock(side_effect=RuntimeError("injected post-publication failure"))
            with patch.object(provisioning.sys, "platform", "win32"), \
                    patch.object(builtins, "__import__", side_effect=doubles.importer), \
                    patch.object(
                        provisioning, "ProvisionedEd25519PublicKey", result_constructor,
                    ):
                with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                    provisioning.provision_windows_dpapi_ed25519_key(destination)

            self.assertEqual(caught.exception.code, "SIGNER_PROVISIONING_FAILED")
            result_constructor.assert_called_once()
            self.assertEqual(doubles.win32crypt.CryptProtectData.call_count, 1)
            self.assertFalse(destination.exists())
            self.assertEqual(sibling.read_bytes(), b"preserve")
            self.assertEqual(tuple(root.iterdir()), (sibling,))

    def test_replacement_sentinel_survives_publication_identity_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="signer-provisioning-") as directory:
            root = Path(directory)
            destination = root / "signer.dpapi"
            sibling = root / "operator-owned.marker"
            replacement_source = root / "replacement-source"
            sibling.write_bytes(b"preserve")
            replacement = b"concurrent replacement must survive"
            replacement_source.write_bytes(replacement)
            doubles = _mock_windows_crypto(_CIPHERTEXT)
            original_rename = provisioning.os.rename
            diagnostics = _SafeProvisioningDiagnostics(doubles)

            def publish_then_replace(source: Path, target: Path) -> None:
                original_rename(source, target)
                provisioning.os.replace(replacement_source, target)

            with patch.object(provisioning.sys, "platform", "win32"), \
                    patch.object(builtins, "__import__", side_effect=doubles.importer), \
                    patch.object(provisioning.os, "rename", side_effect=publish_then_replace), \
                    diagnostics:
                with self.assertRaises(provisioning.SignerProvisioningError) as caught:
                    provisioning.provision_windows_dpapi_ed25519_key(destination)

            self.assertEqual(
                caught.exception.code, "SIGNER_PROVISIONING_PUBLICATION_CONFLICT",
                msg=diagnostics.safe_summary(),
            )
            self.assertEqual(destination.read_bytes(), replacement)
            self.assertEqual(sibling.read_bytes(), b"preserve")
            self.assertEqual({path.name for path in root.iterdir()}, {
                destination.name, sibling.name,
            })


if __name__ == "__main__":
    unittest.main()
