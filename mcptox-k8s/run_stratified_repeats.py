#!/usr/bin/env python3
"""Run a stratified repeated MCPTox sample using run_experiment.py."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parent / "MCPTox-Benchmark"
RUNNER = ROOT / "run_experiment.py"
DEFAULT_MODELS = ("gpt-4o-mini", "gemini-2.5-flash", "deepseek-v4-flash")
DEFAULT_SETTINGS = ("base", "enhanced-important", "enhanced-ignore")


def load_cases_by_paradigm(benchmark_dir: Path) -> dict[str, list[int]]:
    raw = json.loads((benchmark_dir / "pure_tool.json").read_text(encoding="utf-8"))
    cases: dict[str, list[int]] = {}
    for item in raw:
        for value in item.values():
            match = re.fullmatch(r"def_tool/(\d+)\.py", value["tool_address"])
            if not match:
                raise ValueError(f"invalid tool_address: {value['tool_address']}")
            paradigm = value["paradigm"]
            cases.setdefault(paradigm, []).append(int(match.group(1)))
    return {key: sorted(values) for key, values in sorted(cases.items())}


def select_sample(cases_by_paradigm: dict[str, list[int]], k: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    for paradigm, case_ids in cases_by_paradigm.items():
        if k > len(case_ids):
            raise ValueError(f"k={k} exceeds available cases for {paradigm}: {len(case_ids)}")
        for case_id in sorted(rng.sample(case_ids, k)):
            rows.append({"case_id": str(case_id), "paradigm": paradigm})
    return rows


def write_sample(rows: list[dict[str, str]], output_dir: Path) -> Path:
    path = output_dir / "sample_cases.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "paradigm"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_case(args: argparse.Namespace, case_id: str, repetition: int, output_dir: Path) -> None:
    case_dir = output_dir / f"rep_{repetition:02d}_case_{int(case_id):04d}"
    if args.skip_existing and (case_dir / "results.csv").exists():
        print(f"skip existing {case_dir}", flush=True)
        return

    command = [
        sys.executable,
        str(RUNNER),
        "--case",
        case_id,
        "--model",
        *args.models,
        "--setting",
        *args.settings,
        "--seed",
        str(args.seed),
        "--output-dir",
        str(case_dir),
        "--tenant-id",
        f"{args.tenant_prefix}-r{repetition}-case{case_id}",
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
    subprocess.run(command, check=True)


def consolidate(output_dir: Path) -> Path:
    results = sorted(output_dir.glob("rep_*_case_*/results.csv"))
    if not results:
        raise FileNotFoundError(f"no results.csv files found in {output_dir}")

    consolidated = output_dir / "consolidated_results.csv"
    with consolidated.open("w", newline="", encoding="utf-8") as out_handle:
        writer: csv.DictWriter[str] | None = None
        for path in results:
            match = re.fullmatch(r"rep_(\d+)_case_(\d+)", path.parent.name)
            if not match:
                continue
            repetition, sampled_case_id = match.groups()
            with path.open(newline="", encoding="utf-8") as in_handle:
                reader = csv.DictReader(in_handle)
                if reader.fieldnames is None:
                    continue
                fieldnames = ["repetition", "sampled_case_id"] + reader.fieldnames
                if writer is None:
                    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
                    writer.writeheader()
                for row in reader:
                    row["repetition"] = str(int(repetition))
                    row["sampled_case_id"] = str(int(sampled_case_id))
                    writer.writerow(row)
    return consolidated


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--k", type=int, required=True, help="cases sampled per paradigm")
    result.add_argument("--repetitions", type=int, required=True, help="runs per sampled case")
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--benchmark-dir", type=Path, default=BENCHMARK)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--models", nargs="+", choices=DEFAULT_MODELS, default=list(DEFAULT_MODELS))
    result.add_argument("--settings", nargs="+", choices=DEFAULT_SETTINGS, default=list(DEFAULT_SETTINGS))
    result.add_argument("--gateway-url", default=None)
    result.add_argument("--mcp-url", default=None)
    result.add_argument("--tenant-prefix", default="mcptox-stat")
    result.add_argument("--namespace", default="default")
    result.add_argument("--gateway-name", default="envoy-ai-gateway-basic")
    result.add_argument("--mcp-path", default="/mcp")
    result.add_argument("--image", default=None)
    result.add_argument("--skip-deploy", action="store_true")
    result.add_argument("--skip-mcp-probe", action="store_true")
    result.add_argument("--keep-wrapper", action="store_true")
    result.add_argument("--skip-existing", action="store_true")
    result.add_argument("--timeout", type=float, default=120)
    result.add_argument("--request-retries", type=int, default=5)
    result.add_argument("--retry-base-delay", type=float, default=2)
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--replace-output", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be positive")
    if args.k < 1:
        raise SystemExit("--k must be positive")
    if not args.gateway_url and not os.getenv("GATEWAY_URL"):
        raise SystemExit("set GATEWAY_URL or pass --gateway-url")
    if args.replace_output and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sample = select_sample(load_cases_by_paradigm(args.benchmark_dir), args.k, args.seed)
    sample_path = write_sample(sample, args.output_dir)
    metadata = {
        "k": args.k,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "models": args.models,
        "settings": args.settings,
        "sample_path": str(sample_path),
        "runner": str(RUNNER),
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    if args.dry_run:
        print(f"sample={sample_path}")
        print(f"planned_model_calls={len(sample) * len(args.models) * len(args.settings) * args.repetitions}")
        return 0

    for repetition in range(1, args.repetitions + 1):
        for row in sample:
            run_case(args, row["case_id"], repetition, args.output_dir)

    consolidated = consolidate(args.output_dir)
    print(f"consolidated={consolidated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
