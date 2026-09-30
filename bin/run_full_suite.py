#!/usr/bin/env python3
"""run_full_suite.py — 有界全量套件入口（fix-run-hang-amplification D3 / 3.1-3.2 / 4.3）。

背景：裸 ``pytest tests/ -q`` 在存量死循环处挂起时，实现 run 单次等待可超过 1 小时、
I/O 涨至 44-60GB（fix-root-init-import-shadow 事故）。框架能否给出「挂在哪个测试」
直接决定该 run 是数分钟收口还是数小时空转。

本入口：
- 以硬超时运行全量套件，启用 faulthandler（``-p faulthandler
  -o faulthandler_timeout=<N>``，pytest 9 起 CLI 参数 ``--faulthandler-timeout``
  已移除、改为 ini 配置项），挂起时打印各线程栈；
- 超时/挂起时中止子进程**组**（SIGTERM 优雅窗口后 SIGKILL 兜底，孙进程一并
  中止）并输出**挂起测试标识**（faulthandler 栈顶用例）；
- 正常结束返回 pytest 完整输出与退出码；
- ``--baseline <ref>``：在基线 ref 的临时 worktree 跑同一套件，输出两侧失败集合
  差异并给出「存量 / 本次引入」归类（混合情形判为存在本次引入回归）；
- 主机级互斥（``.fenix/full-suite.lock`` fcntl 文件锁）：同一主机全量套件串行，
  锁获取/等待结果写日志可观测（concurrent-suite-isolation）。

用法：
    python3 bin/run_full_suite.py [--timeout <seconds>] [--baseline <ref>] [--json]
    python3 bin/run_full_suite.py --baseline HEAD~1 --timeout 1800
    python3 bin/run_full_suite.py --json [--baseline <ref>]
      （--json 供脚本消费：日志全部走 stderr，stdout 只含末尾的单一 JSON 文档）

约定：本脚本在项目根（含 .git 的祖先目录）执行；由 run 主树/工作树任意目录调用
均定位到框架根。
"""

import argparse
import fcntl
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

# 默认硬超时：1 小时（对齐历史事故「等待超过 1 小时」的上界，避免再次无限期占用预算）。
DEFAULT_TIMEOUT_SECONDS = 3600
# faulthandler 栈打印超时：子进程被等待超过该秒数时打印各线程栈（比硬超时更早定位）。
# pytest 9 起已废弃 CLI 参数 --faulthandler-timeout，改用 ini 配置项
# faulthandler_timeout（经 ``-o`` 注入），详见 docstring。
FAULTHANDLER_TIMEOUT_SECONDS = 300
# 主机级互斥锁文件（相对项目根，.fenix/ fcntl 锁范式）。
LOCK_FILE_REL = ".fenix/full-suite.lock"
# 全量套件 basetemp（临时目录根，相对项目根）。
# 默认 pytest basetemp 落在系统 /tmp/pytest-of-<user>/——多项目/多并发套件共用
# 同一基址，且 pytest 仅在会话结束清理自己那一层、留 ~5 个历史目录，长期累积
# 到 GB 级并拖慢 tmp_path 的 make_numbered_dir（O(n) 扫目录）。
# 改用项目内 .fenix/（gitignored）隔离：目录随项目、可随 .fenix 一并清理，
# 不污染系统 /tmp。会话结束由 tests/conftest.py 的 autouse fixture 自清（B）。
BASETEMP_REL = ".fenix/pytest-basetemp"
# 锁等待超时（秒）：等不到锁也执行（保守不阻塞），但写日志留痕供复盘。
LOCK_WAIT_TIMEOUT_SECONDS = 600
# 基线 ref 上运行同一套件时的硬超时上界（code-review item b6c85da8bccb：旧注释
# 称「较短的硬超时」与常量相悖）。实际生效值 = min(本常量, 调用方超时 × 2)：
# 基线跑的是同一套件、必须收齐**完整**失败集合才能做引入归类——不刻意短于
# 主套件（短超时会产生不完整失败集，把基线打成 baseline-hang 使归类不可信），
# 只设放大上界（7200s）防病态配置下的无限等待。
BASELINE_TIMEOUT_SECONDS = 7200

PYTEST_BASE_ARGS = [
    "pytest",
    "tests/",
    "-q",
    "-p",
    "faulthandler",
    "-o",
    f"faulthandler_timeout={FAULTHANDLER_TIMEOUT_SECONDS}",
]


def _with_basetemp(cmd: list, project_root, unique: bool = False) -> list:
    """给 pytest 命令注入项目内 basetemp（隔离系统 /tmp，且可由 conftest 自清）。

    ``--basetemp`` 指向 ``<project_root>/<BASETEMP_REL>``；pytest 会**先清空**该
    目录再建（given basetemp 语义），故每轮套件从干净目录起跑，天然不累积。

    ``unique=True``（主机锁获取失败的并发回退）：追加 ``-<pid>`` 后缀——
    固定 basetemp 下两个并发套件会在会话开始互相清空对方临时目录（正是
    主机锁要防的损坏）；锁失效时改用进程唯一目录，宁可留残目录也不互删。
    """
    if any(str(a).startswith("--basetemp") for a in cmd):
        return cmd  # 调用方已显式指定，不覆盖
    rel = f"{BASETEMP_REL}-{os.getpid()}" if unique else BASETEMP_REL
    base = Path(project_root) / rel
    # pytest 以 ``mkdir(mode=0o700)``（非 parents=True）创建给定 basetemp，
    # 故父目录须先存在（主树 .fenix 已在；基线临时 worktree 需兜底）。
    base.parent.mkdir(parents=True, exist_ok=True)
    return cmd + [f"--basetemp={base}"]


# ── 端口段派生（concurrent-suite-isolation 4.2）──────────────────────────
# 并发套件从进程/run 派生互不重叠的端口段：默认取 pid 哈希映射到 [31000, 32000)，
# 可经 FENIX_SUITE_PORT_BASE 环境变量覆盖（显式指定基址）；FENIX_VERIFY_PORT
# 语义不变（下发给 pytest 子进程，供测试读取）。

# 端口段宽度（pid 派生偏移空间）：也是 FENIX_SUITE_PORT_BASE 上界校验余量，
# 保证「基址 + 段宽 ≤ 65535」不越界（单一来源，勿在别处硬编码段宽）。
SUITE_PORT_SEGMENT_WIDTH = 1000


def suite_port_base() -> int:
    """返回当前套件进程使用的端口段基址（31000-31999）。

    优先元 ``FENIX_SUITE_PORT_BASE``（显式覆盖），否则按 pid 派生：
    ``31000 + (pid % 1000)``——pid 不同则段不同只是**概率性**不重叠
    （约 1/1000 概率同段）；需要强不重叠保证时用 FENIX_SUITE_PORT_BASE
    显式覆盖。环境变量上界校验含段宽余量（基址+段宽 ≤ 65535）。
    """
    env_base = os.environ.get("FENIX_SUITE_PORT_BASE")
    if env_base:
        try:
            val = int(env_base)
            if 1 <= val <= 65535 - SUITE_PORT_SEGMENT_WIDTH:
                return val
        except (TypeError, ValueError):
            pass
    return 31000 + (os.getpid() % SUITE_PORT_SEGMENT_WIDTH)


def _suite_env() -> dict:
    """子进程环境：注入端口段约定（不破坏既有 FENIX_VERIFY_PORT）。"""
    env = dict(os.environ)
    # 回写校验后的值（非 setdefault）：父环境残留非法值时，子进程须与父层
    # suite_port_base() 的回退派生结果一致，而非透传被判非法的原始值。
    env["FENIX_SUITE_PORT_BASE"] = str(suite_port_base())
    return env


# ── faulthandler 栈解析 ────────────────────────────────────────────────


def extract_hanging_test(stderr: str) -> "str | None":
    """从 faulthandler 栈输出提取挂起测试标识（优先 tests/ 路径下的帧）。

    faulthandler 输出形如：
        Thread 0x7f... (most recent call first):
          File "/repo/tests/test_x.py", line 42, in test_hang
          ...
    faulthandler 会为**每个线程**各打一份栈，且 dump 的首个 File 帧常是
    主线程或 pytest/faulthandler 内部帧而非挂起用例——盲取首帧会把调试
    引向完全无关的方向。故优先取**路径在 tests/ 下**的首个 File 帧（自然
    排除 pytest/pluggy 等内部帧），无 tests/ 帧再回退首帧
    （compat：路径可相对）。

    无匹配返回 None（不误报）。
    """
    first = None
    for line in (stderr or "").splitlines():
        m = re.search(r'File "([^"]+)", line \d+, in (.+)', line)
        if not m:
            continue
        path = m.group(1)
        func = m.group(2).strip()
        if first is None:
            first = f"{path}:{func}"
        norm = path.replace("\\", "/")
        if norm.startswith("tests/") or "/tests/" in norm:
            return f"{path}:{func}"
    return first


# ── 命令运行（有界）────────────────────────────────────────────────────


def run_command(cmd, timeout, cwd, env=None) -> tuple:
    """运行命令并在超时时中止（进程组 SIGTERM→SIGKILL 兜底）；返回 (rc, stdout, stderr, timed_out)。

    子进程以独立进程组启动（``start_new_session=True``）：超时先对整组发
    SIGTERM 给短暂优雅窗口，未退出再 SIGKILL 整组——pytest 拉起的孙进程
    （v2 dev server、daemon 集成类测试等）一并中止，不留孤儿继续占端口/内存。
    进程已退出（ProcessLookupError）等 killpg 失败静默吞掉。
    超时 kill 后仍收集已产出的输出（faulthandler 栈对挂起定位是关键证据）。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # start_new_session=True ⇒ pgid==pid
        except OSError:
            pass  # 进程已退出，无需再中止
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True ⇒ pgid==pid
            except OSError:
                pass  # 进程组已不存在
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            # EOF 迟迟不到（游离孙进程仍持有管道写端）时保留已读到的部分输出：
            # faulthandler 栈是挂起定位的关键证据，置空会让 extract_hanging_test
            # 无从提取。注意 text=True 下 Popen 的 TimeoutExpired 携带的是 bytes
            # （解码只发生在成功路径），须按实际类型归一为 str（兼容 None/str）。
            out = exc.stdout or ""
            err = exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            if isinstance(err, bytes):
                err = err.decode(errors="replace")
        return None, out, err, True


def run_suite(
    project_root, timeout=DEFAULT_TIMEOUT_SECONDS, env=None, cmd_override=None, log=print,
    basetemp_unique=False,
) -> dict:
    """运行一次全量套件（有界）；返回 summary dict。

    summary keys:
        elapsed_seconds, timed_out, returncode, hanging_test, exit_code,
        failed_tests（自未截断原始输出提取的失败集合）,
        stdout, stderr（截断保留，仅作展示/落盘摘要）。

    Args:
        cmd_override: 测试注入——替代 pytest 命令（如固定输出的假命令）。
        basetemp_unique: 主机锁获取失败时置 True——回退 pid 唯一 basetemp，
            防并发套件互相清空对方临时目录。
    """
    started = time.time()
    if cmd_override is not None:
        cmd = list(cmd_override)
    else:
        cmd = _with_basetemp(list(PYTEST_BASE_ARGS), project_root, unique=basetemp_unique)
    rc, out, err, timed_out = run_command(cmd, timeout, cwd=project_root, env=env or _suite_env())
    elapsed = round(time.time() - started, 1)
    hanging = extract_hanging_test(err) if timed_out else None
    # 失败集合须在截断**前**从完整原始输出提取（code-review item c00c0572529d）：
    # pytest 的 FAILED 摘要集中在输出末段，失败条目多时最早的 FAILED 行会被
    # 下方截尾丢掉，基于截断文本提取会让 cur ⊆ base 误判「存量」而漏报本次引入。
    # stdout/stderr 键仍按截断保留（展示用途），完整失败集合经 failed_tests 键给出。
    failed_tests = collect_failed_tests(out, err)
    # 超时约定退出码 124（与 timeout(1) 惯例一致），正常按 pytest 实际退出码。
    exit_code = 124 if timed_out else (rc if rc is not None else 1)
    summary = {
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
        "returncode": rc,
        "hanging_test": hanging,
        "exit_code": exit_code,
        "failed_tests": failed_tests,
        "stdout": (out or "")[-2000:],
        "stderr": (err or "")[-3000:],
    }
    log(
        f"[run_full_suite] elapsed={elapsed}s rc={rc} "
        f"timed_out={timed_out} hanging_test={hanging or 'nil'} "
        f"exit_code={exit_code}"
    )
    if timed_out:
        log(f"[run_full_suite] 挂起测试标识: {hanging or '（无 faulthandler 栈）'}")
    return summary


# ── 失败集合与基线归类 ─────────────────────────────────────────────────


def collect_failed_tests(stdout: str, stderr: str = "") -> list:
    """从 pytest 摘要输出收集失败/错误测试标识（FAILED/ERROR <nodeid> - <reason>）。

    ERROR 条目（收集错误、fixture 实例化错误）同样计入失败集合，加
    ``ERROR: `` 前缀与 FAILED 区分（code-review item a362849b59a6）：
    仅当前侧有新增 ERROR 时若不入集，classify_baseline 会把非零退出的
    套件误判为「pass（全绿）」。

    提取只认 ``short test summary info`` 区段（code-review item c18d45e87cd3）：
    全文逐行匹配会把失败用例 captured stdout 回显、被测代码打印的
    ``FAILED to ...``、日志 ``ERROR xxx`` 等同前缀行误收进失败集合——一条仅
    出现在当前侧的幻影条目即可把存量失败误判为 introduced（exit 1）。某侧
    输出缺该区段时（pytest 异常中断等）降级为窄匹配：仅收 FAILED/ERROR 后
    token 含 tests/ 路径特征的行，兼顾幻影抑制与崩溃输出下的失败可见性。
    """

    def _is_test_path(token: str) -> bool:
        norm = token.replace("\\", "/")
        return norm.startswith("tests/") or "/tests/" in norm

    def _narrow_match(lines) -> list:
        """无摘要区段侧的降级提取：token 须含 tests/ 路径特征才入集。"""
        entries = []
        for line in lines:
            s = line.strip()
            m = re.match(r"FAILED\s+(\S+)", s)
            if m and _is_test_path(m.group(1)):
                entries.append(m.group(1))
                continue
            m = re.match(r"ERROR\s+(?:collecting\s+)?(\S+)", s)
            if m and _is_test_path(m.group(1)):
                entries.append(f"ERROR: {m.group(1)}")
        return entries

    def _extract_section(lines):
        """进入 short summary 区段后提取，返回 (是否找到区段, 条目列表)。

        区段在下一行 ``==...==`` 装饰分隔线（含最终统计行/下一区段头）处结束。
        """
        entries = []
        in_summary = False
        for line in lines:
            s = line.strip()
            if not in_summary:
                if "short test summary info" in s:
                    in_summary = True
                continue
            if re.match(r"=+.*=+$", s):
                break
            m = re.match(r"FAILED\s+(\S+)", s)
            if m:
                entries.append(m.group(1))
                continue
            # 收集错误摘要形如 ``ERROR collecting tests/x.py``（捕获路径而非字面
            # collecting），fixture/实例化错误形如 ``ERROR <nodeid> - <reason>``。
            m = re.match(r"ERROR\s+(?:collecting\s+)?(\S+)", s)
            if m:
                entries.append(f"ERROR: {m.group(1)}")
        return in_summary, entries

    failed = []
    for stream in (stdout or "", stderr or ""):
        lines = stream.splitlines()
        in_summary, entries = _extract_section(lines)
        if in_summary:
            failed.extend(entries)
        else:
            # 该侧无摘要区段（pytest 异常中断/截断）→ 窄匹配降级，见 docstring。
            failed.extend(_narrow_match(lines))
    return sorted(set(failed))


def classify_baseline(current_failures, baseline_failures) -> str:
    """两侧失败集合差异归类（3.2）：

    - "pass"：当前全绿（无失败）；
    - "baseline_only"：当前失败 ⊆ 基线失败（全部为存量）→ 存量归类；
    - "introduced"：当前失败 ∩ 基线失败 = ∅（仅本次引入）→ 本次引入;
    - "mixed"：两者重叠且本次有基线未现失败 → 判为存在本次引入回归。
    """
    cur = set(current_failures)
    base = set(baseline_failures)
    if not cur:
        return "pass"
    if cur <= base:
        return "baseline_only"
    if not (cur & base):
        return "introduced"
    return "mixed"


def classify_outcome(current_failures, baseline_failures) -> str:
    """归类结论（含 mixed 一律判为本次引入回归）。"""
    cls = classify_baseline(current_failures, baseline_failures)
    if cls == "pass":
        return "pass（全绿）"
    if cls == "baseline_only":
        return "存量"
    if cls == "introduced":
        return "本次引入"
    if cls == "mixed":
        return "存量 + 本次引入（混合，判存在本次引入回归）"
    return cls


# ── 主机级互斥（concurrent-suite-isolation 4.3）────────────────────────


class SuiteLock:
    """主机级全量套件互斥（.fenix/full-suite.lock fcntl 文件锁）。

    同一主机并发全量套件串行：获取失败（已被其他进程持有）时等待
    LOCK_WAIT_TIMEOUT_SECONDS；等不到也继续执行（保守不阻塞），但写日志
    留痕，并把 ``self.acquired`` 置 False——调用方据此回退 pid 唯一
    basetemp（并发套件共用固定 basetemp 会在会话开始互删对方临时目录）。
    """

    def __init__(self, project_root: Path, log=print):
        self._lock_path = Path(project_root) / LOCK_FILE_REL
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._log = log
        self.acquired = False

    def __enter__(self):
        self._file = self._lock_path.open("w")
        start = time.time()
        acquired = False
        while time.time() - start < LOCK_WAIT_TIMEOUT_SECONDS:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(2)
        waited = round(time.time() - start, 1)
        self.acquired = acquired
        if acquired:
            # 阻塞等待中拿到锁（说明曾与其他并发套件争抢）
            self._log(f"[run_full_suite] 主机级锁获取成功（wait={waited}s）")
        else:
            self._log(
                f"[run_full_suite] 主机级锁等待超时（>{LOCK_WAIT_TIMEOUT_SECONDS}s），"
                f"继续执行但无串行保证，回退 pid 唯一 basetemp（供复盘）"
            )
        return self

    def __exit__(self, *exc):
        try:
            if self._file is not None:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
        except OSError:
            pass
        self._file = None
        return False


# ── 基线 worktree 对比（3.2）──────────────────────────────────────────


def run_baseline_comparison(project_root, ref, timeout, basetemp_unique=False, log=print) -> dict:
    """在基线 ref 的临时 worktree 跑同一套件，与当前结果做失败集合差异归类。

    Args:
        basetemp_unique: 主机锁获取失败时置 True——与主套件同语义（见 run_suite），
            回退 pid 唯一 basetemp 防并发套件互删临时目录。
        log: 日志通道（透传给 run_suite）；--json 模式下调用方传入 stderr 通道，
            保证 stdout 只含最终 JSON 文档。

    Returns: {"ref", "baseline_failures", "baseline_rc",
              "baseline_timed_out", "classification", "hanging"}。
    """
    with tempfile.TemporaryDirectory(prefix="fenix-baseline-") as tmp:
        wt = Path(tmp) / "baseline_wt"
        add = subprocess.run(
            # ref 来自 --baseline 自由输入：-- 须置于 ref 之前，使其落入纯
            # 位置参数区，防止以 - 开头的值（如 --force）被 git 当作自身选项。
            ["git", "worktree", "add", "--detach", str(wt), "--", ref],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if add.returncode != 0:
            return {
                "ref": ref,
                "baseline_failures": [],
                "classification": "baseline-worktree-error",
                "hanging": None,
                "error": (add.stderr or add.stdout)[-300:],
            }
        try:
            # 基线 worktree 需要 .fenix 目录（配置模板）才能被 pytest 导入；
            # 按真实运行结果归类。注意：.fenix 运行态文件（config.yaml 等，
            # gitignore 排除不入库）不随 worktree 迁移，两侧环境不对称产生的
            # 环境性失败会计入 baseline_failures——调用方的存量归类结论须带上
            # 该限制声明（见 main 归类输出 baseline_env_note），不得静默采信。
            baseline = run_suite(
                wt, timeout=min(BASELINE_TIMEOUT_SECONDS, timeout * 2),
                basetemp_unique=basetemp_unique, log=log,
            )
            # failed_tests 由 run_suite 在截断前自完整原始输出提取（c00c0572529d）。
            failed = baseline.get("failed_tests", [])
            # 基线运行自身结论（code-review item d0945089bcd0）：旧实现传
            # classify_outcome([], failed)——空当前失败集在 classify_baseline
            # 短路返回「pass（全绿）」，基线套件自身有失败也被报告为全绿，
            # classification 不带真实信息。基线侧没有「当前 vs 基线」两侧可
            # 对比，按实际失败集如实陈述：全绿才 pass，否则带失败计数指向
            # baseline_failures。引入/存量的真实归类由调用方（main）用
            # classify_baseline(current, baseline) 完成，不受本值影响。
            classification = (
                ("pass（全绿）" if not failed else
                 f"baseline-failed（基线自身 {len(failed)} 项失败，见 baseline_failures）")
                if not baseline.get("timed_out") else "baseline-hang"
            )
            return {
                "ref": ref,
                "baseline_failures": failed,
                "baseline_rc": baseline.get("returncode"),
                "baseline_timed_out": baseline.get("timed_out"),
                "classification": classification,
                "hanging": baseline.get("hanging_test"),
            }
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
            )


def _log_to_stderr(message: str) -> None:
    """--json 模式的日志通道：日志行走 stderr，stdout 只输出最终 JSON 文档。"""
    print(message, file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="有界全量套件入口（fix-run-hang-amplification）")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"硬超时秒数（默认 {DEFAULT_TIMEOUT_SECONDS}）",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="基线 ref（git rev/分支）：在基线临时 worktree 跑同一套件，"
        "输出两侧失败集合差异并给出存量/引入归类",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出汇总（供脚本消费）")
    args = parser.parse_args(argv)

    # 定位项目根：脚本位于 <root>/bin/run_full_suite.py → 框架根即父目录。
    project_root = FRAMEWORK_ROOT
    if not (project_root / ".git").exists():
        # 兼容通过子目录软链/符号链接执行的情形：向上找含 .git 的祖先。
        cur = project_root
        while cur.parent != cur:
            if (cur / ".git").exists():
                project_root = cur
                break
            cur = cur.parent

    # 入口硬失败兜底（code-review item 840a7a8fd72b）：锁文件建目录/打开
    # （SuiteLock，.fenix 只读时 OSError）与 Popen 启动（cmd 首元素 pytest 不在
    # PATH 时 FileNotFoundError ⊂ OSError）等前置失败若裸 traceback 冒出，
    # --json 模式 stdout 将无任何 JSON，脚本消费方解析失败。统一捕获 OSError
    # 后转为含 error 字段的结果文档走既有出口（--json 时 stdout 出单一 JSON、
    # 以非零码退出），与探针类脚本的确定性 JSON 判据出口对齐。
    try:
        os.chdir(project_root)
        # --json 供脚本消费（code-review item e15ace9e9d3a）：全部 [run_full_suite]
        # 日志行（主机锁、套件摘要、基线对比清单）改走 stderr，stdout 只保留末尾的
        # 单一合法 JSON 文档——日志与 JSON 混在同一 stdout 时，消费方对整体
        # json.loads 会因前导日志行解析失败。
        log = _log_to_stderr if args.json else print
        lock = SuiteLock(project_root, log=log)

        base = None
        with lock:
            # 锁获取失败（等待超时）→ 回退 pid 唯一 basetemp：固定 basetemp 下
            # 并发套件会在会话开始互相清空对方临时目录，正是主机锁要防的损坏。
            current = run_suite(
                project_root, timeout=args.timeout,
                basetemp_unique=not lock.acquired, log=log,
            )
            # baseline 执行纳入同一锁作用域（code-review item b8556d5a478e）：
            # run_baseline_comparison 会再启一套完整 pytest，「同一主机全量套件
            # 串行」必须同时覆盖它——否则基线套件可与另一进程的主套件并发执行，
            # 主机锁只护住一半。锁获取失败时 baseline 与主套件同样回退 pid 唯一
            # basetemp。
            if args.baseline:
                base = run_baseline_comparison(
                    project_root, args.baseline, args.timeout,
                    basetemp_unique=not lock.acquired, log=log,
                )
    except OSError as exc:
        result = {"error": f"套件启动失败: {exc}", "exit_code": 1}
        if args.json:
            print(json_dumps(result))
        else:
            print(f"[run_full_suite] {result['error']}", file=sys.stderr)
        return 1

    result = {
        "timed_out": current.get("timed_out"),
        "hang_test": current.get("hanging_test"),
        "exit_code": current.get("exit_code"),
        "elapsed_seconds": current.get("elapsed_seconds"),
    }

    if args.baseline:
        # base 已在上方锁作用域内执行（见 with lock 块内注释）
        # failed_tests 由 run_suite 在截断前自完整原始输出提取（c00c0572529d）。
        current_failed = current.get("failed_tests", [])
        if current.get("timed_out"):
            # 机器可读键随 result 落盘（code-review item 06acf85563c3）：
            # 与 run_baseline_comparison 的 baseline-hang/baseline-worktree-error
            # 机器值同口径，脚本消费者不必解析中文展示文案。
            result["classification_key"] = "current-hang"
            result["classification"] = "当前套件挂起（无完整失败集合对比）"
        else:
            # baseline 自身错误态显式处置（code-review item 33596cced7f6）：
            # worktree 创建失败时 baseline_failures 为空集，直接归类会把每个
            # 当前失败都判「本次引入」产生假回归；baseline 超时只给出部分失败
            # 集，归类不可靠。两者都不做引入归类、不给 verdict，交人工判读
            # （当前套件自身失败仍经下方 exit_code 透出，不 mask）。
            result["current_failures"] = current_failed
            base_cls = base.get("classification")
            if base_cls == "baseline-worktree-error":
                result["classification"] = "基线不可用（worktree 创建失败），无法对比归类"
                result["baseline_ref"] = args.baseline
                if base.get("error"):
                    result["baseline_error"] = base["error"]
            elif base_cls == "baseline-hang":
                result["classification"] = "基线不可用（基线套件超时，失败集合不完整），归类不可信"
                result["baseline_failures"] = base.get("baseline_failures", [])
                result["baseline_ref"] = args.baseline
            else:
                # verdict 门只认机器可读键（code-review item 790b30bcb7bb）：改用
                # classify_baseline 的稳定键（pass/baseline_only/introduced/mixed）
                # 判定，不再耦合 classify_outcome 的中文展示文案——该函数任何措辞/
                # 格式改动不再静默禁用 verdict 与 exit 1。展示文案仍经
                # classify_outcome 输出，行为不变。
                cls_key = classify_baseline(current_failed, base["baseline_failures"])
                result["classification"] = classify_outcome(
                    current_failed, base["baseline_failures"]
                )
                result["baseline_failures"] = base["baseline_failures"]
                result["baseline_ref"] = args.baseline
                # 按 spec：混合情形 MUST 判为存在本次引入回归（分类文案已体现）。
                if cls_key in ("introduced", "mixed"):
                    result["verdict"] = "本次引入回归"
                # 基线 worktree 的 .fenix 运行态（config.yaml 等，gitignore 排除
                # 不入库）与主树不对等：环境性失败会计入 baseline_failures，
                # 「cur ⊆ base → 存量」判定可把当前侧真实引入的回归误归为存量。
                # 显式声明该限制，避免 verdict/人工判读静默采信不对称基线。
                result["baseline_env_note"] = (
                    "基线运行于临时 worktree，.fenix 运行态文件与主树不对等，"
                    "环境性差异会污染两侧失败集合对比，存量归类可信度受限"
                )
        log(f"\n[run_full_suite] 基线对比 ref={args.baseline} " f"→ {result['classification']}")
        if current_failed:
            log("[run_full_suite] 当前失败清单:")
            for f in current_failed:
                log(f"  FAILED {f}")
        if base["baseline_failures"]:
            log("[run_full_suite] 基线失败清单:")
            for f in base["baseline_failures"]:
                log(f"  BASELINE_FAILED {f}")
        if result.get("baseline_env_note"):
            log(f"[run_full_suite] 注意: {result['baseline_env_note']}")

    if args.json:
        print(json_dumps(result))

    # 退出码：挂起=124；有未归类失败/引入回归=1；否则 0。
    if current.get("timed_out"):
        return 124
    if args.baseline:
        if result.get("verdict") == "本次引入回归":
            return 1
        if current.get("exit_code") not in (0, None):
            # 混杂存量失败仍带回 pytest 退出码，供上层判断（不 mask 为 0）。
            return current["exit_code"]
        return 0
    return current.get("exit_code") if current.get("exit_code") is not None else 1


def json_dumps(data) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())
