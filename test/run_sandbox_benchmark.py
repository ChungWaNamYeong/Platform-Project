#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""沙箱并发性能压测脚本。

场景：
- P1: 5 个容器
- P2: 10 个容器
- P3: 15 个容器

每个场景重复 5 次，按 10s 周期采样，默认观察窗口 180s（3 分钟）。
输出：
- test/output/sandbox_benchmark_runs.csv
- test/output/sandbox_benchmark_runs.json
- test/output/sandbox_benchmark_summary.json
- test/output/sandbox_benchmark_cpu.png
- test/output/sandbox_benchmark_memory.png
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import matplotlib.pyplot as plt

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "stego_backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sandbox_manager import StegoSandbox


SCENARIOS: list[tuple[str, int]] = [("P1", 5), ("P2", 10), ("P3", 15)]
REPEATS = 5
SAMPLE_INTERVAL_SECONDS = 10
SAMPLE_WINDOW_SECONDS = 180
OUTPUT_DIR = CURRENT_DIR / "output"


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


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(statistics.fmean(values))


def _bytes_to_gb(value: float) -> float:
    # 使用二进制换算（GiB）得到更贴近 Docker 的内存观察值。
    return float(value) / float(1024 ** 3)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _calc_cpu_percent(stats: dict[str, Any]) -> float:
    cpu_stats = stats.get("cpu_stats") or {}
    precpu_stats = stats.get("precpu_stats") or {}
    cpu_total = ((cpu_stats.get("cpu_usage") or {}).get("total_usage")) or 0
    prev_cpu_total = ((precpu_stats.get("cpu_usage") or {}).get("total_usage")) or 0
    system_total = cpu_stats.get("system_cpu_usage") or 0
    prev_system_total = precpu_stats.get("system_cpu_usage") or 0
    cpu_delta = float(cpu_total - prev_cpu_total)
    system_delta = float(system_total - prev_system_total)
    online_cpus = cpu_stats.get("online_cpus")
    if not online_cpus:
        online_cpus = len((cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    if cpu_delta > 0 and system_delta > 0 and online_cpus > 0:
        return max((cpu_delta / system_delta) * float(online_cpus) * 100.0, 0.0)
    return 0.0


def _calc_memory_usage_bytes(stats: dict[str, Any]) -> int:
    memory_stats = stats.get("memory_stats") or {}
    memory_usage_raw = int(memory_stats.get("usage") or 0)
    detail = memory_stats.get("stats") or {}
    cache_bytes = int(detail.get("inactive_file") or detail.get("cache") or 0)
    usage = max(memory_usage_raw - cache_bytes, 0) if memory_usage_raw > 0 else 0
    if usage <= 0 and memory_usage_raw > 0:
        usage = memory_usage_raw
    return usage


def _collect_sample(sandbox: StegoSandbox, container_ids: list[str]) -> tuple[float, float]:
    total_cpu = 0.0
    total_memory_bytes = 0.0
    for container_id in container_ids:
        try:
            container = sandbox.client.containers.get(container_id)
            stats = container.stats(stream=False)
            total_cpu += _calc_cpu_percent(stats)
            total_memory_bytes += float(_calc_memory_usage_bytes(stats))
        except Exception:
            # 单容器采样失败时不打断整轮压测，按 0 处理并继续。
            total_cpu += 0.0
            total_memory_bytes += 0.0
    return total_cpu, _bytes_to_gb(total_memory_bytes)


def _run_single_round(
    sandbox: StegoSandbox,
    *,
    scenario: str,
    container_count: int,
    repeat_index: int,
    sample_interval: int,
    sample_window: int,
) -> RunResult:
    container_ids: list[str] = []
    startup_seconds: list[float] = []
    sampled_cpu: list[float] = []
    sampled_memory_gb: list[float] = []
    round_tag = f"{scenario.lower()}-r{repeat_index + 1}-{uuid4().hex[:8]}"

    try:
        for index in range(container_count):
            begin = time.perf_counter()
            started = sandbox.start_container(
                image=StegoSandbox.DEFAULT_IMAGE,
                environment={
                    "LAB_BENCHMARK": "1",
                    "LAB_SCENARIO": scenario,
                    "LAB_REPEAT": str(repeat_index + 1),
                },
                name=f"bench-{round_tag}-c{index + 1}",
            )
            startup_seconds.append(time.perf_counter() - begin)
            container_ids.append(started["container_id"])

        sample_count = max(1, sample_window // sample_interval)
        for i in range(sample_count):
            cpu_total, mem_total_gb = _collect_sample(sandbox, container_ids)
            sampled_cpu.append(cpu_total)
            sampled_memory_gb.append(mem_total_gb)
            if i < sample_count - 1:
                time.sleep(sample_interval)

        return RunResult(
            scenario=scenario,
            container_count=container_count,
            repeat_index=repeat_index + 1,
            avg_cpu_percent=round(_mean(sampled_cpu), 4),
            peak_cpu_percent=round(max(sampled_cpu) if sampled_cpu else 0.0, 4),
            avg_memory_gb=round(_mean(sampled_memory_gb), 4),
            peak_memory_gb=round(max(sampled_memory_gb) if sampled_memory_gb else 0.0, 4),
            avg_startup_seconds=round(_mean(startup_seconds), 4),
            sample_count=len(sampled_cpu),
        )
    finally:
        for container_id in container_ids:
            try:
                sandbox.stop_container(container_id, remove=True)
            except Exception:
                continue


def _summarize(runs: list[RunResult]) -> list[ScenarioSummary]:
    summaries: list[ScenarioSummary] = []
    for scenario, container_count in SCENARIOS:
        items = [x for x in runs if x.scenario == scenario]
        summaries.append(
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
    return summaries


def _write_outputs(runs: list[RunResult], summaries: list[ScenarioSummary]) -> dict[str, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    runs_csv = OUTPUT_DIR / "sandbox_benchmark_runs.csv"
    runs_json = OUTPUT_DIR / "sandbox_benchmark_runs.json"
    summary_json = OUTPUT_DIR / "sandbox_benchmark_summary.json"
    summary_snapshot_json = OUTPUT_DIR / f"sandbox_benchmark_summary_{stamp}.json"
    cpu_chart = OUTPUT_DIR / "sandbox_benchmark_cpu.png"
    memory_chart = OUTPUT_DIR / "sandbox_benchmark_memory.png"

    run_dicts = [asdict(x) for x in runs]
    summary_dicts = [asdict(x) for x in summaries]

    with runs_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(run_dicts[0].keys()))
        writer.writeheader()
        writer.writerows(run_dicts)

    with runs_json.open("w", encoding="utf-8") as f:
        json.dump({"runs": run_dicts}, f, ensure_ascii=False, indent=2)

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_dicts}, f, ensure_ascii=False, indent=2)

    with summary_snapshot_json.open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_dicts}, f, ensure_ascii=False, indent=2)

    x = [x.container_count for x in summaries]
    avg_cpu = [x.avg_cpu_percent for x in summaries]
    peak_cpu = [x.peak_cpu_percent for x in summaries]
    avg_mem = [x.avg_memory_gb for x in summaries]
    peak_mem = [x.peak_memory_gb for x in summaries]

    plt.figure(figsize=(8, 4.8))
    plt.plot(x, avg_cpu, marker="o", label="Average CPU (%)")
    plt.plot(x, peak_cpu, marker="o", label="Peak CPU (%)")
    plt.xlabel("Container Count")
    plt.ylabel("CPU (%)")
    plt.title("Container Count vs CPU")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig(cpu_chart, dpi=150)
    plt.close()

    plt.figure(figsize=(8, 4.8))
    plt.plot(x, avg_mem, marker="o", label="Average Memory (GB)")
    plt.plot(x, peak_mem, marker="o", label="Peak Memory (GB)")
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
    print("[INFO] 初始化沙箱管理器 ...")
    sandbox = StegoSandbox(ensure_image=True)
    all_runs: list[RunResult] = []

    print(
        f"[INFO] 开始压测：场景={len(SCENARIOS)}，每场景重复={REPEATS}，"
        f"采样间隔={SAMPLE_INTERVAL_SECONDS}s，采样窗口={SAMPLE_WINDOW_SECONDS}s"
    )

    for scenario, container_count in SCENARIOS:
        for repeat_index in range(REPEATS):
            print(
                f"[RUN] 场景={scenario} 容器数={container_count} "
                f"第 {repeat_index + 1}/{REPEATS} 轮 ..."
            )
            run_result = _run_single_round(
                sandbox,
                scenario=scenario,
                container_count=container_count,
                repeat_index=repeat_index,
                sample_interval=SAMPLE_INTERVAL_SECONDS,
                sample_window=SAMPLE_WINDOW_SECONDS,
            )
            all_runs.append(run_result)
            print(
                "[RUN] 完成 "
                f"avg_cpu={run_result.avg_cpu_percent:.2f}% "
                f"peak_cpu={run_result.peak_cpu_percent:.2f}% "
                f"avg_mem={run_result.avg_memory_gb:.3f}GB "
                f"peak_mem={run_result.peak_memory_gb:.3f}GB "
                f"avg_startup={run_result.avg_startup_seconds:.3f}s"
            )
            time.sleep(2)

    summary = _summarize(all_runs)
    output_files = _write_outputs(all_runs, summary)

    print("\n[INFO] 场景平均结果：")
    for item in summary:
        print(
            f"  - {item.scenario}({item.container_count}) "
            f"avg_cpu={item.avg_cpu_percent:.2f}% "
            f"peak_cpu={item.peak_cpu_percent:.2f}% "
            f"avg_mem={item.avg_memory_gb:.3f}GB "
            f"peak_mem={item.peak_memory_gb:.3f}GB "
            f"avg_startup={item.avg_startup_seconds:.3f}s"
        )

    print("\n[INFO] 输出文件：")
    for key, value in output_files.items():
        print(f"  - {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
