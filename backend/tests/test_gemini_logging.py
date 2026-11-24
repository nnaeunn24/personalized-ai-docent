import unittest

import httpx
from fastapi import HTTPException

from app.gemini_units import ExtractedUnits, Gemini


class GeminiLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def verify_failure(self, handler, api_status, *expected):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertLogs("uvicorn.error", level="WARNING") as logs:
                with self.assertRaises(HTTPException) as failure:
                    await Gemini(client, "private-test-key").generate(
                        "gemini-test", "private-test-prompt", {"context": "private-test-context"}, ExtractedUnits,
                    )
        self.assertEqual(failure.exception.status_code, api_status)
        output = "\n".join(logs.output)
        for fragment in (*expected, "model=gemini-test", "elapsed_ms="):
            self.assertIn(fragment, output)
        self.assertNotIn("private-test-", output)

    async def test_quota_and_overload_have_distinct_upstream_status(self):
        for status, api_status, category, code, message in (
            (429, 429, "rate_limit_or_quota", "RESOURCE_EXHAUSTED", "You exceeded your current quota"),
            (503, 502, "upstream_unavailable", "UNAVAILABLE", "The model is overloaded"),
        ):
            with self.subTest(status=status):
                await self.verify_failure(
                    lambda _: httpx.Response(status, json={
                        "error": {"status": code, "message": message + ": private-test-key private-test-context"},
                    }),
                    api_status, f"provider_http_status={status}", f"category={category}", code, message, "timed_out=False",
                )

    async def test_timeout_does_not_log_exception_text(self):
        def timeout(request):
            raise httpx.ReadTimeout("private-test-key", request=request)

        await self.verify_failure(timeout, 503, "category=timeout", "provider_http_status=none", "timed_out=True", "ReadTimeout")

    async def test_parsing_failure_does_not_log_response_text(self):
        await self.verify_failure(
            lambda _: httpx.Response(200, text="private-test-context"),
            502, "category=response_parse_failure", "stage=response_json", "provider_http_status=200",
        )
