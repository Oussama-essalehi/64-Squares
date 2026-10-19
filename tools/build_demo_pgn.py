"""Build the anonymous demo profile of the app (``app/data/demo_games.pgn``).

It is a *composite* player, not a real person: 300 random games of the cached sample where one
side is rated 1500-1600, with that side renamed ``JoueurDemo`` and the opponent ``Adversaire``.
Game links and tournament ids are replaced, so nothing points back to the original players.

Usage: ``python tools/build_demo_pgn.py`` (needs the raw sample cache in ``data/raw/``).
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eloscope.ingest import parse_headers, split_pgn  # noqa: E402
from eloscope.settings import load_config, project_path  # noqa: E402

DEMO_NAME, OPPONENT = "JoueurDemo", "Adversaire"
N_GAMES, SEED, LOW, HIGH = 300, 7, 1500, 1600


def anonymise(game: str, demo_is_white: bool, index: int) -> str:
    white, black = (DEMO_NAME, OPPONENT) if demo_is_white else (OPPONENT, DEMO_NAME)
    game = re.sub(r'^\[White "[^"]*"\]', f'[White "{white}"]', game, flags=re.M)
    game = re.sub(r'^\[Black "[^"]*"\]', f'[Black "{black}"]', game, flags=re.M)
    game = re.sub(r'^\[Site "[^"]*"\]', f'[Site "https://lichess.org/demo{index:04d}"]', game, flags=re.M)
    game = re.sub(r"https://lichess\.org/(tournament|swiss)/\w+", r"https://lichess.org/\1/demo", game)
    game = re.sub(r'^\[(WhiteTitle|BlackTitle) "[^"]*"\]\n', "", game, flags=re.M)
    return game.strip()


def main() -> None:
    cfg = load_config()
    raw_dir = project_path("raw", cfg) / f"sample_{cfg['source']['month']}"
    rng = random.Random(SEED)
    candidates: list[tuple[str, bool]] = []
    for path in sorted(raw_dir.glob("batch_*.pgn.zst"))[:4]:
        with open(path, "rb") as fh:
            games = split_pgn(zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True).read())
        for raw in games:
            text = raw.decode("utf-8", errors="replace")
            h = parse_headers(text.partition("\n\n")[0])
            if h.get("Termination") not in ("Normal", "Time forfeit") or "[%clk" not in text:
                continue
            if not h.get("TimeControl", "-")[0].isdigit():
                continue
            sides = [
                s for s in ("White", "Black") if h.get(f"{s}Elo", "?").isdigit() and LOW <= int(h[f"{s}Elo"]) < HIGH
            ]
            if sides:
                candidates.append((text, rng.choice(sides) == "White"))
    picked = rng.sample(candidates, N_GAMES)
    out = ROOT / "app" / "data" / "demo_games.pgn"
    out.write_text("\n\n".join(anonymise(g, w, i) for i, (g, w) in enumerate(picked)) + "\n", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {N_GAMES} games ({out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
