"""Smoke run: sidecar attribute adapter against the real Globex meta file."""

from pathlib import Path

from peerdex.shared.metadata import (
    AttributeFilter,
    CompositeAttributeSource,
    DocumentMetadata,
    ExplicitAttributeSource,
    SidecarAttributeSource,
)

PDF = Path("~/Documents/globex/f797953b.pdf")


def main() -> None:
    sidecar_attrs = SidecarAttributeSource().load(PDF)
    print("sidecar attributes:", sidecar_attrs)

    composed = CompositeAttributeSource(
        [SidecarAttributeSource(), ExplicitAttributeSource({"benchmark": True})]
    ).load(PDF)
    meta = DocumentMetadata(
        company="Globex", year=2025, source_uri=str(PDF), attributes=composed
    )
    print("document attributes:", meta.attributes)
    print("company:", meta.company, "year:", meta.year)

    filt = AttributeFilter("globex", {"benchmark": True})
    node_metadata = {"company": meta.company, "year": meta.year, **meta.attributes}
    print("filter pairs:", filt.pairs)
    print("filter matches indexed node:", filt.matches(node_metadata))


if __name__ == "__main__":
    main()
