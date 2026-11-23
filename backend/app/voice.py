import base64
import io
import json
import logging
import re
import wave

import httpx
from fastapi import HTTPException


logger = logging.getLogger("uvicorn.error")
GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
DEFAULT_PCM_SAMPLE_RATE = 24000

WHY_SPEECH = {
    "discover": (
        "Zephyr",
        "Speak in natural Korean with a bright, curious, engaging museum-docent tone. "
        "Clear articulation, medium pace, gentle enthusiasm, as if pointing out an interesting discovery.",
    ),
    "relax": (
        "Aoede",
        "Speak in natural Korean with a calm, soft, soothing museum-docent tone. "
        "Slightly slower pace, gentle pauses, low vocal tension, and no dramatic delivery.",
    ),
    "reflect": (
        "Kore",
        "Speak in natural Korean with a warm, thoughtful, reflective museum-docent tone. "
        "Medium-slow pace with natural pauses that give the listener time to think. Avoid sounding overly sentimental.",
    ),
    "together": (
        "Leda",
        "Speak in natural Korean with a friendly, conversational, lightly energetic museum-docent tone. "
        "Make it feel like inviting two people to notice and discuss the artwork together.",
    ),
}


def _wav_audio(audio_data: bytes, mime_type: str | None) -> bytes:
    if audio_data.startswith(b"RIFF") and audio_data[8:12] == b"WAVE":
        return audio_data
    if mime_type and not mime_type.lower().startswith("audio/pcm"):
        raise HTTPException(502, "Gemini TTS returned an unsupported audio format.")

    sample_rate = DEFAULT_PCM_SAMPLE_RATE
    if mime_type:
        match = re.search(r"(?:rate|sample_rate)=(\d+)", mime_type, re.IGNORECASE)
        if match:
            sample_rate = int(match.group(1))

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)
    return output.getvalue()


def _provider_error(response: httpx.Response, api_key: str) -> tuple[str, str]:
    try:
        payload = response.json()
    except ValueError:
        return "UNKNOWN", "Gemini returned a non-JSON error response."
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    code = str(error.get("status") or error.get("code") or "UNKNOWN")
    message = str(error.get("message") or "Gemini could not generate speech.")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return code[:120], message[:1000]


async def synthesize_speech(client: httpx.AsyncClient, text: str, why: str, settings) -> bytes:
    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise HTTPException(503, "GEMINI_API_KEY를 백엔드에 설정해 주세요.")
    if why not in WHY_SPEECH:
        raise HTTPException(422, "지원하지 않는 WHY 값입니다.")

    voice, style = WHY_SPEECH[why]
    request_body = {
        "model": GEMINI_TTS_MODEL,
        "input": [{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": text,
                "annotations": [{"type": "speech_metadata", "style": style}],
            }],
        }],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }

    try:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=request_body,
            timeout=90.0,
        )
    except httpx.RequestError as error:
        logger.warning("Gemini TTS transport failure: model=%s error=%s", GEMINI_TTS_MODEL, type(error).__name__)
        raise HTTPException(503, "Gemini TTS에 연결할 수 없거나 응답 시간이 초과되었습니다.") from None

    if not response.is_success:
        code, message = _provider_error(response, api_key)
        logger.warning(
            "Gemini TTS failed: model=%s status=%d code=%s message=%s",
            GEMINI_TTS_MODEL, response.status_code, code, message,
        )
        if response.status_code == 429:
            raise HTTPException(429, f"Gemini TTS 사용량 한도에 도달했습니다: {message}")
        raise HTTPException(502, f"Gemini TTS 요청 실패 (HTTP {response.status_code}, {code}): {message}")

    try:
        result = response.json()
        audio_outputs = [
            item
            for step in result["steps"]
            if step.get("type") == "model_output"
            for item in step.get("content", [])
            if item.get("type") == "audio" and isinstance(item.get("data"), str)
        ]
        if not audio_outputs:
            raise ValueError("No audio output")
        audio_output = audio_outputs[-1]
        audio_data = base64.b64decode(audio_output["data"], validate=True)
        if not audio_data:
            raise ValueError("Empty audio output")
        return _wav_audio(audio_data, audio_output.get("mime_type"))
    except (KeyError, TypeError, ValueError, wave.Error) as error:
        logger.warning(
            "Gemini TTS response invalid: model=%s error=%s",
            GEMINI_TTS_MODEL, type(error).__name__,
        )
        raise HTTPException(502, "Gemini TTS 응답에서 재생 가능한 오디오를 확인하지 못했습니다.") from None
