# Each target delegates to run.py so that `make <target>` and `python run.py <target>` are identical.
PYTHON ?= python

.PHONY: ingest clean model analyze export test all

ingest:
	$(PYTHON) run.py ingest

clean:
	$(PYTHON) run.py clean

model:
	$(PYTHON) run.py model

analyze:
	$(PYTHON) run.py analyze

export:
	$(PYTHON) run.py export

test:
	$(PYTHON) run.py test

all:
	$(PYTHON) run.py all
