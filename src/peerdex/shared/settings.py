"""Application settings loaded from YAML + environment variables."""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "config.yaml"
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

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


class ChunkerCfg(BaseModel):
    tokenizer: str = "cl100k_base"
    max_tokens: int = 512
    parent_chunk_tokens: int = 1024
    child_chunk_tokens: int = 256


class EmbedCfg(BaseModel):
    model: str
    dim: int = 1536
    batch_size: int = 128


class LLMCfg(BaseModel):
    """Text-only LLMs. Vision lives under ``vlm`` below."""

    model: str
    synth_model: str | None = None
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
    exact brute-force recall of 19/28 once refined, so the default is chosen on
    storage: IVF_PQ costs 0.55KB per row against 1.70 for scalar quantisation and
    6.55 for whole vectors. The PQ variants *require* ``vector_refine_factor``.
    """

    vector_type: Literal[
        "IVF_FLAT",
        "IVF_SQ",
        "IVF_PQ",
        "IVF_RQ",
        "IVF_HNSW_FLAT",
        "IVF_HNSW_SQ",
        "IVF_HNSW_PQ",
    ] = "IVF_PQ"


class RetrievalCfg(BaseModel):
    """How passages are found. ``query_type`` selects the search mode."""

    final_top_k: int = 25
    query_type: Literal["fts", "vector"] = "fts"
    vector_refine_factor: int = 5


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
