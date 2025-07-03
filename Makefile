.ONESHELL:
.SHELLFLAGS := -c

.PHONY: run
.PHONY: uninstall
.PHONY: install
.PHONY: install-pre-commit
.PHONY: build
.PHONY: deploy


detect_conda_bin := $(shell bash -c 'if [ "${CONDA_EXE} " == " " ]; then \
    CONDA_EXE=$$((find /opt/conda/bin/conda || find ~/anaconda3/bin/conda || \
    find /usr/local/anaconda3/bin/conda || find ~/miniconda3/bin/conda || \
    find /root/miniconda/bin/conda || find ~/Anaconda3/Scripts/conda || \
    find $$CONDA/bin/conda) 2>/dev/null); fi; \
    if [ "${CONDA_EXE}_" == "_" ]; then \
    echo "Please install Anaconda w/ Python 3.10+ first"; \
    echo "See: https://www.anaconda.com/distribution/"; \
    exit 1; fi; \
    echo $$(dirname $${CONDA_EXE})')

CONDA_BIN := $(detect_conda_bin)

run:
	uvicorn main:app --reload

uninstall:
	conda env remove -n hummingbot-api -y

install:
	if conda env list | grep -q '^hummingbot-api '; then \
	    echo "Environment already exists."; \
	else \
	    conda env create -f environment.yml; \
	fi
	conda activate hummingbot-api
	$(MAKE) install-pre-commit

install-pre-commit:
	/bin/bash -c 'source "${CONDA_BIN}/activate" hummingbot-api && \
	if ! conda list pre-commit | grep pre-commit &> /dev/null; then \
	    pip install pre-commit; \
	fi && pre-commit install'

build:
	docker build -t hummingbot/hummingbot-api:latest .

deploy:
	docker compose up -d
