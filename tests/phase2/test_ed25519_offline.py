"""Offline tests for the pure-Python test-lane Ed25519 signer (RFC 8032 5.1).

Vectors from RFC 8032 section 7.1. Included: TEST 1, TEST 2, TEST 3 (full:
public key, exact signature, verify) and the TEST SHA(abc) public key only.
Omitted: TEST 1024 (1023-byte message) and the TEST SHA(abc) signature,
because they could not be reproduced byte for byte from memory.
"""

from __future__ import annotations

import hashlib

import pytest

from business_ai_gateway.phase2 import ed25519

_L = 2**252 + 27742317777372353535851937790883648493

# (name, seed, public key, message, signature) -- all hex
_VECTORS = [
    (
        "TEST 1",
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "TEST 2",
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da08"
        "5ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "TEST 3",
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18"
        "ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]

_SHA_ABC_SEED = "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5"
_SHA_ABC_PUB = "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e"


@pytest.mark.parametrize("name,seed,pub,msg,sig", _VECTORS, ids=[v[0] for v in _VECTORS])
def test_rfc8032_vectors(name, seed, pub, msg, sig):
    seed_b, pub_b, msg_b, sig_b = map(bytes.fromhex, (seed, pub, msg, sig))
    assert ed25519.public_key_from_seed(seed_b) == pub_b
    assert ed25519.sign(seed_b, msg_b) == sig_b
    assert ed25519.verify(pub_b, msg_b, sig_b) is True


def test_rfc8032_sha_abc_public_key_only():
    assert (
        ed25519.public_key_from_seed(bytes.fromhex(_SHA_ABC_SEED)).hex() == _SHA_ABC_PUB
    )


def _t1():
    _, seed, pub, msg, sig = _VECTORS[1]
    return bytes.fromhex(seed), bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)


def test_flipped_message_bit_rejected():
    _, pub, msg, sig = _t1()
    assert ed25519.verify(pub, bytes([msg[0] ^ 1]), sig) is False


def test_flipped_signature_bits_rejected():
    _, pub, msg, sig = _t1()
    for idx in (0, 31, 32, 63):
        bad = bytearray(sig)
        bad[idx] ^= 0x01
        assert ed25519.verify(pub, msg, bytes(bad)) is False


def test_wrong_key_rejected():
    _, _, msg, sig = _t1()
    other_pub = bytes.fromhex(_VECTORS[0][2])
    assert ed25519.verify(other_pub, msg, sig) is False


def test_s_ge_l_malleated_signature_rejected():
    _, pub, msg, sig = _t1()
    s = int.from_bytes(sig[32:], "little")
    malleated = sig[:32] + (s + _L).to_bytes(32, "little")  # s + L < 2**256
    assert ed25519.verify(pub, msg, malleated) is False
    assert ed25519.verify(pub, msg, sig[:32] + _L.to_bytes(32, "little")) is False


def test_truncated_and_extended_signature_rejected():
    _, pub, msg, sig = _t1()
    assert ed25519.verify(pub, msg, sig[:63]) is False
    assert ed25519.verify(pub, msg, b"") is False
    assert ed25519.verify(pub, msg, sig + b"\x00") is False


def test_bad_key_lengths_rejected():
    _, pub, msg, sig = _t1()
    assert ed25519.verify(pub[:31], msg, sig) is False
    assert ed25519.verify(pub + b"\x00", msg, sig) is False
    assert ed25519.verify(b"", msg, sig) is False


def test_non_canonical_and_undecodable_points_rejected():
    _, pub, msg, sig = _t1()
    p = 2**255 - 19
    # y = p (non-canonical encoding of y = 0) as public key and as R
    noncanon = p.to_bytes(32, "little")
    assert ed25519.verify(noncanon, msg, sig) is False
    assert ed25519.verify(pub, msg, noncanon + sig[32:]) is False
    # y = 2 has no valid x on the curve
    assert ed25519.verify((2).to_bytes(32, "little"), msg, sig) is False


def test_bad_seed_lengths_raise():
    for bad in (b"", b"\x00" * 31, b"\x00" * 33):
        with pytest.raises(ValueError):
            ed25519.public_key_from_seed(bad)
        with pytest.raises(ValueError):
            ed25519.sign(bad, b"m")


def test_deterministic_round_trips():
    for i in range(20):
        seed = hashlib.sha256(b"ed25519-offline-seed-%d" % i).digest()
        msg = hashlib.sha512(b"ed25519-offline-msg-%d" % i).digest()[: i * 3]
        pub = ed25519.public_key_from_seed(seed)
        sig = ed25519.sign(seed, msg)
        assert len(pub) == 32 and len(sig) == 64
        assert ed25519.sign(seed, msg) == sig
        assert ed25519.verify(pub, msg, sig) is True
        assert ed25519.verify(pub, msg + b"x", sig) is False
