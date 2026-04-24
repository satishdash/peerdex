# peerdex Makefile
#
# Usage:
#   make install
#   make index PDF=~/Documents/suncor_2025.pdf COMPANY=suncor YEAR=2025 TYPE=annual_report
#   make index PDF=report.pdf COMPANY=acme YEAR=2025 TYPE=annual_report EXTRACTOR=docling
#   make ask Q="Total number of employees?" COMPANY=suncor YEAR=2025
#   make ask Q="Total revenue?" COMPANY=neste YEAR=2025 TYPE=annual_report
#   make suite NAME=annual COMPANY=suncor YEAR=2025
#   make eval COMPANY=suncor YEAR=2025
#   make eval-retrieval COMPANY=suncor YEAR=2025
#   make eval-synthesis COMPANY=suncor YEAR=2025
#   make eval-vlm
#   make eval-fast COMPANY=suncor YEAR=2025

UV  ?= uv
RAG := $(UV) run rag

TYPE      ?=
TOP_K     ?= 5
Q         ?=
PDF       ?=
COMPANY   ?=
YEAR      ?=
NAME      ?=
EXTRACTOR ?= docling

.PHONY: install clean index ask suite \
        eval eval-retrieval eval-synthesis eval-vlm eval-fast

# ---------- setup ----------

install:
	$(UV) sync --all-extras
	@mkdir -p cache/docling-models lancedb
	@test -f .env || (test -f .env.example && cp .env.example .env || true)
	@test -n "$$(ls -A cache/docling-models 2>/dev/null)" \
	  || $(UV) run docling-tools models download --output-dir ./cache/docling-models
	@echo "done. set OPENAI_API_KEY in .env, then run 'make index'."

clean:
	rm -rf cache lancedb

# ---------- pipeline ----------

index:
	@test -n "$(PDF)"     || (echo "PDF=... required"     && exit 2)
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	@test -n "$(TYPE)"    || (echo "TYPE=... required"    && exit 2)
	$(RAG) index "$(PDF)" --company "$(COMPANY)" --year $(YEAR) --type $(TYPE) --extractor $(EXTRACTOR)

ask:
	@test -n "$(Q)"       || (echo 'Q="..." required'     && exit 2)
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(RAG) ask "$(Q)" --company "$(COMPANY)" --year $(YEAR) $(if $(TYPE),--type $(TYPE)) --top-k $(TOP_K)

suite:
	@test -n "$(NAME)"    || (echo 'NAME=annual|sustainability required' && exit 2)
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(RAG) suite $(NAME) --company "$(COMPANY)" --year $(YEAR) $(if $(TYPE),--type $(TYPE)) --top-k $(TOP_K)

# ---------- evaluation ----------

eval:
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(UV) run pytest experiments/ -v --company $(COMPANY) --year $(YEAR)

eval-retrieval:
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(UV) run pytest experiments/test_retrieval.py -v --company $(COMPANY) --year $(YEAR)

eval-synthesis:
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(UV) run pytest experiments/test_synthesis.py -v --company $(COMPANY) --year $(YEAR)

eval-vlm:
	$(UV) run pytest experiments/test_vlm.py -v

eval-fast:
	@test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
	@test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
	$(UV) run pytest experiments/test_retrieval.py::test_retrieval_page_precision -v --company $(COMPANY) --year $(YEAR)
