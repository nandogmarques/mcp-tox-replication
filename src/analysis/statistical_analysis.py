#!/usr/bin/env python3
"""Compute ASR and Refused Ratio confidence intervals and variability for repeated MCPTox runs.

Both rates follow the MCPTox paper (section 4.1): the numerator is the number of
Success (ASR) or Failure-Refused (Refused Ratio) outputs and the denominator is
the number of valid outputs, i.e. every row except the None and Error labels.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable


INVALID_LABELS = {"None", "Error"}
CELL_FIELDS = ("model", "paradigm", "setting")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_valid(row: dict[str, str]) -> bool:
    return row.get("label", "") not in INVALID_LABELS


def is_success(row: dict[str, str]) -> bool:
    return row.get("label", "") == "Success"


def is_refused(row: dict[str, str]) -> bool:
    return row.get("label", "") == "Failure-Refused"


def wilson_interval(success: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return (math.nan, math.nan)
    phat = success / total
    denom = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def proportion_z_test(a_success: int, a_total: int, b_success: int, b_total: int) -> tuple[float, float]:
    if min(a_total, b_total) == 0:
        return (math.nan, math.nan)
    pooled = (a_success + b_success) / (a_total + b_total)
    se = math.sqrt(pooled * (1 - pooled) * (1 / a_total + 1 / b_total))
    if se == 0:
        return (math.nan, math.nan)
    z = (a_success / a_total - b_success / b_total) / se
    p = math.erfc(abs(z) / math.sqrt(2))
    return (z, p)


def group_rows(rows: Iterable[dict[str, str]], fields: tuple[str, ...]) -> dict[tuple[str, ...], list[dict[str, str]]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(field, "") for field in fields)].append(row)
    return grouped


def write_dicts(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def asr_by_cell(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for key, local_rows in sorted(group_rows(rows, CELL_FIELDS).items()):
        valid = [row for row in local_rows if is_valid(row)]
        success = sum(is_success(row) for row in valid)
        refused = sum(is_refused(row) for row in valid)
        total = len(valid)
        low, high = wilson_interval(success, total)
        refused_low, refused_high = wilson_interval(refused, total)
        output.append({
            "model": key[0],
            "paradigm": key[1],
            "setting": key[2],
            "valid": total,
            "success": success,
            "asr": success / total if total else math.nan,
            "ci95_low": low,
            "ci95_high": high,
            "refused": refused,
            "refused_ratio": refused / total if total else math.nan,
            "refused_ci95_low": refused_low,
            "refused_ci95_high": refused_high,
            "invalid": len(local_rows) - total,
        })
    return output


def variability_by_case(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    fields = ("model", "paradigm", "setting", "case_id")
    case_rates: list[dict[str, object]] = []
    for key, local_rows in sorted(group_rows(rows, fields).items()):
        valid = [row for row in local_rows if is_valid(row)]
        success = sum(is_success(row) for row in valid)
        total = len(valid)
        case_rates.append({
            "model": key[0],
            "paradigm": key[1],
            "setting": key[2],
            "case_id": key[3],
            "valid": total,
            "success": success,
            "case_asr": success / total if total else math.nan,
            "invalid": len(local_rows) - total,
        })
    return case_rates


def variability_by_cell(case_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in case_rows:
        value = row["case_asr"]
        if isinstance(value, float) and not math.isnan(value):
            grouped[(str(row["model"]), str(row["paradigm"]), str(row["setting"]))].append(value)

    output: list[dict[str, object]] = []
    for key, values in sorted(grouped.items()):
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1) if len(values) > 1 else 0.0
        output.append({
            "model": key[0],
            "paradigm": key[1],
            "setting": key[2],
            "cases": len(values),
            "mean_case_asr": mean,
            "sd_case_asr": math.sqrt(variance),
            "min_case_asr": min(values),
            "max_case_asr": max(values),
        })
    return output


def pairwise_model_comparisons(cell_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in cell_rows:
        grouped[(str(row["paradigm"]), str(row["setting"]))].append(row)

    for (paradigm, setting), rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: str(row["model"]))
        for i, first in enumerate(rows):
            for second in rows[i + 1:]:
                z, p = proportion_z_test(
                    int(first["success"]),
                    int(first["valid"]),
                    int(second["success"]),
                    int(second["valid"]),
                )
                output.append({
                    "paradigm": paradigm,
                    "setting": setting,
                    "model_a": first["model"],
                    "model_b": second["model"],
                    "asr_a": first["asr"],
                    "asr_b": second["asr"],
                    "diff_a_minus_b": float(first["asr"]) - float(second["asr"]),
                    "z": z,
                    "p_value": p,
                })
    return output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    rows = read_rows(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cells = asr_by_cell(rows)
    cases = variability_by_case(rows)
    variability = variability_by_cell(cases)
    comparisons = pairwise_model_comparisons(cells)

    write_dicts(
        args.output_dir / "asr_by_cell.csv",
        cells,
        ["model", "paradigm", "setting", "valid", "success", "asr", "ci95_low", "ci95_high",
         "refused", "refused_ratio", "refused_ci95_low", "refused_ci95_high", "invalid"],
    )
    write_dicts(
        args.output_dir / "case_variability.csv",
        cases,
        ["model", "paradigm", "setting", "case_id", "valid", "success", "case_asr", "invalid"],
    )
    write_dicts(
        args.output_dir / "variability_by_cell.csv",
        variability,
        ["model", "paradigm", "setting", "cases", "mean_case_asr", "sd_case_asr", "min_case_asr", "max_case_asr"],
    )
    write_dicts(
        args.output_dir / "pairwise_model_comparisons.csv",
        comparisons,
        ["paradigm", "setting", "model_a", "model_b", "asr_a", "asr_b", "diff_a_minus_b", "z", "p_value"],
    )
    print(f"stats={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
