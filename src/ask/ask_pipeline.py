"""The ask flow: route, find, read, resolve, and at most one escalation."""

from collections.abc import Sequence
from dataclasses import replace
from typing import ClassVar

from ask.answer import Answer
from ask.answer_kind import AnswerKind
from ask.citation import Citation
from ask.escalate import ParentFetch, Rewriter
from ask.find import Finder
from ask.passage import Passage
from ask.question import Question
from ask.read import ProseReader, Reader
from ask.reading import Reading
from ask.resolution import Resolution
from ask.resolve import Resolver
from ask.route import Router, Routing
from shared.settings import get_settings


class AskPipeline:
    """Runs one question to an answer or a refusal.

    Static: two attempts at most, no agent, no loop. Every path is the same length
    every time, which is what makes a toggle measurable.
    """

    _NO_PASSAGES: ClassVar[str] = "no passages matched the question"
    _NO_PROSE: ClassVar[str] = "the passages do not answer the question"

    @classmethod
    async def ask(cls, question: Question) -> Answer:
        """Answer one question, escalating once when the first attempt refuses.

        Args:
            question: The question, carrying the answer's shape and the slice to search.

        Returns:
            The answer, or a refusal carrying its reason.
        """
        routing: Routing = Router.route(question)
        passages: list[Passage] = await Finder.find(question)
        first: Answer = await cls._attempt(question, routing, passages, attempts=1)
        if not first.refused or not get_settings().retrieval.escalate_on_refusal:
            return first
        return await cls._escalated(question, routing, passages)

    @classmethod
    async def _escalated(
        cls, question: Question, routing: Routing, passages: Sequence[Passage]
    ) -> Answer:
        """The second and final attempt, on whichever branch the refusal calls for.

        Nothing came back means rewriting lexically and searching once more; something
        came back but held no value means fetching those passages' parents by id,
        without searching at all.

        Args:
            question: The question being answered.
            routing: The answer's shape and the period.
            passages: What the first search returned.

        Returns:
            The answer, or a refusal carrying its reason.
        """
        widened: list[Passage] = (
            await cls._searched_again(question, passages)
            if not passages
            else ParentFetch.widen(question.domain, passages)
        )
        return await cls._attempt(question, routing, widened, attempts=2)

    @staticmethod
    async def _searched_again(question: Question, passages: Sequence[Passage]) -> list[Passage]:
        """One more search, on a query broadened from what came back.

        Args:
            question: The question whose first search returned nothing.
            passages: What came back, which is nothing on this branch.

        Returns:
            The passages the broadened query found.
        """
        broader: str = Rewriter.rewrite(question.text, passages)
        return await Finder.find(replace(question, text=broader))

    @classmethod
    async def _attempt(
        cls,
        question: Question,
        routing: Routing,
        passages: Sequence[Passage],
        *,
        attempts: int,
    ) -> Answer:
        """One read and resolve over the passages in hand.

        Args:
            question: The question being answered.
            routing: The answer's shape and the period.
            passages: The passages to read.
            attempts: Which attempt this is, for the caller to see.

        Returns:
            The answer, or a refusal carrying its reason.
        """
        if not passages:
            return cls._nothing_found(routing, attempts)
        if routing.kind is AnswerKind.QUALITATIVE:
            prose: str = await ProseReader.read(question, passages)
            return cls._prose(routing, prose, passages, attempts)
        readings: list[Reading] = await Reader.read(question, passages)
        resolved: Resolution = Resolver.resolve(readings, routing.period, question.text)
        return cls._quantitative(routing, resolved, passages, attempts)

    @classmethod
    def _nothing_found(cls, routing: Routing, attempts: int) -> Answer:
        """A refusal when the search returned nothing, so there was nothing to read.

        Args:
            routing: The answer's shape and the period.
            attempts: Which attempt this is.

        Returns:
            The refusal, which sends the flow down the no-passages branch.
        """
        return Answer(kind=routing.kind, refused=True, reason=cls._NO_PASSAGES, attempts=attempts)

    @classmethod
    def _quantitative(
        cls,
        routing: Routing,
        resolved: Resolution,
        passages: Sequence[Passage],
        attempts: int,
    ) -> Answer:
        """The value alone, or a refusal naming which gate it failed.

        Args:
            routing: The answer's shape and the period.
            resolved: What the gates decided.
            passages: The chunks the value was read from.
            attempts: Which attempt this is.

        Returns:
            The answer.
        """
        return Answer(
            kind=routing.kind,
            value=resolved.value,
            unit=resolved.unit,
            refused=resolved.refused,
            reason=resolved.reason,
            attempts=attempts,
            citations=cls._cited(passages, refused=resolved.refused),
        )

    @classmethod
    def _prose(
        cls, routing: Routing, text: str, passages: Sequence[Passage], attempts: int
    ) -> Answer:
        """The prose answer, or a refusal when the passages support none.

        Args:
            routing: The answer's shape and the period.
            text: What the prose reader returned.
            passages: The chunks the prose was read from.
            attempts: Which attempt this is.

        Returns:
            The answer.
        """
        return Answer(
            kind=routing.kind,
            text=text,
            refused=not text,
            reason="" if text else cls._NO_PROSE,
            attempts=attempts,
            citations=cls._cited(passages, refused=not text),
        )

    @staticmethod
    def _cited(passages: Sequence[Passage], *, refused: bool) -> tuple[Citation, ...]:
        """The chunks an answer traces back to.

        Args:
            passages: The chunks that were read.
            refused: Whether the attempt refused, in which case there is nothing to trace.

        Returns:
            One citation per passage, or none at all when the answer was refused.
        """
        if refused:
            return ()
        return tuple(Citation.of(p) for p in passages)
