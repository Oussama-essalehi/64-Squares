"""Tests for PGN parsing, clock extraction, streaming and sampling (``eloscope.ingest``)."""

from __future__ import annotations

import io
from pathlib import Path

import chess.pgn
import numpy as np
import pytest
import zstandard

from eloscope import ingest

FIXTURES = Path(__file__).parent / "fixtures" / "sample_games.pgn"
SALT = "test-salt"


@pytest.fixture(scope="module")
def raw_games() -> list[bytes]:
    return ingest.split_pgn(FIXTURES.read_bytes())


@pytest.fixture(scope="module")
def records(raw_games: list[bytes]) -> dict[str, dict]:
    rows = [ingest.parse_game(game, SALT, i) for i, game in enumerate(raw_games)]
    return {row["game_id"]: row for row in rows}


# --- headers ---------------------------------------------------------------------------
def test_parse_headers_reads_all_tags() -> None:
    text = '[Event "Rated Blitz game"]\n[Site "https://lichess.org/abc"]\n[Opening "King\'s Pawn Game"]'
    assert ingest.parse_headers(text) == {
        "Event": "Rated Blitz game",
        "Site": "https://lichess.org/abc",
        "Opening": "King's Pawn Game",
    }


def test_parse_headers_handles_escaped_quotes() -> None:
    assert ingest.parse_headers('[Annotator "a \\"b\\" c"]') == {"Annotator": 'a "b" c'}


def test_fixture_file_contains_all_cases(raw_games: list[bytes]) -> None:
    assert len(raw_games) == 24
    assert all(game.startswith(b"[Event ") for game in raw_games)


def test_header_columns_are_extracted(records: dict[str, dict]) -> None:
    row = records["fx_bullet_normal"]
    assert row["event"] == "Rated Bullet game"
    assert row["time_control"] == "120+1"
    assert row["termination"] == "Normal"
    assert row["utc_date"].startswith("2026.09.")
    assert row["white_elo"].isdigit() and row["black_elo"].isdigit()
    assert row["eco"] and row["opening"]
    assert row["variant"] is None
    assert records["fx_variant_chess960"]["variant"] == "Chess960"
    assert records["fx_bot"]["white_title"] == "BOT"
    assert records["fx_no_ratingdiff"]["white_rating_diff"] is None


def test_game_id_from_site() -> None:
    assert ingest.game_id_from_site("https://lichess.org/bcRJNu4b") == "bcRJNu4b"
    assert ingest.game_id_from_site("https://lichess.org/bcRJNu4b/") == "bcRJNu4b"
    assert ingest.game_id_from_site(None) is None


def test_usernames_are_hashed_never_stored(records: dict[str, dict]) -> None:
    row = records["fx_bullet_normal"]
    assert "white" not in row and "black" not in row
    assert row["white_hash"] == ingest.hash_username("PlayerWhite", SALT)
    assert len(row["white_hash"]) == 16
    # case-insensitive (Lichess usernames are), salt-dependent
    assert ingest.hash_username("playerwhite", SALT) == row["white_hash"]
    assert ingest.hash_username("PlayerWhite", "other-salt") != row["white_hash"]
    assert ingest.hash_username(None, SALT) is None


# --- clocks and moves ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "seconds"),
    [("0:03:00", 180.0), ("1:00:00", 3600.0), ("0:00:05", 5.0), ("0:00:05.3", 5.3), ("12:34:56", 45296.0)],
)
def test_parse_clock(value: str, seconds: float) -> None:
    assert ingest.parse_clock(value) == pytest.approx(seconds)


@pytest.mark.parametrize("value", ["", "3:00", "abc", "0:3:00:00"])
def test_parse_clock_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        ingest.parse_clock(value)


def test_parse_movetext_with_clocks_and_eval() -> None:
    movetext = (
        "1. e4 { [%eval 0.2] [%clk 0:03:00] } 1... e5 { [%eval 0.3] [%clk 0:03:00] } "
        "2. Nf3?! { [%clk 0:02:58] } 2... Nc6 $1 { [%clk 0:02:55] } 3. Bb5 { [%clk 0:02:50] } 1-0"
    )
    plies, clocks, has_eval = ingest.parse_movetext(movetext)
    assert plies == 5
    assert clocks == [180, 180, 178, 175, 170]
    assert has_eval


def test_parse_movetext_without_clocks() -> None:
    plies, clocks, has_eval = ingest.parse_movetext("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 1/2-1/2")
    assert (plies, clocks, has_eval) == (7, [], False)


def test_parse_movetext_promotion_and_castling() -> None:
    plies, _, _ = ingest.parse_movetext("1. e4 d5 2. exd5 c6 3. dxc6 Nf6 4. cxb7 Bd7 5. bxa8=Q O-O 0-1")
    assert plies == 10


def test_ply_count_matches_python_chess(raw_games: list[bytes]) -> None:
    """The fast tokenizer must agree with a full python-chess parse on every fixture game."""
    for raw in raw_games:
        game = chess.pgn.read_game(io.StringIO(raw.decode()))
        expected = sum(1 for _ in game.mainline_moves())
        plies, _, _ = ingest.parse_movetext(raw.decode().partition("\n\n")[2])
        assert plies == expected, game.headers["Site"]


def test_clock_features(records: dict[str, dict]) -> None:
    row = records["fx_bullet_normal"]  # 120+1, 86 plies, clocks on every move
    assert row["plies"] == row["n_clocks"] == 86
    assert row["white_clk_start"] == row["black_clk_start"] == 120.0
    assert 0 < row["white_clk_10"] <= 129 and 0 < row["black_clk_10"] <= 129


def test_clock_features_missing_when_no_clock_data(records: dict[str, dict]) -> None:
    row = records["fx_no_clock"]
    assert row["n_clocks"] == 0 and row["plies"] > 20
    assert row["white_clk_start"] is None and row["white_clk_10"] is None


def test_clock_after_move_10_missing_for_short_games(records: dict[str, dict]) -> None:
    row = records["fx_short"]
    assert row["plies"] < 10
    assert row["white_clk_10"] is None and row["black_clk_10"] is None


def test_berserk_start_clock_is_halved(records: dict[str, dict]) -> None:
    row = records["fx_berserk"]
    assert row["time_control"] == "480+0"
    assert row["white_clk_start"] == 240.0


def test_eval_flag(records: dict[str, dict]) -> None:
    assert records["fx_eval"]["has_eval"] is True
    assert records["fx_no_clock"]["has_eval"] is False


# --- streaming and sampling ------------------------------------------------------------
def _compress_in_frames(data: bytes, frames: int) -> bytes:
    size = len(data) // frames + 1
    compressor = zstandard.ZstdCompressor()
    return b"".join(compressor.compress(data[i : i + size]) for i in range(0, len(data), size))


@pytest.mark.parametrize("read_size", [97, 1024, 1 << 20])
@pytest.mark.parametrize("frames", [1, 3])
def test_stream_splitting_is_independent_of_chunking(raw_games: list[bytes], read_size: int, frames: int) -> None:
    compressed = _compress_in_frames(FIXTURES.read_bytes(), frames)
    chunks = [compressed[i : i + read_size] for i in range(0, len(compressed), read_size)]
    games = [ingest.restore_game(g).strip() for block in ingest.iter_game_blocks(chunks) for g in block]
    assert games == [g.strip() for g in raw_games]


def test_sampler_is_deterministic_and_chunk_independent() -> None:
    one = ingest.BernoulliSampler(0.3, seed=42).select(1000)
    sampler = ingest.BernoulliSampler(0.3, seed=42)
    split = np.concatenate([sampler.select(10), sampler.select(490) + 10, sampler.select(500) + 500])
    assert np.array_equal(one, split)
    assert not np.array_equal(one, ingest.BernoulliSampler(0.3, seed=7).select(1000))


def test_sampler_rate_close_to_p() -> None:
    selected = ingest.BernoulliSampler(0.02, seed=1).select(1_000_000)
    assert abs(len(selected) / 1_000_000 - 0.02) < 0.001


def test_sampler_rejects_invalid_probability() -> None:
    with pytest.raises(ValueError):
        ingest.BernoulliSampler(0, seed=1)


def test_sample_stream_writes_batches_and_resumes(tmp_path: Path) -> None:
    compressed = zstandard.ZstdCompressor().compress((FIXTURES.read_bytes() + b"\n") * 20)  # 480 games
    chunks = [compressed[i : i + 2048] for i in range(0, len(compressed), 2048)]

    def run(state: ingest.IngestState, out: Path) -> ingest.IngestState:
        out.mkdir(exist_ok=True)
        return ingest.sample_stream(
            chunks,
            ingest.BernoulliSampler(state.p, state.seed),
            state,
            out,
            out,
            SALT,
            batch_size=50,
            checkpoint_path=out / "ck.json",
        )

    full = run(ingest.IngestState("t", 42, 0.5, 480), tmp_path / "full")
    assert full.complete and full.games_seen == 480
    assert full.batches >= 2

    # Simulate a crash after the first batch, then resume.
    partial_dir = tmp_path / "resume"
    partial_dir.mkdir()
    first = ingest.read_parquet_indices(tmp_path / "full" / "batch_00000.parquet")
    for name in ("batch_00000.parquet", "batch_00000.pgn.zst", "batch_00000.idx.npy"):
        (partial_dir / name).write_bytes((tmp_path / "full" / name).read_bytes())
    checkpoint = ingest.IngestState("t", 42, 0.5, 480, games_seen=max(first) + 1, sampled=len(first), batches=1)
    resumed = run(checkpoint, partial_dir)
    assert resumed.sampled == full.sampled

    def all_indices(folder: Path) -> list[int]:
        return sorted(i for f in sorted(folder.glob("*.parquet")) for i in ingest.read_parquet_indices(f))

    assert all_indices(partial_dir) == all_indices(tmp_path / "full")


def test_raw_cache_rebuilds_identical_parquet(tmp_path: Path) -> None:
    compressed = zstandard.ZstdCompressor().compress(FIXTURES.read_bytes())
    state = ingest.IngestState("t", 1, 1.0, 24)
    ingest.sample_stream(
        [compressed], ingest.BernoulliSampler(1.0, 1), state, tmp_path, tmp_path, SALT, 10, tmp_path / "ck.json"
    )
    original = sorted(tmp_path.glob("*.parquet"))
    expected = [ingest.pq.read_table(f).to_pylist() for f in original]
    for f in original:
        f.unlink()
    assert ingest.parse_raw_cache(tmp_path, tmp_path, SALT) == len(original)
    assert [ingest.pq.read_table(f).to_pylist() for f in sorted(tmp_path.glob("*.parquet"))] == expected
