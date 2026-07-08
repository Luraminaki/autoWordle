#!/usr/bin/env python3
"""Tool to read and print profiling statistics from a cProfile output file.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

# Quick command examples (run from the repository root):
# 1) Default review bundle + console summary:
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof
#
# 2) Top cumulative time hotspots:
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof --sort cumtime --limit 30
#
# 3) Top self-time hotspots (usually best for optimization):
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof --sort tottime --limit 30
#
# 4) Focus only on specific functions:
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof \
#        --include compute_pattern build_pattern_compendium
#
# 5) Exclude import/bootstrap noise:
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof \
#        --exclude "<frozen importlib" "~:0::<built-in method builtins.exec>"
#
# 6) Export bundle to a specific folder:
#    python -m scripts.profiling.read_profile scripts/benchmarks/testouille_wordle.prof --export-dir profile_reports/latest

import argparse
import logging
import pathlib
import pstats
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CWD = pathlib.Path.cwd()


@dataclass(frozen=True)
class ProfileRow:
    """Normalized pstats row."""

    filename: str
    line_no: int
    func_name: str
    primitive_calls: int
    total_calls: int
    total_time: float
    cumulative_time: float

    @property
    def key(self) -> str:
        """Unique identifier for this row: `filename:line_no::func_name`."""
        return f"{self.filename}:{self.line_no}::{self.func_name}"


def _build_rows(stats: pstats.Stats) -> list[ProfileRow]:
    stats_dict: dict[tuple[str, int, str], tuple[int, int, float, float, dict[tuple[str, int, str], Any]]] = getattr(stats, 'stats', {})
    rows: list[ProfileRow] = []
    for (filename, line_no, func_name), (primitive_calls, total_calls, total_time, cumulative_time, _callers) in stats_dict.items():
        rows.append(ProfileRow(filename=filename,
                               line_no=line_no,
                               func_name=func_name,
                               primitive_calls=primitive_calls,
                               total_calls=total_calls,
                               total_time=total_time,
                               cumulative_time=cumulative_time))

    return rows


def _apply_filters(rows: list[ProfileRow],
                   include: list[str],
                   exclude: list[str],
                   min_cumtime: float) -> list[ProfileRow]:
    filtered: list[ProfileRow] = []
    for row in rows:
        row_id = row.key
        if include and not any(token in row_id for token in include):
            continue
        if exclude and any(token in row_id for token in exclude):
            continue
        if row.cumulative_time < min_cumtime:
            continue
        filtered.append(row)

    return filtered


def _sort_rows(rows: list[ProfileRow], sort_by: str) -> list[ProfileRow]:
    if sort_by == 'tottime':
        return sorted(rows, key=lambda row: row.total_time, reverse=True)
    if sort_by == 'ncalls':
        return sorted(rows, key=lambda row: row.total_calls, reverse=True)
    return sorted(rows, key=lambda row: row.cumulative_time, reverse=True)


def _print_rows(rows: list[ProfileRow], limit: int) -> None:
    print(_format_rows(rows, limit))


def _format_rows(rows: list[ProfileRow], limit: int) -> str:
    lines = ["\nTop functions",
             "cumtime(s)  tottime(s)  ncalls       pcalls       location"]
    for row in rows[:limit]:
        lines.append(f"{row.cumulative_time:10.4f}  {row.total_time:10.4f}  {row.total_calls:11d}  {row.primitive_calls:11d}  {row.key}")
    return "\n".join(lines)


def _print_file_hotspots(rows: list[ProfileRow], limit: int) -> None:
    print(_format_file_hotspots(rows, limit))


def _format_file_hotspots(rows: list[ProfileRow], limit: int) -> str:
    agg: dict[str, tuple[float, float, int]] = defaultdict(lambda: (0.0, 0.0, 0))
    for row in rows:
        cum, tot, calls = agg[row.filename]
        agg[row.filename] = (cum + row.cumulative_time, tot + row.total_time, calls + row.total_calls)

    by_file = sorted(agg.items(), key=lambda item: item[1][0], reverse=True)

    lines = ["\nTop files",
             "cumtime(s)  tottime(s)  ncalls       file"]
    for filename, (cum, tot, calls) in by_file[:limit]:
        lines.append(f"{cum:10.4f}  {tot:10.4f}  {calls:11d}  {filename}")

    return "\n".join(lines)


def _print_context(stats: pstats.Stats, rows: list[ProfileRow], limit: int) -> None:
    print(_format_context(stats, rows, limit))


def _format_context(stats: pstats.Stats, rows: list[ProfileRow], limit: int) -> str:
    if limit <= 0:
        return ""

    stats_dict: dict[tuple[str, int, str], tuple[int, int, float, float, dict[tuple[str, int, str], Any]]] = getattr(stats, 'stats', {})
    reverse_calls: dict[tuple[str, int, str], list[tuple[tuple[str, int, str], float]]] = defaultdict(list)
    for callee_key, (_, _, _, _, callers) in stats_dict.items():
        for caller_key in callers:
            caller_stats = stats_dict.get(caller_key)
            caller_cumtime = caller_stats[3] if caller_stats else 0.0
            reverse_calls[caller_key].append((callee_key, caller_cumtime))

    lines = ["\nCaller/Callee context"]
    for row in rows[:limit]:
        current_key = (row.filename, row.line_no, row.func_name)
        _, _, _, _, callers = stats_dict.get(current_key, (0, 0, 0.0, 0.0, {}))
        lines.append(f"\n{row.key}")

        if callers:
            caller_strings = [f"{caller[0]}:{caller[1]}::{caller[2]}" for caller in callers]
            lines.append(f"  callers: {', '.join(caller_strings[:5])}")
        else:
            lines.append("  callers: <none>")

        callees = sorted(reverse_calls.get(current_key, []), key=lambda item: item[1], reverse=True)
        if callees:
            callee_strings = [f"{callee[0][0]}:{callee[0][1]}::{callee[0][2]}" for callee in callees[:5]]
            lines.append(f"  callees: {', '.join(callee_strings)}")
        else:
            lines.append("  callees: <none>")

    return "\n".join(lines)


def _format_header(profile_file: pathlib.Path,
                   total_calls: int,
                   primitive_calls: int,
                   total_time: float,
                   rows_count: int) -> str:
    return (f"Profile file: {profile_file.as_posix()}\n"
            f"Total calls: {total_calls} | Primitive calls: {primitive_calls} | Total time: {total_time:.4f}s\n"
            f"Rows after filters: {rows_count}")


def _write_default_reports(export_dir: pathlib.Path,
                           header: str,
                           stats: pstats.Stats,
                           rows: list[ProfileRow],
                           limit: int,
                           context: int) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)

    rows_cumtime = _sort_rows(rows, 'cumtime')
    rows_tottime = _sort_rows(rows, 'tottime')
    rows_ncalls = _sort_rows(rows, 'ncalls')

    reports: dict[str, str] = {
        '00_summary.txt': "\n\n".join([
            header,
            _format_rows(rows_cumtime, limit),
            _format_file_hotspots(rows_cumtime, max(10, min(limit, 50))),
            _format_context(stats, rows_cumtime, min(context, limit)),
        ]),
        '01_top_cumtime.txt': "\n\n".join([header, _format_rows(rows_cumtime, limit)]),
        '02_top_tottime.txt': "\n\n".join([header, _format_rows(rows_tottime, limit)]),
        '03_top_ncalls.txt': "\n\n".join([header, _format_rows(rows_ncalls, limit)]),
        '04_top_files.txt': "\n\n".join([header, _format_file_hotspots(rows_cumtime, max(10, min(limit, 50)))]),
    }

    for filename, content in reports.items():
        _ = (export_dir / filename).write_text(content + "\n", encoding='utf-8')

    print(f"\nReport bundle written to: {export_dir.as_posix()}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read and summarize cProfile statistics")
    _ = parser.add_argument("profile_file", nargs='?', default=(CWD / 'main_launcher.prof').as_posix(),
                            help="Path to cProfile output (.prof)")
    _ = parser.add_argument("--sort", dest="sort_stats", choices=["cumtime", "tottime", "ncalls"], default="cumtime",
                            help="Sort metric for top functions")
    _ = parser.add_argument("--limit", type=int, default=40, help="Number of rows to print")
    _ = parser.add_argument("--include", nargs='*', default=[], help="Only keep rows containing at least one token")
    _ = parser.add_argument("--exclude", nargs='*', default=[], help="Drop rows containing any token")
    _ = parser.add_argument("--min-cumtime", type=float, default=0.0, help="Minimum cumulative time threshold")
    _ = parser.add_argument("--context", type=int, default=10, help="Caller/callee context rows")
    _ = parser.add_argument("--export-dir", default="", help="Directory where report files will be written")
    _ = parser.add_argument("--no-default-report", action='store_true',
                            help="Disable automatic generation of report bundle files")
    return parser.parse_args()


def main(profile_file: str | pathlib.Path,
         sort_stats: str = 'cumtime',
         limit: int = 40,
         include: list[str] | None = None,
         exclude: list[str] | None = None,
         min_cumtime: float = 0.0,
         context: int = 10,
         export_dir: str | pathlib.Path | None = None,
         default_report: bool = True) -> None:
    """Parse and print actionable profiling statistics from a cProfile output file.

    Args:
        profile_file (str | pathlib.Path): Path to the cProfile output file.
        sort_stats (str, optional): Criteria to sort the profiling statistics. Defaults to 'cumtime'.
        limit (int, optional): Number of rows to print. Defaults to 40.
        include (list[str] | None, optional): Include tokens filter. Defaults to None.
        exclude (list[str] | None, optional): Exclude tokens filter. Defaults to None.
        min_cumtime (float, optional): Minimum cumulative time filter. Defaults to 0.0.
        context (int, optional): Number of rows with caller/callee context. Defaults to 10.
        export_dir (str | pathlib.Path | None, optional): Output folder for report files. Defaults to None.
        default_report (bool, optional): Generate a default bundle of review files. Defaults to True.
    """
    include = include or []
    exclude = exclude or []

    if isinstance(profile_file, str):
        profile_file = pathlib.Path(profile_file)

    if not profile_file.exists():
        logger.error(f"Profile file '{profile_file}' does not exist.")
        return

    stats = pstats.Stats(profile_file.as_posix())
    _ = stats.strip_dirs()

    rows = _build_rows(stats)
    filtered = _apply_filters(rows=rows,
                              include=include,
                              exclude=exclude,
                              min_cumtime=min_cumtime)
    ordered = _sort_rows(filtered, sort_stats)

    total_calls = int(getattr(stats, 'total_calls', 0))
    primitive_calls = int(getattr(stats, 'prim_calls', 0))
    total_time = float(getattr(stats, 'total_tt', 0.0))
    header = _format_header(profile_file=profile_file,
                            total_calls=total_calls,
                            primitive_calls=primitive_calls,
                            total_time=total_time,
                            rows_count=len(ordered))
    print(header)

    _print_rows(rows=ordered, limit=limit)
    _print_file_hotspots(rows=ordered, limit=max(10, min(limit, 50)))
    _print_context(stats=stats, rows=ordered, limit=min(context, limit))

    if default_report:
        resolved_export_dir = pathlib.Path(export_dir) if export_dir else (CWD / 'profile_reports' / profile_file.stem)
        _write_default_reports(export_dir=resolved_export_dir,
                               header=header,
                               stats=stats,
                               rows=ordered,
                               limit=limit,
                               context=context)

    logger.info("Profile statistics printed successfully.")


if __name__ == "__main__":
    m_tic = time.perf_counter()

    # Standalone reset (no shared project-wide logging setup to defer to here):
    # drop any handlers a previous import may have attached to the root logger
    # before configuring our own, so re-running in the same process doesn't
    # duplicate log lines.
    for _handler in logging.root.handlers[:]:
        logging.root.removeHandler(_handler)

    level = logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(process)s] [%(name)s] [%(levelname)s]: %(funcName)s -- %(message)s",
        handlers=[
            logging.FileHandler(f'{pathlib.Path(__file__).stem}.log', mode='w', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logger.setLevel(level)

    args = _parse_args()

    try:
        main(profile_file=args.profile_file, sort_stats=args.sort_stats, limit=args.limit, include=args.include,
             exclude=args.exclude, min_cumtime=args.min_cumtime, context=args.context,
             export_dir=args.export_dir, default_report=not args.no_default_report)
    except Exception as error:
        logger.info(f"App chrashed at {time.asctime(time.localtime())} -- {error!r}")

    m_tac = time.perf_counter() - m_tic
    logger.info(f"Ellapsed time: {round(m_tac, 3)}")
