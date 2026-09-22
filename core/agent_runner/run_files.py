"""run_files.py — .fenix/runs/ 运行产物写入与生命周期（refactor-core-packages 阶段 2）。

模块级函数组件：append_run_line / append_run_error / run_spec_part /
archive_spec_runs。门面 runner.py 转导这些名字，`from core.agent_runner
import run_spec_part` 等外部 import 路径保持可用。

产物保留语义（fix-dashboard-read-path-performance D4）：活跃 runs 目录的
有界性由「终态即移出」保证——daemon 周期保留清理（core/dashboard/data/runs.py
runs_retention_check）把终态 run 移入 archive/，归档目录再按 runs.keep 上限
清理。file 从顶层移入 archive/ 的另一入口是所属 SPEC 被归档
（archive_spec_runs，由 bin/fenix_archive.py 与 SPEC 归档路径调用）。
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
    # add-code-review-agent-and-quality-tab：code-review- 独立前缀，与既有
    # 前缀无子串冲突（顺序无关，放此处便于横向检索）
    ("code-review-", "code-review"),
    # add-code-review-auto-fix：code-fix- 独立前缀（与 code-review- 无子串
    # 冲突，顺序无关，放 code-review- 相邻处便于横向检索）
    ("code-fix-", "code-fix"),
    ("planner-judge-", "planner-judge"),
    ("planner-plan-", "planner-plan"),
    ("planner-", "planner"),
    # add-impl-ocr-parallel-lane（任务 3.5）：impl-ocr- 独立前缀，MUST 排在
    # 其子串前缀 impl- 之前（顺序敏感，首个命中即止）——否则车道 run 在
    # 时间线上会退化为 implementer 归属。
    ("impl-ocr-", "impl-ocr"),
    ("impl-", "implementer"),
    ("repair-", "repair"),
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

    每行独立 open("a") + flush。写入端**多线程并发**（同一 run 的不同事件
    由 daemon 主循环/worker/子进程收尾等多个写线程追加）时，短行依赖内核
    O_APPEND 的原子性避免交错；但该保证有边界（code-review item 12723ef0e4df）：
    Python 的 TextIOWrapper/BufferedWriter 只在单次行数据不超过内部缓冲
    （默认约 8 KiB）时才走缓冲一次 write；**超缓冲的大行**（超长 error/result）
    会绕过缓冲分发为多次 raw write，仍可能与并发 writer 交错产生半行 JSON。
    调用方若需保证大行完整性，须在进程内自行串行化（本函数不持有跨调用锁，
    以维持既有「每行独立 open」的零共享语义）。实测常见行（事件/终态）远小于
    该阈值，故此处只显式记录该限制，不改变实现。
    """
    with run_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def append_run_error(run_file: Path, error: str, exit_code: int) -> None:
    """异常/超时/kill 终止时向产物文件追加 error 终态行。"""
    append_run_line(run_file, {"type": "error", "error": error, "exit_code": exit_code})


# 后缀剥离正则：attempt（-a<n>）与瞬态重试（-r<n>）段，任意顺序、可重复出现。
# 与 core/agent_runner/runner.py AgentRunner._normalize_run_id（(?:-a\d+|-r\d+)+$）
# 及 core/admin_monitor.py _spec_from_run_id（重复组 -(?:a|r)\d+）同口径
# （fix-robustness-edge-cases 1.0/1.2：三者对 -r<n> 的剥除语义 MUST 一致，
# 否则 run 归属解析互相漂移——-r<n> 漏剥会把在跑 run 判成「非本 spec」）。
RUN_ID_SUFFIX_RE = re.compile(r"(-(?:a|r)\d+)+$")


def strip_run_id_suffixes(run_id: str) -> str:
    """剥除 run_id 尾部 attempt/瞬态重试后缀（``-a<n>`` / ``-r<n>``），返回基础 run_id。

    与 ``AgentRunner._normalize_run_id``（add-run-cancel 归一化助手）同口径；
    本处为模块级纯函数，供 ``run_spec_part`` 与按 run 分组（预算 attempt 归并，
    core/pm_engine/budget.py _count_normal_completed_impl_runs）共用，避免后缀
    剥离逻辑在判定点重复实现（1.2 唯一解析来源约束）。
    """
    return RUN_ID_SUFFIX_RE.sub("", run_id)


def run_spec_part(run_id: str) -> str:
    """从 run_id 推断 spec 名（与 get_runs 的推断逻辑对齐，供索引分组使用）。

    依次剥离 agent 类型前缀、attempt/瞬态重试段（-a<n> / -r<n>，见
    ``strip_run_id_suffixes``）与时间戳段（-<unix秒>）。

    -r<n> 由 runner.py 瞬态重试子循环生成（形如 ``<base>-a1-r1``），漏剥会把
    在跑的 run 解析成整段非 spec 名，全等归属守卫将其判为「非本 spec」→ 活性/
    近期活动判定取假、误报 stuck（与 admin_monitor._spec_from_run_id 事故口径
    一致，evo-verifier-result-single-source）。

    前缀表 = 本模块 ``RUN_ID_AGENT_PREFIXES``（唯一真源，见其定义处注释）。
    """
    _agent_type, spec_part = infer_run_agent_type(run_id)
    spec_part = strip_run_id_suffixes(spec_part)
    # 时间戳剥离限定 9-10 位数字（code-review item 6c089e65a080）：spec 名以
    # 9-10 位数字结尾时会被误剥（如 spec-123456789 → spec）。属极边界场景，
    # 与 fenixd._spec_from_run_id 的解析互为补充；此处保持既有口径（与
    # get_runs 的推断对齐），仅记录该已知限制，不扩大改动面。
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
    except OSError as e:
        # 扫描失败与「runs_dir 不存在」旧实现同返回 0 且无日志（code-review
        # item 23e672c8f873）：上游 bin/fenix_archive.py / spec_archive.py 是
        # fail-open 调用方，会把「扫描失败、零归档」当正常结果，导致已归档 SPEC
        # 的产物残留无人察觉。记 WARNING 使该形态可观测。
        _logger.warning("archive_spec_runs: 扫描 %s 失败（本 SPEC 零归档）: %s", runs_dir, e)
        return 0
    moved = 0
    archive_dir = runs_dir / "archive"
    for victim in candidates:
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / victim.name
            if dest.exists():
                # 去重删除前做轻量判等（code-review item ca47fc88588f）：旧实现
                # 无条件 unlink 且不留日志，仅在「归档副本与顶层副本同源」假设下
                # 安全。一旦顶层副本因 retention 移档后又按原路径追加终态行而与
                # 归档副本分歧，较新的顶层产物会被静默销毁、排障无迹。分歧时记
                # WARNING 再删（仍以归档为准，保持既有去重语义）。
                if _files_differ(victim, dest):
                    _logger.warning(
                        "archive_spec_runs: 顶层副本与归档副本内容分歧，仍按归档为准删除顶层: %s",
                        victim,
                    )
                else:
                    _logger.debug("archive_spec_runs: 去重删除同源顶层副本 %s", victim)
                victim.unlink()
            else:
                victim.replace(dest)
            moved += 1
        except OSError as e:
            _logger.warning("archive_spec_runs: 无法归档 %s: %s", victim, e)
            continue
    return moved


def _files_differ(a: Path, b: Path) -> bool:
    """轻量判等：size 或 mtime 不同即视为分歧；探测失败保守返回 True。

    用于 archive_spec_runs 去重删除前的分歧检测（code-review item
    ca47fc88588f），不做逐字节比对（产物可能较大，且此处只需发现明显分歧）。
    """
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return True
    return sa.st_size != sb.st_size or int(sa.st_mtime) != int(sb.st_mtime)
