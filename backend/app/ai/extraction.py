"""Document extraction: the LLM reads a supplier PDF into a typed structure.

The model is used only as a reader here. Its output must validate against
ExtractedQuote, and every judgement about the result (arithmetic, matching,
duplicates) is made afterwards by services/quote_intake.py.
"""

from __future__ import annotations

import copy

from pydantic import BaseModel, ValidationError

from app.ai.providers import LLMProvider
from app.schemas.intake import ExtractedQuote

EXTRACTION_PROMPT = """\
Extract the data from this supplier document (a quotation or invoice sent to VoltRide \
Systems, an e-bike drive-system manufacturer).

Rules:
- Copy values exactly as printed. Do not correct, recompute or complete anything: if the \
printed line total or grand total looks wrong, still report what is printed.
- The supplier is the company issuing the document, not VoltRide Systems.
- Use null for anything that is not present.
- Unit prices and line totals are numbers without currency symbols or thousands separators.
- List in uncertain_fields every value you could not read with confidence (blurred, \
ambiguous, handwritten), using paths like "total" or "lines[0].quantity".
- If the document is not a supplier quote or invoice, set document_type to "other".
"""


class ExtractionError(Exception):
    """The provider's answer could not be turned into an ExtractedQuote."""


def llm_json_schema(model: type[BaseModel]) -> dict:
    """A self-contained JSON schema both providers accept for structured output.

    Pydantic emits `$defs`/`$ref`; we inline them, close every object
    (additionalProperties: false) and mark every property required (optional
    values are expressed as nullable instead), which is what strict
    structured-output modes expect.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


QUOTE_SCHEMA = llm_json_schema(ExtractedQuote)


async def extract_quote(provider: LLMProvider, pdf: bytes) -> ExtractedQuote:
    raw = await provider.extract_pdf(pdf, EXTRACTION_PROMPT, QUOTE_SCHEMA)  # LLMError propagates
    try:
        return ExtractedQuote.model_validate(raw)
    except ValidationError as exc:
        raise ExtractionError(f"The AI returned data in an unexpected shape: {exc.error_count()} problem(s).") from exc
