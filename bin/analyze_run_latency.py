#!/usr/bin/env python3
"""analyze_run_latency.py — 历史 run 转录批量延迟分析（add-planner-efficiency）。

与在线摘要同口径（复用 runner.py 的 latency_samples_from_events /
latency_stats / format_latency_summary，见 design D3「复用公共解析函数」）：
对每条 run 转录（.fenix/runs/*.jsonl），按「tool_result → 下一个 assistant」
间隔提取 API 往返样本，输出直方图摘要（轮数/中位/p90/max/长尾>60s 计数与占比）。

用法：
    python3 bin/analyze_run_latency.py .fenix/runs/planner-plan-*.jsonl
    python3 bin/analyze_run_latency.py .fenix/runs/*.jsonl

行为：
- 支持 glob 批量扫描（shell 展开或脚本内 glob）；
- 按 p90 降序输出（长尾最重的 run 排前）；
- 损坏/空文件跳过并报告（不中断批量扫描）；
- 无 timestamp 的旧转录样本为空 → 摘要标注 0 rounds（跳过不报错）。
"""

import argparse
import json
import sys
from pathlib import Path

# 项目根（经 .fenix/bin/ 软链接调用时 = 项目目录）
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
# 框架根：core/ 所在目录（直连与经软链接调用都能定位）
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from core.agent_runner.runner import (  # noqa: E402
    format_latency_summary,
    latency_samples_from_events,
    latency_stats,
)


def load_events(run_file: Path) -> list:
    """读取单条 run 转录的事件序列；损坏/空文件抛 ValueError。"""
    try:
        lines = run_file.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise ValueError(f"读取失败: {e}") from e
    events: list = []
    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"第 {lineno} 行非 JSON（可能损坏）: {e}") from e
        if isinstance(entry, dict):
            events.append(entry)
    return events


def analyze_file(run_file: Path) -> tuple:
    """分析单条转录：返回 (run_id, stats, summary)。

    损坏/空文件抛 ValueError（调用方跳过并报告）。
    """
    events = load_events(run_file)
    samples = latency_samples_from_events(events)
    stats = latency_stats(samples)
    summary = format_latency_summary(run_file.stem, stats)
    return run_file.stem, stats, summary


def expand_globs(paths) -> list:
    """展开脚本内 glob（shell 未展开时兜底）；缺失路径跳过并告警。"""
    out: list = []
    for raw in paths:
        p = Path(raw)
        if p.exists():
            out.append(p)
            continue
        # 尝试 glob（含递归）
        import glob

        matched = sorted(Path(m) for m in glob.glob(str(p)))
        out.extend(matched)
    # 去重保序
    seen = set()
    dedup = []
    for p in out:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup


def main() -> int:
    parser = argparse.ArgumentParser(description="历史 run 转录批量延迟分析")
    parser.add_argument("files", nargs="+", help="run jsonl 路径或 glob")
    parser.add_argument(
        "--sort", choices=["p90", "name"], default="p90", help="排序键（默认 p90 降序）"
    )
    args = parser.parse_args()

    files = expand_globs(args.files)
    if not files:
        print("未匹配到任何 run 转录文件", file=sys.stderr)
        return 1

    results = []
    skipped = []
    for f in files:
        try:
            run_id, stats, summary = analyze_file(f)
            results.append((run_id, stats, summary, f))
        except ValueError as e:
            skipped.append((f, str(e)))

    if results:
        if args.sort == "p90":
            results.sort(key=lambda r: r[1].get("p90") or -1, reverse=True)
        else:
            results.sort(key=lambda r: r[0])
        print(f"== 共 {len(results)} 条转录（按 {args.sort} 排序）==\n")
        for run_id, stats, summary, f in results:
            print(summary)

    if skipped:
        print("\n== 跳过（损坏/空） ==")
        for f, err in skipped:
            print(f"- {f}: {err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
