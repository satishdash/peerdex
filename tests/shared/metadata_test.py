"""Unit tests for per-document metadata, attribute validation, filters and parsing."""

import pytest

from peerdex.shared.metadata import (
    AttributeFilter,
    DocumentMetadata,
    KeyValueParser,
    MetadataVisibility,
    Scalar,
    ScalarSetValueParser,
    ScalarValueParser,
)

SCALAR: ScalarValueParser = ScalarValueParser()
SCALAR_SET: ScalarSetValueParser = ScalarSetValueParser()


def test_given_valid_attributes_when_constructed_then_identity_normalized() -> None:
    meta: DocumentMetadata = DocumentMetadata(
        company=" Acme ",
        year=2025,
        source_uri="/docs/a.pdf",
        extractor="liteparse",
        attributes={"benchmark": True, "title": "T"},
    )
    assert meta.company == "acme"
    assert meta.year == 2025
    assert meta.source_uri == "/docs/a.pdf"
    assert meta.extractor == "liteparse"
    assert meta.attributes == {"benchmark": 1, "title": "T"}
    assert type(meta.attributes["benchmark"]) is int


@pytest.mark.parametrize(
    "key", ["doc_id", "year", "company", "is_table", "prompt_version", "extractor"]
)
def test_given_reserved_attribute_key_when_constructed_then_rejected(key: str) -> None:
    with pytest.raises(ValueError, match=key):
        DocumentMetadata(
            company="a", year=2025, source_uri="u", extractor="e", attributes={key: "x"}
        )


@pytest.mark.parametrize("value", [[1, 2], {"a": 1}, None, (1,)])
def test_given_non_scalar_attribute_when_constructed_then_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="scalar"):
        DocumentMetadata(
            company="a", year=2025, source_uri="u", extractor="e", attributes={"k": value}
        )


@pytest.mark.parametrize(
    ("values", "pair", "expected"),
    [
        (SCALAR, "benchmark=true", {"benchmark": True}),
        (SCALAR, "benchmark=FALSE", {"benchmark": False}),
        (SCALAR, "year=2025", {"year": 2025}),
        (SCALAR, "title=Annual Report 2025", {"title": "Annual Report 2025"}),
        (SCALAR, "ratio=1.5", {"ratio": "1.5"}),
        (SCALAR, "k=v=w", {"k": "v=w"}),
        (SCALAR, "title=Index, 2025", {"title": "Index, 2025"}),
        (SCALAR_SET, "year=2025", {"year": (2025,)}),
        (SCALAR_SET, "year=2023,2024", {"year": (2023, 2024)}),
        (SCALAR_SET, "benchmark=true,FALSE", {"benchmark": (True, False)}),
        (SCALAR_SET, "type=Annual,Data Index", {"type": ("Annual", "Data Index")}),
        (SCALAR_SET, "title=Index\\, 2025", {"title": ("Index, 2025",)}),
        (SCALAR_SET, "title=Index\\, 2025,Annual", {"title": ("Index, 2025", "Annual")}),
        (SCALAR_SET, "k=v=w,x", {"k": ("v=w", "x")}),
        (SCALAR_SET, "year=2023,draft", {"year": ("2023", "draft")}),
    ],
)
def test_given_key_value_pair_when_parsed_then_typed_value(
    values: ScalarValueParser | ScalarSetValueParser,
    pair: str,
    expected: dict[str, Scalar] | dict[str, tuple[Scalar, ...]],
) -> None:
    assert KeyValueParser(values).parse([pair]) == expected


@pytest.mark.parametrize(
    ("values", "pairs", "expected"),
    [
        (SCALAR, ["benchmark=true", "year=2024"], {"benchmark": True, "year": 2024}),
        (
            SCALAR_SET,
            ["year=2023,2024", "region=emea"],
            {"year": (2023, 2024), "region": ("emea",)},
        ),
    ],
)
def test_given_multiple_pairs_when_parsed_then_all_present(
    values: ScalarValueParser | ScalarSetValueParser,
    pairs: list[str],
    expected: dict[str, Scalar] | dict[str, tuple[Scalar, ...]],
) -> None:
    assert KeyValueParser(values).parse(pairs) == expected


@pytest.mark.parametrize("pair", ["novalue", "=x"])
def test_given_malformed_pair_when_parsed_then_rejected(pair: str) -> None:
    with pytest.raises(ValueError, match="KEY=VALUE"):
        KeyValueParser(SCALAR).parse([pair])


@pytest.mark.parametrize("values", [SCALAR, SCALAR_SET])
def test_given_repeated_key_when_parsed_then_rejected(
    values: ScalarValueParser | ScalarSetValueParser,
) -> None:
    with pytest.raises(ValueError, match="'year'"):
        KeyValueParser(values).parse(["year=2023", "year=2024"])


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        pytest.param(
            {"benchmark": True, "year": 2024},
            {"company": ("acme",), "benchmark": (1,), "year": (2024,)},
            id="single-values",
        ),
        pytest.param(
            {"year": [2023, 2024], "benchmark": (True, False)},
            {"company": ("acme",), "year": (2023, 2024), "benchmark": (1, 0)},
            id="multi-values",
        ),
    ],
)
def test_given_company_and_attributes_when_filter_built_then_pairs_canonical(
    attributes: dict[str, Scalar | list[Scalar] | tuple[Scalar, ...]],
    expected: dict[str, tuple[Scalar, ...]],
) -> None:
    filt: AttributeFilter = AttributeFilter(" Acme ", attributes)
    assert filt.pairs == expected
    assert {type(value) for values in filt.pairs.values() for value in values} == {str, int}


@pytest.mark.parametrize("values", [[2023, "draft"], []])
def test_given_unusable_value_set_when_filter_built_then_rejected(values: list[Scalar]) -> None:
    with pytest.raises(ValueError, match="year"):
        AttributeFilter("acme", {"year": values})


@pytest.mark.parametrize(
    ("attributes", "metadata", "expected"),
    [
        pytest.param(None, {"company": "acme", "year": 2023}, True, id="company-only"),
        pytest.param(None, {"company": "other", "year": 2025}, False, id="wrong-company"),
        pytest.param(
            {"year": [2023, 2024]},
            {"company": "acme", "year": 2024},
            True,
            id="multi-value-member",
        ),
        pytest.param(
            {"year": [2023, 2024]},
            {"company": "acme", "year": 2025},
            False,
            id="multi-value-non-member",
        ),
        pytest.param(
            {"year": [2023, 2024]},
            {"company": "acme"},
            False,
            id="multi-value-key-missing",
        ),
        pytest.param(
            {"year": [2023, 2024], "region": "emea"},
            {"company": "acme", "year": 2023, "region": "emea"},
            True,
            id="and-across-keys-or-within-key",
        ),
        pytest.param(
            {"year": [2023, 2024], "region": "emea"},
            {"company": "acme", "year": 2023, "region": "apac"},
            False,
            id="and-across-keys-one-key-fails",
        ),
        pytest.param(
            {"benchmark": [True, False]},
            {"company": "acme", "benchmark": 0},
            True,
            id="bool-set-matches-canonical-node-value",
        ),
        pytest.param(
            {"benchmark": True},
            {"company": "acme", "benchmark": 1},
            True,
            id="bool-filter-matches-canonical-node-value",
        ),
        pytest.param(
            {"benchmark": True},
            {"company": "acme", "benchmark": 0},
            False,
            id="attribute-differs",
        ),
        pytest.param(
            {"benchmark": True},
            {"company": "acme"},
            False,
            id="attribute-missing",
        ),
    ],
)
def test_given_node_metadata_when_matched_then_predicate_decides(
    attributes: dict[str, Scalar | list[Scalar]] | None,
    metadata: dict[str, Scalar],
    expected: bool,
) -> None:
    assert AttributeFilter("acme", attributes).matches(metadata) is expected


def test_given_node_metadata_when_classified_then_opaque_keys_excluded() -> None:
    metadata: dict[str, Scalar] = {
        "doc_id": "d",
        "company": "acme",
        "year": 2025,
        "page_no": 1,
        "heading_path": "H",
        "is_table": False,
        "is_figure": False,
        "is_parent": False,
        "idx": 0,
        "source_uri": "/docs/a.pdf",
        "prompt_version": "v1",
        "extractor": "liteparse",
        "title": "T",
        "type": "Sustainability report",
        "bucket_key": "A/a.pdf",
        "url": "https://x",
    }
    excluded: list[str] = MetadataVisibility().excluded(metadata)
    assert excluded == [
        "bucket_key",
        "doc_id",
        "extractor",
        "idx",
        "is_parent",
        "prompt_version",
        "source_uri",
        "url",
    ]
