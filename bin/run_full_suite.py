#!/usr/bin/env python3
"""run_full_suite.py — 有界全量套件入口（fix-run-hang-amplification D3 / 3.1-3.2 / 4.3）。

背景：裸 ``pytest tests/ -q`` 在存量死循环处挂起时，实现 run 单次等待可超过 1 小时、
I/O 涨至 44-60GB（fix-root-init-import-shadow 事故）。框架能否给出「挂在哪个测试」
直接决定该 run 是数分钟收口还是数小时空转。

本入口：
- 以硬超时运行全量套件，启用 faulthandler（``-p faulthandler
  -o faulthandler_timeout=<N>``，pytest 9 起 CLI 参数 ``--faulthandler-timeout``
  已移除、改为 ini 配置项），挂起时打印各线程栈；
- 超时/挂起时中止子进程并输出**挂起测试标识**（faulthandler 栈顶用例）；
- 正常结束返回 pytest 完整输出与退出码；
- ``--baseline <ref>``：在基线 ref 的临时 worktree 跑同一套件，输出两侧失败集合
  差异并给出「存量 / 本次引入」归类（混合情形判为存在本次引入回归）；
- 主机级互斥（``.fenix/full-suite.lock`` fcntl 文件锁）：同一主机全量套件串行，
  锁获取/等待结果写日志可观测（concurrent-suite-isolation）。

用法：
    python3 bin/run_full_suite.py [--timeout <seconds>] [--baseline <ref>]
    python3 bin/run_full_suite.py --baseline HEAD~1 --timeout 1800

约定：本脚本在项目根（含 .git 的祖先目录）执行；由 run 主树/工作树任意目录调用
均定位到框架根。
"""

import argparse
import fcntl
import os
import re
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
# 锁等待超时（秒）：等不到锁也执行（保守不阻塞），但写日志留痕供复盘。
LOCK_WAIT_TIMEOUT_SECONDS = 600
# 基线 ref 上运行同一套件时使用较短的硬超时（基线只需复现失败集合，不必等满主套件）。
BASELINE_TIMEOUT_SECONDS = 7200

PYTEST_BASE_ARGS = ["pytest", "tests/", "-q",
                    "-p", "faulthandler",
                    "-o", f"faulthandler_timeout={FAULTHANDLER_TIMEOUT_SECONDS}"]


# ── 端口段派生（concurrent-suite-isolation 4.2）──────────────────────────
# 并发套件从进程/run 派生互不重叠的端口段：默认取 pid 哈希映射到 [31000, 32000)，
# 可经 FENIX_SUITE_PORT_BASE 环境变量覆盖（显式指定基址）；FENIX_VERIFY_PORT
# 语义不变（下发给 pytest 子进程，供测试读取）。

def suite_port_base() -> int:
    """返回当前套件进程使用的端口段基址（31000-31999）。

    优先元 ``FENIX_SUITE_PORT_BASE``（显式覆盖），否则按 pid 派生：
    ``31000 + (pid % 1000)``——并发进程 pid 不同则段不同，互不重叠。
    """
    env_base = os.environ.get("FENIX_SUITE_PORT_BASE")
    if env_base:
        try:
            val = int(env_base)
            if 1 <= val <= 65534:
                return val
        except (TypeError, ValueError):
            pass
    return 31000 + (os.getpid() % 1000)


def _suite_env() -> dict:
    """子进程环境：注入端口段约定（不破坏既有 FENIX_VERIFY_PORT）。"""
    env = dict(os.environ)
    env.setdefault("FENIX_SUITE_PORT_BASE", str(suite_port_base()))
    return env


# ── faulthandler 栈解析 ────────────────────────────────────────────────

def extract_hanging_test(stderr: str) -> "str | None":
    """从 faulthandler 栈输出提取挂起测试标识（栈顶用例）。

    faulthandler 输出形如：
        Thread 0x7f... (most recent call first):
          File "/repo/tests/test_x.py", line 42, in test_hang
          ...
    取**第一个** File 行 → ``tests/test_x.py:test_hang``（compat：路径可相对）。

    无匹配返回 None（不误报）。
    """
    for line in (stderr or "").splitlines():
        m = re.search(r'File "([^"]+)", line \d+, in (.+)', line)
        if m:
            path = m.group(1)
            func = m.group(2).strip()
            return f"{path}:{func}"
    return None


# ── 命令运行（有界）────────────────────────────────────────────────────

def run_command(cmd, timeout, cwd, env=None) -> tuple:
    """运行命令并在超时时中止（SIGKILL 兜底）；返回 (rc, stdout, stderr, timed_out)。

    超时 kill 后仍收集已产出的输出（faulthandler 栈对挂起定位是关键证据）。
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(cwd), env=env,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return None, out, err, True


def run_suite(project_root, timeout=DEFAULT_TIMEOUT_SECONDS, env=None,
              cmd_override=None, log=print) -> dict:
    """运行一次全量套件（有界）；返回 summary dict。

    summary keys:
        elapsed_seconds, timed_out, returncode, hanging_test, exit_code,
        stdout, stderr（截断保留）。

    Args:
        cmd_override: 测试注入——替代 pytest 命令（如固定输出的假命令）。
    """
    started = time.time()
    if cmd_override is not None:
        cmd = list(cmd_override)
    else:
        cmd = list(PYTEST_BASE_ARGS)
    rc, out, err, timed_out = run_command(
        cmd, timeout, cwd=project_root, env=env or _suite_env())
    elapsed = round(time.time() - started, 1)
    hanging = extract_hanging_test(err) if timed_out else None
    # 超时约定退出码 124（与 timeout(1) 惯例一致），正常按 pytest 实际退出码。
    exit_code = 124 if timed_out else (rc if rc is not None else 1)
    summary = {
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
        "returncode": rc,
        "hanging_test": hanging,
        "exit_code": exit_code,
        "stdout": (out or "")[-2000:],
        "stderr": (err or "")[-3000:],
    }
    log(f"[run_full_suite] elapsed={elapsed}s rc={rc} "
        f"timed_out={timed_out} hanging_test={hanging or 'nil'} "
        f"exit_code={exit_code}")
    if timed_out:
        log(f"[run_full_suite] 挂起测试标识: {hanging or '（无 faulthandler 栈）'}")
    return summary


# ── 失败集合与基线归类 ─────────────────────────────────────────────────

def collect_failed_tests(stderr: str, stdout: str = "") -> list:
    """从 pytest 摘要输出收集失败测试标识（FAILED <nodeid> - <reason>）。"""
    failed = []
    text = (stdout or "") + "\n" + (stderr or "")
    for line in text.splitlines():
        m = re.match(r"FAILED\s+(\S+)", line.strip())
        if m:
            failed.append(m.group(1))
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
    LOCK_WAIT_TIMEOUT_SECONDS；等不到也继续执行（保守不阻塞），但写日志留痕。
    """

    def __init__(self, project_root: Path, log=print):
        self._lock_path = Path(project_root) / LOCK_FILE_REL
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._log = log

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
        if acquired:
            # 阻塞等待中拿到锁（说明曾与其他并发套件争抢）
            self._log(f"[run_full_suite] 主机级锁获取成功（wait={waited}s）")
        else:
            self._log(
                f"[run_full_suite] 主机级锁等待超时（>{LOCK_WAIT_TIMEOUT_SECONDS}s），"
                f"继续执行但无串行保证（供复盘）")
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

def run_baseline_comparison(project_root, ref, timeout) -> dict:
    """在基线 ref 的临时 worktree 跑同一套件，与当前结果做失败集合差异归类。

    Returns: {"ref", "baseline_failures", "baseline_rc",
              "baseline_timed_out", "classification", "hanging"}。
    """
    import subprocess as sp
    with tempfile.TemporaryDirectory(prefix="fenix-baseline-") as tmp:
        wt = Path(tmp) / "baseline_wt"
        add = sp.run(["git", "worktree", "add", "--detach", str(wt), ref],
                     cwd=str(project_root), capture_output=True, text=True)
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
            # 按真实运行结果归类（部分测试跳过时不影响失败集合）。
            baseline = run_suite(
                wt, timeout=min(BASELINE_TIMEOUT_SECONDS, timeout * 2))
            failed = collect_failed_tests(
                baseline.get("stderr", ""), baseline.get("stdout", ""))
            classification = (classify_outcome([], failed)
                              if not baseline.get("timed_out")
                              else "baseline-hang")
            return {
                "ref": ref,
                "baseline_failures": failed,
                "baseline_rc": baseline.get("returncode"),
                "baseline_timed_out": baseline.get("timed_out"),
                "classification": classification,
                "hanging": baseline.get("hanging_test"),
            }
        finally:
            sp.run(["git", "worktree", "remove", "--force", str(wt)],
                   cwd=str(project_root), capture_output=True, text=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="有界全量套件入口（fix-run-hang-amplification）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help=f"硬超时秒数（默认 {DEFAULT_TIMEOUT_SECONDS}）")
    parser.add_argument("--baseline", type=str, default=None,
                        help="基线 ref（git rev/分支）：在基线临时 worktree 跑同一套件，"
                             "输出两侧失败集合差异并给出存量/引入归类")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 输出汇总（供脚本消费）")
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

    os.chdir(project_root)
    lock = SuiteLock(project_root)

    with lock:
        current = run_suite(project_root, timeout=args.timeout)

    result = {
        "timed_out": current.get("timed_out"),
        "hang_test": current.get("hanging_test"),
        "exit_code": current.get("exit_code"),
        "elapsed_seconds": current.get("elapsed_seconds"),
    }

    if args.baseline:
        base = run_baseline_comparison(project_root, args.baseline, args.timeout)
        current_failed = collect_failed_tests(
            current.get("stderr", ""), current.get("stdout", ""))
        if current.get("timed_out"):
            classification = "current-hang"
            result["classification"] = "当前套件挂起（无完整失败集合对比）"
        else:
            classification = classify_outcome(current_failed, base["baseline_failures"])
            result["classification"] = classification
            result["current_failures"] = current_failed
            result["baseline_failures"] = base["baseline_failures"]
            result["baseline_ref"] = args.baseline
            # 按 spec：混合情形 MUST 判为存在本次引入回归（分类文案已体现）。
            if classification not in ("pass（全绿）", "存量"):
                result["verdict"] = "本次引入回归"
        print(f"\n[run_full_suite] 基线对比 ref={args.baseline} "
              f"→ {result['classification']}")
        if current_failed:
            print("[run_full_suite] 当前失败清单:")
            for f in current_failed:
                print(f"  FAILED {f}")
        if base["baseline_failures"]:
            print("[run_full_suite] 基线失败清单:")
            for f in base["baseline_failures"]:
                print(f"  BASELINE_FAILED {f}")

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