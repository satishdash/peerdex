UV  ?= uv
RAG := $(UV) run rag

TOP_K     ?= 5
Q         ?=
PDF       ?=
PDF_DIR   ?=
COMPANY   ?=
DOMAIN    ?= corporate
YEAR      ?=
NAME      ?= default
EXTRACTOR ?= docling
META      ?=
FILTER    ?=

need_company = test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
need_domain  = test -n "$(DOMAIN)"  || (echo "DOMAIN=... required"  && exit 2)
need_year    = test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
need_pdfs    = test -n "$(PDF_DIR)$(PDF)" || (echo "PDF_DIR=/abs/dir or PDF=/abs/file.pdf required" && exit 2)
year_filter  = $(if $(YEAR),-f year=$(YEAR))

.PHONY: install clean tests lint format index ask suite

install:
	$(UV) sync --all-extras
	@mkdir -p cache/docling-models lancedb
	@test -f .env || (test -f .env.example && cp .env.example .env || true)
	@test -n "$$(ls -A cache/docling-models 2>/dev/null)" \
	  || $(UV) run docling-tools models download --output-dir ./cache/docling-models
	@echo "done. set OPENAI_API_KEY in .env, then run 'make index'."

clean:
	rm -rf cache lancedb

tests:
	$(UV) run pytest tests/ -q -p no:deepeval -W error

lint:
	$(UV) run ruff check src tests && $(UV) run ruff format --check src tests

format:
	$(UV) run ruff check --fix src tests && $(UV) run ruff format src tests

index:
	@$(need_pdfs)
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(RAG) index "$(if $(PDF_DIR),$(PDF_DIR),$(PDF))" -c "$(COMPANY)" -d $(DOMAIN) -y $(YEAR) -e $(EXTRACTOR) $(META)

ask:
	@test -n "$(Q)" || (echo 'Q="..." required' && exit 2)
	@$(need_company)
	@$(need_domain)
	$(RAG) ask "$(Q)" -c "$(COMPANY)" -d $(DOMAIN) $(year_filter) $(FILTER) -k $(TOP_K)

suite:
	@$(need_company)
	@$(need_domain)
	$(RAG) suite $(NAME) -c "$(COMPANY)" -d $(DOMAIN) $(year_filter) $(FILTER) -k $(TOP_K)
