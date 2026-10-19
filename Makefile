# Each target delegates to run.py so that `make <target>` and `python run.py <target>` are identical.
PYTHON ?= python

.PHONY: ingest clean test all

ingest:
	$(PYTHON) run.py ingest

clean:
	$(PYTHON) run.py clean

test:
	$(PYTHON) run.py test

all:
	$(PYTHON) run.py all
