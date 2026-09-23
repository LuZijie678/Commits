SHELL := /bin/bash

STEP1_DIR := 待实验step1文件包
STEP2_DIR := 待实验step2文件包

STEP1_RUN_NAME ?= step1_strategy_compare
STEP1_BASE_OUTPUT_DIR ?= outputs
STEP2_STEP1_INPUT ?= step1输出放这里/conservative_atomic_sources.csv
STEP2_SOURCE_OUTPUT ?= data/step2_source_candidates_from_step1.csv
STEP2_SOURCE_MANIFEST ?= data/step2_source_candidates_from_step1_manifest.json
STEP2_CONFIG ?= configs/step2_from_step1_source_config.json

.PHONY: help step1-help step1-run step2-bridge step2-help step2-preflight step2-mock

help:
	@echo "Available targets:"
	@echo "  make step1-help       # Show Step1 runner help"
	@echo "  make step1-run        # Run Step1 strategy compare wrapper"
	@echo "  make step2-bridge     # Convert Step1 conservative source pool to Step2 source CSV"
	@echo "  make step2-help       # Show Step2 runner help"
	@echo "  make step2-preflight  # Run Step2 preflight with STEP2_CONFIG"
	@echo "  make step2-mock       # Run Step2 mock-generator path with STEP2_CONFIG"

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
	cd "$(STEP2_DIR)" && python3 code/construct_simple_two_intent.py --help

step2-preflight:
	cd "$(STEP2_DIR)" && \
	python3 code/construct_simple_two_intent.py \
	  --preflight \
	  --config "$(STEP2_CONFIG)"

step2-mock:
	cd "$(STEP2_DIR)" && \
	python3 code/construct_simple_two_intent.py \
	  --debug-mock-generator \
	  --config "$(STEP2_CONFIG)"
