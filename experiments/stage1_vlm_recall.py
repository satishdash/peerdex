"""Stage 1 — parse + VLM recall: stage 0 with each picture's VLM description made searchable.

The number that matters is the delta against stage 0: how many oracle values are
reachable only through a figure. It is written as ``vlm_only_reachable``. The
per-image cache keys on (image bytes, model, prompt_version), so sweeping
``--vlm-model`` is additive. Costs OpenAI calls for uncached pictures.

Usage:
    uv run python experiments/stage1_vlm_recall.py --company globex --year 2025 \
        --vlm-model gpt-5.4-mini [--pdf-dir /abs/dir] [--pdf /abs/file.pdf ...] \
        [--extractors liteparse docling] [--out-dir results/funnel]
"""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from funnel_common import (
    CorpusBuilder,
    ExtractedCorpus,
    load_oracle,
    pdf_paths,
    stage_payload,
    summary_table,
    write_json,
)
from rich.console import Console

from peerdex.funnel import BlockProjector, OracleValue, ParseRecall, QuestionRecall, SearchableBlock
from peerdex.parse import PictureBlock, available_extractors
from peerdex.shared.clients import openai_async
from peerdex.shared.settings import get_settings
from peerdex.vlm import OpenAIPictureDescriber, PictureRef


class Stage1Runner:
    """Stage 0 measurement plus VLM descriptions, reporting the figure-only delta."""

    def __init__(
        self,
        company: str,
        year: int,
        extractors: Sequence[str],
        pdfs: Sequence[Path],
        out_dir: Path,
        vlm_model: str,
    ) -> None:
        self._company: str = company
        self._year: int = year
        self._extractors: list[str] = list(extractors)
        self._pdfs: list[Path] = list(pdfs)
        self._out_dir: Path = out_dir
        self._vlm_model: str = vlm_model

    async def run(self) -> list[list[str]]:
        """One summary row per extractor; each stage1_<extractor>.json is written as it goes."""
        oracle: list[OracleValue] = load_oracle(self._company, self._year)
        return [await self._run_extractor(name, oracle) for name in self._extractors]

    async def _run_extractor(self, name: str, oracle: Sequence[OracleValue]) -> list[str]:
        corpus: ExtractedCorpus = await CorpusBuilder().build(name, self._pdfs)
        projector: BlockProjector = BlockProjector()
        text_blocks: list[SearchableBlock] = corpus.text_blocks(projector)
        picture_blocks: list[SearchableBlock] = await self._describe(name, corpus, projector)
        recall: ParseRecall = ParseRecall()
        text_only: list[QuestionRecall] = recall.evaluate(oracle, text_blocks)
        full: list[QuestionRecall] = recall.evaluate(oracle, [*text_blocks, *picture_blocks])
        vlm_only: list[str] = ParseRecall.vlm_only(text_only, full)
        summary: dict[str, Any] = {
            **ParseRecall.summary(full),
            "text_only_reachable": ParseRecall.summary(text_only)["reachable"],
            "vlm_only_reachable": len(vlm_only),
            "pictures_described": len(picture_blocks),
            "vlm_model": self._vlm_model,
        }
        write_json(
            self._out_dir / f"stage1_{name}.json",
            stage_payload(
                stage=1,
                extractor=name,
                company=self._company,
                year=self._year,
                summary=summary,
                questions=[asdict(result) for result in full],
                vlm_only_questions=vlm_only,
                sources=corpus.sources,
                errors=corpus.errors,
            ),
        )
        return [
            name,
            str(summary["text_only_reachable"]),
            str(summary["reachable"]),
            str(summary["vlm_only_reachable"]),
            str(summary["pictures_described"]),
            str(summary["population"]),
        ]

    async def _describe(
        self, name: str, corpus: ExtractedCorpus, projector: BlockProjector
    ) -> list[SearchableBlock]:
        pictures: list[tuple[str, PictureBlock]] = corpus.pictures()
        if not pictures:
            return []
        refs: list[PictureRef] = [self._ref(picture) for _, picture in pictures]
        describer = OpenAIPictureDescriber(openai_async(), model=self._vlm_model)
        descriptions = await describer.describe(refs, doc_id=f"stage1:{name}")
        blocks: list[SearchableBlock] = []
        for (source, picture), description in zip(pictures, descriptions, strict=True):
            blocks.extend(projector.project_pictures(source, [picture], [description]))
        return blocks

    @staticmethod
    def _ref(picture: PictureBlock) -> PictureRef:
        return PictureRef(
            page_no=picture.page_no,
            heading_path=list(picture.heading_path),
            pil_image=picture.pil_image,
            bbox_area_pct=picture.bbox_area_pct,
            self_ref=picture.self_ref,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1: parse + VLM recall per extractor.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--vlm-model", default=None)
    parser.add_argument("--pdf-dir", type=Path, default=None)
    parser.add_argument("--pdf", type=Path, nargs="*", default=[])
    parser.add_argument("--extractors", nargs="*", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("results/funnel"))
    return parser.parse_args()


def main() -> None:
    """Run stage 1 and print text-only vs +VLM reachability per extractor."""
    args: argparse.Namespace = _parse_args()
    pdfs: list[Path] = pdf_paths(args.pdf_dir, args.pdf)
    if not pdfs:
        raise SystemExit("no PDFs: pass --pdf-dir and/or --pdf with absolute paths")
    runner = Stage1Runner(
        args.company,
        args.year,
        args.extractors or available_extractors(),
        pdfs,
        args.out_dir,
        args.vlm_model or get_settings().vlm.model,
    )
    rows: list[list[str]] = asyncio.run(runner.run())
    Console().print(
        summary_table(
            "stage 1 — parse + VLM recall",
            ["extractor", "text only", "+vlm", "vlm-only delta", "pictures", "of"],
            rows,
        )
    )


if __name__ == "__main__":
    main()
