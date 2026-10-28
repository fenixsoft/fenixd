"""regression.py — 全量回归：JUnit XML 解析、结果快照读写、执行调度。

## 背景

全量回归此前只能由 implementer agent 在 run 内手工跑（``bin/run_full_suite.py``，
pytest 专用），没有独立车道、没有历史留存、也没有可观测视图。本次新增独立的回归
执行车道（test-regression-execution 能力），与 code-review 范式完全同构：声明式
执行契约（``verify.yaml regression``）→ daemon 主循环消费文件信号 → 后台 worker
执行 → 结果快照落盘。

## 文件与目录

- 快照：``.fenix/regression/last-run.json``（单文件覆盖式快照，gitignored，
  只留最近一次结果；多轮历史为 Non-Goal，见 design D5/D6）。
- 状态：``.fenix/regression/state.json``（``last_run_date``，同自然日防重，
  MUST NOT 复用自省/code-review 的防重状态——独立防重文件避免互相覆盖，即
  code-review 当年踩过的坑）。
- 信号：``.fenix/regression_request.json``（dashboard 原子写 → daemon
  消费，与 code-review 同构）。

## JUnit XML 宽松解析（design R1）

不同框架的 XML 层级/属性命名略有差异（testsuite 嵌套 vs 平铺、
testcase@classname 语义不同）。解析器按宽松策略：递归找所有
testcase，time 缺失记 0，file 从 file/classname 兜底，
failure/error/skipped 子元素判定分类。MUST NOT 假设被测项目用
Python/pytest——命令形态、测试目录、测试数量均由项目声明。

## 主机级锁互斥（design D7）

回归执行起跑前抢占 bin/run_full_suite.py 的同一把主机级 fcntl
文件锁（.fenix/full-suite.lock，等待上限600s）：同一主机同一时间
只允许一套全量测试（CPU/磁盘/端口不互相干扰）。拿不到锁即放弃
本次并记日志（首版不重试，单快照语义下无历史可查——这与 SuiteLock
的保守语义一致）。

## 设计决策注释

JUnit XML 为跨语言事实标准（pytest --junit-xml、jest-junit、
go-junit-report、maven-surefire 均可产出；testcase@time 承载
单个用例耗时）——框架只写一个 JUnit XML 解析器，避免为每种语言
写解析器。单快照 Non-Goal：首版只需「最近一次结果」，历史多轮留
待后续。进程组杀树形态对齐 core/verify_contract.py:527 与
core/v2_dev_server.py:175——start_new_session=True 创建独立会话组，
超时后 killpg 终止整个森林；仅杀直接子进程会让 shell 形态 cmd
派生的测试进程存活，回归名存实亡且产物锁被占。
"""

import datetime
import errno
import fcntl
import json
import logging
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core import timelib
from core.fs_utils import atomic_write_text
from core.log_adapter import StdLoggerAdapter
from core.verify_contract import RegressionSpec

from core.proc_utils import kill_process_group

_logger = logging.getLogger("fenixd.regression")

# 适配器收口到 core.log_adapter.StdLoggerAdapter（code-review item
# 205eef6ee458）：原与 knowledge_backfill 各持一份同名 _StdLoggerAdapter 且
# 签名语义漂移（本处对多余参数告警丢弃、彼处严格两参 TypeError），单点实现
# 由参数选择形态；本车道沿用告警丢弃形态与既有 ``[component] message`` 格式。
_default_logger = StdLoggerAdapter(_logger)

# ── 主机级锁常量（与 bin/run_full_suite.py SuiteLock 同值）──
# .fenix/ 目录随项目、不入 git——多进程间共享的 fcntl 锁路径。
_LOCK_FILE_REL = ".fenix/full-suite.lock"
_LOCK_WAIT_TIMEOUT_SECONDS = 600


# ── JUnit XML 宽松解析（task 2.1 + design R1）─────────────────────────


def _iter_testcases(root: ET.Element):
    """递归遍历所有 testcase 元素（兼容 testsuite 嵌套/平铺两态）。

    JUnit XML 形态差异（R1）：
    - pytest: testsuites > testsuite > testcase
    - jest-junit: testsuites > testsuite > testcase（多层嵌套）
    - maven-surefire: testsuite 平铺，无包裹 testsuites
    宽松递归即可覆盖。
    """
    for tc in root.iter("testcase"):
        yield tc


def _safe_float(val: Optional[str], default: float = 0.0) -> float:
    """安全浮点转换，缺失/非法值回退 default。"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _resolve_file(tc: ET.Element) -> str:
    """从 testcase 元素提取文件路径（file 属性优先，classname 兜底）。

    file/classname 语义因框架而异：
    - pytest: file=源文件路径，classname=模块.类
    - jest-junit: 文件路径在 classname
    - go-junit-report: file 属性
    两者取第一个非空值。
    """
    return tc.get("file") or tc.get("classname") or ""


def _resolve_line(tc: ET.Element) -> int:
    """从 testcase 元素提取行号，缺失返回 0。"""
    raw = tc.get("line") or tc.get("lineno")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


# 实体膨胀守卫（code-review item d25b89a98831）：xml.etree.ElementTree 对
# billion laughs / quadratic blowup 实体膨胀攻击无防护（官方文档明示），而
# 本模块在 daemon 进程内同步解析被测项目侧产出的 XML（verify.yaml 与测试
# 命令均由项目侧 author）。defusedxml 本仓库不可用（无依赖声明、无先例），
# 故解析前探测头部：合法 JUnit XML（pytest/jest-junit/surefire/
# go-junit-report 产出）从不携带 DOCTYPE/ENTITY 声明，命中即拒。
_XML_ENTITY_GUARD_PROBE_BYTES = 65536
# NUL 剥离后再匹配：UTF-16 编码变体（字符间夹 NUL）同样命中。
_XML_ENTITY_GUARD_RE = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def parse_junit_xml(path: Union[str, Path]) -> Dict[str, Any]:
    """宽松递归解析 JUnit XML，返回结构化结果 dict。

    返回格式（对齐 design D6）：

    - total / passed / failed / errors / skipped: 计数
    - failures: 失败/错误用例列表（name/file/line/time/kind/message）
    - cases: 全部用例（供 extract_long_tests 消费）

    文件缺失抛出 FileNotFoundError；其余解析期文件异常（XML 存在但
    打开/读取失败等）与格式错误均归一为 ValueError（调用方据此归为
    parse_error）。含 DOCTYPE/ENTITY 声明的 XML 在解析前即拒绝（同样
    归一 ValueError，防实体膨胀，code-review item d25b89a98831）。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"JUnit XML 不存在: {path}")

    # 实体膨胀守卫（item d25b89a98831，纵深防御）：只探头部——DOCTYPE/
    # ENTITY 声明按 XML 规范必须位于根元素之前，头部若干 KB 足以覆盖；
    # 命中即拒并留 WARNING。FileNotFoundError 保持原契约不归一。
    try:
        with path.open("rb") as f:
            head = f.read(_XML_ENTITY_GUARD_PROBE_BYTES)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise ValueError(f"JUnit XML 无法读取: {e}") from e
    if _XML_ENTITY_GUARD_RE.search(head.replace(b"\x00", b"")):
        _logger.warning(
            "regression: JUnit XML 含 DOCTYPE/ENTITY 声明，拒绝解析"
            f"（防实体膨胀）: {path}"
        )
        raise ValueError(
            "JUnit XML 含 DOCTYPE/ENTITY 声明，已拒绝解析（防实体膨胀攻击）"
        )

    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise ValueError(f"JUnit XML 解析失败: {e}") from e
    except FileNotFoundError:
        # 缺失契约保持 FileNotFoundError（测试与调用方分别断言），不归一
        raise
    except OSError as e:
        # code-review item e78e0a401797：文件存在但打开/读取失败（权限、
        # 被测命令写一半的竞态等）同样归一为 ValueError，否则 OSError
        # 炸穿 run_regression 捕获元组，整轮回归蒸发且无 parse_error 留痕
        raise ValueError(f"JUnit XML 无法读取: {e}") from e

    root = tree.getroot()
    failures: List[Dict[str, Any]] = []
    cases: List[Dict[str, Any]] = []

    for tc in _iter_testcases(root):
        name = tc.get("name") or tc.get("classname") or "unnamed"
        tc_file = _resolve_file(tc)
        tc_line = _resolve_line(tc)
        tc_time = _safe_float(tc.get("time"))
        tc_classname = tc.get("classname") or ""

        case_info: Dict[str, Any] = {
            "name": name,
            "file": tc_file,
            "line": tc_line,
            "time": tc_time,
            "classname": tc_classname,
        }

        # 分类判定：failure / error / skipped 子元素
        failure_el = tc.find("failure")
        error_el = tc.find("error")
        skipped_el = tc.find("skipped")

        # failure 与 error 两个分类分支除 kind 外完全一致，合并为单循环
        # 避免字段集/截断长度双处维护漂移（item 72536d64a662）。
        # 顺序保持 failure 在前：与旧 elif 链一致，两者并存时只记 failure。
        for el, kind in ((failure_el, "failure"), (error_el, "error")):
            if el is None:
                continue
            # message 属性与 text 兜底统一截断（jest-junit 等会把整段堆栈
            # 塞进 message，超长原文会撑爆单文件覆盖式快照 last-run.json）
            msg = (el.get("message") or (el.text or "").strip())[:500]
            case_info["kind"] = kind
            case_info["message"] = msg
            failures.append({
                "name": name,
                "file": tc_file,
                "line": tc_line,
                "time": tc_time,
                "kind": kind,
                "message": msg,
                # classname（add-codefix-targeted-retry 1.1）：失败用例 nodeid
                # 重构的映射源——pytest junitxml 不产 file 属性，nodeid 以
                # classname 主导重构（tests.test_x.TestFoo → tests/test_x.py
                # ::TestFoo::<name>）。cases 侧本就携带，failures 侧补齐对齐。
                "classname": tc_classname,
            })
            break
        else:
            if skipped_el is not None:
                case_info["kind"] = "skipped"
            else:
                case_info["kind"] = "passed"

        cases.append(case_info)

    total = len(cases)
    failed = sum(1 for c in cases if c["kind"] == "failure")
    errors = sum(1 for c in cases if c["kind"] == "error")
    skipped = sum(1 for c in cases if c["kind"] == "skipped")
    passed = total - failed - errors - skipped

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "failures": failures,
        "cases": cases,
    }


# ── 长耗时用例抽取（task 2.2）─────────────────────────────────────────


def extract_long_tests(
    cases: List[Dict[str, Any]], threshold: float
) -> List[Dict[str, Any]]:
    """从用例列表抽取 time > threshold 的用例（含通过的），返回 long_tests。

    对齐 design D6：long_tests 独立于 failures——一个慢但通过的用例也
    在其中（名称、文件:行、耗时）。

    classname（add-regression-issues-rerun 1.1）：对齐 failures 侧
    add-codefix-targeted-retry 1.1 的补齐做法——cases 侧本就携带，此侧
    原样透传，作为定向子集回归 nodeid 映射源；缺 classname 的存量快照
    读侧宽松（映射判失败回退全量，不影响展示）。
    """
    return [
        {
            "name": c["name"],
            "file": c["file"],
            "line": c["line"],
            "time": c["time"],
            "classname": c.get("classname", ""),
        }
        for c in cases
        if c["time"] > threshold
    ]


# ── 快照读写（task 2.3）────────────────────────────────────────────────


def regression_dir(project_root) -> Path:
    """返回 .fenix/regression/ 目录路径（gitignored 运行时产物）。"""
    return Path(project_root) / ".fenix" / "regression"


def _result_path(project_root) -> Path:
    """last-run.json 路径（单文件覆盖式快照，design D5）。"""
    return regression_dir(project_root) / "last-run.json"


def _atomic_write(path: Path, content: str) -> None:
    """原子写：薄委托 core.fs_utils.atomic_write_text 收口单点
    （code-review item e9311f1be2ee，对齐 escalation/infra_classify 等
    兄弟模块口径，不再手写第二套 mkstemp 实现）。

    mkstemp 唯一临时名 + fsync + os.replace + 权限修复（新文件 0644，
    对非 root 辅助进程/人工其它账号可读，旧实现恒 0600）+ 尽力而为
    目录 fsync 的纪律单点维护于 fs_utils；mkdir 与失败清理临时文件
    由助手内建，调用点行为保持不变。
    """
    atomic_write_text(path, content)


def current_repo_fingerprint(project_root) -> Dict[str, Any] | None:
    """采集当前仓库指纹 ``(branch, merge_base, head_commit)``（3.2）。

    读侧（quality-gates full-suite 门）据此判定框架侧回归产物是否对应当前
    仓库状态：快照指纹与当前指纹**完全一致**才可见；HEAD / merge-base 移动
    即判陈旧。git 子进程采集，任一步失败返回 None（fail-open：调用方照常
    落盘快照、读侧按不可见逐级回落，MUST NOT 抛异常阻断写/读路径）。
    project_root 非 git 仓库 / 裸目录同样 fail-open。

    ``merge_base`` 取 ``git merge-base HEAD main``；无 main 分支的仓库置空串
    （读写两侧同式采集，比较仍自洽）。
    """
    root = str(project_root)

    def _git(*args: str) -> subprocess.CompletedProcess:
        # errors="replace"（code-review item 330c2eb6fdeb）：text=True 严格解码，
        # git 输出含非 UTF-8 字节（如 locale 不符时的分支名）会抛
        # UnicodeDecodeError 逃出下方兜底、违背本函数 fail-open 契约——有损
        # 替换解码即可（指纹只做等值比较，不消费字节语义）。
        return subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True, text=True, errors="replace", timeout=10,
        )

    try:
        head = _git("rev-parse", "HEAD")
        if head.returncode != 0:
            return None
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        merge_base = _git("merge-base", "HEAD", "main")
        return {
            "head_commit": head.stdout.strip(),
            "branch": branch.stdout.strip() if branch.returncode == 0 else "",
            "merge_base": merge_base.stdout.strip() if merge_base.returncode == 0 else "",
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        # SubprocessError 覆盖 TimeoutExpired 及其余子进程异常；ValueError 兜
        # 解码残面（与 errors="replace" 双保险）。一律 fail-open 返回 None。
        return None


def write_result(project_root, result: Dict[str, Any]) -> None:
    """原子写入 .fenix/regression/last-run.json（单快照覆盖式）。

    写坏在系统层面不可能出现（atomic_write 同式）。

    add-impl-selfcheck-model-probe 3.2：落盘前 stamp 仓库指纹
    ``repo_fingerprint = {branch, merge_base, head_commit}``，读侧
    quality-gates 据此校验产物新鲜度（指纹陈旧/存量无指纹按不可见）。
    指纹采集失败 fail-open：快照照常落盘，仅缺该字段（读侧按存量快照
    处置）。不改写调用方传入的 dict。
    """
    path = _result_path(project_root)
    stamp = current_repo_fingerprint(project_root)
    if stamp is not None:
        result = {**result, "repo_fingerprint": stamp}
    _atomic_write(path, json.dumps(result, ensure_ascii=False, indent=2))


def read_result(project_root) -> Dict[str, Any]:
    """读取 last-run.json 快照；缺失返回 never_run，损坏/根非对象返回 parse_error。

    对齐 test-regression-execution 读侧契约：快照缺失/损坏不报 500。
    """
    path = _result_path(project_root)
    if not path.is_file():
        return {"status": "never_run"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        # UnicodeDecodeError（code-review item 2ad57cac768d）属 ValueError 族、
        # 非 OSError 子类：非 UTF-8 快照（外部写手）原本会穿出本函数、违背
        # docstring「损坏返回 parse_error」契约。与 is_regression_running/
        # read_progress 捕 ValueError 的口径对齐，在源头归一损坏降级。
        return {"status": "parse_error", "reason": str(e)}
    # code-review item 222752de454d：合法 JSON 但根非对象（null/[]/字符串，
    # 外部写手可产生此形态）原样外溢非 dict 值，防御责任会外溢到每个消费方
    # 各自补 try/isinstance 守卫。与 _read_json_file（item 10dcd2a6d170）的
    # 归一口径对齐，读取侧统一归一为 parse_error；消费方既有守卫保持不作
    # 纵深防御。
    if not isinstance(data, dict):
        return {"status": "parse_error", "reason": "快照根非对象"}
    return data


# ── 状态文件读写（task 2.4）───────────────────────────────────────────


def _state_path(project_root) -> Path:
    """regression state.json 路径（独立于自省/code-review 防重状态）。"""
    return Path(project_root) / ".fenix" / "regression" / "state.json"


def _read_json_file(path: Path) -> Dict[str, Any]:
    """通用 JSON 读取：缺失/损坏/根非对象返回空 dict（非对象记日志）。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        # 同 read_result（code-review item 2ad57cac768d）：补捕非 UTF-8 文件的
        # UnicodeDecodeError，归一为空 dict，不让异常穿破「损坏返回空 dict」
        # 契约（坏档 state.json 曾令 admin_monitor 回归检查点每周期报错）。
        return {}
    # code-review item 10dcd2a6d170：合法 JSON 但根非对象（[]/字符串/null，
    # 外部写手）没有 .get，消费侧（admin_monitor 同日防重 state.get）会
    # AttributeError 中断回归车道周期检查点；与 marker 读取侧的 isinstance
    # 防御（item 1e2951cac732/63b7d232dd9e）同口径，归一为空 dict。
    if not isinstance(data, dict):
        _logger.warning("regression: %s 为合法 JSON 但根非对象，按空状态处理", path)
        return {}
    return data


def read_state(project_root) -> Dict[str, Any]:
    """读取 .fenix/regression/state.json（last_run_date，同日防重）。"""
    return _read_json_file(_state_path(project_root))


def save_state(project_root, date_str: str) -> None:
    """写入 .fenix/regression/state.json 的 last_run_date。

    独立于自省/code-review 的防重状态文件——同自然日防重，
    复用会被同轮自省检查点写为今天导致本车道永不派发
    （code-review 踩过的坑）。
    """
    path = _state_path(project_root)
    try:
        # 原子写（_atomic_write 自带 mkdir），截断的 state.json 会让
        # _read_json_file 回退 {} 使同自然日防重失效。
        _atomic_write(
            path,
            json.dumps(
                {
                    "last_run_date": date_str,
                    "updated_at": timelib.to_storage(timelib.now_utc()),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except OSError as e:
        _logger.warning("regression: state.json 写入失败: %s", e)


# ── 本日日期字符串（与 code_review/local_today_str 同语义）──────────


def local_today_str() -> str:
    """本地自然日字符串 YYYY-MM-DD（同自然日防重基准）。"""
    return timelib.now_local().date().isoformat()  # SPEC-B 批④收拢


# ── 运行中标记（POST /api/regression/run 的 409 守卫）─────────────


def _running_marker_path(project_root) -> Path:
    """运行中标记文件：.fenix/regression/.running（gitignored 运行时产物）。

    回归可跑 1800s（远超 HTTP 请求生命周期），POST /api/regression/run 的
    「已有回归在跑 → 409」若靠前端本地计时（跨刷新丢失）或 daemon 进程内
    标志（HTTP 线程不可达）都不成立。落盘 marker + 新鲜度判定的形态让任何
    读侧（dashboard HTTP 进程）都能独立判定运行态。
    """
    return regression_dir(project_root) / ".running"


def mark_running(project_root, timeout_seconds: int = 1800) -> None:
    """写运行中标记（started_at + timeout，供新鲜度判定）。"""
    path = _running_marker_path(project_root)
    try:
        # 原子写，截断的 marker 会被 is_regression_running 视为 stale
        # 使 POST 409 守卫误放行第二个并发触发。
        _atomic_write(
            path,
            json.dumps(
                {
                    "started_at": timelib.to_storage(timelib.now_utc()),
                    "timeout_seconds": int(timeout_seconds),
                }
            ),
        )
    except OSError as e:
        _logger.warning("regression: .running marker 写入失败: %s: %s", path, e)


def clear_running(project_root) -> None:
    """清除运行中标记（回归收尾调用；崩溃残留由新鲜度判定兜底）。"""
    try:
        _running_marker_path(project_root).unlink()
    except OSError:
        pass


def is_regression_running(project_root) -> bool:
    """判定是否有回归在跑（marker 新鲜度判定）。

    marker 的存活窗口 = timeout_seconds + 30s 宽限：超窗视为崩溃/断电残留
    （回归进程已死但 marker 未清），不阻塞后续触发（防 409 恒真锁死）。
    无法解析的 marker 同样视为 stale（不误判运行中）。
    """
    path = _running_marker_path(project_root)
    if not path.is_file():
        return False
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        # 畸形 marker 防御（code-review item 1e2951cac732）：合法 JSON 非对象
        # （null/[]/字符串）没有 .get，AttributeError 不在捕获元组——两者都会
        # 渗入 HTTP 409 守卫。此处归一：非 dict / 不可解析时间戳一律视为
        # stale；naive（无偏移，旧/外部写手）按系统本地时区解读
        # （timelib.parse_ts 唯一策略，add-timelib-consolidation-layer 3.3
        # 收拢原 astimezone() 的 naive 语义——外部写手多为本地
        # now().isoformat()，按 UTC 解释会让东侧时区的陈旧 marker 多锁一个
        # 时区偏移）。
        if not isinstance(meta, dict):
            return False
        started = timelib.parse_ts(str(meta.get("started_at", "")))
        if started is None:
            return False
        timeout_seconds = int(meta.get("timeout_seconds", 1800))
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return False
    life = timelib.now_utc() - started
    return life.total_seconds() < timeout_seconds + 30


# ── 运行中进度读取（dashboard 进度条数据源）──────────────────────────

# tail 窗口：pytest 进度标记集中在输出尾部（行满换行 + [ NN%]），8KB 足以
# 覆盖最近数百个用例的进度行，无需整文件读。
_PROGRESS_TAIL_BYTES = 8192
# pytest terminal reporter 的进度标记（-q 与默认模式均为 [ NN%] 形态；
# 其他测试框架无此标记 → 自然落入耗时估算/未知口径）
_PROGRESS_MARKER_RE = re.compile(r"\[\s*(\d+)%\]")


def _progress_log_path(project_root, output_rel: str) -> Path:
    """stdout 进度日志路径：``<output>.log``（resolve 后的绝对路径构造）。

    写侧（run_regression）与读侧（read_progress）共用同一构造口
    （code-review item dec73e92402f）：resolve 在拼 ``.log`` 后缀之前执行，
    output_rel 含符号链接目录或 ``..`` 分量（乃至绝对路径整体替换根）时
    两侧仍解析到同一物理路径，避免真实进度静默退化为估算口径。resolve
    幂等且非严格（目标不存在同样可调用），对既有绝对路径零变化。
    """
    return Path(str((Path(project_root) / str(output_rel)).resolve()) + ".log")


def _resolve_output_paths(project_root, output_rel: str) -> Optional[Tuple[Path, Path]]:
    """resolve 回归产物路径并校验包含于 project_root（写读两侧单点收口）。

    code-review item 2a2702ee5ad2：``output`` 一字两用——run_regression 写侧
    （XML 落盘/清理、进度日志 open）与 read_progress 读侧（进度日志 tail），
    且取值与 spec/last-run.json 快照同源、项目侧可篡改，两侧必须同一防御
    口径：绝对路径会整体替换根、``..`` 可越出项目目录，故 resolve 后做
    ``is_relative_to(root_abs)`` 包含校验，任一路径越界返回 None（读侧按
    无真实进度回落，写侧按 skipped 放弃本次回归）。resolve 幂等且非严格
    （目标不存在同样可调用）。
    """
    root_abs = Path(project_root).resolve()
    output_abs = (Path(project_root) / str(output_rel)).resolve()
    log_abs = _progress_log_path(project_root, output_rel)
    if not (output_abs.is_relative_to(root_abs) and log_abs.is_relative_to(root_abs)):
        return None
    return output_abs, log_abs


def read_progress(project_root) -> Dict[str, Any]:
    """读取运行中回归的执行进度（GET /api/regression/result 透出 progress）。

    三级口径（框架无关——模块头 MUST NOT 假设 pytest，只是真实进度源
    恰好是 pytest 终端标记时精度最高）：

    - 真实进度：tail 本次 stdout 日志（``<output>.log``），取最后一个
      pytest 终端进度标记 ``[ NN%]``；
    - 估算进度：无标记（非 pytest / 输出尚未刷新）时用
      已耗时 ÷ 上次快照总耗时 合成近似百分比（estimated=True）；
    - 未知：marker 不可读或无上次耗时 → percent=None，前端渲染
      不确定动画条。

    返回 {elapsed_seconds, percent, estimated, total_estimate,
    last_duration_seconds}。读侧 MUST NOT 抛异常（dashboard data 层不设防
    二次兜底）。
    """
    info: Dict[str, Any] = {
        "elapsed_seconds": None,
        "percent": None,
        "estimated": False,
        "total_estimate": None,
        "last_duration_seconds": None,
    }
    # marker 已耗时（started_at 起算）
    output_rel: Optional[str] = None
    try:
        meta = json.loads(
            _running_marker_path(project_root).read_text(encoding="utf-8")
        )
        # 畸形 marker 防御（code-review item 63b7d232dd9e，与 is_regression_running
        # 同款）：合法 JSON 非对象（null/[]/字符串）没有 .get，AttributeError 不在
        # 捕获元组——而本函数 docstring 明确读侧 MUST NOT 抛异常；naive 时间戳
        # （无偏移）按本地时区解读（timelib.parse_ts 唯一策略），与
        # is_regression_running 口径一致。
        if not isinstance(meta, dict):
            return info
        started = timelib.parse_ts(str(meta.get("started_at", "")))
        if started is None:
            return info
        info["elapsed_seconds"] = round(
            max(
                0.0,
                (timelib.now_utc() - started).total_seconds(),
            ),
            1,
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    # 上次快照：分母（total）、估算基准（duration）、stdout 日志路径（output）
    try:
        last = read_result(project_root)
        if isinstance(last, dict) and last.get("status") not in ("never_run", "parse_error"):
            info["total_estimate"] = last.get("total")
            info["last_duration_seconds"] = last.get("duration_seconds")
            output_rel = last.get("output")
    except Exception:
        pass
    # 真实进度：tail stdout 日志找最后一个 [ NN%]
    percent_real: Optional[int] = None
    try:
        if output_rel:
            # code-review item cb9951c9fc1b：output 取自 last-run.json 快照
            # （外部可篡改），读取前校验其解析后仍位于 project_root 内——
            # 绝对路径会整体替换根、``..`` 可越出项目目录；不合规按无真实
            # 进度处理（percent_real 保持 None，照常回落估算/未知口径）。
            # item 2a2702ee5ad2：包含校验收口 _resolve_output_paths 单点
            # 助手，与 run_regression 写侧共用同一防御口径。
            resolved = _resolve_output_paths(project_root, output_rel)
            if resolved is not None:
                log_abs = resolved[1]
                if log_abs.is_file():
                    with log_abs.open("rb") as f:
                        f.seek(0, os.SEEK_END)
                        size = f.tell()
                        f.seek(max(0, size - _PROGRESS_TAIL_BYTES))
                        chunk = f.read().decode("utf-8", "replace")
                    marks = _PROGRESS_MARKER_RE.findall(chunk)
                    if marks:
                        percent_real = int(marks[-1])
    except Exception:
        pass
    if percent_real is not None:
        # 运行中恒封顶 99（收尾统计行 [100%] 出现即命令已近结束，但快照
        # 尚未写盘——显示 99% 比假 100% 诚实）
        info["percent"] = min(99, percent_real)
    else:
        last_dur = info.get("last_duration_seconds")
        elapsed = info.get("elapsed_seconds")
        if (
            isinstance(last_dur, (int, float)) and last_dur > 0
            and isinstance(elapsed, (int, float))
        ):
            info["percent"] = min(99, int(elapsed / last_dur * 100))
            info["estimated"] = True
    return info


# ── 主机级全量套件互斥锁（task 2.7 + design D7）─────────────────────


class _SuiteLock:
    """主机级全量套件互斥（.fenix/full-suite.lock fcntl 文件锁）。

    与 bin/run_full_suite.py SuiteLock 同一路径、同一等待上限（600s）。
    拿不到锁即放弃本次并记日志（设计 D7：首版不重试，单快照语义）。
    命令形态无法在锁内执行时（无锁文件权限等）记 WARNING 后继续
    ——与 SuiteLock「等不到也继续执行」同款保守语义。
    """

    def __init__(self, project_root, log_fn=None):
        self._lock_path = Path(project_root) / _LOCK_FILE_REL
        self._log = log_fn or (lambda msg: _logger.warning(msg))
        self._file = None

    def __enter__(self):
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # [fenix-ignore:017ff9adf2fd] 锁文件仅作 fcntl 锚点、无内容语义，"w" 截断无害；
            # 与 bin/run_full_suite.py SuiteLock（同 "w" 打开同一路径）行为一致，均不写诊断内容
            self._file = self._lock_path.open("w")
        except OSError as e:
            # 锁文件无法创建（权限问题等）——保守继续，不阻断回归。
            # code-review item 138d7e3202e6：旧实现只记 WARNING 即 return、
            # `_acquired` 未置位，acquired=False 使 run_regression 短路成
            # skipped/full_suite_lock_not_acquired——本分支声称容忍的降级
            # 场景被静默丢弃（且无快照落盘）。显式标记 bypassed，调用方
            # 据此继续执行（无串行保证，与类注释的保守语义一致）。
            self._bypassed = True
            self._log(f"regression: 无法创建主机级锁文件（跳过锁，无串行保证）: {e}")
            return self
        start = time.time()
        acquired = False
        while time.time() - start < _LOCK_WAIT_TIMEOUT_SECONDS:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as e:
                # code-review item 599356fb5fa1：仅「锁被占」类 errno 值得
                # 空转重试（EACCES 保守纳入——flock 文档虽只列 EWOULDBLOCK，
                # 但不确定现网实现差异，宁可多试不误杀）。其余 errno
                # （ENOLCK、EBADF 等）是持久性基础设施故障，按 2s 间隔
                # 空转满 600s 只会把故障误报成「锁等待超时」，带偏排障
                # 方向——记 WARNING 后立即放弃。放弃路径与超时放弃同构
                # （acquired=False，调用方照旧走 skipped 分支），仅日志与
                # 时机不同。
                if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                    self._log(
                        f"regression: 主机级锁不可用（errno={e.errno}: "
                        f"{e.strerror}），放弃本次回归（供复盘）"
                    )
                    self._acquired = False
                    return self
                time.sleep(2)
        waited = round(time.time() - start, 1)
        if acquired:
            self._log(f"regression: 主机级锁获取成功（wait={waited}s）")
        else:
            self._log(
                f"regression: 主机级锁等待超时（>{_LOCK_WAIT_TIMEOUT_SECONDS}s），"
                "放弃本次回归（供复盘）"
            )
            # 标记未拿到锁，调用方据此放弃
            self._acquired = False
            return self
        self._acquired = acquired
        return self

    @property
    def acquired(self) -> bool:
        """锁是否成功获取（文件句柄不可用时也返回 False）。

        bypassed（锁文件不可用而按无锁继续）不改变本属性——「拿到锁」与
        「绕过锁」是两个维度，调用方以 ``acquired or bypassed`` 判定可否执行。
        """
        return getattr(self, "_acquired", False)

    @property
    def bypassed(self) -> bool:
        """锁文件不可用而按「无锁继续」降级（区别于等待超时的放弃执行）。"""
        return getattr(self, "_bypassed", False)

    def __exit__(self, *exc):
        try:
            if self._file is not None:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
        except OSError:
            pass
        self._file = None
        return False


# ── 进程组杀树（task 2.8 + design D8）─────────────────────────────────


def _kill_process_group(proc: subprocess.Popen) -> None:
    """中止整个进程组（start_new_session 创建的独立会话组）。

    进程组清扫纪律（SIGTERM → wait 宽限 → SIGKILL 补刀）收口于
    core/proc_utils.kill_process_group 单点实现（item 21d8a42c21c1 收口、
    item b090579ac5a0 把本车道变体并入单点）：本函数只是调用适配，本车道
    既有的「SIGKILL 前先探活整组、组仍有成员才补刀」口径（item
    72a90eb6cb2e：兜底不以直接子进程超时为前提）经
    ``sigkill_only_if_group_alive=True`` 表达；caller 回传自身标识，保留
    守卫告警的取证锚点。

    仅杀直接子进程会让 shell 形态 cmd 派生的测试进程存活，回归名存实亡
    且产物锁被占——故必须按整组收口。
    """
    kill_process_group(
        proc,
        sigkill_only_if_group_alive=True,
        caller="regression._kill_process_group",
    )
    # 收尸留调用方（单点实现约定的差异化收尾）：SIGKILL 补刀（若发生）后
    # 留收尾窗口；未补刀（组已清空/守卫拒绝）时进程已被单点内 wait 回收，
    # 立即返回。
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# ── 回归执行（task 2.5 + 2.7 + 2.8）──────────────────────────────────


def run_regression(
    project_root,
    spec: RegressionSpec,
    logger=None,
    lock_root=None,
) -> Dict[str, Any]:
    """执行一次全量回归：加锁 → spawn cmd → 超时中止 → 解析 XML → 写盘。

    对齐 test-regression-execution 执行契约：
    - shell 字符串 / argv 列表两态（VerifyContract.spec.cmd 形态）；
    - 硬超时 spec.timeout_seconds 中止整个进程组（D8）；
    - 非零退出但 XML 可解析时以解析结果为准（XML 有失败/错误 → status:
      failed；XML 全绿仍 status: passed，不因非零退出降级，但结果附
      exit_code 字段并以 WARNING 留痕——非零退出不静默蒸发）；
    - XML 不可解析 → status: parse_error（附非空 reason）；
    - 命令启动失败（Popen OSError，argv 形态可执行文件缺失等）→ status 同为
      parse_error，附 ``launch_error: True`` 结构化判别（「未起跑」≠「跑完产
      不出 XML」，code-review item 1cc2d91268e4）；不新增状态枚举，消费侧对
      parse_error 的保守回落语义不变。
    - 主机级锁互斥（D7）；拿不到锁即放弃并记日志。

    lock_root（add-code-review-auto-fix D10）：主机级锁锚定根。缺省 None
    回落 project_root（既有调用点零迁移）；非 None 时锁文件取
    ``lock_root/.fenix/full-suite.lock`` 而 cwd 与产物仍取 project_root——
    供 worktree 内回归（执行根=worktree）与主树共用同一把锁，串行化
    同一主机的全量测试。

    返回值包含 status（passed/failed/timeout/parse_error）+ 计数 +
    时间 + failures + long_tests（design D6）。
    """
    log = logger or _default_logger
    now_iso = lambda: timelib.to_storage(timelib.now_utc())
    cmd_display = spec.cmd if isinstance(spec.cmd, str) else " ".join(str(s) for s in spec.cmd)
    output_rel = str(spec.output)
    # code-review item 2a2702ee5ad2：output_rel 与 spec/last-run.json 快照
    # 同源、项目侧可篡改，写侧在清理旧产物/落盘进度日志前做与 read_progress
    # 读侧同款的 resolve 后包含校验（单点助手两侧共用，纵深口径一致）——
    # 越出 project_root 的路径不 mkdir/open/unlink，本次回归按 skipped 放弃
    # （与主机级锁未获取同形的返回，不落快照）。
    resolved = _resolve_output_paths(project_root, output_rel)
    if resolved is None:
        log.warning(
            "regression",
            f"回归产物路径越出项目根，放弃本次回归: {output_rel}",
        )
        return {"status": "skipped", "reason": "output_path_outside_project_root"}
    output_abs, log_abs = resolved
    # stdout 进度日志（与 XML 同名 + .log，junit.xml → junit.xml.log）：运行中
    # 由 read_progress tail 提取 pytest 终端进度标记 [ NN%]（junit XML 9.x 是
    # sessionfinish 一次性写盘，运行中不可读，进度只能来自 stdout）。
    # code-review item dec73e92402f：log_abs 经单点助手统一以 resolve 后的
    # 绝对路径拼 .log 后缀（output_rel 含符号链接/.. 分量时写读两侧仍解析到
    # 同一物理路径）。

    # D7: 主机级锁互斥——同一主机只允许一套全量测试（D10：锁根可锚定主树）
    lock = _SuiteLock(
        lock_root if lock_root is not None else project_root,
        log_fn=lambda m: log.info("regression", m),
    )
    with lock:
        if not lock.acquired and not lock.bypassed:
            # 放弃本次（D7：首版不重试，单快照语义下无历史可查）。
            # bypassed（锁文件不可用）不在此列：按「跳过锁，无串行保证」继续
            # 执行（item 138d7e3202e6——旧实现把该降级也短路成 skipped）。
            log.warning("regression", "主机级锁未获取，放弃本次回归")
            return {"status": "skipped", "reason": "full_suite_lock_not_acquired"}
        if lock.bypassed:
            log.warning(
                "regression",
                "主机级锁不可用，按无锁继续执行本次回归（无串行保证）",
            )

        # 清理旧产物（确保解析的是本次执行产出，不是上次残留）
        if output_abs.is_file():
            try:
                output_abs.unlink()
            except OSError:
                pass
        if log_abs.is_file():
            try:
                log_abs.unlink()
            except OSError:
                pass

        started_at = now_iso()
        started_mono = time.monotonic()
        timed_out = False

        # D8: start_new_session=True 创建独立进程组，超时后 killpg
        use_shell = isinstance(spec.cmd, str)
        # stdout 落进度日志；打开失败回退 DEVNULL（进度退化为耗时估算，
        # 执行本身不受影响）。Popen 成功 dup2 到子进程后父进程侧即可关闭。
        # stderr 并入 stdout（code-review item e1f50794bdfd）：旧实现
        # stderr=PIPE 且全程无人排空（等 wait 而非 communicate），杂谈命令
        # 写满约 64KB 内核管道缓冲后阻塞写入直到硬超时——本可完成的 run 被
        # 报成 status: timeout（常伴 XML 缺失）。STDOUT 随 stdout 落同一进度
        # 日志（无管道可填满，诊断信息仍在 .log 里可查）；stdout 回退 DEVNULL
        # 时一并丢弃，不引入新泄漏面。
        try:
            log_abs.parent.mkdir(parents=True, exist_ok=True)
            log_fh = log_abs.open("wb")
        except OSError:
            log_fh = None
        try:
            proc = subprocess.Popen(
                spec.cmd,
                shell=use_shell,
                cwd=str(project_root),
                stdout=log_fh if log_fh is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            elapsed = round(time.monotonic() - started_mono, 2)
            return {
                "status": "parse_error",
                # 启动失败子语义（code-review item 1cc2d91268e4）：与「跑完产
                # 不出 XML」同归 parse_error（不新增状态枚举，read_progress /
                # 质量门的保守回落语义不变）；本字段供消费侧结构化判别「未起跑」。
                "launch_error": True,
                "cmd": cmd_display,
                "output": output_rel,
                "started_at": started_at,
                "finished_at": now_iso(),
                "duration_seconds": elapsed,
                "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                "failures": [], "long_tests": [],
                "reason": f"回归命令启动失败: {e}",
                "long_test_threshold_seconds": spec.long_test_threshold_seconds,
            }
        finally:
            if log_fh is not None:
                log_fh.close()

        # 等待完成或超时
        try:
            proc.wait(timeout=spec.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            log.warning(
                "regression",
                f"回归命令超时（>{spec.timeout_seconds}s），中止进程组: {cmd_display}",
            )
            _kill_process_group(proc)

        elapsed = round(time.monotonic() - started_mono, 2)
        finished_at = now_iso()
        returncode = proc.returncode

        # 解析 JUnit XML
        parse_result: Optional[Dict[str, Any]] = None
        parse_error_reason: Optional[str] = None
        if not output_abs.is_file():
            parse_error_reason = (
                f"命令退出码 {returncode}，但 JUnit XML 产物不存在: {output_rel}"
            )
        else:
            try:
                parse_result = parse_junit_xml(output_abs)
            except (ValueError, FileNotFoundError) as e:
                parse_error_reason = str(e)

        # 超时判定优先（design/执行契约：硬超时中止 → 整体 timeout，
        # 即使 XML 未产出/不可解析也不降级为 parse_error——命令根本没跑完，
        # 归因应是「未完成」而非「产不出 XML」；failed/parse_error 同列带
        # reason 供分面展示）
        if timed_out:
            return {
                "status": "timeout",
                "cmd": cmd_display,
                "output": output_rel,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": elapsed,
                "total": parse_result["total"] if parse_result else 0,
                "passed": parse_result["passed"] if parse_result else 0,
                "failed": parse_result["failed"] if parse_result else 0,
                "errors": parse_result["errors"] if parse_result else 0,
                "skipped": parse_result["skipped"] if parse_result else 0,
                "long_test_threshold_seconds": spec.long_test_threshold_seconds,
                "failures": (parse_result or {}).get("failures", []),
                "long_tests": extract_long_tests(
                    (parse_result or {}).get("cases", []),
                    spec.long_test_threshold_seconds,
                )
                if parse_result
                else [],
                # code-review item 384a3007b9ba：归因主句恒为超时（与上方注释
                # 「未完成」口径一致），XML 缺失/不可解析仅作补充附于其后
                "reason": (
                    f"回归命令超过硬超时（>{spec.timeout_seconds}s）被中止，本次回归未完成"
                    + (f"；{parse_error_reason}" if parse_error_reason else "")
                ),
            }

        if parse_result is not None:
            cases = parse_result["cases"]
            long_tests = extract_long_tests(cases, spec.long_test_threshold_seconds)
            # 状态判定：timeout 优先；否则按解析结果（退出码不改判——XML 全绿
            # 仍 passed，非零退出经下方 exit_code 留痕，不静默蒸发）
            if parse_result["failed"] > 0 or parse_result["errors"] > 0:
                status = "failed"
            else:
                status = "passed"
            result = {
                "status": status,
                "cmd": cmd_display,
                "output": output_rel,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": elapsed,
                "total": parse_result["total"],
                "passed": parse_result["passed"],
                "failed": parse_result["failed"],
                "errors": parse_result["errors"],
                "skipped": parse_result["skipped"],
                "long_test_threshold_seconds": spec.long_test_threshold_seconds,
                "failures": parse_result["failures"],
                "long_tests": long_tests,
            }
            # 非零退出但 XML 全绿（如 runner 在 sessionfinish 收尾阶段崩溃、
            # 命令含测试后处理步骤失败）：status 仍按解析结果 passed（不新增
            # 状态枚举，quality_gates 等消费侧的白名单回落语义不变），附
            # exit_code 结构化留痕 + WARNING——退出码异常不因解析全绿被吞掉。
            if status == "passed" and returncode != 0:
                result["exit_code"] = returncode
                log.warning(
                    "regression",
                    f"回归命令非零退出（exit={returncode}）但 JUnit XML 可解析且无失败，"
                    f"按解析结果判 {status}（exit_code 已附入结果/快照留痕）: {cmd_display}",
                )
            return result

        # parse_error 路径：XML 不可解析
        return {
            "status": "parse_error",
            "cmd": cmd_display,
            "output": output_rel,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": elapsed,
            "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
            "failures": [], "long_tests": [],
            "reason": parse_error_reason or "JUnit XML 不可解析",
            "long_test_threshold_seconds": spec.long_test_threshold_seconds,
        }


def run_and_write_regression(
    project_root,
    spec: RegressionSpec,
    logger=None,
    lock_root=None,
    run_scope: Optional[str] = None,
) -> Dict[str, Any]:
    """执行回归并写入快照盘（write_result），返回结果 dict。

    供 maintenance_runs.run_regression / admin_monitor checkpoint 调用。
    起跑前写运行中标记（供 POST /api/regression/run 的 409 守卫与分面
    「运行中」判定），收尾 finally 清除——崩溃残留由新鲜度判定兜底。

    lock_root（add-code-review-auto-fix D10）：透传给 run_regression 的
    主机级锁锚定根（缺省 None 回落 project_root，既有调用点零迁移）。
    worktree 内回归传 ``lock_root=<主树根>`` 使其与主树共用同一把锁。

    run_scope（add-regression-issues-rerun 1.2）：定向子集标记，缺省 None
    （既有调用点零迁移，真全量不落标记）。非 None 时在 write_result 前
    stamp 进结果 dict（单点覆盖全部状态路径——passed/failed/timeout/
    parse_error 同一写盘口）；仅子集改写实际生效时由门面传 ``"issues"``，
    full-suite 质量门据此判子集产物不可见（防白洗通道）。
    """
    log = logger or _default_logger
    # 声明窗口计入锁等待预算（code-review item 652febabc458）：run_regression
    # 在计时命令启动前先在 _SuiteLock.__enter__ 中阻塞多达
    # _LOCK_WAIT_TIMEOUT_SECONDS（600s）——marker 若只声明 spec.timeout_seconds，
    # 锁等待耗尽新鲜度窗口后 is_regression_running 已报 False，POST
    # /api/regression/run 的 409 守卫放行第二个并发触发。声明窗口 =
    # timeout + 锁等待上限（+ 既有 30s 宽限在读取侧）；正常收尾 finally 仍
    # 清 marker，仅崩溃残留的兜底窗口变长，代价可忽略。
    mark_running(project_root, spec.timeout_seconds + _LOCK_WAIT_TIMEOUT_SECONDS)
    try:
        result = run_regression(project_root, spec, logger=log, lock_root=lock_root)
        if result.get("status") != "skipped":
            # run_scope 单点 stamp（add-regression-issues-rerun 1.2）：write_result
            # 之前统一盖章，覆盖 passed/failed/timeout/parse_error 全部落盘路径；
            # write_result 不改写调用方传入的 dict（{**result, ...} 拷贝式）
            if run_scope is not None:
                result = {**result, "run_scope": run_scope}
            try:
                # code-review item c567b861a566：快照写盘失败（磁盘满/权限）
                # 与同函数 mark_running/clear_running 的吞错降级同口径——回归
                # 已实际跑完，OSError 不外溢中断收尾日志/向上传播，WARNING 留痕。
                write_result(project_root, result)
            except OSError as e:
                log.warning(
                    "regression",
                    f"回归快照写入失败（last-run.json 未更新，"
                    f"本轮结果仅本日志可查）: {e}",
                )
            log.info(
                "regression",
                f"回归完成: status={result['status']}, "
                f"total={result.get('total', 0)}, "
                f"duration={result.get('duration_seconds', 0)}s",
            )
        else:
            log.info("regression", f"回归已跳过: {result.get('reason', '')}")
    finally:
        # 清除运行中标记（任务 5.6 判据：分面以快照 started_at 是否推进判定
        # 运行中，POST 409 守卫以 marker 判定；崩溃残留由新鲜度判定兜底）
        clear_running(project_root)
    return result