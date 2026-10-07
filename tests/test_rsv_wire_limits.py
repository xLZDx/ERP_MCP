import asyncio

import anyio
import mcp.client.stdio as sdk_stdio
import pytest

from business_ai_gateway.adapters.onec import rsv_privacy
from business_ai_gateway.adapters.onec.rsv_privacy import (
    RSVWireLimitExceeded,
    private_rsv_diagnostics,
)


class Bytes:
    def __init__(self, *chunks):
        self.chunks = iter(chunks)
        self.closed = False

    async def receive(self):
        try:
            return next(self.chunks)
        except StopIteration:
            raise anyio.EndOfStream from None

    async def aclose(self):
        self.closed = True


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setattr(rsv_privacy, 'MAX_RSV_WIRE_LINE_BYTES', 8)
    monkeypatch.setattr(rsv_privacy, 'MAX_RSV_SESSION_WIRE_BYTES', 24)
    monkeypatch.setattr(rsv_privacy, 'MAX_RSV_SESSION_FRAMES', 3)


async def test_fragmented_line_is_rejected_before_sdk_json_parse_and_pipe_closed(limits):
    byte_stream = Bytes(b'private-', b'token-without-newline')
    with private_rsv_diagnostics():
        stream = sdk_stdio.TextReceiveStream(byte_stream)
    assert await stream.receive() == 'private-'
    with pytest.raises(RSVWireLimitExceeded) as failure:
        await stream.receive()
    assert str(failure.value) == 'RSV_WIRE_LIMIT_EXCEEDED' and byte_stream.closed


async def test_utf8_fragmented_multibyte_counts_bytes_not_characters(limits):
    value = 'я' * 5
    encoded = value.encode()
    byte_stream = Bytes(encoded[:1], encoded[1:6], encoded[6:])
    with private_rsv_diagnostics():
        stream = sdk_stdio.TextReceiveStream(byte_stream)
    assert await stream.receive() == 'я' * 3
    with pytest.raises(RSVWireLimitExceeded):
        await stream.receive()
    assert byte_stream.closed


async def test_line_counter_resets_on_sdk_newline_and_exact_boundary_is_allowed(limits):
    byte_stream = Bytes(b'12345678\n', b'ab\ncd\n')
    with private_rsv_diagnostics():
        stream = sdk_stdio.TextReceiveStream(byte_stream)
    assert await stream.receive() == '12345678\n'
    assert await stream.receive() == 'ab\ncd\n'
    assert not byte_stream.closed


async def test_session_total_and_frame_flood_are_bounded(limits):
    for chunks in ((b'12345678\n', b'12345678\n', b'12345678\n'), (b'\n\n', b'\n\n')):
        byte_stream = Bytes(*chunks)
        with private_rsv_diagnostics():
            stream = sdk_stdio.TextReceiveStream(byte_stream)
        with pytest.raises(RSVWireLimitExceeded):
            while True:
                await stream.receive()
        assert byte_stream.closed


async def test_outside_and_parallel_sdk_sessions_are_unchanged(limits):
    with private_rsv_diagnostics():
        private = sdk_stdio.TextReceiveStream(Bytes(b'123456789'))
    ordinary_bytes = Bytes(b'123456789-unrelated')
    ordinary = sdk_stdio.TextReceiveStream(ordinary_bytes)
    result = await asyncio.gather(private.receive(), ordinary.receive(), return_exceptions=True)
    assert isinstance(result[0], RSVWireLimitExceeded)
    assert result[1] == '123456789-unrelated' and not ordinary_bytes.closed


def test_guard_installs_once_and_does_not_stack_across_calls():
    with private_rsv_diagnostics():
        installed = sdk_stdio.TextReceiveStream
    with private_rsv_diagnostics():
        assert sdk_stdio.TextReceiveStream is installed


async def test_pipe_cleanup_failure_cannot_replace_fixed_limit_code_with_private_path(limits):
    class BrokenClose(Bytes):
        async def aclose(self):
            raise OSError('private-pipe-path-and-token')

    with private_rsv_diagnostics():
        stream = sdk_stdio.TextReceiveStream(BrokenClose(b'123456789'))
    with pytest.raises(RSVWireLimitExceeded) as failure:
        await stream.receive()
    assert str(failure.value) == 'RSV_WIRE_LIMIT_EXCEEDED' and failure.value.__cause__ is None
