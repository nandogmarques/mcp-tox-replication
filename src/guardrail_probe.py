#!/usr/bin/env python3
"""Probe mcp-context-protector's LlamaFirewall guardrail one MCPTox variant at
a time (1 case + 1 setting = 1 tool per deploy).

Why one at a time: the guardrail's model (meta-llama/Llama-Prompt-Guard-2-86M)
truncates its input at 512 tokens (~4 tool descriptions' worth). Bundling
several variants into a single mcptox-wrapper deploy makes the scan silently
blind to whatever falls past that cutoff -- see
investigations/R3E/docs/context-protector-guardrail-todo.md. This script
avoids that by redeploying mcptox-wrapper with exactly one tool, restarting
mcp-context-protector so it reconnects and rescans, then reading the verdict
back from the pod's logs.

Each iteration costs ~30s (dominated by the guardrail reloading its model
from disk on every scan -- see the TODO doc for why that's not cached yet).

Usage:
    python guardrail_probe.py --random 10 --seed 42 --config config.yaml
    python guardrail_probe.py --case 1 --case 2 --setting base
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "run_experiment.py"
DEFAULT_BENCHMARK = ROOT.parent / "MCPTox-Benchmark"
SETTINGS = ("base", "enhanced-important", "enhanced-ignore")
NAMESPACE = "default"
DEPLOYMENT = "mcp-context-protector"
LABEL_SELECTOR = "app.kubernetes.io/name=mcp-context-protector"

SCAN_DECISION_RE = re.compile(r"Scan result decision: ScanDecision\.(\w+)")
SCAN_REASON_RE = re.compile(r"Scan result reason: (.+)")
GUARDRAIL_ERROR_RE = re.compile(r"Guardrail flagged server config: (.+)")


def load_runner():
    """Import run_experiment.py as a module, reusing its Case/load_cases/etc."""
    spec = importlib.util.spec_from_file_location("run_experiment", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # needed before exec: dataclass() resolves __module__ via sys.modules
    spec.loader.exec_module(module)
    return module


def kubectl(*args: str, timeout: float = 60, retries: int = 3) -> subprocess.CompletedProcess:
    """Run kubectl, retrying on transient API server errors (e.g. etcd timeouts)."""
    last: subprocess.CompletedProcess | None = None
    for attempt in range(1, retries + 1):
        last = subprocess.run(
            ["kubectl", *args], capture_output=True, text=True, timeout=timeout
        )
        if last.returncode == 0:
            return last
        if "etcdserver" in last.stderr or "timed out" in last.stderr.lower():
            time.sleep(min(2 * attempt, 10))
            continue
        return last
    return last


def deploy_variant(case_id: int, setting: str, config_path: Path | None) -> subprocess.CompletedProcess:
    command = [
        sys.executable, str(RUNNER),
        "--case", str(case_id),
        "--setting", setting,
        "--deploy-only",
    ]
    if config_path:
        command += ["--config", str(config_path)]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def restart_protector_and_wait(rollout_timeout: float) -> tuple[bool, str]:
    """Restart mcp-context-protector and wait for the rollout. Returns (ok, detail)."""
    restart = kubectl("rollout", "restart", f"deployment/{DEPLOYMENT}", "-n", NAMESPACE)
    if restart.returncode != 0:
        return False, f"rollout restart failed: {restart.stderr.strip()}"

    status = kubectl(
        "rollout", "status", f"deployment/{DEPLOYMENT}", "-n", NAMESPACE,
        f"--timeout={int(rollout_timeout)}s", timeout=rollout_timeout + 15,
    )
    if status.returncode != 0:
        return False, f"rollout status failed/timed out: {status.stderr.strip() or status.stdout.strip()}"
    return True, "ok"


def read_verdict(pod_wait_timeout: float = 30) -> dict[str, Any]:
    """Fetch the current pod's logs and extract the guardrail verdict."""
    deadline = time.monotonic() + pod_wait_timeout
    pod_name = ""
    while time.monotonic() < deadline:
        pods = kubectl(
            "get", "pods", "-n", NAMESPACE, "-l", LABEL_SELECTOR,
            "-o", "jsonpath={.items[0].metadata.name}",
        )
        pod_name = pods.stdout.strip()
        if pod_name:
            break
        time.sleep(1)

    if not pod_name:
        return {"decision": "error", "reason": "no pod found", "pod": ""}

    logs = kubectl("logs", pod_name, "-n", NAMESPACE, "--tail=200", timeout=30)
    text = logs.stdout

    decision_match = SCAN_DECISION_RE.search(text)
    reason_match = SCAN_REASON_RE.search(text)
    if decision_match:
        return {
            "decision": decision_match.group(1),
            "reason": reason_match.group(1).strip() if reason_match else "",
            "pod": pod_name,
        }

    error_match = GUARDRAIL_ERROR_RE.search(text)
    if error_match:
        return {"decision": "guardrail_error", "reason": error_match.group(1).strip(), "pod": pod_name}

    if "Guardrail (LlamaFirewall) found no issues" in text:
        return {"decision": "ALLOW", "reason": "(config unchanged from a prior approved scan)", "pod": pod_name}

    return {"decision": "no_scan", "reason": "no scan line found in logs (config may be unchanged)", "pod": pod_name}


def load_completed(output_path: Path) -> set[tuple[int, str]]:
    if not output_path.exists():
        return set()
    done = set()
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        done.add((row["case_id"], row["setting"]))
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case", type=int, action="append", help="repeatable")
    mode.add_argument("--random", type=int, metavar="N")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--setting", nargs="+", choices=SETTINGS, default=list(SETTINGS))
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--config", type=Path, default=None,
                         help="passed through to run_experiment.py --deploy-only")
    parser.add_argument("--rollout-timeout", type=float, default=90,
                         help="seconds to wait for the protector rollout per variant")
    parser.add_argument("--output", type=Path, default=None,
                         help="JSONL results file; existing (case,setting) rows are skipped (resumable)")
    args = parser.parse_args()

    runner = load_runner()
    all_cases = runner.load_cases(args.benchmark_dir)
    cases_by_id = {c.case_id: c for c in all_cases}

    if args.random is not None:
        import random
        if not (1 <= args.random <= len(all_cases)):
            raise SystemExit(f"--random must be between 1 and {len(all_cases)}")
        selected = random.Random(args.seed).sample(all_cases, args.random)
        case_ids = sorted(c.case_id for c in selected)
    else:
        case_ids = args.case
        for cid in case_ids:
            if cid not in cases_by_id:
                raise SystemExit(f"unknown case_id: {cid}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output or (ROOT.parent / "reports" / f"guardrail-probe-{timestamp}.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_completed(output_path)

    variants = [(cid, setting) for cid in case_ids for setting in args.setting]
    total = len(variants)
    print(f"probing {total} variant(s) ({len(case_ids)} case(s) x {len(args.setting)} setting(s)), "
          f"seed={args.seed}, output={output_path}", flush=True)

    with output_path.open("a", encoding="utf-8") as out:
        for i, (case_id, setting) in enumerate(variants, start=1):
            if (case_id, setting) in done:
                print(f"[{i}/{total}] case={case_id} setting={setting}: already done, skipping", flush=True)
                continue

            case = cases_by_id[case_id]
            row: dict[str, Any] = {
                "case_id": case_id, "setting": setting, "tool_name": case.tool_name,
                "server_name": case.server_name, "security_risk": case.security_risk,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

            deployed = deploy_variant(case_id, setting, args.config)
            if deployed.returncode != 0:
                row.update(decision="error", reason=f"deploy failed: {deployed.stderr.strip()}")
                print(f"[{i}/{total}] case={case_id} setting={setting}: DEPLOY FAILED", flush=True)
                out.write(json.dumps(row) + "\n")
                out.flush()
                continue

            ok, detail = restart_protector_and_wait(args.rollout_timeout)
            if not ok:
                row.update(decision="error", reason=detail)
                print(f"[{i}/{total}] case={case_id} setting={setting}: ROLLOUT FAILED ({detail})", flush=True)
                out.write(json.dumps(row) + "\n")
                out.flush()
                continue

            verdict = read_verdict()
            row.update(verdict)
            row["finished_at"] = datetime.now(timezone.utc).isoformat()
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"[{i}/{total}] case={case_id} setting={setting} tool={case.tool_name}: "
                  f"{row['decision']} -- {row['reason'][:100]}", flush=True)

    print(f"done. results: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
