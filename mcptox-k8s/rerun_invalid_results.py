#!/usr/bin/env python3
"""Rerun only None/Error rows from a consolidated MCPTox report."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "run_experiment.py"
INVALID_LABELS = {"None", "Error"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def invalid_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("repetition", ""),
        row.get("case_id", ""),
        row.get("model", ""),
        row.get("setting", ""),
    )


def run_invalid_row(args: argparse.Namespace, row: dict[str, str], index: int) -> Path:
    repetition, case_id, model, setting = invalid_key(row)
    output_dir = args.output_dir / f"rerun_{index:02d}_rep_{int(repetition):02d}_case_{int(case_id):04d}_{model}_{setting}"
    command = [
        sys.executable,
        str(RUNNER),
        "--case",
        case_id,
        "--model",
        model,
        "--setting",
        setting,
        "--seed",
        str(args.seed),
        "--output-dir",
        str(output_dir),
        "--tenant-id",
        f"{args.tenant_prefix}-r{repetition}-case{case_id}-{model}-{setting}",
        "--namespace",
        args.namespace,
        "--gateway-name",
        args.gateway_name,
        "--mcp-path",
        args.mcp_path,
        "--timeout",
        str(args.timeout),
        "--request-retries",
        str(args.request_retries),
        "--retry-base-delay",
        str(args.retry_base_delay),
    ]
    if args.gateway_url:
        command.extend(["--gateway-url", args.gateway_url])
    if args.mcp_url:
        command.extend(["--mcp-url", args.mcp_url])
    if args.image:
        command.extend(["--image", args.image])
    if args.skip_deploy:
        command.append("--skip-deploy")
    if args.skip_mcp_probe:
        command.append("--skip-mcp-probe")
    if args.keep_wrapper:
        command.append("--keep-wrapper")

    print(" ".join(command), flush=True)
    if not args.dry_run:
        subprocess.run(command, check=True)
    return output_dir


def load_rerun_result(path: Path, original: dict[str, str]) -> dict[str, str] | None:
    results_path = path / "results.csv"
    if not results_path.exists():
        return None
    rows = read_rows(results_path)
    if len(rows) != 1:
        raise ValueError(f"{results_path}: expected exactly one row, got {len(rows)}")
    replacement = dict(rows[0])
    replacement["repetition"] = original.get("repetition", "")
    replacement["sampled_case_id"] = original.get("sampled_case_id", original.get("case_id", ""))
    return replacement


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--gateway-url", default=None)
    result.add_argument("--mcp-url", default=None)
    result.add_argument("--tenant-prefix", default="mcptox-invalid-rerun")
    result.add_argument("--namespace", default="default")
    result.add_argument("--gateway-name", default="envoy-ai-gateway-basic")
    result.add_argument("--mcp-path", default="/mcp")
    result.add_argument("--image", default=None)
    result.add_argument("--skip-deploy", action="store_true")
    result.add_argument("--skip-mcp-probe", action="store_true")
    result.add_argument("--keep-wrapper", action="store_true")
    result.add_argument("--timeout", type=float, default=120)
    result.add_argument("--request-retries", type=int, default=5)
    result.add_argument("--retry-base-delay", type=float, default=2)
    result.add_argument("--dry-run", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.gateway_url and not os.getenv("GATEWAY_URL"):
        raise SystemExit("set GATEWAY_URL or pass --gateway-url")

    rows = read_rows(args.input)
    fieldnames = list(rows[0].keys()) if rows else []
    invalid_rows = [row for row in rows if row.get("label") in INVALID_LABELS]
    print(f"invalid_rows={len(invalid_rows)}")

    replacements: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for index, row in enumerate(invalid_rows, start=1):
        rerun_dir = run_invalid_row(args, row, index)
        if args.dry_run:
            continue
        replacement = load_rerun_result(rerun_dir, row)
        if replacement and replacement.get("label") not in INVALID_LABELS:
            replacements[invalid_key(row)] = replacement
        elif replacement:
            print(
                "still invalid:",
                invalid_key(row),
                replacement.get("label"),
                replacement.get("error", "")[:200],
                flush=True,
            )

    if args.dry_run:
        return 0

    patched = [replacements.get(invalid_key(row), row) for row in rows]
    write_rows(args.output, patched, fieldnames)
    remaining = sum(row.get("label") in INVALID_LABELS for row in patched)
    print(f"replaced={len(replacements)}")
    print(f"remaining_invalid={remaining}")
    print(f"patched={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
