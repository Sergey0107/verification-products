import json

import httpx

from app.core.config import settings


class CompareParseError(RuntimeError):
    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


def _extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _get_prompt() -> dict:
    with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.get(f"{settings.PROMPT_REGISTRY_URL}/prompts/comparison")
        resp.raise_for_status()
        return resp.json()


def compare_json(tz_data: dict, passport_data: dict) -> dict:
    prompt_payload = _get_prompt()
    prompt_text = prompt_payload.get("prompt", "")
    schema = prompt_payload.get("schema", {})

    system_message = (
        f"{prompt_text}\n\nReturn JSON that matches this schema:\n"
        f"{json.dumps(schema, ensure_ascii=True)}"
    )
    user_message = json.dumps(
        {"tz": tz_data, "passport": passport_data},
        ensure_ascii=True,
    )

    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    try:
        return _extract_json(content)
    except json.JSONDecodeError as exc:
        raise CompareParseError(str(exc), content)
