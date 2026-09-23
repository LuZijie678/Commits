SHELL := /bin/bash

STEP1_DIR := code/step1
STEP2_DIR := code/step2

STEP1_RUN_NAME ?= step1_strategy_compare
STEP1_BASE_OUTPUT_DIR ?= outputs
STEP2_LOCAL_CONFIG_FILE := $(STEP2_DIR)/configs/step2_runtime_config.local.json
STEP2_DEFAULT_CONFIG := $(if $(wildcard $(STEP2_LOCAL_CONFIG_FILE)),configs/step2_runtime_config.local.json,configs/step2_runtime_config.json)
STEP2_STEP1_INPUT ?= ../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv
STEP2_SOURCE_OUTPUT ?= ../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv
STEP2_SOURCE_MANIFEST ?= ../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json
STEP2_CONFIG ?= $(STEP2_DEFAULT_CONFIG)
STEP2_MOCK_CONFIG ?= configs/step2_from_step1_source_config.json
STEP2_FULLSCALE_CONFIG ?= configs/step2_fullscale_config.json
STEP2_FULLSCALE_GENERATION_CONFIG ?= $(STEP2_DEFAULT_CONFIG)
STEP2_PREFLIGHT_ARGS ?=
STEP2_PREFLIGHT_OUTPUT_DIR ?= ../../datasets/step2/delivery/current
STEP2_FEWSHOT_REVIEW ?= ../../datasets/step2/review/m_only_review_sheet.csv
STEP2_FEWSHOT_DELIVERY ?= ../../datasets/step2/delivery/current
STEP2_FULLSCALE_OUTPUT_ROOT ?= outputs/step2_fullscale_current
STEP2_FULLSCALE_ARGS ?=
STEP2_PROXY_ENV := eval "$$(python3 tools/emit_proxy_env.py)"
STEP2_MPLCONFIGDIR ?= /private/tmp/step2_mplconfig

.PHONY: help datasets-check step1-help step1-run step2-bridge step2-help step2-preflight step2-mock step2-fullscale-plan step2-fullscale-run step2-fewshot-prepare step2-fewshot-report step2-fewshot-materialize

help:
	@echo "Available targets:"
	@echo "  make datasets-check   # Verify live datasets needed by full Step1/Step2 runs"
	@echo "  make step1-help       # Show Step1 runner help"
	@echo "  make step1-run        # Run Step1 strategy compare wrapper"
	@echo "  make step2-bridge     # Convert current Step1 source pool to Step2 source CSV"
	@echo "  make step2-help       # Show Step2 runner help"
	@echo "  make step2-preflight  # Run Step2 formal preflight with STEP2_CONFIG"
	@echo "  make step2-mock       # Run Step2 mock-generator path with STEP2_MOCK_CONFIG"
	@echo "  make step2-fullscale-plan # Materialize the Step2 full-scale primary plan and shards"
	@echo "  make step2-fullscale-run  # Run the Step2 full-scale sharded pipeline"
	@echo "  make step2-fewshot-prepare     # Build M-only disjoint few-shot candidates and review sheet"
	@echo "  make step2-fewshot-report      # Summarize current few-shot review sheet blockers"
	@echo "  make step2-fewshot-materialize # Build formal-ready few-shot delivery from reviewed rows"

datasets-check:
	python3 scripts/check_dataset_readiness.py

step1-help:
	cd "$(STEP1_DIR)" && python3 -m src.pipeline.run_step1 --help

step1-run:
	cd "$(STEP1_DIR)" && \
	RUN_NAME="$(STEP1_RUN_NAME)" \
	BASE_OUTPUT_DIR="$(STEP1_BASE_OUTPUT_DIR)" \
	bash scripts/run_step1_strategy_compare.sh

step2-bridge:
	cd "$(STEP2_DIR)" && \
	python3 tools/export_step1_to_step2_source.py \
	  --input "$(STEP2_STEP1_INPUT)" \
	  --output "$(STEP2_SOURCE_OUTPUT)" \
	  --manifest "$(STEP2_SOURCE_MANIFEST)"

step2-help:
	cd "$(STEP2_DIR)" && $(STEP2_PROXY_ENV) && python3 code/construct_simple_two_intent.py --help

step2-preflight:
	cd "$(STEP2_DIR)" && \
	$(STEP2_PROXY_ENV) && \
	MPLCONFIGDIR="$(STEP2_MPLCONFIGDIR)" \
	python3 code/construct_simple_two_intent.py \
	  --preflight \
	  $(STEP2_PREFLIGHT_ARGS) \
	  --output-dir "$(STEP2_PREFLIGHT_OUTPUT_DIR)" \
	  --config "$(STEP2_CONFIG)"

step2-mock:
	cd "$(STEP2_DIR)" && \
	$(STEP2_PROXY_ENV) && \
	MPLCONFIGDIR="$(STEP2_MPLCONFIGDIR)" \
	python3 code/construct_simple_two_intent.py \
	  --debug-mock-generator \
	  --config "$(STEP2_MOCK_CONFIG)"

step2-fullscale-plan:
	cd "$(STEP2_DIR)" && \
	$(STEP2_PROXY_ENV) && \
	MPLCONFIGDIR="$(STEP2_MPLCONFIGDIR)" \
	python3 code/run_step2_fullscale_sharded.py \
	  --config "$(STEP2_FULLSCALE_CONFIG)" \
	  --output-root "$(STEP2_FULLSCALE_OUTPUT_ROOT)" \
	  --plan-only \
	  $(STEP2_FULLSCALE_ARGS)

step2-fullscale-run:
	cd "$(STEP2_DIR)" && \
	$(STEP2_PROXY_ENV) && \
	MPLCONFIGDIR="$(STEP2_MPLCONFIGDIR)" \
	python3 code/run_step2_fullscale_sharded.py \
	  --config "$(STEP2_FULLSCALE_CONFIG)" \
	  --generation-config "$(STEP2_FULLSCALE_GENERATION_CONFIG)" \
	  --output-root "$(STEP2_FULLSCALE_OUTPUT_ROOT)" \
	  $(STEP2_FULLSCALE_ARGS)

step2-fewshot-prepare:
	cd "$(STEP2_DIR)" && \
	python3 code/build_formal_fewshot_pool.py prepare

step2-fewshot-report:
	cd "$(STEP2_DIR)" && \
	python3 code/build_formal_fewshot_pool.py report \
	  --review-sheet-csv "$(STEP2_FEWSHOT_REVIEW)"

step2-fewshot-materialize:
	cd "$(STEP2_DIR)" && \
	python3 code/build_formal_fewshot_pool.py materialize \
	  --review-sheet-csv "$(STEP2_FEWSHOT_REVIEW)" \
	  --delivery-dir "$(STEP2_FEWSHOT_DELIVERY)"
