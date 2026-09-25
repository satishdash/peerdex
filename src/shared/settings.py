"""Application settings loaded from YAML + environment variables."""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

load_dotenv(ENV_PATH, override=False)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class StorageCfg(BaseModel):
    lancedb_uri: str
    cache_uri: str


class DoclingCfg(BaseModel):
    artifacts_path: str
    do_ocr: bool = False
    do_table_structure: bool = True
    generate_page_images: bool = False
    generate_picture_images: bool = True
    picture_image_scale: float = 1.0
    pdfium_lib_path: str = ""


class DoclingRsCfg(BaseModel):
    heading_hierarchy: bool = False
    no_text_panels: bool = False
    artifacts_path: str = ""


class XbergCfg(BaseModel):
    target_dpi: int = 300


class ChunkerCfg(BaseModel):
    tokenizer: str = "cl100k_base"
    parent_chunk_tokens: int = 1024
    child_chunk_tokens: int = 256
    child_chunk_overlap: int = 32


class EmbedCfg(BaseModel):
    model: str
    batch_size: int = 128


class LLMCfg(BaseModel):
    """Text-only LLMs. Vision lives under ``vlm`` below."""

    model: str
    temperature: float = 0.0
    judge_model: str | None = None


class VLMCfg(BaseModel):
    """OpenAI Vision used during ingestion."""

    model: str
    cache_dir: str
    image_max_dim: int = 1600
    min_bbox_area_pct: float = 1.5
    skip_header_footer_band_pct: float = 8.0
    concurrency: int = 8


class ResilienceCfg(BaseModel):
    openai_rpm: int = 500
    openai_tpm: int = 200_000
    retry_attempts: int = 5
    timeout_seconds: int = 60


class IndexCfg(BaseModel):
    """How the vector index is built.

    Switching ``vector_type`` is a rebuild, never a migration: the index is derived
    from the stored vectors, so no re-embedding, schema change or data move is
    involved. Measured over all seven types on 4,739 rows, every one reached the
    exact brute-force recall of 19/28 once refined.

    Scalar quantisation is the default because it needs no refinement pass. Product
    quantisation compares compressed codes, which is approximate, so it only reaches
    that recall by re-scoring a shortlist against the whole vectors — paying at read
    time to undo its own compression. SQ costs 1.70KB per row against 0.55 for PQ and
    6.55 for whole vectors, which buys an exact read path for three times the storage.
    """

    vector_type: Literal[
        "IVF_FLAT",
        "IVF_SQ",
        "IVF_PQ",
        "IVF_RQ",
        "IVF_HNSW_FLAT",
        "IVF_HNSW_SQ",
        "IVF_HNSW_PQ",
    ] = "IVF_SQ"


class RetrievalCfg(BaseModel):
    """The four toggles the ask flow is measured over.

    Reciprocal-rank fusion merges two ranked lists by position, so it has nothing to
    merge under a single-list mode and is refused there.
    """

    final_top_k: int = 25
    query_type: Literal["fts", "vector", "hybrid"] = "vector"
    reranker: Literal["none", "rrf", "cross_encoder"] = "none"
    reranker_model: str = "BAAI/bge-reranker-base"
    escalate_on_refusal: bool = True

    @model_validator(mode="after")
    def _rrf_needs_two_lists(self) -> "RetrievalCfg":
        """Refuse reciprocal-rank fusion unless the mode produces two ranked lists.

        Returns:
            The validated settings.

        Raises:
            ValueError: If ``rrf`` is asked for under a mode that ranks once.
        """
        if self.reranker == "rrf" and self.query_type != "hybrid":
            raise ValueError("reranker 'rrf' needs query_type 'hybrid'; it merges two ranked lists")
        return self


class LoggingCfg(BaseModel):
    level: str = "INFO"


class Settings(BaseModel):
    """Everything configurable. ``domains`` is the set of document domains served.

    A domain owns one LanceDB table and one prompt set, so it must be declared here
    before it can be ingested or queried. Without that check a mistyped domain would
    quietly open an empty table and every answer would be a refusal.
    """

    env: str = "dev"
    domains: list[str] = Field(default_factory=lambda: ["corporate"])
    storage: StorageCfg
    docling: DoclingCfg
    docling_rs: DoclingRsCfg = DoclingRsCfg()
    xberg: XbergCfg = XbergCfg()
    chunker: ChunkerCfg
    embed: EmbedCfg
    llm: LLMCfg
    vlm: VLMCfg
    resilience: ResilienceCfg
    index: IndexCfg = Field(default_factory=IndexCfg)
    retrieval: RetrievalCfg
    logging: LoggingCfg = Field(default_factory=LoggingCfg)

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


def _coerce_numerics(d: dict) -> dict:
    """Recursively coerce string values that look numeric to int/float.

    Env-var expansion turns everything into strings; Pydantic's strict
    numeric fields reject those. This runs once at load time.
    """
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _coerce_numerics(v)
        elif isinstance(v, str):
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    expanded = _expand(raw)
    coerced = _coerce_numerics(expanded)
    return Settings(**coerced)


def resolve_domain(domain: str) -> str:
    """The domain, normalised, once it is known to be one this deployment serves.

    Refusing an unknown domain is the point: it names one LanceDB table, so a typo
    would otherwise create or open an empty one and turn every answer into a refusal.
    """
    normalised: str = domain.strip().lower()
    known: list[str] = get_settings().domains
    if normalised not in known:
        raise ValueError(f"unknown domain {domain!r}; configured domains are {known}")
    return normalised
