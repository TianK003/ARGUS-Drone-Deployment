"""Gemini image-description client.

Exposes one synchronous function `describe_detection(image_bytes, sam_prompt)`
which posts the raw JPEG + the SAM prompt to gemini-flash-latest and returns a
(description, confidence) tuple. Called from FastAPI routes — blocking is fine
because the route runs on a worker thread and the hub is single-tenant.

Failure modes (network error, missing key, unparseable response) never raise;
they return a fallback tuple so the UI can render something meaningful.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Tuple

import requests

from .config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_TIMEOUT_SEC = 30
_FALLBACK: Tuple[str, int] = ("(description unavailable)", 0)

_PROMPT_TEMPLATE = (
    'A computer-vision tracker has flagged a "{sam_prompt}" in this image.\n'
    "\n"
    "Describe ONLY the {sam_prompt} itself. Focus exclusively on its physical\n"
    "attributes — color, material, shape, size, distinguishing marks, state,\n"
    "orientation.\n"
    "\n"
    "Do NOT mention:\n"
    "  - the surroundings, room, background, or scene\n"
    "  - any people, body parts, hands, or actions\n"
    "  - anything the {sam_prompt} is attached to, held by, or near\n"
    "  - lighting, reflections of other objects, or context\n"
    "\n"
    "If multiple {sam_prompt}s appear, describe the most prominent instance.\n"
    "\n"
    "Output EXACTLY this format, nothing else:\n"
    "Line 1: one short sentence, max 20 words, about the {sam_prompt} only.\n"
    "         Do not start with \"A \" — just describe attributes (e.g. "
    '"Silver metallic travel mug with matte finish and a black lid").\n'
    "Line 2: CONFIDENCE: XX\n"
    "         where XX is an integer 0-100 for how confidently you can\n"
    "         describe the {sam_prompt} from this image. If you cannot see\n"
    "         it clearly, output 0 and say so on line 1."
)

_CONF_RE = re.compile(r"CONFIDENCE\s*:\s*(\d{1,3})", re.IGNORECASE)


def describe_detection(image_bytes: bytes, sam_prompt: str) -> Tuple[str, int]:
    """Call Gemini, return (description, confidence 0-100). Never raises."""
    if not GEMINI_API_KEY:
        return _FALLBACK
    if not image_bytes:
        return _FALLBACK

    url = _ENDPOINT.format(model=GEMINI_MODEL)
    payload = {
        "contents": [{
            "parts": [
                {"text": _PROMPT_TEMPLATE.format(sam_prompt=sam_prompt or "object")},
                {"inlineData": {
                    "mimeType": "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }},
            ]
        }],
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SEC)
    except requests.RequestException as exc:
        log.warning("gemini: network error: %s", exc)
        return _FALLBACK

    if resp.status_code != 200:
        # Deliberately log only the status and a truncated body — never the key.
        log.warning("gemini: HTTP %s: %s", resp.status_code, resp.text[:200])
        return _FALLBACK

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, ValueError, IndexError) as exc:
        log.warning("gemini: unparseable response: %s", exc)
        return _FALLBACK

    return _parse_description_and_confidence(text)


def _parse_description_and_confidence(text: str) -> Tuple[str, int]:
    """Split Gemini's reply into the prose line(s) and the CONFIDENCE integer."""
    match = _CONF_RE.search(text)
    if not match:
        # No confidence marker — return the whole text with 0 confidence as a soft fallback.
        return text.strip() or _FALLBACK[0], 0

    confidence = max(0, min(100, int(match.group(1))))
    description = _CONF_RE.sub("", text).strip().rstrip(".").strip() or _FALLBACK[0]
    return description, confidence
