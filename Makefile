# Each target delegates to run.py so that `make <target>` and `python run.py <target>` are identical.
PYTHON ?= python

.PHONY: ingest test all

ingest:
	$(PYTHON) run.py ingest

test:
	$(PYTHON) run.py test

all:
	$(PYTHON) run.py all
