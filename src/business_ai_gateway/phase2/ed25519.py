"""Pure-Python Ed25519 (RFC 8032 section 5.1), stdlib only (hashlib).

TEST-LANE signer for the simulated D9/D10b components. It is NOT audited,
NOT constant-time, and must NOT be used for production keys. All seeds used
with this module are synthetic. Clarity is preferred over speed: points use
extended homogeneous coordinates and field inversion is ``pow(x, p-2, p)``.
"""

from __future__ import annotations

import hashlib

__all__ = ["is_small_order", "public_key_from_seed", "sign", "verify"]

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

_SEED_LEN = 32
_KEY_LEN = 32
_SIG_LEN = 64


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign_bit: int) -> int | None:
    """Recover x from y per RFC 8032 5.1.3; None when no valid x exists."""
    if y >= _P:
        return None
    x2 = ((y * y - 1) * _inv(_D * y * y + 1)) % _P
    if x2 == 0:
        return None if sign_bit else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = (x * _SQRT_M1) % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign_bit:
        x = _P - x
    return x


# Extended homogeneous coordinates (X, Y, Z, T) with x = X/Z, y = Y/Z, T = XY/Z.
_Point = tuple[int, int, int, int]
_NEUTRAL: _Point = (0, 1, 1, 0)


def _add(p: _Point, q: _Point) -> _Point:
    a = ((p[1] - p[0]) * (q[1] - q[0])) % _P
    b = ((p[1] + p[0]) * (q[1] + q[0])) % _P
    c = (2 * p[3] * q[3] * _D) % _P
    d = (2 * p[2] * q[2]) % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _mul(s: int, p: _Point) -> _Point:
    q = _NEUTRAL
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p: _Point, q: _Point) -> bool:
    if (p[0] * q[2] - q[0] * p[2]) % _P != 0:
        return False
    return (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p: _Point) -> bytes:
    zinv = _inv(p[2])
    x = (p[0] * zinv) % _P
    y = (p[1] * zinv) % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes) -> _Point | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign_bit = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign_bit)  # rejects y >= p (non-canonical)
    if x is None:
        return None
    return (x, y, 1, (x * y) % _P)


def _is_small_order_point(p: _Point) -> bool:
    """True when [8]P is the neutral point, i.e. P has order 1, 2, 4 or 8."""
    return _equal(_mul(8, p), _NEUTRAL)


def is_small_order(point_bytes: bytes) -> bool:
    """True when the 32-byte encoding decodes to a small-order point (order dividing 8).

    Undecodable input returns False (it is rejected by decompression elsewhere).
    """
    if not isinstance(point_bytes, (bytes, bytearray)):
        return False
    point = _decompress(bytes(point_bytes))
    return point is not None and _is_small_order_point(point)


_G_Y = (4 * _inv(5)) % _P
_G_X = _recover_x(_G_Y, 0)
assert _G_X is not None
_G: _Point = (_G_X, _G_Y, 1, (_G_X * _G_Y) % _P)


def _expand_seed(seed: bytes) -> tuple[int, bytes]:
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != _SEED_LEN:
        raise ValueError("seed must be exactly 32 bytes")
    h = _sha512(bytes(seed))
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key_from_seed(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte seed."""
    a, _ = _expand_seed(seed)
    return _compress(_mul(a, _G))


def sign(seed: bytes, message: bytes) -> bytes:
    """Return the 64-byte Ed25519 signature of ``message``."""
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    message = bytes(message)
    a, prefix = _expand_seed(seed)
    pub = _compress(_mul(a, _G))
    r = int.from_bytes(_sha512(prefix + message), "little") % _L
    big_r = _compress(_mul(r, _G))
    k = int.from_bytes(_sha512(big_r + pub + message), "little") % _L
    s = (r + k * a) % _L
    return big_r + int.to_bytes(s, 32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return True only for a valid, canonical signature; never raises on bad input."""
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != _KEY_LEN:
        return False
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != _SIG_LEN:
        return False
    if not isinstance(message, (bytes, bytearray)):
        return False
    public_key, signature, message = bytes(public_key), bytes(signature), bytes(message)
    a_point = _decompress(public_key)
    if a_point is None:
        return False
    r_bytes = signature[:32]
    r_point = _decompress(r_bytes)
    if r_point is None:
        return False
    # Small-order A or R makes the cofactorless equation satisfiable for any message (e.g. A = R = neutral, S = 0).
    if _is_small_order_point(a_point) or _is_small_order_point(r_point):
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_sha512(r_bytes + public_key + message), "little") % _L
    # Cofactorless check: [S]B == R + [k]A
    lhs = _mul(s, _G)
    rhs = _add(r_point, _mul(k, a_point))
    return _equal(lhs, rhs)
