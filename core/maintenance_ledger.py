"""maintenance_ledger.py — 维护型/延伸型工作轻量登记台账（maintenance-work-ledger）。

框架流水线只有 spec 全流程一种记账形态：spec done 后的延伸/维护型工作与
散件没有认领出口，从产生即无主（告警无法路由、记账不可见）。本模块提供
最小登记通道：一行登记（时间、范围、执行者、证据位置）落到项目级台账
文件 ``.fenix/maintenance_log.jsonl``，延伸/维护型工作开工或收尾时自助落账。

关键取舍（design）：独立 jsonl 而非 STATE.md 新节——STATE 写者是全量重写
语义（_admit_entry 丢弃非 spec 条目），混入登记条目会被抹掉；独立文件零
风险且可追加。台账只登记事实，不派生执行车道；条目的 ``run_id`` 字段与
``maintenance-`` 前缀 run 关联（R3），供告警归因与复盘引用。
"""

from pathlib import Path
import json
import time

# 原子追加复用 run_files 的成文约定（单行单次写入；行超
# _ATOMIC_APPEND_LINE_BYTES=4096 时走二进制 os.write，O_APPEND 下由内核对
# 并发写者串行化——先例 code-review item 29df176ff441：TextIOWrapper 长行
# 会裂成多次 raw write、与并发写者交错产生半行 JSON 被读侧跳过）。台账落账
# 是执行者自助（执行者进程与 daemon 可并存并发写），并非单进程顺序写。
from core.agent_runner.run_files import append_run_line
from core.timelib import now_utc, to_storage

# 项目级台账文件名（相对 <project>/.fenix/）
LEDGER_FILENAME = "maintenance_log.jsonl"


def _ledger_path(project) -> Path:
    return Path(project) / ".fenix" / LEDGER_FILENAME


def append_maintenance_entry(project, scope, actor, evidence, note, run_id=None) -> dict:
    """追加一条登记到项目台账，返回写入的条目（含生成的 ts）。

    文件不存在则创建（含 .fenix 目录）；写入用追加模式并沿用 run_files.py
    的原子追加约定。字段：ts / scope / actor / evidence / note / run_id
    （run_id 未提供时写 None，字段恒在——读侧契约稳定）。
    """
    entry = {
        "ts": to_storage(now_utc()),
        "scope": str(scope),
        "actor": str(actor),
        "evidence": str(evidence),
        "note": str(note),
        "run_id": run_id,
    }
    path = _ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_run_line(path, entry)
    return entry


def list_maintenance_entries(project) -> list:
    """读取全量台账条目（旧→新），坏行容错跳过；文件不存在返回空列表。

    坏行（非法 JSON / 非 dict 顶层 / 空行）不中断读取——台账是并发追加的
    jsonl，半行交错（写侧已按原子约定防）或手工编辑损伤不应让全量读取失败。
    """
    try:
        text = _ledger_path(project).read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def make_maintenance_run_id(scope: str) -> str:
    """生成登记型 run id：``maintenance-<scope>-<epoch 秒>``。

    形态与既有 ``<prefix><spec>-<ts>`` 一致（maintenance_runs.py:215/906 同
    款），使 run_files.infer_run_agent_type 归属 "maintenance"、
    admin_monitor._spec_from_run_id 能还原 scope 供归因。
    """
    return f"maintenance-{scope}-{int(time.time())}"


def list_entries_for_run(project, run_id: str) -> list:
    """按 run_id 过滤台账条目（R3 关联读侧：告警归因/盘点按 run 反查登记）。"""
    return [
        e for e in list_maintenance_entries(project) if e.get("run_id") == run_id
    ]
