"""remove-aged-spec-archive 验证场景探针（fast-track 场景集，供 verifier 复用）。

每个 ``--case`` 在隔离临时目录构造夹具项目，调用仓库内真实
``core.dashboard.data.spec_archive.auto_archive_check``，打印单行 JSON
结果供场景 ``json_output`` 断言消费。只触碰临时夹具、不涉及真实项目
（不归档任何真实 SPEC、不写真实 STATE）。

case 清单：
- threshold-drain：R1 终态积压达到阈值触发排水（4 条终态/阈值 2 → 归档 3 条）；
- terminal-aged-not-archived：R2 反转——终态+报告+滞留≥72h 且计数低于
  阈值 → 不被归档，水位观测覆盖；
- orphan-takeover：R3 孤儿接管边界（≥72h 归档 auto-orphan / <72h 仅盘点 /
  终态目录不被误伤）；
- daily-audit-water：R4 水位观测（计数+龄期单条 INFO、不按单目录列示、
  孤儿列示、24h 去重）；
- threshold-zero：threshold=0 禁用 R1/R3，backfill 与盘点不受约束。
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.config import ConfigLoader  # noqa: E402
from core.dashboard.data import spec_archive  # noqa: E402
from core.dashboard.data.state import parse_archived_state, parse_state  # noqa: E402


def _build_root():
    root = Path(tempfile.mkdtemp(prefix="spec-archive-probe-"))
    (root / ".fenix").mkdir(parents=True)
    (root / "spec" / "changes").mkdir(parents=True)
    # 每日盘点 24h 去重水位是模块级状态：逐 case 重置，保证首查必触发
    spec_archive._daily_audit_last_ts = 0.0
    return root


def _add_spec(root, name, *, report=False, age_seconds=None):
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text("# t\n", encoding="utf-8")
    if report:
        (d / "verification-report.md").write_text("# vr\n", encoding="utf-8")
    if age_seconds is not None:
        ts = time.time() - age_seconds
        os.utime(d, (ts, ts))


def _write_state(root, specs):
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, entry in specs.items():
        lines += [
            f"### {name}",
            f"- status: {entry['status']}",
            f"- updated: {entry.get('updated', '2026-01-01T00:00:00+00:00')}",
            "",
        ]
    (root / ".fenix" / "STATE.md").write_text(
        "\n".join(lines), encoding="utf-8")


def _set_threshold(root, threshold):
    (root / ".fenix" / "config.yaml").write_text(
        f"project:\n  name: t\narchive:\n  auto_threshold: {threshold}\n",
        encoding="utf-8")


class _Capture:
    """duck-type (component, message) 签名 logger，捕获 _archive_log 记录。"""

    def __init__(self):
        self.records = []

    def info(self, component, msg):
        self.records.append(("info", msg))

    def warning(self, component, msg):
        self.records.append(("warning", msg))


def _run_check(root, logger=None):
    return spec_archive.auto_archive_check(
        root, ConfigLoader.resolve_config(root), logger)


def case_threshold_drain():
    """R1：4 条终态 + 阈值 2 → >= 触发，updated 升序排水 3 条至阈值下。"""
    root = _build_root()
    specs = {}
    for i, name in enumerate(["a", "b", "c", "d"]):
        specs[name] = {
            "status": "done",
            "updated": f"2026-01-0{i + 1}T00:00:00+00:00",
        }
    _write_state(root, specs)
    for name in specs:
        _add_spec(root, name)
    _set_threshold(root, 2)

    r = _run_check(root)
    changes = root / "spec" / "changes"
    manifest = parse_archived_state(root)
    print(json.dumps({
        "archived": r["archived"],
        "target_count": r["target_count"],
        "total_terminal_unarchived": r["total_terminal_unarchived"],
        "a_gone": not (changes / "a").exists(),
        "b_gone": not (changes / "b").exists(),
        "c_gone": not (changes / "c").exists(),
        "d_kept": (changes / "d").is_dir(),
        "manifest_a": manifest.get("a", {}).get("archived_by"),
        "a_left_state": "a" in parse_state(root),
        "orphan_archived": r["orphan_archived"],
    }))


def case_terminal_aged_not_archived():
    """R2 反转：终态+报告+滞留≥72h 且计数低于阈值 → 不被归档，仅水位观测。"""
    root = _build_root()
    _write_state(root, {
        "age-young": {"status": "pushed", "updated": "2026-01-01T00:00:00+00:00"},
        "age-old": {"status": "pushed", "updated": "2026-01-02T00:00:00+00:00"},
    })
    _add_spec(root, "age-young", report=True, age_seconds=71 * 3600)
    _add_spec(root, "age-old", report=True, age_seconds=73 * 3600)
    _set_threshold(root, 10)

    r = _run_check(root)
    changes = root / "spec" / "changes"
    print(json.dumps({
        "archived": r["archived"],
        "orphan_archived": r["orphan_archived"],
        "young_kept": (changes / "age-young").is_dir(),
        "old_kept": (changes / "age-old").is_dir(),
        "old_in_state": "age-old" in parse_state(root),
        "old_not_in_manifest": "age-old" not in parse_archived_state(root),
        "audit_fired": r["audit"]["fired"],
        "terminal_unarchived": r["audit"]["terminal_unarchived"],
        "stale_dirs": r["audit"]["stale_dirs"],
    }))


def case_orphan_takeover():
    """R3：>=72h 孤儿归档（auto-orphan）/ <72h 仅盘点 / 终态目录不被误伤。"""
    root = _build_root()
    _write_state(root, {
        "keep-active": {"status": "implementing"},
        "term-aged": {"status": "done"},
    })
    _add_spec(root, "keep-active")
    _add_spec(root, "term-aged", report=True, age_seconds=73 * 3600)
    _add_spec(root, "orphan-young", report=True, age_seconds=71 * 3600)
    _add_spec(root, "orphan-old", report=True, age_seconds=73 * 3600)
    _set_threshold(root, 10)

    log = _Capture()
    r = _run_check(root, log)
    changes = root / "spec" / "changes"
    manifest = parse_archived_state(root)
    logs = " ".join(m for _lv, m in log.records)
    print(json.dumps({
        "orphan_archived": r["orphan_archived"],
        "orphan_old_gone": not (changes / "orphan-old").exists(),
        "orphan_young_kept": (changes / "orphan-young").is_dir(),
        "term_aged_kept": (changes / "term-aged").is_dir(),
        "term_in_state": "term-aged" in parse_state(root),
        "term_not_in_manifest": "term-aged" not in manifest,
        "orphan_no_state": "orphan-old" not in parse_state(root),
        "orphan_no_manifest": "orphan-old" not in manifest,
        "log_auto_orphan": ("orphan-old" in logs and "auto-orphan" in logs),
        "stale_dirs": r["audit"]["stale_dirs"],
        "terminal_unarchived": r["audit"]["terminal_unarchived"],
    }))


def case_daily_audit_water():
    """R4：终态水位观测单条 INFO（不按单目录列示）+ 孤儿列示 + 24h 去重。"""
    root = _build_root()
    _write_state(root, {
        "dup-1": {"status": "done"},
        "dup-2": {"status": "pushed"},
    })
    _add_spec(root, "dup-1", age_seconds=73 * 3600)
    _add_spec(root, "dup-2", age_seconds=100 * 3600)
    _add_spec(root, "orph-x")  # 孤儿目录（STATE 无条目）
    _set_threshold(root, 10)

    log = _Capture()
    r1 = _run_check(root, log)
    r2 = _run_check(root, log)  # 24h 去重窗口内
    infos = [m for _lv, m in log.records if "每日滞留盘点" in m]
    print(json.dumps({
        "fired_1": r1["audit"]["fired"],
        "fired_2": r2["audit"]["fired"],
        "terminal_unarchived": r1["audit"]["terminal_unarchived"],
        "oldest_days": r1["audit"]["oldest_terminal_age_days"],
        "stale_dirs": r1["audit"]["stale_dirs"],
        "info_count": len(infos),
        "info_has_water": ("终态未归档 2 个" in infos[0]) if infos else False,
        "info_no_terminal_dir_name": bool(infos) and (
            "dup-1" not in infos[0] and "dup-2" not in infos[0]),
    }))


def case_threshold_zero():
    """threshold=0：R1/R3 全禁用（终态+报告+超期与孤儿均原地保留），
    backfill 与盘点信号不受约束。"""
    root = _build_root()
    _write_state(root, {
        "zero-aged": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"},
        "z-old": {"status": "pushed", "updated": "2026-01-02T00:00:00+00:00"},
    })
    _add_spec(root, "zero-aged", report=True, age_seconds=73 * 3600)
    _add_spec(root, "zero-orphan", report=True, age_seconds=73 * 3600)
    _set_threshold(root, 0)

    r = _run_check(root)
    changes = root / "spec" / "changes"
    print(json.dumps({
        "threshold": r["threshold"],
        "archived": r["archived"],
        "orphan_archived": r["orphan_archived"],
        "term_kept": (changes / "zero-aged").is_dir(),
        "orphan_kept": (changes / "zero-orphan").is_dir(),
        "backfill_evicted": r["backfill"]["evicted"],
        "audit_fired": r["audit"]["fired"],
        "terminal_unarchived": r["audit"]["terminal_unarchived"],
        "stale_dirs": r["audit"]["stale_dirs"],
    }))


_CASES = {
    "threshold-drain": case_threshold_drain,
    "terminal-aged-not-archived": case_terminal_aged_not_archived,
    "orphan-takeover": case_orphan_takeover,
    "daily-audit-water": case_daily_audit_water,
    "threshold-zero": case_threshold_zero,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=sorted(_CASES))
    args = parser.parse_args()
    _CASES[args.case]()


if __name__ == "__main__":
    main()
