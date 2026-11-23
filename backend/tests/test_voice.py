import base64
import io
import json
import unittest
import wave
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from pydantic import SecretStr

from app.voice import GEMINI_TTS_MODEL, WHY_SPEECH, synthesize_speech


class VoiceTest(unittest.IsolatedAsyncioTestCase):
    async def request(self, why, audio_data, mime_type="audio/wav"):
        request_data = {}

        def respond(request):
            request_data["url"] = str(request.url)
            request_data["headers"] = request.headers
            request_data["json"] = json.loads(request.content)
            return httpx.Response(200, json={
                "steps": [{
                    "type": "model_output",
                    "content": [{
                        "type": "audio",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                        "mime_type": mime_type,
                    }],
                }],
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        settings = SimpleNamespace(gemini_api_key=SecretStr("test-key"))
        audio = await synthesize_speech(client, "Exact supplied text.", why, settings)
        await client.aclose()
        return audio, request_data

    async def test_selects_expected_voice_and_style_without_rewriting_text(self):
        pcm = b"\x00\x00" * 24
        audio, request_data = await self.request("discover", pcm, "audio/pcm;rate=24000")
        payload = request_data["json"]
        self.assertEqual(request_data["url"], "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request_data["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(payload["model"], GEMINI_TTS_MODEL)
        self.assertEqual(payload["input"][0]["content"][0]["text"], "Exact supplied text.")
        self.assertEqual(
            payload["input"][0]["content"][0]["annotations"][0]["style"],
            WHY_SPEECH["discover"][1],
        )
        self.assertEqual(payload["generation_config"]["speech_config"], [{"voice": "Zephyr"}])
        self.assertTrue(audio.startswith(b"RIFF"))
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            self.assertEqual((wav_file.getnchannels(), wav_file.getsampwidth(), wav_file.getframerate()), (1, 2, 24000))

    async def test_preserves_api_wav_audio_and_uses_config_for_all_whys(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 8)
        wav_bytes = output.getvalue()
        for why, (voice, style) in WHY_SPEECH.items():
            with self.subTest(why=why):
                audio, request_data = await self.request(why, wav_bytes)
                self.assertEqual(audio, wav_bytes)
                config = request_data["json"]["generation_config"]["speech_config"]
                self.assertEqual(config, [{"voice": voice}])
                self.assertEqual(
                    request_data["json"]["input"][0]["content"][0]["annotations"][0]["style"],
                    style,
                )

    async def test_reports_provider_status_and_message_without_logging_api_key(self):
        api_key = "private-test-key"

        def respond(_request):
            return httpx.Response(400, json={
                "error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Bad request " + api_key},
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        settings = SimpleNamespace(gemini_api_key=SecretStr(api_key))
        with self.assertLogs("uvicorn.error", level="WARNING") as logs:
            with self.assertRaises(HTTPException) as raised:
                await synthesize_speech(client, "Text", "discover", settings)
        await client.aclose()
        logged = "\n".join(logs.output)
        self.assertIn("status=400", logged)
        self.assertIn("INVALID_ARGUMENT", logged)
        self.assertIn("[REDACTED]", logged)
        self.assertNotIn(api_key, logged)
        self.assertIn("HTTP 400", raised.exception.detail)
        self.assertNotIn(api_key, raised.exception.detail)

    async def test_requires_existing_gemini_key(self):
        settings = SimpleNamespace(gemini_api_key=SecretStr(""))
        with self.assertRaises(HTTPException) as raised:
            await synthesize_speech(None, "Text", "discover", settings)
        self.assertEqual(raised.exception.status_code, 503)
