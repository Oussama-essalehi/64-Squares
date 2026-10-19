"""Opening board diagrams and the side that "chooses" each opening family.

The position that defines a family is its shortest root line in the reference dataset
(``lichess-org/chess-openings``); its last move tells who chose the opening (odd number of plies =
White's move, even = Black's), with a few hand-checked corrections (:data:`OVERRIDES`).
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


# Families whose shortest root line in the reference ends with a move of the *other* side, checked
# by hand against the 90 families with at least 2,000 games in the sample.
OVERRIDES: dict[str, tuple[str | None, str]] = {
    "King's Indian Defense": ("1. d4 Nf6 2. c4 g6", "Noirs"),  # root ends 3.Nc3; 2...g6 defines it
    "Old Indian Defense": ("1. d4 Nf6 2. c4 d6", "Noirs"),  # root ends 2.c4 after 1...d6
    "Rat Defense": (None, "Noirs"),  # 1...d6 set-ups; the root line ends with White's 2.f4
}


def family_roots(reference: pd.DataFrame) -> pd.DataFrame:
    """One defining line per family: ``family, eco, moves, n_plies, chosen_by, fen``.

    The defining line is the shortest entry named exactly like the family (its shortest line when
    there is no such entry); the side that made its last move chose the opening. A few families
    whose root line ends with a move of the other side are corrected in :data:`OVERRIDES`.
    """
    rows = []
    for family, group in reference.groupby("family", sort=True):
        roots = group[group["name"] == family]
        pool = roots if not roots.empty else group
        first = pool.sort_values(["n_plies", "eco"]).iloc[0]
        moves = first["pgn"]
        override_moves, override_side = OVERRIDES.get(family, (None, None))
        moves = override_moves or moves
        plies = sum(1 for t in moves.split() if not t[0].isdigit())
        rows.append(
            {
                "family": family,
                "eco": first["eco"],
                "moves": moves,
                "n_plies": plies,
                "chosen_by": override_side or ("Blancs" if plies % 2 == 1 else "Noirs"),
                "fen": board_after(moves).fen(),
            }
        )
    return pd.DataFrame(rows)


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
