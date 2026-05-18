#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""使用 Docker CLI 进行沙箱并发压测（避免 SDK stats 阻塞）。"""

from __future__ import annotations

import csv
import json
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4


SCENARIOS: list[tuple[str, int]] = [("P1", 5), ("P2", 10), ("P3", 15)]
REPEATS = 5
SAMPLE_INTERVAL_SECONDS = 10
SAMPLE_WINDOW_SECONDS = 180
IMAGE = "stego-lab:py312"
NETWORK = "stego_labs_net"
CONTAINER_PORT = 8501
MEM_LIMIT = "512m"
CPU_PERIOD = "100000"
CPU_QUOTA = "50000"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


@dataclass
class RunResult:
    scenario: str
    container_count: int
    repeat_index: int
    avg_cpu_percent: float
    peak_cpu_percent: float
    avg_memory_gb: float
    peak_memory_gb: float
    avg_startup_seconds: float
    sample_count: int


@dataclass
class ScenarioSummary:
    scenario: str
    container_count: int
    avg_cpu_percent: float
    peak_cpu_percent: float
    avg_memory_gb: float
    peak_memory_gb: float
    avg_startup_seconds: float


def _run_cmd(command: list[str], timeout: int = 30) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    return completed.stdout.strip()


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return float(statistics.fmean(items)) if items else 0.0


def _to_gb(value: float) -> float:
    return float(value) / float(1024 ** 3)


def _parse_percent(text: str) -> float:
    cleaned = (text or "").strip().replace("%", "")
    return float(cleaned) if cleaned else 0.0


def _parse_memory_to_bytes(mem_text: str) -> float:
    # 例：15.62MiB / 512MiB，只取左侧当前使用值。
    left = (mem_text or "").split("/", 1)[0].strip()
    match = re.match(r"^([0-9]*\.?[0-9]+)\s*([kKmMgGtTpP]i?[bB])$", left)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2).lower()
    unit_map = {
        "kb": 1000,
        "mb": 1000 ** 2,
        "gb": 1000 ** 3,
        "tb": 1000 ** 4,
        "kib": 1024,
        "mib": 1024 ** 2,
        "gib": 1024 ** 3,
        "tib": 1024 ** 4,
        "pb": 1000 ** 5,
        "pib": 1024 ** 5,
    }
    return value * float(unit_map.get(unit, 1))


def _ensure_network() -> None:
    existing = _run_cmd(
        ["docker", "network", "ls", "--filter", f"name=^{NETWORK}$", "--format", "{{.Name}}"]
    )
    if existing.strip() == NETWORK:
        return
    _run_cmd(["docker", "network", "create", "--driver", "bridge", NETWORK])


def _ensure_image() -> None:
    image_id = _run_cmd(["docker", "images", "-q", IMAGE])
    if image_id:
        return
    raise RuntimeError(f"未找到镜像 {IMAGE}，请先在系统中构建该镜像。")


def _start_container(name: str, retries: int = 2) -> tuple[str, float]:
    last_error = ""
    for attempt in range(retries + 1):
        start_ts = time.perf_counter()
        container_id = _run_cmd(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                NETWORK,
                "--memory",
                MEM_LIMIT,
                "--cpu-period",
                CPU_PERIOD,
                "--cpu-quota",
                CPU_QUOTA,
                "-p",
                f"0:{CONTAINER_PORT}",
                IMAGE,
            ],
            timeout=60,
        )

        # 确认已分配 host 端口，作为启动成功判定点。
        for _ in range(80):
            try:
                _ = _run_cmd(["docker", "port", container_id, f"{CONTAINER_PORT}/tcp"], timeout=10)
                return container_id, (time.perf_counter() - start_ts)
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.25)

        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, text=True, check=False)
        if attempt < retries:
            # 避免短时端口/网络抖动导致整轮失败，做一次快速重试。
            time.sleep(0.8)

    raise RuntimeError(f"容器 {name} 多次启动后仍未完成端口映射：{last_error or 'unknown'}")


def _collect_sample(container_ids: list[str]) -> tuple[float, float]:
    if not container_ids:
        return 0.0, 0.0
    output = _run_cmd(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.Container}};{{.CPUPerc}};{{.MemUsage}}",
            *container_ids,
        ],
        timeout=30,
    )
    total_cpu = 0.0
    total_mem_bytes = 0.0
    for line in output.splitlines():
        parts = line.split(";")
        if len(parts) < 3:
            continue
        total_cpu += _parse_percent(parts[1])
        total_mem_bytes += _parse_memory_to_bytes(parts[2])
    return total_cpu, _to_gb(total_mem_bytes)


def _remove_containers(container_ids: list[str]) -> None:
    if not container_ids:
        return
    subprocess.run(["docker", "rm", "-f", *container_ids], capture_output=True, text=True, check=False)


def _run_single_round(scenario: str, container_count: int, repeat_index: int) -> RunResult:
    round_tag = f"{scenario.lower()}-r{repeat_index + 1}-{uuid4().hex[:8]}"
    startup_seconds: list[float] = []
    sampled_cpu: list[float] = []
    sampled_mem_gb: list[float] = []
    container_ids: list[str] = []

    try:
        for i in range(container_count):
            container_id, startup = _start_container(name=f"bench-{round_tag}-c{i + 1}")
            container_ids.append(container_id)
            startup_seconds.append(startup)

        sample_count = max(1, SAMPLE_WINDOW_SECONDS // SAMPLE_INTERVAL_SECONDS)
        for i in range(sample_count):
            total_cpu, total_mem_gb = _collect_sample(container_ids)
            sampled_cpu.append(total_cpu)
            sampled_mem_gb.append(total_mem_gb)
            if i < sample_count - 1:
                time.sleep(SAMPLE_INTERVAL_SECONDS)

        return RunResult(
            scenario=scenario,
            container_count=container_count,
            repeat_index=repeat_index + 1,
            avg_cpu_percent=round(_mean(sampled_cpu), 4),
            peak_cpu_percent=round(max(sampled_cpu) if sampled_cpu else 0.0, 4),
            avg_memory_gb=round(_mean(sampled_mem_gb), 4),
            peak_memory_gb=round(max(sampled_mem_gb) if sampled_mem_gb else 0.0, 4),
            avg_startup_seconds=round(_mean(startup_seconds), 4),
            sample_count=len(sampled_cpu),
        )
    finally:
        _remove_containers(container_ids)


def _summarize(runs: list[RunResult]) -> list[ScenarioSummary]:
    output: list[ScenarioSummary] = []
    for scenario, container_count in SCENARIOS:
        items = [x for x in runs if x.scenario == scenario]
        output.append(
            ScenarioSummary(
                scenario=scenario,
                container_count=container_count,
                avg_cpu_percent=round(_mean(x.avg_cpu_percent for x in items), 4),
                peak_cpu_percent=round(_mean(x.peak_cpu_percent for x in items), 4),
                avg_memory_gb=round(_mean(x.avg_memory_gb for x in items), 4),
                peak_memory_gb=round(_mean(x.peak_memory_gb for x in items), 4),
                avg_startup_seconds=round(_mean(x.avg_startup_seconds for x in items), 4),
            )
        )
    return output


def _write_outputs(runs: list[RunResult], summaries: list[ScenarioSummary]) -> dict[str, str]:
    import matplotlib.pyplot as plt

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    runs_csv = OUTPUT_DIR / "sandbox_benchmark_runs.csv"
    runs_json = OUTPUT_DIR / "sandbox_benchmark_runs.json"
    summary_json = OUTPUT_DIR / "sandbox_benchmark_summary.json"
    summary_snapshot_json = OUTPUT_DIR / f"sandbox_benchmark_summary_{stamp}.json"
    cpu_chart = OUTPUT_DIR / "sandbox_benchmark_cpu.png"
    memory_chart = OUTPUT_DIR / "sandbox_benchmark_memory.png"

    run_rows = [asdict(x) for x in runs]
    summary_rows = [asdict(x) for x in summaries]

    with runs_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(run_rows[0].keys()))
        writer.writeheader()
        writer.writerows(run_rows)

    with runs_json.open("w", encoding="utf-8") as f:
        json.dump({"runs": run_rows}, f, ensure_ascii=False, indent=2)

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_rows}, f, ensure_ascii=False, indent=2)

    with summary_snapshot_json.open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_rows}, f, ensure_ascii=False, indent=2)

    xs = [x.container_count for x in summaries]
    avg_cpu = [x.avg_cpu_percent for x in summaries]
    peak_cpu = [x.peak_cpu_percent for x in summaries]
    avg_mem = [x.avg_memory_gb for x in summaries]
    peak_mem = [x.peak_memory_gb for x in summaries]

    plt.figure(figsize=(8, 4.8))
    plt.plot(xs, avg_cpu, marker="o", label="Average CPU (%)")
    plt.plot(xs, peak_cpu, marker="o", label="Peak CPU (%)")
    plt.xlabel("Container Count")
    plt.ylabel("CPU (%)")
    plt.title("Container Count vs CPU")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig(cpu_chart, dpi=150)
    plt.close()

    plt.figure(figsize=(8, 4.8))
    plt.plot(xs, avg_mem, marker="o", label="Average Memory (GB)")
    plt.plot(xs, peak_mem, marker="o", label="Peak Memory (GB)")
    plt.xlabel("Container Count")
    plt.ylabel("Memory (GB)")
    plt.title("Container Count vs Memory")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig(memory_chart, dpi=150)
    plt.close()

    return {
        "runs_csv": str(runs_csv),
        "runs_json": str(runs_json),
        "summary_json": str(summary_json),
        "summary_snapshot_json": str(summary_snapshot_json),
        "cpu_chart": str(cpu_chart),
        "memory_chart": str(memory_chart),
    }


def main() -> int:
    print("[INFO] 检查 Docker 网络与镜像 ...", flush=True)
    _ensure_network()
    _ensure_image()

    all_runs: list[RunResult] = []
    print(
        f"[INFO] 开始压测：场景={len(SCENARIOS)}，每场景重复={REPEATS}，"
        f"采样间隔={SAMPLE_INTERVAL_SECONDS}s，采样窗口={SAMPLE_WINDOW_SECONDS}s",
        flush=True,
    )

    for scenario, container_count in SCENARIOS:
        for repeat_index in range(REPEATS):
            print(
                f"[RUN] 场景={scenario} 容器数={container_count} 第 {repeat_index + 1}/{REPEATS} 轮 ...",
                flush=True,
            )
            run = _run_single_round(scenario, container_count, repeat_index)
            all_runs.append(run)
            print(
                "[RUN] 完成 "
                f"avg_cpu={run.avg_cpu_percent:.2f}% "
                f"peak_cpu={run.peak_cpu_percent:.2f}% "
                f"avg_mem={run.avg_memory_gb:.3f}GB "
                f"peak_mem={run.peak_memory_gb:.3f}GB "
                f"avg_startup={run.avg_startup_seconds:.3f}s",
                flush=True,
            )
            time.sleep(1)

    summaries = _summarize(all_runs)
    files = _write_outputs(all_runs, summaries)

    print("\n[INFO] 场景平均结果：", flush=True)
    for item in summaries:
        print(
            f"  - {item.scenario}({item.container_count}) "
            f"avg_cpu={item.avg_cpu_percent:.2f}% "
            f"peak_cpu={item.peak_cpu_percent:.2f}% "
            f"avg_mem={item.avg_memory_gb:.3f}GB "
            f"peak_mem={item.peak_memory_gb:.3f}GB "
            f"avg_startup={item.avg_startup_seconds:.3f}s",
            flush=True,
        )

    print("\n[INFO] 输出文件：", flush=True)
    for key, value in files.items():
        print(f"  - {key}: {value}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
