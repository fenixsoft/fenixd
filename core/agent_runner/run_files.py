"""run_files.py — .fenix/runs/ 运行产物写入与生命周期（refactor-core-packages 阶段 2）。

模块级函数组件：append_run_line / append_run_error / run_spec_part /
archive_spec_runs。门面 runner.py 转导这些名字，`from core.agent_runner
import run_spec_part` 等外部 import 路径保持可用。

产物保留语义（remove-auto-run-cleanup）：顶层产物只增不减，不设任何
按数量/时间的自动清理；文件从顶层移入 archive/ 的唯一入口是所属 SPEC
被归档（archive_spec_runs，由 bin/fenix_archive.py 调用）。
"""

from pathlib import Path
import json
import logging
import re

_logger = logging.getLogger("fenixd.agent_runner.run_files")


# run_id 前缀 → agent 类型（唯一真源）。⚠️ 顺序敏感：更长的前缀必须排在
# 其子串前缀之前（planner-judge-/planner-plan- 先于 planner-），首个命中即止。
# core/dashboard/data.py:get_runs 与本模块 run_spec_part 均消费此表；
# core/admin_monitor.py:_RUN_PREFIXES 是它的子集（只统计计入失败的前缀）。
# 新增 run 前缀只改这里，别再复制一份——data.py 曾因漂移副本漏掉
# spec-review-/dispute-judge-，评审 Agent 在时间线上退化为泛型 "agent"。
RUN_ID_AGENT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("admin-", "administrator"),
    ("dispute-judge-", "dispute-judge"),
    ("spec-review-", "spec-review"),
    ("planner-judge-", "planner-judge"),
    ("planner-plan-", "planner-plan"),
    ("planner-", "planner"),
    ("impl-", "implementer"),
    ("verify-", "verifier"),
    ("test-", "tester"),
)


def infer_run_agent_type(run_id: str) -> tuple[str, str]:
    """从 run_id 推断 ``(agent_type, 剥前缀后的剩余段)``。

    未识别前缀 → ``("agent", run_id)``（泛型兜底，不强行归属）。
    """
    for prefix, agent_type in RUN_ID_AGENT_PREFIXES:
        if run_id.startswith(prefix):
            return agent_type, run_id[len(prefix) :]
    return "agent", run_id


def append_run_line(run_file: Path, entry: dict) -> None:
    """向运行产物文件追加一行 JSON 并立即 flush，保证运行期间 Dashboard 可读。

    每行独立 open("a") + flush，两个读线程并发写入时依赖 O_APPEND 的原子性，
    避免长行被交错切碎。
    """
    with run_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def append_run_error(run_file: Path, error: str, exit_code: int) -> None:
    """异常/超时/kill 终止时向产物文件追加 error 终态行。"""
    append_run_line(run_file, {"type": "error", "error": error, "exit_code": exit_code})


def run_spec_part(run_id: str) -> str:
    """从 run_id 推断 spec 名（与 get_runs 的推断逻辑对齐，供索引分组使用）。

    依次剥离 agent 类型前缀、attempt 段（-a<n>）与时间戳段（-<unix秒>）。

    前缀表 = 本模块 ``RUN_ID_AGENT_PREFIXES``（唯一真源，见其定义处注释）。
    """
    _agent_type, spec_part = infer_run_agent_type(run_id)
    spec_part = re.sub(r"-a\d+$", "", spec_part)
    m = re.match(r"^(.*)-\d{9,10}$", spec_part)
    if m:
        spec_part = m.group(1)
    return spec_part


def archive_spec_runs(runs_dir: Path, spec_name: str) -> int:
    """把 runs_dir 顶层中属于 spec_name 的运行产物移入 runs_dir/archive/。

    产物归档的唯一入口（remove-auto-run-cleanup）：SPEC 归档时由
    bin/fenix_archive.py 调用，将数据生命周期绑定到 SPEC 生命周期。

    仅扫描顶层 `*.jsonl`（不递归 archive/）；run_spec_part 与 spec_name
    精确匹配的文件移入 archive/。同 run_id 的归档副本已存在时仅删除顶层
    副本（内容同源，以归档为准）。单文件 OSError 记 warning 继续处理
    其余文件。不删除任何其他文件，不修改文件内容。

    Returns: 成功归档（含去重删除）的文件数；runs_dir 不存在返回 0。
    """
    if not runs_dir.is_dir():
        return 0
    try:
        candidates = [p for p in runs_dir.glob("*.jsonl") if run_spec_part(p.stem) == spec_name]
    except OSError:
        return 0
    moved = 0
    archive_dir = runs_dir / "archive"
    for victim in candidates:
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / victim.name
            if dest.exists():
                victim.unlink()
            else:
                victim.replace(dest)
            moved += 1
        except OSError as e:
            _logger.warning("archive_spec_runs: 无法归档 %s: %s", victim, e)
            continue
    return moved
