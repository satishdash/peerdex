"""Document-agnostic prompt set shared by retrieval, synthesis and ingestion."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DocumentPrompts:
    """Domain knowledge injected into every LLM prompt in the pipeline."""

    label: str
    domain_brief: str
    expansion_vocab: str
    rerank_criteria: str
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
    domain_brief=(
        "A published corporate report: annual report, Form 10-K, 40-F, AIF, "
        "sustainability, ESG, climate or TCFD report, data index or assurance "
        "statement. Quantitative facts live in consolidated financial statements, "
        "notes, MD&A, five-year summaries, segment breakdowns, ESG performance data "
        "tables, GHG inventories, safety and workforce tables, and GRI or SASB "
        "indices. Back-of-book data tables carry the precise figures; narrative "
        "sections restate them approximately."
    ),
    expansion_vocab=(
        "total revenue, net earnings, operating earnings, capital expenditures, "
        "total assets, shareholders equity, total employees, headcount, workforce, "
        "full-time equivalents, employee turnover, scope 1 emissions, scope 2 "
        "location-based, scope 2 market-based, scope 3 emissions, GHG intensity, "
        "tCO2e, energy consumption, renewable energy, water withdrawal, water "
        "consumption, hazardous waste, TRIR, LTIR, recordable injuries, hours "
        "worked, board diversity, gender split, collective bargaining, community "
        "investment, net zero target year, ESG performance data, GRI index, SASB, "
        "TCFD, science-based targets"
    ),
    rerank_criteria=(
        "Strongly prefer passages from financial statements, notes, MD&A, ESG "
        "performance data tables, GRI or SASB indices and assurance statements. "
        "A passage stating the exact requested figure with its label and unit is a "
        "10. A passage that only discusses the topic narratively without the number "
        "is at most a 3."
    ),
    synthesis_rules=(
        "Quote the row label, period column and unit verbatim as the document "
        "spells them, including spacing and punctuation. Preserve scope and boundary "
        "qualifiers such as operated versus equity share, scope 1+2, or hours per "
        "200,000 hours worked."
    ),
    ingest_vlm_prompt=_VLM_PROMPT,
)
