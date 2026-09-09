"""Document-agnostic prompt set shared by retrieval, synthesis and ingestion."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DocumentPrompts:
    """Domain knowledge injected into every LLM prompt in the pipeline."""

    label: str
    synthesis_rules: str
    ingest_vlm_prompt: str
    prompt_version: int = 2


_VLM_PROMPT: Final[str] = (
    "You are extracting quantitative data from a figure in a corporate report. "
    "Read the image carefully and return STRICT JSON with this exact schema:\n"
    "  {\n"
    '    "has_quant_data": bool,\n'
    '    "title": str,\n'
    '    "description": str,\n'
    '    "values": [{"label": str, "value": str, "unit": str}]\n'
    "  }\n"
    "has_quant_data is true when the figure shows any numeric value, percentage, "
    "currency amount, year-over-year comparison, unit of measure or labelled axis; "
    "false only for logos, dividers and symbolic illustrations. title is the caption "
    "visible in or near the image, empty when absent. description is 1-3 sentences "
    "naming the metric, scope or boundary, time range and units. values holds every "
    "data point you can read, with the label carrying its qualifiers, the value "
    "verbatim including thousands separators, and the unit empty when unitless. "
    "Never invent numbers. If unreadable, return has_quant_data=false."
)


PROMPTS: Final[DocumentPrompts] = DocumentPrompts(
    label="corporate report",
    synthesis_rules=(
        "Quote the row label, period column and unit verbatim as the document "
        "spells them, including spacing and punctuation. Preserve scope and boundary "
        "qualifiers such as operated versus equity share, scope 1+2, or hours per "
        "200,000 hours worked."
    ),
    ingest_vlm_prompt=_VLM_PROMPT,
)
