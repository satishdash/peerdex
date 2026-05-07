"""Per-report-type prompt registry.

One source of truth for every LLM prompt that depends on the document
type. Each report type contributes domain knowledge (vocabulary,
where facts live, what a 'good' answer looks like) into the prompts
used by:
  - QueryExpander  (retrieval recall)
  - LLMReranker    (retrieval precision)
  - CitedSynthesizer (answer quality)
  - VLM/ingestion  (reserved for image & table description prompts;
                    currently not wired but kept here so when we
                    enable a VLM the per-type prompt is ready)

Add a new ReportType → add a new ReportPrompts entry. No other file
needs to change.
"""

from dataclasses import dataclass, field

from peerdex.shared.schema import ReportType


@dataclass(frozen=True)
class TopicRoute:
    """A canonical question topic for a report type.

    The router matches a question against ``triggers`` (case-insensitive
    substring match against the query). On a hit it:

      1. Augments retrieval with one extra dense + BM25 pass using
         ``query + " " + keywords``  → recovers passages whose surface
         form differs from the user's wording (e.g. user asks "number of
         employees", document says "Total Suncor Employees year-end").
      2. Adds gentle additive boosts to fusion candidates whose
         ``heading_path`` substring-matches ``heading_patterns``, whose
         text contains any keyword, and whose ``is_table=True`` matches
         ``prefer_table``.

    Boosts are soft on purpose — the LLM reranker still casts the final
    vote with its score threshold. We never hard-filter; that risks
    refusing answers when the heading path was OCR'd weirdly.
    """
    name: str
    triggers: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    heading_patterns: tuple[str, ...] = ()
    prefer_table: bool = False
    # additive bonuses (tuned conservatively)
    boost_heading: float = 0.50
    boost_keyword: float = 0.30
    boost_table: float = 0.20


@dataclass(frozen=True)
class ReportPrompts:
    # short label used inline in prompts
    label: str

    # 1-paragraph description of the document genre, named entities,
    # typical structure, and where quantitative facts hide.
    domain_brief: str

    # extra vocabulary the QueryExpander should sprinkle into HyDE +
    # paraphrases (free-form text, lower-cased phrases joined by ", ")
    expansion_vocab: str

    # criteria the LLM reranker should weight when scoring passages
    rerank_criteria: str

    # extra rules the synthesizer must follow on top of generic ones
    synthesis_rules: str

    # System prompt for the OpenAI Vision describer (one chunk per
    # picture region detected by Docling layout). Must instruct the
    # model to return STRICT JSON with the schema documented in
    # peerdex.vlm._describer.
    ingest_vlm_prompt: str

    # Bump when ingest_vlm_prompt or its expected JSON schema changes,
    # so the per-image VLM cache invalidates correctly.
    prompt_version: int = 1

    # Canonical question-topic routes. Used by ``retrieve._router``
    # to add a keyword-augmented retrieval pass and softly boost
    # candidates whose heading/text/kind matches the canonical
    # location for that topic. Order matters: the first matching
    # route wins (we don't stack routes, to keep ranking explainable).
    topics: tuple[TopicRoute, ...] = field(default_factory=tuple)


# ---------- annual report ----------
_ANNUAL = ReportPrompts(
    label="annual report",
    domain_brief=(
        "An annual report (Form 10-K / 40-F / AIF style) for a public company. "
        "Quantitative facts live in: Consolidated Statements of Income, Balance Sheet, "
        "Cash Flow, Notes to the Financial Statements, Management's Discussion & "
        "Analysis (MD&A), Five-Year Financial Summary, Five-Year Operating Summary, "
        "Reserves & Resources tables, and segment breakdowns (Oil Sands, E&P, "
        "Refining & Marketing, etc.). Headcount typically appears in 'Five-Year "
        "Financial Summary' or 'Employees' under 'Our People' / Human Resources."
    ),
    expansion_vocab=(
        "total employees, number at year end, headcount, workforce, full-time "
        "equivalents, FTE, total revenue, net earnings, operating earnings, "
        "adjusted funds from operations, capital expenditures, capex, total assets, "
        "shareholders' equity, dividend per share, scope 1 emissions, GHG, proved "
        "reserves, production volumes, bbl/d, mboe/d, segment results, MD&A, "
        "Five-Year Financial Summary, Notes to Consolidated Financial Statements"
    ),
    rerank_criteria=(
        "Strongly prefer passages from official financial statements, notes, MD&A, "
        "and the Five-Year Financial / Operating Summary tables. A passage that "
        "states the exact requested figure with its label and unit is a 10. "
        "A passage that only discusses the topic narratively (e.g. 'employee future "
        "benefits' for an employee count question) is at most a 3."
    ),
    synthesis_rules=(
        "When the source is a financial-summary table row, quote the row label and "
        "the year column verbatim, e.g. 'Total Suncor Employees (number at year "
        "end), 2025 = 15 424'. Use the exact spacing/punctuation of the document."
    ),
    ingest_vlm_prompt=(
        "You are extracting quantitative data from a figure in a public-company "
        "annual report. Read the image carefully and return STRICT JSON with this "
        "exact schema:\n"
        "  {\n"
        "    \"has_quant_data\": bool,   // true if the figure shows ANY numeric "
        "value, percentage, currency amount, year-over-year comparison, units of "
        "measure (bbl, mboe, tCO2e, $, %, etc.), or labelled axes; false only for "
        "pure logos, decorative dividers, or symbolic illustrations.\n"
        "    \"title\": str,             // figure title or section caption visible "
        "in or near the image; empty string if none.\n"
        "    \"description\": str,       // 1-3 sentences describing what the "
        "figure shows: metric, time range, axis units, scope/segment.\n"
        "    \"values\": [                // every numeric data point you can read,\n"
        "      {\"label\": str,          // metric name + qualifier "
        "(e.g. 'Net earnings 2025', 'Total Suncor Employees year-end 2024')\n"
        "       \"value\": str,          // verbatim, including thousands separators\n"
        "       \"unit\":  str}          // e.g. '$', 'CAD billion', '%', 'bbl/d', "
        "'employees', '' if unitless\n"
        "    ]\n"
        "  }\n"
        "Rules: Never invent numbers. If unreadable, return has_quant_data=false."
    ),
    topics=(
        TopicRoute(
            name="employees",
            triggers=("employee", "headcount", "workforce", "people", "fte"),
            keywords=(
                "Total Suncor Employees", "number at year end",
                "headcount", "workforce", "full-time equivalents",
            ),
            heading_patterns=(
                "Five-Year Financial Summary",
                "Five-Year Operating Summary",
                "Our People", "Employees", "Human Resources",
            ),
            prefer_table=True,
        ),
        TopicRoute(
            name="revenue",
            triggers=("revenue", "gross revenue", "total revenue", "sales",
                      "operating revenue"),
            keywords=(
                "Total Gross Revenue", "Revenue from Contracts with Customers",
                "Disaggregation of Revenue",
                "Operating revenues", "Total operating revenues",
                "Total revenues", "Net revenues",
            ),
            heading_patterns=(
                "Consolidated Statements of Income",
                "Consolidated Statement of Operations",
                "Consolidated Statements of Operations",
                "Notes to the Consolidated Financial Statements",
                "Disaggregation of Revenue",
                "Annual information", "Selected financial",
                "Results of operations", "Financial highlights",
            ),
            prefer_table=True,
        ),
    ),
)
_SUSTAINABILITY = ReportPrompts(
    label="sustainability report",
    domain_brief=(
        "A sustainability / ESG / climate report. Quantitative facts live in: "
        "ESG Performance Data tables, Climate / TCFD section, GHG inventory, "
        "Safety performance (TRIR, LTIR), Diversity & Inclusion metrics, "
        "Water & Waste tables, GRI / SASB indices, Assurance statements. "
        "Headcount, gender %, indigenous % typically live in 'Our People' or "
        "the back-of-book ESG data tables."
    ),
    expansion_vocab=(
        "scope 1 emissions, scope 2 emissions, scope 3 emissions, GHG intensity, "
        "tCO2e, methane, flaring, freshwater withdrawal, recycled water, TRIR, "
        "LTIR, fatalities, recordable injuries, total workforce, women in "
        "workforce, indigenous employees, board diversity, community investment, "
        "tailings, reclamation, ESG performance data, GRI index, SASB, TCFD, "
        "net zero, science-based targets, SBTi"
    ),
    rerank_criteria=(
        "Strongly prefer passages from ESG performance data tables, GRI/SASB "
        "indices, the climate (TCFD) section, and assurance statements. A "
        "passage that quotes the exact metric value with units (tCO2e, %, m3) "
        "is a 10. Marketing/narrative restatements without numbers are at most a 4."
    ),
    synthesis_rules=(
        "Always preserve units exactly (tCO2e, kt CO2e, m3, %, hours per "
        "200,000 hours worked). When a figure has scope or boundary qualifiers "
        "(operated vs equity, scope 1+2, etc.), quote them in the answer."
    ),
    ingest_vlm_prompt=(
        "You are extracting quantitative data from a figure in a corporate "
        "sustainability / ESG report. Read the image carefully and return STRICT "
        "JSON with this exact schema:\n"
        "  {\n"
        "    \"has_quant_data\": bool,   // true if the figure shows ANY ESG "
        "metric, GHG number, intensity, percentage, headcount, safety rate, water "
        "or waste volume, or labelled axes; false only for logos / decoration.\n"
        "    \"title\": str,             // figure title or caption near the image\n"
        "    \"description\": str,       // 1-3 sentences: metric, scope/boundary, "
        "time range, units.\n"
        "    \"values\": [                // every numeric data point you can read\n"
        "      {\"label\": str,          // include scope/boundary qualifiers "
        "(e.g. 'Scope 1 emissions, operated, 2025')\n"
        "       \"value\": str,          // verbatim, with thousands separators\n"
        "       \"unit\":  str}          // tCO2e, kt CO2e, m3, %, hours per "
        "200,000 hours worked, etc. Empty string if unitless.\n"
        "    ]\n"
        "  }\n"
        "Rules: Never invent numbers. If unreadable, return has_quant_data=false."
    ),
    topics=(
        TopicRoute(
            name="scope1",
            triggers=("scope 1", "scope-1", "direct ghg", "direct emissions"),
            keywords=(
                "Scope 1 emissions", "direct GHG emissions",
                "operated", "tCO2e", "kt CO2e",
            ),
            heading_patterns=(
                "ESG Performance Data", "GHG", "Climate", "TCFD",
                "Emissions",
            ),
            prefer_table=True,
        ),
        TopicRoute(
            name="trir",
            triggers=("trir", "recordable injury", "recordable injuries", "safety performance"),
            keywords=(
                "Total Recordable Injury Rate", "TRIR",
                "per 200,000 hours worked", "recordable injuries",
            ),
            heading_patterns=("Safety", "ESG Performance Data", "Our People"),
            prefer_table=True,
        ),
        TopicRoute(
            name="hours_worked",
            triggers=("hours worked", "exposure hours", "man hours", "manhours"),
            keywords=(
                "hours worked", "total hours worked",
                "exposure hours", "200,000 hours",
            ),
            heading_patterns=("Safety", "ESG Performance Data", "Our People"),
            prefer_table=True,
        ),
    ),
)


_REGISTRY: dict[ReportType, ReportPrompts] = {
    ReportType.ANNUAL_REPORT: _ANNUAL,
    ReportType.SUSTAINABILITY_REPORT: _SUSTAINABILITY,
}


def prompts_for(report_type: ReportType | str | None) -> ReportPrompts:
    """Look up per-type prompts. Falls back to annual_report if unknown."""
    if report_type is None:
        return _ANNUAL
    if isinstance(report_type, str):
        try:
            report_type = ReportType(report_type)
        except ValueError:
            return _ANNUAL
    return _REGISTRY.get(report_type, _ANNUAL)
