from __future__ import annotations

import json
import unittest

import httpx

from business_ai_gateway.capability_client import (
    CapabilityObserverClient,
    CapabilityObserverUnavailable,
)


REQUEST_ID = "8a11b26a-1c6e-4a3c-aea4-99b73b3768b4"


class CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]):
        self.chunks = chunks
        self.consumed = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk

    async def aclose(self) -> None:
        return None


class CapabilityObserverClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_parses_valid_bounded_response(self):
        payload = {
            "source_id": "onec-reference",
            "request_id": REQUEST_ID,
            "status": "STABLE",
            "observation_id": 7,
        }
        body = json.dumps(payload).encode()

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        client = CapabilityObserverClient(
            base_url="https://observer.example",
            token="test-token",
            production=True,
            timeout_seconds=1,
            max_response_bytes=len(body),
            transport=httpx.MockTransport(respond),
        )
        try:
            result = await client.refresh(
                source_id="onec-reference", access_token=None, request_id=REQUEST_ID,
            )
        finally:
            await client.close()

        self.assertEqual(result, payload)

    async def test_refresh_stops_reading_when_stream_exceeds_limit(self):
        stream = CountingStream((b"12345", b"67890", b"ignored"))

        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=stream)

        client = CapabilityObserverClient(
            base_url="https://observer.example",
            token="test-token",
            production=True,
            timeout_seconds=1,
            max_response_bytes=8,
            transport=httpx.MockTransport(respond),
        )
        try:
            with self.assertRaises(CapabilityObserverUnavailable):
                await client.refresh(
                    source_id="onec-reference", access_token=None, request_id=REQUEST_ID,
                )
        finally:
            await client.close()

        self.assertEqual(stream.consumed, 2)


if __name__ == "__main__":
    unittest.main()
