"""Tests for opening roots, the choosing side and board diagrams."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from eloscope.boards import board_after, board_svg, family_roots, slug, write_boards

REFERENCE = pd.DataFrame(
    {
        "eco": ["B20", "B27", "C50", "C50", "A40", "E61", "E90", "B06", "A41"],
        "name": [
            "Sicilian Defense", "Sicilian Defense", "Italian Game", "Italian Game: Giuoco Piano", "Englund Gambit",
            "King's Indian Defense", "King's Indian Defense: Normal Variation", "Modern Defense", "Modern Defense",
        ],
        "pgn": [
            "1. e4 c5", "1. e4 c5 2. Nf3", "1. e4 e5 2. Nf3 Nc6 3. Bc4", "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5", "1. d4 e5",
            "1. d4 Nf6 2. c4 g6 3. Nc3", "1. d4 Nf6 2. c4 g6 3. Nc3 Bg7 4. e4 d6 5. Nf3",
            "1. e4 g6", "1. d4 g6 2. c4 Bg7",
        ],
    }
)  # fmt: skip
REFERENCE["family"] = REFERENCE["name"].str.split(":").str[0]
REFERENCE["n_plies"] = REFERENCE["pgn"].str.split().map(lambda t: sum(1 for x in t if not x[0].isdigit()))


def test_family_roots_takes_the_shortest_root_line() -> None:
    roots = family_roots(REFERENCE).set_index("family")
    assert roots.loc["Sicilian Defense", "moves"] == "1. e4 c5"
    assert roots.loc["Italian Game", "moves"] == "1. e4 e5 2. Nf3 Nc6 3. Bc4"
    assert len(roots) == 5


def test_choosing_side_from_ply_parity() -> None:
    roots = family_roots(REFERENCE).set_index("family")
    assert roots.loc["Sicilian Defense", "chosen_by"] == "Noirs"  # 1...c5 is Black's move
    assert roots.loc["Italian Game", "chosen_by"] == "Blancs"  # 3.Bc4 is White's move
    assert roots.loc["Englund Gambit", "chosen_by"] == "Noirs"


def test_overrides_fix_roots_ending_with_the_other_side() -> None:
    roots = family_roots(REFERENCE).set_index("family")
    # the only exact root of the King's Indian ends with 3.Nc3, but 2...g6 is the defining move
    assert roots.loc["King's Indian Defense", "moves"] == "1. d4 Nf6 2. c4 g6"
    assert roots.loc["King's Indian Defense", "chosen_by"] == "Noirs"
    # a family reached by several first moves keeps its shortest root
    assert roots.loc["Modern Defense", "moves"] == "1. e4 g6"
    assert roots.loc["Modern Defense", "chosen_by"] == "Noirs"


def test_board_after_and_svg() -> None:
    board = board_after("1. e4 c5")
    assert board.fen().startswith("rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w")
    svg = board_svg("1. e4 c5", size=120)
    assert svg.startswith("<svg") and "#b58863" in svg


def test_write_boards(tmp_path: Path) -> None:
    roots = family_roots(REFERENCE)
    paths = write_boards(["Sicilian Defense", "Unknown family"], roots, tmp_path)
    assert [p.name for p in paths] == ["sicilian-defense.svg"]
    assert slug("Queen's Pawn Game") == "queens-pawn-game"
    assert slug("Van't Kruijs Opening") == "vant-kruijs-opening"
