UV  ?= uv
RAG := $(UV) run rag

TOP_K      ?= 5
Q          ?=
PDF        ?=
PDF_DIR    ?=
COMPANY    ?=
DOMAIN     ?= corporate
YEAR       ?=
NAME       ?= default
EXTRACTOR  ?= docling
EXTRACTORS ?=
VLM_MODEL  ?=
META       ?=
FILTER     ?=
LIMIT      ?=
RESULTS    ?= results/funnel

need_company = test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
need_domain  = test -n "$(DOMAIN)"  || (echo "DOMAIN=... required"  && exit 2)
need_year    = test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
need_pdfs    = test -n "$(PDF_DIR)$(PDF)" || (echo "PDF_DIR=/abs/dir or PDF=/abs/file.pdf required" && exit 2)
year_filter  = $(if $(YEAR),-f year=$(YEAR))
corpus_args  = $(if $(PDF_DIR),--pdf-dir "$(PDF_DIR)") $(if $(PDF),--pdf "$(PDF)") $(if $(EXTRACTORS),--extractors $(EXTRACTORS))

.PHONY: install clean index ask suite test lint format \
        eval eval-retrieval eval-synthesis eval-vlm eval-fast \
        stage0 stage1 stage2 stage3 bench

install:
	$(UV) sync --all-extras
	@mkdir -p cache/docling-models lancedb
	@test -f .env || (test -f .env.example && cp .env.example .env || true)
	@test -n "$$(ls -A cache/docling-models 2>/dev/null)" \
	  || $(UV) run docling-tools models download --output-dir ./cache/docling-models
	@echo "done. set OPENAI_API_KEY in .env, then run 'make index'."

clean:
	rm -rf cache lancedb

test:
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

eval:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(UV) run pytest experiments/ -v --company $(COMPANY) --domain $(DOMAIN) --year $(YEAR)

eval-retrieval:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(UV) run pytest experiments/test_retrieval.py -v --company $(COMPANY) --domain $(DOMAIN) --year $(YEAR)

eval-synthesis:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(UV) run pytest experiments/test_synthesis.py -v --company $(COMPANY) --domain $(DOMAIN) --year $(YEAR)

eval-vlm:
	$(UV) run pytest experiments/test_vlm.py -v

eval-fast:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(UV) run pytest experiments/test_retrieval.py::test_retrieval_surfaces_value_on_recorded_pages -v --company $(COMPANY) --domain $(DOMAIN) --year $(YEAR) $(if $(EXTRACTOR),--extractor $(EXTRACTOR))

stage0:
	@$(need_company)
	@$(need_year)
	@$(need_pdfs)
	$(UV) run python experiments/stage0_parse_recall.py --company "$(COMPANY)" --year $(YEAR) $(corpus_args) --out-dir $(RESULTS)

stage1:
	@$(need_company)
	@$(need_year)
	@$(need_pdfs)
	$(UV) run python experiments/stage1_vlm_recall.py --company "$(COMPANY)" --year $(YEAR) $(corpus_args) $(if $(VLM_MODEL),--vlm-model $(VLM_MODEL)) --out-dir $(RESULTS)

stage2:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	@test -f $(RESULTS)/stage0_$(EXTRACTOR).json || (echo "run 'make stage0' first: $(RESULTS)/stage0_$(EXTRACTOR).json missing" && exit 2)
	$(UV) run python experiments/stage2_retrieval_recall.py --company "$(COMPANY)" --domain $(DOMAIN) --year $(YEAR) --extractor $(EXTRACTOR) --stage0 $(RESULTS)/stage0_$(EXTRACTOR).json $(if $(wildcard $(RESULTS)/stage1_$(EXTRACTOR).json),--stage1 $(RESULTS)/stage1_$(EXTRACTOR).json) --out-dir $(RESULTS)

stage3:
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	$(UV) run python experiments/score_suite.py --company "$(COMPANY)" --domain $(DOMAIN) --year $(YEAR) --extractor $(EXTRACTOR) $(if $(LIMIT),--limit $(LIMIT)) --out $(RESULTS)/stage3_$(EXTRACTOR).json

bench:
	$(UV) run python experiments/funnel_report.py --dir $(RESULTS)
