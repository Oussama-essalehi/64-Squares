"""Cross-platform task runner (equivalent of the Makefile, works on Windows).

Usage: ``python run.py <target> [<target> ...]`` with targets
ingest, clean, model, analyze, export, test, all.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def ingest() -> None:
    from eloscope import ingest as step

    step.run()


def test() -> None:
    code = subprocess.call([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    if code:
        raise SystemExit(code)


TARGETS: dict[str, Callable[[], None]] = {
    "ingest": ingest,
    "test": test,
}
PIPELINE = ["ingest"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("targets", nargs="+", choices=[*TARGETS, "all"])
    args = parser.parse_args()

    from eloscope.settings import setup_logging

    setup_logging()
    targets = [t for name in args.targets for t in ([*PIPELINE, "test"] if name == "all" else [name])]
    for name in targets:
        start = time.perf_counter()
        print(f"==> {name}", flush=True)
        TARGETS[name]()
        print(f"<== {name} done in {time.perf_counter() - start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
