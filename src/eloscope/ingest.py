"""Stream a monthly Lichess PGN dump, draw a reproducible random sample and parse it to Parquet.

How it works
------------
1. The ``.pgn.zst`` file is read from the network in compressed chunks (HTTP ``Range``
   requests resume the transfer after a dropped connection) and decompressed on the fly with
   ``zstandard``. The full file never touches the disk.
2. Decompressed bytes are split into games on the ``"\\n\\n[Event "`` boundary. Splitting is a
   C-level bytes operation, so the ~90M games of a month are scanned without parsing them.
3. Bernoulli sampling: every game ``i`` gets one uniform draw ``u_i`` from a seeded NumPy
   generator and is kept when ``u_i < p`` with ``p = sample_size / games_in_month``. Draws are
   consumed in file order, so the selection does not depend on how bytes are chunked.
4. Only selected games are parsed (headers, ply count, clock comments, eval flag). Usernames
   are replaced by salted SHA-256 hashes before anything is written.
5. Every ``batch_size`` sampled games, a Parquet batch, a compressed copy of the raw sampled
   PGN and a checkpoint are written. A rerun skips finished batches; when the raw sample cache
   is complete, the network is not used at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import multiprocessing
import os
import re
import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import zstandard
from tqdm import tqdm

from eloscope.settings import get_hash_salt, load_config, project_path, setup_logging

log = logging.getLogger("eloscope.ingest")

GAME_SEPARATOR = b"\n\n[Event "
EVENT_PREFIX = b"[Event "

HEADER_RE = re.compile(r'^\[(\w+) "((?:[^"\\]|\\.)*)"\]\s*$', re.MULTILINE)
COMMENT_RE = re.compile(r"\{[^}]*\}")
CLOCK_RE = re.compile(r"\[%clk (\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\]")
MOVE_NUMBER_RE = re.compile(r"^\d+\.+")
RESULT_TOKENS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})

# Headers kept from each game, mapped to their Parquet column names.
HEADER_COLUMNS: dict[str, str] = {
    "Event": "event",
    "Site": "site",
    "UTCDate": "utc_date",
    "UTCTime": "utc_time",
    "Result": "result",
    "WhiteElo": "white_elo",
    "BlackElo": "black_elo",
    "WhiteRatingDiff": "white_rating_diff",
    "BlackRatingDiff": "black_rating_diff",
    "WhiteTitle": "white_title",
    "BlackTitle": "black_title",
    "ECO": "eco",
    "Opening": "opening",
    "TimeControl": "time_control",
    "Termination": "termination",
    "Variant": "variant",
}

SCHEMA = pa.schema(
    [
        ("game_index", pa.int64()),
        ("game_id", pa.string()),
        *[(col, pa.string()) for col in HEADER_COLUMNS.values()],
        ("white_hash", pa.string()),
        ("black_hash", pa.string()),
        ("plies", pa.int32()),
        ("n_clocks", pa.int32()),
        ("has_eval", pa.bool_()),
        ("white_clk_start", pa.float64()),
        ("black_clk_start", pa.float64()),
        ("white_clk_10", pa.float64()),
        ("black_clk_10", pa.float64()),
    ]
)


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------
def parse_headers(header_text: str) -> dict[str, str]:
    """Parse PGN tag pairs (``[Key "Value"]``) into a dictionary."""
    return {key: value.replace('\\"', '"') for key, value in HEADER_RE.findall(header_text)}


def parse_clock(value: str) -> float:
    """Convert a ``h:mm:ss`` (optionally fractional) clock string to seconds."""
    match = CLOCK_RE.fullmatch(f"[%clk {value}]")
    if not match:
        raise ValueError(f"invalid clock value: {value!r}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_movetext(movetext: str) -> tuple[int, list[float], bool]:
    """Return ``(plies, clocks_in_seconds, has_eval)`` for a PGN movetext.

    Plies are counted from SAN tokens once comments, move numbers, NAGs and the result are
    removed. Clocks are returned in ply order (White, Black, White, ...).
    """
    clocks = [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in CLOCK_RE.findall(movetext)]
    has_eval = "[%eval" in movetext
    plies = 0
    for token in COMMENT_RE.sub(" ", movetext).split():
        if token in RESULT_TOKENS or token.startswith("$"):
            continue
        token = MOVE_NUMBER_RE.sub("", token)
        if token and token not in RESULT_TOKENS:
            plies += 1
    return plies, clocks, has_eval


def hash_username(name: str | None, salt: str) -> str | None:
    """Salted SHA-256 of a username, truncated to 16 hex characters (64 bits)."""
    if not name:
        return None
    return hashlib.sha256(f"{salt}{name.lower()}".encode()).hexdigest()[:16]


def game_id_from_site(site: str | None) -> str | None:
    """Extract the game id from a ``Site`` URL (``https://lichess.org/<id>``)."""
    if not site:
        return None
    return site.rstrip("/").rsplit("/", 1)[-1] or None


def parse_game(raw: bytes | str, salt: str, game_index: int = -1, opening_moves: int = 10) -> dict[str, Any]:
    """Parse one PGN game into a flat record matching :data:`SCHEMA`."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    header_text, _, movetext = text.partition("\n\n")
    headers = parse_headers(header_text)
    plies, clocks, has_eval = parse_movetext(movetext)

    record: dict[str, Any] = {"game_index": game_index, "game_id": game_id_from_site(headers.get("Site"))}
    for tag, column in HEADER_COLUMNS.items():
        record[column] = headers.get(tag)
    record["white_hash"] = hash_username(headers.get("White"), salt)
    record["black_hash"] = hash_username(headers.get("Black"), salt)
    record["plies"] = plies
    record["n_clocks"] = len(clocks)
    record["has_eval"] = has_eval

    # Clock comments are only trusted when there is exactly one per ply.
    complete = plies > 0 and len(clocks) == plies
    white, black = (clocks[0::2], clocks[1::2]) if complete else ([], [])
    record["white_clk_start"] = white[0] if white else None
    record["black_clk_start"] = black[0] if black else None
    record["white_clk_10"] = white[opening_moves - 1] if len(white) >= opening_moves else None
    record["black_clk_10"] = black[opening_moves - 1] if len(black) >= opening_moves else None
    return record


# --------------------------------------------------------------------------------------
# Streaming and sampling
# --------------------------------------------------------------------------------------
def fetch_range(session: requests.Session, url: str, start: int, end: int, max_retries: int = 8) -> bytes:
    """Download bytes ``start..end`` (inclusive) of ``url`` with retries and length check."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=(30, 300))
            resp.raise_for_status()
            if resp.status_code != 206 or len(resp.content) != end - start + 1:
                raise requests.ConnectionError(f"incomplete range {start}-{end}: got {len(resp.content)} bytes")
            return resp.content
        except requests.RequestException as exc:
            if attempt == max_retries:
                raise
            wait = min(2**attempt, 120)
            log.warning("range %s-%s failed (%s); retry %d in %ss", f"{start:,}", f"{end:,}", exc, attempt, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


def iter_http_chunks(url: str, read_size: int, workers: int = 4) -> Iterator[bytes]:
    """Yield the compressed bytes of ``url`` in order, fetched as parallel ``Range`` requests.

    A single long-lived connection is often throttled; several short range requests are not.
    At most ``2 * workers`` ranges are held in memory at once.
    """
    head = requests.head(url, timeout=60, allow_redirects=True)
    head.raise_for_status()
    total = int(head.headers["Content-Length"])
    ranges = iter([(start, min(start + read_size, total) - 1) for start in range(0, total, read_size)])
    local = threading.local()

    def task(bounds: tuple[int, int]) -> bytes:
        if not hasattr(local, "session"):
            local.session = requests.Session()
        return fetch_range(local.session, url, *bounds)

    with (
        ThreadPoolExecutor(max_workers=workers) as pool,
        tqdm(total=total, unit="B", unit_scale=True, desc="download", mininterval=5) as progress,
    ):
        pending: deque[Future[bytes]] = deque()
        for bounds in islice(ranges, 2 * workers):
            pending.append(pool.submit(task, bounds))
        while pending:
            data = pending.popleft().result()
            for bounds in islice(ranges, 1):
                pending.append(pool.submit(task, bounds))
            progress.update(len(data))
            yield data


def iter_file_chunks(path: Path, read_size: int) -> Iterator[bytes]:
    """Yield compressed bytes from a local file (tests and cached downloads)."""
    with open(path, "rb") as fh:
        while chunk := fh.read(read_size):
            yield chunk


def iter_game_blocks(compressed_chunks: Iterable[bytes]) -> Iterator[list[bytes]]:
    """Decompress a zstd stream and yield lists of complete games.

    Each yielded game is the raw PGN *without* its leading ``[Event `` prefix (restored only for
    selected games, see :func:`restore_game`) so that unselected games are never copied.
    """
    decompressor = zstandard.ZstdDecompressor(max_window_size=2**31).decompressobj(read_across_frames=True)
    remainder = b""
    first = True
    for chunk in compressed_chunks:
        data = decompressor.decompress(chunk)
        if not data:
            continue
        buffer = remainder + data
        if first:
            buffer = buffer.lstrip()
            if buffer.startswith(EVENT_PREFIX):
                buffer = buffer[len(EVENT_PREFIX) :]
            first = False
        pieces = buffer.split(GAME_SEPARATOR)
        remainder = pieces.pop()
        if pieces:
            yield pieces
    if remainder.strip():
        yield [remainder]


def restore_game(piece: bytes) -> bytes:
    """Re-attach the ``[Event `` prefix removed by :func:`iter_game_blocks`."""
    return EVENT_PREFIX + piece


def split_pgn(data: bytes) -> list[bytes]:
    """Split an uncompressed multi-game PGN into complete games (with their prefix)."""
    data = data.strip()
    if not data:
        return []
    if data.startswith(EVENT_PREFIX):
        data = data[len(EVENT_PREFIX) :]
    return [restore_game(piece) for piece in data.split(GAME_SEPARATOR)]


@dataclass
class BernoulliSampler:
    """Keep each game independently with probability ``p`` using one seeded draw per game."""

    p: float
    seed: int
    rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0 < self.p <= 1:
            raise ValueError(f"sampling probability must be in (0, 1], got {self.p}")
        self.rng = np.random.default_rng(self.seed)

    def select(self, n: int) -> np.ndarray:
        """Return the indices (0..n-1) of the selected games among the next ``n`` games."""
        return np.flatnonzero(self.rng.random(n) < self.p)


def fetch_month_game_count(counts_url: str, month: str) -> int:
    """Read the number of games of ``month`` from the Lichess ``counts.txt`` file."""
    resp = requests.get(counts_url, timeout=60)
    resp.raise_for_status()
    suffix = f"_{month}.pgn.zst"
    for line in resp.text.splitlines():
        name, _, count = line.partition(" ")
        if name.endswith(suffix):
            return int(count)
    raise ValueError(f"month {month} not found in {counts_url}")


# --------------------------------------------------------------------------------------
# Batch writing and checkpointing
# --------------------------------------------------------------------------------------
@dataclass
class IngestState:
    """Checkpoint persisted after every batch."""

    month: str
    seed: int
    p: float
    month_games: int
    games_seen: int = 0
    sampled: int = 0
    batches: int = 0
    complete: bool = False

    @classmethod
    def load(cls, path: Path) -> IngestState | None:
        if not path.exists():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")
        tmp.replace(path)


def write_batch(records: list[dict[str, Any]], path: Path) -> None:
    """Write parsed records to a Parquet file atomically."""
    table = pa.Table.from_pylist(records, schema=SCHEMA)
    tmp = path.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)


def read_parquet_indices(path: Path) -> list[int]:
    """Positions (in the monthly file) of the games stored in a Parquet batch."""
    return pq.read_table(path, columns=["game_index"]).column(0).to_pylist()


def write_raw_batch(games: list[bytes], indices: list[int], path: Path) -> None:
    """Write the raw PGN of the sampled games, zstd-compressed (download cache).

    The position of each game in the monthly file is stored next to it (``.idx.npy``).
    """
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh, zstandard.ZstdCompressor(level=10).stream_writer(fh) as writer:
        for game in games:
            writer.write(game.rstrip() + b"\n\n")
    np.save(raw_index_path(path), np.asarray(indices, dtype=np.int64))
    tmp.replace(path)


def raw_index_path(raw_path: Path) -> Path:
    return raw_path.with_name(raw_path.name.replace(".pgn.zst", ".idx.npy"))


def sample_stream(
    compressed_chunks: Iterable[bytes],
    sampler: BernoulliSampler,
    state: IngestState,
    sample_dir: Path,
    raw_dir: Path,
    salt: str,
    batch_size: int,
    checkpoint_path: Path,
    opening_moves: int = 10,
) -> IngestState:
    """Core loop: split, sample, parse and write batches; resumes from ``state.games_seen``."""
    resume_from = state.games_seen
    games_seen = 0
    pending_raw: list[bytes] = []
    pending_rows: list[dict[str, Any]] = []
    sample_bar = tqdm(
        total=round(state.p * state.month_games), initial=state.sampled, desc="sampled", unit="game", mininterval=5
    )

    def flush() -> None:
        name = f"batch_{state.batches:05d}"
        write_raw_batch(pending_raw, [row["game_index"] for row in pending_rows], raw_dir / f"{name}.pgn.zst")
        write_batch(pending_rows, sample_dir / f"{name}.parquet")
        state.batches += 1
        state.sampled += len(pending_rows)
        state.games_seen = games_seen
        state.save(checkpoint_path)
        log.info("batch %s written: %s games sampled out of %s scanned", name, f"{state.sampled:,}", f"{games_seen:,}")
        pending_raw.clear()
        pending_rows.clear()

    for block in iter_game_blocks(compressed_chunks):
        selected = sampler.select(len(block))
        start = games_seen
        games_seen += len(block)
        if games_seen <= resume_from:
            continue  # this block was already processed in a previous run
        for i in selected:
            index = start + int(i)
            if index < resume_from:
                continue
            raw = restore_game(block[i])
            pending_raw.append(raw)
            pending_rows.append(parse_game(raw, salt, index, opening_moves))
            sample_bar.update(1)
        if len(pending_rows) >= batch_size:
            flush()

    if pending_rows:
        flush()
    sample_bar.close()
    state.games_seen = games_seen
    state.complete = True
    state.save(checkpoint_path)
    return state


def _rebuild_batch(raw_path: Path, out: Path, salt: str, opening_moves: int) -> int:
    """Parse one cached raw batch into its Parquet file; returns the number of games."""
    with open(raw_path, "rb") as fh:
        games = split_pgn(zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True).read())
    indices = np.load(raw_index_path(raw_path))
    if len(indices) != len(games):
        raise RuntimeError(f"{raw_path.name}: {len(games)} games but {len(indices)} indices")
    records = [parse_game(game, salt, int(i), opening_moves) for game, i in zip(games, indices)]
    write_batch(records, out)
    return len(records)


def parse_raw_cache(raw_dir: Path, sample_dir: Path, salt: str, opening_moves: int = 10, workers: int = 0) -> int:
    """Rebuild missing Parquet batches from the cached raw sample (no network), in parallel."""
    todo = [
        (raw_path, sample_dir / raw_path.name.replace(".pgn.zst", ".parquet"))
        for raw_path in sorted(raw_dir.glob("batch_*.pgn.zst"))
    ]
    todo = [(raw, out) for raw, out in todo if not out.exists()]
    if not todo:
        return 0
    workers = workers or max(1, min(len(todo), (os.cpu_count() or 2)))
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = {pool.submit(_rebuild_batch, raw, out, salt, opening_moves): out for raw, out in todo}
        for future in tqdm(as_completed(futures), total=len(futures), desc="parse cache", unit="batch"):
            log.info("rebuilt %s from the raw cache (%s games)", futures[future].name, f"{future.result():,}")
    return len(todo)


def run(config: dict[str, Any] | None = None) -> IngestState:
    """Run the ingestion step described in ``config.yaml``."""
    cfg = config or load_config()
    src, smp = cfg["source"], cfg["sampling"]
    month = src["month"]
    sample_dir = project_path("sample", cfg) / month
    raw_dir = project_path("raw", cfg) / f"sample_{month}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = raw_dir / "_checkpoint.json"
    salt = get_hash_salt()
    opening_moves = cfg["cleaning"]["opening_moves"]

    state = IngestState.load(checkpoint_path)
    if state and state.complete:
        log.info("raw sample cache for %s is complete (%s games); no download needed", month, f"{state.sampled:,}")
        parse_raw_cache(raw_dir, sample_dir, salt, opening_moves)
        return state

    if state is None:
        month_games = fetch_month_game_count(src["counts_url"], month)
        p = min(1.0, smp["sample_size"] / month_games)
        state = IngestState(month=month, seed=smp["seed"], p=p, month_games=month_games)
        state.save(checkpoint_path)
    else:
        log.info("resuming %s after %s games (%d batches)", month, f"{state.games_seen:,}", state.batches)
        parse_raw_cache(raw_dir, sample_dir, salt, opening_moves)

    log.info(
        "month %s: %s games, sampling probability p=%.6f, seed=%d", month, f"{state.month_games:,}", state.p, state.seed
    )
    url = src["url_template"].format(month=month)
    chunks = iter_http_chunks(url, smp["read_size_mb"] * 1024 * 1024, smp["download_workers"])
    state = sample_stream(
        chunks,
        BernoulliSampler(state.p, state.seed),
        state,
        sample_dir,
        raw_dir,
        salt,
        smp["batch_size"],
        checkpoint_path,
        opening_moves,
    )
    if state.games_seen != state.month_games:
        log.warning("scanned %s games but counts.txt announces %s", f"{state.games_seen:,}", f"{state.month_games:,}")
    log.info("done: %s games sampled out of %s", f"{state.sampled:,}", f"{state.games_seen:,}")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="path to an alternative config.yaml")
    args = parser.parse_args()
    setup_logging()
    run(load_config(args.config) if args.config else None)


if __name__ == "__main__":
    main()
