"""Document-agnostic prompt set shared by retrieval, synthesis and ingestion."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class DocumentPrompts:
    """Domain knowledge injected into every LLM prompt in the pipeline."""

    label: str
    synthesis_rules: str
    ingest_vlm_prompt: str
    read_prompt: str
    prose_prompt: str
    prompt_version: int = 2

    _VLM: ClassVar[str] = (
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
    _RULES: ClassVar[str] = (
        "Quote the row label, period column and unit verbatim as the document "
        "spells them, including spacing and punctuation. Preserve scope and boundary "
        "qualifiers such as operated versus equity share, scope 1+2, or hours per "
        "200,000 hours worked."
    )
    _LABEL: ClassVar[str] = "corporate report"
    _PROSE: ClassVar[str] = (
        "You answer from the passages given to you, and nothing else. Answer in prose, "
        "in as few sentences as the question needs. State only what the passages state: "
        "never infer, never estimate, and never add context the passages do not carry. "
        "If the passages do not answer the question, say so plainly."
    )
    _READ: ClassVar[str] = (
        "You read one figure out of the passages given to you, and nothing else. "
        "Return STRICT JSON with this exact schema:\n"
        "  {\n"
        '    "value": str,\n'
        '    "unit": str,\n'
        '    "label": str,\n'
        '    "column": str\n'
        "  }\n"
        "value is the number alone: digits, a leading minus sign, thousands separators "
        "and a decimal point, exactly as the document writes them, and empty when the "
        "passages do not state it. unit is everything the document writes around that "
        "number, verbatim and in the document's order: a currency symbol or code, a "
        "scale word such as thousand or million, a percent sign, a unit of measure. "
        "unit is empty when the number stands alone. label is the row label the value "
        "sits on, quoted verbatim with its scope and boundary qualifiers. column is the "
        "column heading the value sits under, quoted verbatim, and empty when the "
        "passages show no column. Never infer, never convert, never compute. If the "
        "figure is not stated in the passages, return every field empty."
    )

    @classmethod
    def current(cls) -> DocumentPrompts:
        """The prompt set every stage reads.

        Returns:
            The prompts, with the version that keys the caches.
        """
        return cls(
            label=cls._LABEL,
            synthesis_rules=cls._RULES,
            ingest_vlm_prompt=cls._VLM,
            read_prompt=cls._READ,
            prose_prompt=f"{cls._PROSE}\n\n{cls._RULES}",
        )
