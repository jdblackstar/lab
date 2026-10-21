"""Structure a source document into canonical menus with Claude.

One request per document: the model sees every part (PDF pages, photos, text) and
returns zero or more menus validated against ``schema.MenuBody``.
"""

from __future__ import annotations

import base64

from pydantic import BaseModel, Field

from ..schema import MenuBody
from .sources import Part, SourceDoc

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"

SYSTEM_PROMPT = """You convert catering menus into structured records for a research dataset \
about menu composition. Documents may be designed PDFs, phone photos of printed menus, \
spreadsheets, proposals, emails, or banquet event orders.

Rules:
- Copy dish names and descriptions verbatim (fix only obvious OCR errors). Never invent, \
merge, or embellish dishes.
- Leave out prices, per-person costs, minimums, fees, taxes, gratuity, and any client, \
host, honoree, venue, or company names, contact details, and exact dates. Keep the month \
or season if stated or clearly implied; keep the event type ("wedding", "corporate lunch").
- One record per distinct menu. A document can hold several menus (e.g. a proposal with \
three dinner options, or a cocktail hour followed by a plated dinner for the same event; \
the latter is ONE menu with sections in service order).
- kind: "event" if it is what was (or will be) served at a specific event; "sample" if it \
is a complete, composed showcase menu; "package" for tiered/priced bundles; "catalog" for \
lists of options the client chooses from ("select three", "choice of"). When unsure \
between event and sample, use sample.
- Sections follow the order of service. Use the course that matches the section's role \
(passed and displayed bites are hors_doeuvres or display; a raw bar is raw_bar). Set \
section.service when it differs from or refines the menu's overall service (passed \
hors d'oeuvres at a plated dinner, a family-style main at a seated dinner, a carving station).
- selection: "guest_choice" when each guest chooses (e.g. "choice of entrée"); \
"host_choice" when the client selects some items when booking (set select_count).
- Mark dietary tags only when the menu states them (V, VG, GF, DF, etc.). Use role \
"dietary_alternate" for items offered only to guests with restrictions, "kids" for a \
children's meal, "upgrade" for optional add-ons.
- Drinks: signature cocktails, wine pairings, beer, non-alcoholic drinks, coffee service \
and bar packages are their own sections. A wine paired with a course goes in that item's \
pairing field instead.
- If the document contains no menu, return an empty list and say why in document_notes. \
Use document_notes for anything illegible or ambiguous."""


class ExtractionResult(BaseModel):
    menus: list[MenuBody]
    document_notes: list[str] = Field(default_factory=list)


class ExtractionError(Exception):
    pass


def _block(part: Part) -> dict:
    if part.kind == "text":
        return {
            "type": "text",
            "text": f"<file name={part.label!r}>\n{part.data}\n</file>",
        }
    data = base64.standard_b64encode(part.data).decode("ascii")
    if part.kind == "pdf":
        return {
            "type": "document",
            "title": part.label,
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": part.media_type, "data": data},
    }


def extract_menus(
    doc: SourceDoc,
    *,
    client=None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    use_fallbacks: bool = True,
) -> ExtractionResult:
    import anthropic

    client = client or anthropic.Anthropic()
    content = [_block(p) for p in doc.parts]
    content.append(
        {
            "type": "text",
            "text": "Extract every menu from the file(s) above. Notes from loading: "
            + ("; ".join(doc.notes) or "none"),
        }
    )
    extra = {}
    if use_fallbacks:
        # Re-run a safety-declined request on Anthropic's recommended fallback model
        # inside the same call, instead of failing the document.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort},
        output_format=ExtractionResult,
        **extra,
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise ExtractionError(f"model declined: {message.stop_details}")
    if message.stop_reason == "max_tokens":
        raise ExtractionError("output hit max_tokens; split the document and retry")
    if message.parsed_output is None:
        raise ExtractionError(
            f"no structured output (stop_reason={message.stop_reason})"
        )
    return message.parsed_output
