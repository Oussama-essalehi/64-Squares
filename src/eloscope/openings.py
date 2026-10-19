"""Opening families: map Lichess opening names to families, cross-checked with the reference
dataset ``lichess-org/chess-openings`` (ECO code, name, moves; CC0).

A family is the part of the opening name before the colon, e.g.
``"Sicilian Defense: Najdorf Variation"`` -> ``"Sicilian Defense"``.
"""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from eloscope.settings import load_config, project_path

log = logging.getLogger("eloscope.openings")

PARTS = ("a", "b", "c", "d", "e")
UNKNOWN = "Unknown"


def opening_family(name: str | None) -> str:
    """Return the family of an opening name (text before the first ``:``)."""
    if name is None or not isinstance(name, str) or not name.strip() or name.strip() == "?":
        return UNKNOWN
    return name.split(":", 1)[0].strip()


def opening_variation(name: str | None) -> str | None:
    """Return the variation part of an opening name (text after the first ``:``), if any."""
    if not isinstance(name, str) or ":" not in name:
        return None
    return name.split(":", 1)[1].strip() or None


def download_reference(config: dict[str, Any] | None = None, force: bool = False) -> Path:
    """Download the five reference TSV files once and merge them into ``openings.tsv``."""
    cfg = config or load_config()
    out = project_path("raw", cfg) / "openings" / "openings.tsv"
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for part in PARTS:
        url = cfg["source"]["openings_url_template"].format(part=part)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        frames.append(pd.read_csv(StringIO(resp.text), sep="\t", dtype=str))
    reference = pd.concat(frames, ignore_index=True)
    reference.to_csv(out, sep="\t", index=False)
    log.info("reference openings downloaded: %s lines", f"{len(reference):,}")
    return out


def load_reference(config: dict[str, Any] | None = None) -> pd.DataFrame:
    """Reference openings with columns ``eco, name, pgn, family, n_plies``."""
    reference = pd.read_csv(download_reference(config), sep="\t", dtype=str)
    reference["family"] = reference["name"].map(opening_family)
    reference["n_plies"] = reference["pgn"].str.split().map(lambda t: sum(1 for x in t if not x[0].isdigit()))
    return reference


def map_families(openings: pd.Series, reference: pd.DataFrame) -> pd.DataFrame:
    """Map opening names to families and flag whether each name exists in the reference.

    Returns a frame aligned with ``openings`` with columns ``opening_family`` and
    ``in_reference``. The family is derived from the name in both cases, so names missing from
    the reference (rare, e.g. renamed lines) still get a family.
    """
    known = set(reference["name"])
    names = openings.astype("string")
    unique = pd.Series(names.dropna().unique())
    families = dict(zip(unique, unique.map(opening_family)))
    return pd.DataFrame(
        {
            "opening_family": names.map(families).fillna(UNKNOWN),
            "in_reference": names.isin(known).fillna(False).astype(bool),
        },
        index=openings.index,
    )


def reference_family_check(reference: pd.DataFrame) -> dict[str, int]:
    """Sanity checks on the reference itself: every family has a root (name without ``:``)."""
    roots = set(reference.loc[~reference["name"].str.contains(":"), "name"])
    families = set(reference["family"])
    return {
        "reference_names": int(reference["name"].nunique()),
        "reference_families": len(families),
        "families_without_root_entry": len(families - roots),
    }
