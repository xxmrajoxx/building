"""AI-assisted takeoff: Claude reads drawing pages and proposes quantities.

Optional. Needs Anthropic credentials (ANTHROPIC_API_KEY, or an `ant auth login`
profile). Results are a first pass for an estimator to check, not a measured
takeoff - every item comes back with its measurement basis and a confidence.
"""
from __future__ import annotations

import base64
import json

import anthropic
import pymupdf

from .models import TRADES, UNITS, new_item

MODEL = "claude-opus-5-5"
MAX_PDF_BYTES = 30 * 1024 * 1024  # API request limit is 32 MB

SYSTEM_PROMPT = """You are an experienced Australian quantity surveyor preparing a quantity takeoff \
for a contractor's tender, working from architectural and engineering drawings.

Measure in metric units (m, m2, m3, t, no, item) following Australian measurement practice \
(AIQS Australian Standard Method of Measurement conventions). Quantities are net as drawn; \
waste is added later in the rates, so do not add waste.

Use the drawing scale from the title block or scale bar, and prefer written dimensions over \
scaled measurements. For each item, state in `basis` how you derived it (dimensions used, \
grid lines, rooms, schedule references) so an estimator can check it. Set confidence to \
"low" whenever you had to scale off the drawing, infer something not shown, or the drawing \
was unclear. Do not invent elements that are not shown; list things you could not determine \
(for example, a missing scale, unclear levels or missing sections) in `assumptions`."""

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "trade": {"type": "string", "enum": TRADES},
        "description": {"type": "string"},
        "unit": {"type": "string", "enum": UNITS},
        "quantity": {"type": "number"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "basis": {"type": "string"},
        "page": {"type": "integer"},
    },
    "required": ["trade", "description", "unit", "quantity", "confidence", "basis", "page"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "drawing_summary": {"type": "string"},
        "scale_notes": {"type": "string"},
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["drawing_summary", "scale_notes", "items", "assumptions"],
    "additionalProperties": False,
}


class AITakeoffError(Exception):
    pass


def _subset_pdf(pdf: bytes, pages: list[int]) -> bytes:
    with pymupdf.open(stream=pdf, filetype="pdf") as src, pymupdf.open() as out:
        for p in pages:
            out.insert_pdf(src, from_page=p, to_page=p)
        return out.tobytes(garbage=3, deflate=True)


def ai_takeoff(pdf: bytes, pages: list[int], instructions: str = "", effort: str = "high") -> dict:
    """Ask Claude for a takeoff of the given 0-based pages.

    Returns {"summary", "scale_notes", "assumptions", "items": [takeoff rows], "usage"}.
    """
    if not pages:
        raise AITakeoffError("Select at least one page.")
    subset = _subset_pdf(pdf, pages)
    if len(subset) > MAX_PDF_BYTES:
        raise AITakeoffError(
            f"Selected pages are {len(subset) / 1e6:.1f} MB; the limit is about 30 MB. Select fewer pages."
        )
    page_map = ", ".join(f"page {i + 1} of this extract = sheet page {p + 1}" for i, p in enumerate(pages))
    task = (
        "Prepare a quantity takeoff from the attached drawing pages for pricing a tender. "
        f"Page numbering: {page_map}. Report `page` as the sheet page number.\n"
    )
    if instructions.strip():
        task += f"\nEstimator's instructions:\n{instructions.strip()}\n"

    try:
        client = anthropic.Anthropic()
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM_PROMPT,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(subset).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": task},
                ],
            }],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise AITakeoffError(
            "No valid Anthropic credentials. Set ANTHROPIC_API_KEY (see README) and restart the app."
        ) from e
    except anthropic.CredentialsError as e:
        raise AITakeoffError(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY (see README) and restart the app."
        ) from e
    except TypeError as e:
        # The SDK raises TypeError when no credential source is configured at all.
        if "authentication" not in str(e):
            raise
        raise AITakeoffError(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY (see README) and restart the app."
        ) from e
    except anthropic.RateLimitError as e:
        raise AITakeoffError("Rate limited by the API. Wait a minute and try again.") from e
    except anthropic.BadRequestError as e:
        raise AITakeoffError(f"The API rejected the request: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise AITakeoffError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AITakeoffError("Could not reach the Anthropic API. Check your internet connection.") from e

    if message.stop_reason == "refusal":
        raise AITakeoffError("The model declined to process these drawings.")
    if message.stop_reason == "max_tokens":
        raise AITakeoffError("The response was cut off. Select fewer pages and try again.")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AITakeoffError("The model returned an unreadable response. Try again.") from e

    items = [
        new_item(
            it["trade"], it["description"], it["unit"], it["quantity"],
            source="AI (PDF)", ref=f"PDF p.{it['page']}", confidence=it["confidence"], notes=it["basis"],
        )
        for it in data["items"]
        if it["quantity"] > 0
    ]
    return {
        "summary": data["drawing_summary"],
        "scale_notes": data["scale_notes"],
        "assumptions": data["assumptions"],
        "items": items,
        "usage": {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens},
    }
