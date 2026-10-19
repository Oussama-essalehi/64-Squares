"""Validate the Power BI project in ``powerbi/``.

1. Every JSON file that declares a ``$schema`` (``.pbip``, ``.pbir``, ``.pbism``, report,
   pages, visuals) is validated against the published Microsoft JSON schema. Schemas are
   downloaded once into ``.cache/pbip-schemas/``.
2. Every field used by a visual (column, measure, hierarchy level) must exist in the TMDL
   semantic model.
3. The theme file must be valid JSON with a name and data colours.

The TMDL itself is parsed by Microsoft's serializer in ``tools/TmdlValidate`` (needs .NET 8).

Usage: ``python tools/validate_pbip.py``
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

from jsonschema import validators
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
POWERBI = ROOT / "powerbi"
CACHE = ROOT / ".cache" / "pbip-schemas"


def fetch(url: str) -> dict[str, Any]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / hashlib.sha1(url.encode()).hexdigest()
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as resp:
            path.write_bytes(resp.read())
    return json.loads(path.read_bytes())


def retrieve(uri: str) -> Resource:
    return Resource.from_contents(fetch(uri.split("#")[0]))


def validate_schemas() -> list[str]:
    errors: list[str] = []
    registry = Registry(retrieve=retrieve)
    files = [
        p for p in POWERBI.rglob("*") if p.suffix in {".json", ".pbip", ".pbir", ".pbism"} and ".pbi" not in p.parts
    ]
    checked = 0
    for path in sorted(files):
        data = json.loads(path.read_text(encoding="utf-8"))
        url = data.get("$schema") if isinstance(data, dict) else None
        if not url:
            continue
        schema = fetch(url)
        validator = validators.validator_for(schema)(schema, registry=registry)
        for err in validator.iter_errors(data):
            location = "/".join(str(p) for p in err.absolute_path)
            errors.append(f"{path.relative_to(ROOT)}: {location}: {err.message[:300]}")
        checked += 1
    print(f"schema validation: {checked} files checked")
    return errors


def tmdl_objects() -> dict[str, set[str]]:
    """Map each table to the names of its columns, measures and hierarchy levels."""
    objects: dict[str, set[str]] = {}
    for path in (POWERBI / "EloScope.SemanticModel" / "definition" / "tables").glob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        table = re.search(r"^table (.+)$", text, re.M).group(1).strip().strip("'")
        names = set()
        for _kind, name in re.findall(r"^\t(column|measure|hierarchy) ('[^']+'|[^ =\n]+)", text, re.M):
            names.add(name.strip("'"))
        for hierarchy, body in re.findall(r"^\thierarchy (\S+)\n((?:\t\t.*\n|\n)*)", text, re.M):
            for lvl in re.findall(r"^\t\tlevel ('[^']+'|\S+)", body, re.M):
                names.add(f"{hierarchy.strip(chr(39))}.{lvl.strip(chr(39))}")
        objects[table] = names
    return objects


def walk(node: Any, aliases: dict[str, str], found: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        if "From" in node and isinstance(node["From"], list):
            aliases = aliases | {f["Name"]: f["Entity"] for f in node["From"] if "Entity" in f}
        for kind in ("Column", "Measure"):
            body = node.get(kind)
            if isinstance(body, dict) and "Property" in body:
                ref = body["Expression"]["SourceRef"]
                found.append((ref.get("Entity") or aliases.get(ref.get("Source"), "?"), body["Property"]))
        level = node.get("HierarchyLevel")
        if isinstance(level, dict):
            h = level["Expression"]["Hierarchy"]
            found.append((h["Expression"]["SourceRef"]["Entity"], f"{h['Hierarchy']}.{level['Level']}"))
        for value in node.values():
            walk(value, aliases, found)
    elif isinstance(node, list):
        for value in node:
            walk(value, aliases, found)


def validate_fields() -> list[str]:
    objects = tmdl_objects()
    errors = []
    visuals = sorted((POWERBI / "EloScope.Report" / "definition" / "pages").rglob("visual.json"))
    refs = 0
    for path in visuals:
        found: list[tuple[str, str]] = []
        walk(json.loads(path.read_text(encoding="utf-8")), {}, found)
        for entity, name in found:
            refs += 1
            if name not in objects.get(entity, set()):
                errors.append(f"{path.relative_to(ROOT)}: unknown field {entity}[{name}]")
    print(f"field references: {refs} references in {len(visuals)} visuals checked")
    return errors


def validate_theme() -> list[str]:
    errors = []
    for path in [POWERBI / "theme.json", *POWERBI.rglob("RegisteredResources/*.json")]:
        theme = json.loads(path.read_text(encoding="utf-8"))
        if not theme.get("name") or len(theme.get("dataColors", [])) < 3:
            errors.append(f"{path.relative_to(ROOT)}: theme needs a name and at least 3 dataColors")
    return errors


def main() -> int:
    errors = validate_schemas() + validate_fields() + validate_theme()
    for err in errors:
        print("ERROR:", err)
    print("PBIP OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
