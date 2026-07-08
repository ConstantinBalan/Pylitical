VENV = venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

.PHONY: bootstrap run lint fmt

bootstrap:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

# Usage: make run ARGS="--start-date 2026-07-01 --end-date 2026-07-02"
run:
	$(PYTHON) __main__.py $(ARGS)

lint:
	$(VENV)/bin/pylint pylitical __main__.py

fmt:
	$(VENV)/bin/black pylitical __main__.py
