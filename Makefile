UV  ?= uv
RAG := $(UV) run rag

SHELL       := /bin/bash
.SHELLFLAGS := -o pipefail -c

TOP_K     ?= 5
Q         ?=
DATA_FILE ?=
DATA_DIR  ?=
COMPANY   ?=
DOMAIN    ?= corporate
YEAR      ?=
NAME      ?=
SUITE     ?=
EVAL_FLAGS ?=
EXTRACTOR ?=
KIND      ?=
META      ?=
FILTER    ?=
CACHE_DIR ?= $(HOME)/.cache/peerdex/cache
DB_DIR    ?= $(HOME)/.cache/peerdex/lancedb
MODELS_DIR ?= $(HOME)/.cache/peerdex/docling-models
LOG_DIR   ?= /tmp/peerdex/logs

need_company = test -n "$(COMPANY)" || (echo "COMPANY=... required" && exit 2)
need_domain  = test -n "$(DOMAIN)"  || (echo "DOMAIN=... required"  && exit 2)
need_year    = test -n "$(YEAR)"    || (echo "YEAR=... required"    && exit 2)
need_data    = test -n "$(DATA_DIR)$(DATA_FILE)" || (echo "DATA_DIR=/abs/dir or DATA_FILE=/abs/file required" && exit 2)
need_extractor = test -n "$(EXTRACTOR)" || (echo "EXTRACTOR=docling|docling-rs|liteparse|odl|xberg required" && exit 2)
need_kind    = test -n "$(KIND)"    || (echo "KIND=quantitative|qualitative required" && exit 2)
year_filter  = $(if $(YEAR),-f year=$(YEAR))

.PHONY: install clean-cache clean-db clean-parse refresh-models tests lint format index ask eval

install:
	$(UV) sync --all-extras
	@mkdir -p $(CACHE_DIR) $(DB_DIR) $(MODELS_DIR)
	@test -f .env || (test -f .env.example && cp .env.example .env || true)
	@echo "done. set OPENAI_API_KEY in .env, then run 'make index'."


clean-cache:
	rm -rf $(CACHE_DIR)


clean-db:
	rm -rf $(DB_DIR)


clean-parse:
	rm -rf $(CACHE_DIR)/parse $(CACHE_DIR)/chunks


refresh-models:
	@$(need_extractor)
	@case "$(EXTRACTOR)" in \
	  docling)    $(UV) run docling-tools models download --output-dir $(MODELS_DIR) ;; \
	  docling-rs) $(UV) run python experiments/refresh_models.py $(if $(DRY),--dry-run) ;; \
	  *)          echo "$(EXTRACTOR): no models to fetch" ;; \
	esac


tests:
	$(UV) run pytest tests/ -q -p no:deepeval -W error


lint:
	$(UV) run ruff check src tests && $(UV) run ruff format --check src tests


format:
	$(UV) run ruff check --fix src tests && $(UV) run ruff format src tests


index:
	@$(need_extractor)
	@$(need_data)
	@$(need_company)
	@$(need_domain)
	@$(need_year)
	@mkdir -p $(LOG_DIR)
	$(RAG) index "$(if $(DATA_DIR),$(DATA_DIR),$(DATA_FILE))" -c "$(COMPANY)" -d $(DOMAIN) -y $(YEAR) -e $(EXTRACTOR) $(META) 2>&1 | tee -a $(LOG_DIR)/index.log


ask:
	@test -n "$(Q)" || (echo 'Q="..." required' && exit 2)
	@$(need_company)
	@$(need_domain)
	@$(need_kind)
	$(RAG) ask "$(Q)" -c "$(COMPANY)" -d $(DOMAIN) $(year_filter) $(FILTER) -k $(KIND)


eval:
	@mkdir -p $(LOG_DIR)
	$(UV) run python experiments/test_eval_suite.py \
	  $(if $(COMPANY),--company "$(COMPANY)") \
	  $(if $(YEAR),--year $(YEAR)) \
	  $(if $(NAME),--name $(NAME)) \
	  $(if $(SUITE),--suite "$(SUITE)") \
	  --domain $(DOMAIN) --top-k $(TOP_K) $(EVAL_FLAGS) 2>&1 | tee -a $(LOG_DIR)/eval.log
