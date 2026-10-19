"""Opening board diagrams and the side that "chooses" each opening family.

For each family the reference dataset (``lichess-org/chess-openings``) gives one or more root
lines (entries named exactly like the family). The shortest one is the position that defines the
family: its last move tells who chose it (odd number of plies = White's move, even = Black's).
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import chess
import chess.pgn
import chess.svg
import pandas as pd

BOARD_COLORS = {
    "square light": "#f0d9b5",
    "square dark": "#b58863",
    "square light lastmove": "#cdd16f",
    "square dark lastmove": "#aaa23b",
    "margin": "#262421",
    "coord": "#f0d9b5",
}


def slug(name: str) -> str:
    """File-system friendly name: ``"Queen's Pawn Game"`` -> ``"queens-pawn-game"``."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def family_roots(reference: pd.DataFrame) -> pd.DataFrame:
    """One defining line per family: ``family, eco, moves, n_plies, chosen_by, fen``."""
    roots = reference[reference["name"] == reference["family"]].copy()
    missing = reference[~reference["family"].isin(roots["family"])]
    roots = pd.concat([roots, missing])  # families without a root entry: use their shortest line
    roots = roots.sort_values(["family", "n_plies", "eco"]).drop_duplicates("family")
    rows = []
    for _, r in roots.iterrows():
        board = board_after(r["pgn"])
        rows.append(
            {
                "family": r["family"],
                "eco": r["eco"],
                "moves": r["pgn"],
                "n_plies": int(r["n_plies"]),
                "chosen_by": "Blancs" if int(r["n_plies"]) % 2 == 1 else "Noirs",
                "fen": board.fen(),
            }
        )
    return pd.DataFrame(rows).reset_index(drop=True)


def board_after(moves: str) -> chess.Board:
    """Board after a SAN move sequence such as ``"1. e4 c5 2. Nf3"``."""
    game = chess.pgn.read_game(io.StringIO(moves))
    board = game.board()
    for move in game.mainline_moves():
        board.push(move)
    return board


def board_svg(moves: str, size: int = 240) -> str:
    """SVG diagram of the position after ``moves``, last move highlighted, Lichess colours."""
    board = board_after(moves)
    last = board.peek() if board.move_stack else None
    return chess.svg.board(board, size=size, lastmove=last, coordinates=False, colors=BOARD_COLORS)


def write_boards(families: list[str], roots: pd.DataFrame, out_dir: Path, size: int = 240) -> list[Path]:
    """Write one SVG per family to ``out_dir/<slug>.svg``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_family = roots.set_index("family")
    paths = []
    for family in families:
        if family not in by_family.index:
            continue
        path = out_dir / f"{slug(family)}.svg"
        path.write_text(board_svg(by_family.loc[family, "moves"], size), encoding="utf-8")
        paths.append(path)
    return paths
