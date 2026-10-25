#!/usr/bin/env python3
"""run_full_suite.py — 有界全量套件入口（fix-run-hang-amplification D3 / 3.1-3.2 / 4.3）。

背景：裸 ``pytest tests/ -q`` 在存量死循环处挂起时，实现 run 单次等待可超过 1 小时、
I/O 涨至 44-60GB（fix-root-init-import-shadow 事故）。框架能否给出「挂在哪个测试」
直接决定该 run 是数分钟收口还是数小时空转。

本入口：
- 以硬超时运行全量套件，启用 faulthandler（``-p faulthandler
  -o faulthandler_timeout=<N>``，pytest 9 起 CLI 参数 ``--faulthandler-timeout``
  已移除、改为 ini 配置项），挂起时打印各线程栈；
- 超时/挂起时中止子进程**组**（SIGTERM 优雅窗口后对整组补发 SIGKILL，孙进程
  一并中止）并输出**挂起测试标识**（faulthandler 栈顶用例）；
- 子进程输出落盘匿名临时文件（另伴随生尾窗文件），回读与磁盘占用双有界
  （回读留尾部窗口，收割线程周期把末尾窗口快照到伴生文件后截断主文件回收
  磁盘，失控输出不再无界涨盘、尾部证据不因收割丢失）；
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
import threading
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

# 子进程输出回读上限（每流字节，code-review item 4865784b5be5）：正常套件输出
# （pytest -q 全量，通常数 MB）远低于该值、原样完整回读；失控输出（死循环 print
# 等，同 docstring 所述 I/O 事故形态）只回读尾部——FAILED 摘要与 faulthandler
# 栈集中在输出后段，尾部足以支撑提取，父进程内存占用恒有上界。
OUTPUT_READBACK_LIMIT_BYTES = 64 * 1024 * 1024

# 输出临时文件的磁盘收割窗口（code-review item 77429f359c2d）：子进程对临时
# 文件的写入量本身不受限，失控输出在硬超时窗口内可持续涨盘。收割线程
# （_drain_output_disk）周期把文件**末尾**该窗口经 os.pread 快照到伴生尾窗
# 文件后再截断主文件（POSIX ftruncate 只能保留头部、就地截断恰丢最新写入
# 的尾部，而 FAILED 摘要与 faulthandler 栈集中在输出后段，故先快照后截断）：
# 被截区间留稀疏洞、不占实际磁盘块（tmpfs 亦不占页），主文件磁盘占用上界
# ≈ 窗口 + 单个轮询周期内的新增写入，伴生文件 ≤ 窗口。窗口 ≥ 回读上限
# （4 倍冗余），_read_back_output 拼接「伴生尾窗 + 截断后新增」的尾部回读
# 不受影响。
OUTPUT_DISK_KEEP_BYTES = 4 * OUTPUT_READBACK_LIMIT_BYTES

# 以当前解释器起子进程（``sys.executable -m pytest``，与 bin/test_for.py 的
# _build_pytest_cmd 同形态内联，code-review item a3b6cb6e85c5）：裸 "pytest"
# 经 PATH 解析，调用方经某虚拟环境 python3 运行本脚本而 PATH 上的 pytest 属
# 另一环境时，套件会跑在与框架 python 不同的解释器/插件集下。
PYTEST_BASE_ARGS = [
    sys.executable,
    "-m",
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
    显式覆盖。环境变量校验取值域 [31000, 65535-段宽]（下界对齐 pid 派生段，
    上界含段宽余量；越界同按非法值回退派生，code-review item 28562fe24bb9）。
    """
    env_base = os.environ.get("FENIX_SUITE_PORT_BASE")
    if env_base:
        try:
            val = int(env_base)
            # 下界对齐 pid 派生段（code-review item 28562fe24bb9）：1-1023 的
            # 特权端口段在非 root 环境绑定 EACCES、报错落在具体用例内部难以
            # 归因到端口段配置——显式覆盖值低于派生段下界时同按非法值回退
            # pid 派生（上界校验含段宽余量不变）。
            if 31000 <= val <= 65535 - SUITE_PORT_SEGMENT_WIDTH:
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
          File "/repo/tests/test_x.py", line 42 in test_hang
          ...
    注意 CPython faulthandler 的帧格式是 ``line N in func``（``in`` 前无逗号，
    本机实测 ``File "<string>", line 4 in <module>``）——与 traceback 模块的
    ``line N, in func`` 不同，正则对逗号做可选兼容（code-review item
    ec2bacdabe00：此前误按带逗号格式匹配，真实挂起场景恒解析为空）。
    faulthandler 会为**每个线程**各打一份栈，且 dump 的首个 File 帧常是
    主线程或 pytest/faulthandler 内部帧而非挂起用例——盲取首帧会把调试
    引向完全无关的方向。故优先取**路径在 tests/ 下**的首个 File 帧（自然
    排除 pytest/pluggy 等内部帧），无 tests/ 帧再回退首帧
    （compat：路径可相对）。

    无匹配返回 None（不误报）。
    """
    first = None
    for line in (stderr or "").splitlines():
        m = re.search(r'File "([^"]+)", line \d+,? in (.+)', line)
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


def _read_back_output(
    stream, limit: int = OUTPUT_READBACK_LIMIT_BYTES, tail_stream=None, tail_start=None,
) -> str:
    """回读子进程输出流并解码为文本；超出上限只保留尾部 limit 字节。

    输出经临时文件落盘（见 run_command），回读设上限保证父进程内存有界：
    FAILED 摘要与 faulthandler 栈集中在输出后段，尾部截取不损害提取。
    截断起点可能落在多字节字符中间，``errors="replace"`` 容忍。

    tail_stream（伴生尾窗文件，见 _drain_output_disk）持有主文件最近 keep
    字节的快照、tail_start 为最近一次快照边界（主文件该偏移之后是收割后的
    新增写入）时，回读取「伴生尾窗 + 主文件边界之后新增」拼接后的尾部——
    与未收割时的尾部窗口语义等价，末端证据不因收割丢失；只取边界之后是为
    避免边界前的头部/稀疏洞与伴生尾窗重复入文。无伴生（收割未触发）时
    退化为直接读主文件尾部，语义与既有行为一致。
    """
    parts = []
    total = 0
    if tail_stream is not None:
        tsize = os.fstat(tail_stream.fileno()).st_size
        if tsize > 0:
            tail_stream.seek(max(0, tsize - limit))
            parts.append(tail_stream.read(limit))
            total += tsize
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if tail_start is not None and total:
        start = max(tail_start, size - limit)  # limit 封顶防单周期巨量新增
        total += max(0, size - tail_start)
    else:
        start = max(0, size - limit)
        total += size
    stream.seek(start)
    parts.append(stream.read(limit))
    data = b"".join(parts)[-limit:]
    text = data.decode("utf-8", errors="replace")
    if total > limit:
        text = f"[run_full_suite] 子进程输出超过 {limit} 字节回读上限，仅保留尾部\n" + text
    return text


def _copy_tail_snapshot(fd, tail_file, size: int, keep: int, chunk=1024 * 1024) -> None:
    """把主文件末尾 [max(0, size-keep), size) 拷贝到伴生尾窗文件（整窗重写）。

    读侧用 ``os.pread``（独立偏移，不触碰子进程共享的写偏移，不干扰追加写），
    写侧伴生文件只由收割线程与停机后的回读访问，整窗重写（seek(0)+truncate(0)
    后覆写）无并发冲突。
    """
    start = max(0, size - keep)
    tail_file.seek(0)
    tail_file.truncate(0)
    pos = start
    while pos < size:
        block = os.pread(fd, min(chunk, size - pos), pos)
        if not block:
            break
        tail_file.write(block)
        pos += len(block)
    # 立即冲刷：回读经 os.fstat 判断伴生文件是否持有尾窗，缓冲未落盘时
    # st_size 恒为 0，尾窗会被整段跳过（实测探针抓到的缺陷）。
    tail_file.flush()


def _drain_output_disk(
    fds, stop_event, keep=OUTPUT_DISK_KEEP_BYTES, poll_seconds=1.0,
    tail_files=None, snapshots=None,
) -> None:
    """收割线程体：周期把输出临时文件末尾 keep 窗口快照到伴生文件后截断主
    文件，回收磁盘（有界收割且不丢尾部证据）。

    子进程（含逃过 killpg 的游离孙进程）对输出临时文件的写入量本身不受限，
    本线程周期收割使失控输出的磁盘占用有界（内存/磁盘双有界）。POSIX
    ftruncate 只能保留文件**前** size-keep 字节（本机实测：截断后首字节仍为
    旧数据、子进程续写偏移不回退、被截区间成稀疏洞）——就地截断丢弃的恰是
    最新写入的末端，而 FAILED 摘要与 faulthandler 栈集中在输出后段，正是
    不能丢的证据。故每轮先经 _copy_tail_snapshot 把末尾 keep 字节存入伴生
    尾窗文件（tail_files，与 fds 一一对应），快照落定并记入 snapshots
    （fd → 截断前 size，供 _read_back_output 拼接边界之后的新增写入）后才
    ftruncate 主文件：尾部块已存伴生、丢弃安全，头部保留为稀疏洞夹旧数据、
    不占实际块，磁盘占用仍有界（主文件 ≈ 窗口 + 单轮询周期新增，伴生 ≤ 窗口）。

    顺序纪律：先快照、后截断——任一步异常直接停机（fail-open 退化为「磁盘
    维度无界」的现状，不干扰主流程），绝不出现「截断了却没快照」的证据丢失。
    tail_files/snapshots 缺省 None 时退化为就地截断（无伴生文件的调用方，
    不保留尾部窗口之外的语义承诺）。
    """
    while not stop_event.wait(poll_seconds):
        try:
            for i, fd in enumerate(fds):
                size = os.fstat(fd).st_size
                if size <= keep:
                    continue
                if tail_files is not None:
                    _copy_tail_snapshot(fd, tail_files[i], size, keep)
                    if snapshots is not None:
                        snapshots[fd] = size
                os.ftruncate(fd, size - keep)
        except Exception:
            return


def run_command(cmd, timeout, cwd, env=None) -> tuple:
    """运行命令并在超时时中止（进程组 SIGTERM→SIGKILL 兜底）；返回 (rc, stdout, stderr, timed_out)。

    子进程以独立进程组启动（``start_new_session=True``）：超时先对整组发
    SIGTERM 给短暂优雅窗口，宽限期结束再对整组**无条件**补发 SIGKILL（不
    论组长是否已退出——组长通常即刻退出，SIGKILL 若只挂在 wait 超时分支，
    组内忽略 SIGTERM 的幸存孙进程会逃过清扫；组已空时补发是无害 no-op）
    ——pytest 拉起的孙进程（v2 dev server、daemon 集成类测试等）一并中止，
    不留孤儿继续占端口/内存。进程已退出（ProcessLookupError）等 killpg
    失败静默吞掉。
    超时 kill 后仍读取已产出的输出（faulthandler 栈对挂起定位是关键证据）。

    输出经系统匿名临时文件落盘而非管道（code-review item 4865784b5be5）：
    失控输出（死循环 print 等）只涨文件不涨内存，回读另有上限
    （_read_back_output）——管道方案下 communicate 全量缓冲可在硬超时窗口
    内被撑到 OOM，且游离孙进程持有管道写端会让 EOF 迟迟不到。收割线程
    （_drain_output_disk）另把临时文件末尾窗口快照到伴生尾窗文件后周期截断
    主文件，磁盘占用同样有界且尾部证据不因收割丢失（code-review item
    77429f359c2d）。收割纪律与 bin/test_for.run_bounded 同口径：SIGTERM/
    SIGKILL 阶梯后无条件 wait 收尾，不留僵尸（code-review item 05c30167fbc9）。
    """
    # 匿名临时文件（系统临时目录、创建即 unlink、随 with 块关闭）：
    # 不经 .fenix/ 也不在系统 /tmp 留命名残留；游离孙进程逃过 killpg 时
    # 仍持继承 fd 继续写，只影响文件内容不影响本函数返回（不阻塞）。
    # 每流另伴随生尾窗文件（out_tail/err_tail）：收割线程把主文件末尾窗口
    # 快照于此再截断主文件，回读据此拼接尾部（见 _drain_output_disk /
    # OUTPUT_DISK_KEEP_BYTES）——子进程写入量本身不受限，磁盘维度由收割
    # 有界化，且最新写入（FAILED 摘要/faulthandler 栈）不因截断丢失。
    with tempfile.TemporaryFile("w+b") as out_file, tempfile.TemporaryFile("w+b") as err_file, \
            tempfile.TemporaryFile("w+b") as out_tail, tempfile.TemporaryFile("w+b") as err_tail:
        proc = subprocess.Popen(
            cmd,
            stdout=out_file,
            stderr=err_file,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
        )
        # 有界收割（code-review item 77429f359c2d）：后台线程周期把输出临时
        # 文件末尾窗口快照到伴生尾窗文件后截断主文件回收磁盘（子进程写入量
        # 本身无上限）；线程起不来或中途异常均 fail-open 退化为磁盘维度无界
        # 的现状，不干扰主流程。snapshots 记录每流最近一次快照边界（fd →
        # 截断前 size），供回读拼接伴生尾窗与其后的新增写入。
        stop_drain = threading.Event()
        snapshots = {}
        drainer = None
        try:
            thread = threading.Thread(
                target=_drain_output_disk,
                args=([out_file.fileno(), err_file.fileno()], stop_drain),
                kwargs={"tail_files": [out_tail, err_tail], "snapshots": snapshots},
                daemon=True,
            )
            thread.start()
            drainer = thread
        except Exception:
            drainer = None
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # start_new_session=True ⇒ pgid==pid
            except OSError:
                pass  # 进程已退出，无需再中止
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # [fenix-ignore:58de4e6a75c9] 双文件同构阶梯系书面记录的既定取舍；抽共享助手属跨文件重构，待任一侧下次实际改动时再收敛
            # 宽限期结束无论组长是否已退出都对整组补发 SIGKILL（与
            # bin/test_for.run_bounded 同构）：组长通常即刻响应 SIGTERM 退出，
            # SIGKILL 若只留在 wait 超时分支，组内忽略 SIGTERM 的幸存孙进程
            # （及窗口期新拉起的子进程）会逃过清扫成为孤儿；组已空时 killpg
            # 抛 ProcessLookupError，静默吞掉（无害 no-op）。
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True ⇒ pgid==pid
            except OSError:
                pass  # 进程组已不存在
            try:
                proc.wait(timeout=10)  # 收割 SIGKILL 后的子进程，不留僵尸
            except subprocess.TimeoutExpired:
                pass
        # 回读前停机收割线程，避免快照/截断与下方回读竞争（set 立即生效，
        # join 兜足一个轮询周期余量；线程未启动/已退出时不执行；join 返回后
        # snapshots 不再被收割线程写入，读取无竞争）。
        stop_drain.set()
        if drainer is not None:
            drainer.join(timeout=5)
        # join 超时时收割线程可能仍停在 _copy_tail_snapshot 的整窗重写中
        # （truncate(0) 后逐块覆写，窗口上限 OUTPUT_DISK_KEEP_BYTES，慢盘/
        # 高负载下可超 5s）——此时回读伴生尾窗会与该重写并发，读到撕裂尾部。
        # 放弃伴生路径（tail_stream/tail_start 均置 None），退化为直接回读主
        # 文件尾部（语义与未收割一致；主文件侧与残余 ftruncate 并发至多短读，
        # 不产生撕裂内容），与收割线程「起不来/中途异常均 fail-open 退化、不
        # 干扰主流程」的既定纪律同口径；线程为 daemon，不再等待，随进程退出
        # 回收。join 正常返回（含线程未启动）时行为与原先完全一致。
        read_tail = drainer is None or not drainer.is_alive()
        out = _read_back_output(
            out_file,
            tail_stream=out_tail if read_tail else None,
            tail_start=snapshots.get(out_file.fileno()) if read_tail else None,
        )
        err = _read_back_output(
            err_file,
            tail_stream=err_tail if read_tail else None,
            tail_start=snapshots.get(err_file.fileno()) if read_tail else None,
        )
        return (None if timed_out else proc.returncode), out, err, timed_out


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
    # 提取输入是 run_command 的回读文本：回读上限（64MB）远大于下方展示截尾，
    # 常规套件即完整输出；仅输出超限的失控场景降级为尾部尽力提取（此时全量
    # 已不可得，内存有界优先，见 _read_back_output）。
    # stdout/stderr 键仍按截断保留（展示用途），完整失败集合经 failed_tests 键给出。
    failed_tests = collect_failed_tests(out, err)
    # 超时约定退出码 124（与 timeout(1) 惯例一致），正常按 pytest 实际退出码。
    # 负 rc = 进程被信号终止（如 OOM killer 的 SIGKILL → -9）：按 shell 惯例
    # 归一为 128+signum（code-review item a9c0cbc6eef8）——负值原样经
    # sys.exit 会按 C 惯例对 256 取模回绕成无关退出码（-9 → 247），进程
    # 实际退出码与 JSON 文档的 exit_code 将不一致；归一后两者同值。
    # returncode 键保留原始负值（含基线侧）供诊断。
    if timed_out:
        exit_code = 124
    elif rc is None:
        exit_code = 1
    elif rc < 0:
        exit_code = 128 + abs(rc)
    else:
        exit_code = rc
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
            # acquired 分支含两种情形：首次 flock 即成功（wait≈0，无争抢）
            # 与阻塞等待后拿到锁（曾与其他并发套件争抢）；以 wait 秒数区分。
            self._log(f"[run_full_suite] 主机级锁获取成功（wait={waited}s）")
        else:
            self._log(
                f"[run_full_suite] 主机级锁等待超时（>{LOCK_WAIT_TIMEOUT_SECONDS}s），"
                f"继续执行但无串行保证，回退 pid 唯一 basetemp（供复盘）"
            )
        return self

    def __exit__(self, *exc):
        try:
            try:
                if self._file is not None:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except OSError:
                # 解锁失败（fd 已失效等罕见情形）不得连坐跳过 close——
                # 句柄仍须回收，否则文件描述符泄漏到进程退出。
                pass
            if self._file is not None:
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
              "baseline_timed_out", "classification", "hanging_test"}。
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
                "hanging_test": None,
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
                "hanging_test": baseline.get("hanging_test"),
            }
        finally:
            remove = subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
            )
            # 清理失败必留痕：静默吞掉会残留 .git/worktrees/baseline_wt 悬挂
            # 元数据（需 git worktree prune 才能清理），后续枚举与排查无从得知。
            if remove.returncode != 0:
                log(
                    "[run_full_suite] 基线 worktree 清理失败（可 git worktree prune）: "
                    f"{(remove.stderr or remove.stdout)[-300:]}"
                )


def _log_to_stderr(message: str) -> None:
    """--json 模式的日志通道：日志行走 stderr，stdout 只输出最终 JSON 文档。"""
    print(message, file=sys.stderr)


def _positive_int(value):
    """--timeout 取值校验（code-review item 084b705344b2）：仅接受正整数。

    0/负数传入 run_command 后 wait(timeout<=0) 立即抛 TimeoutExpired，
    套件一个用例未跑即被整组 SIGKILL 并误归为「挂起」。与
    fenix_dashboard._port_type 同口径：argparse 校验失败自动以退出码 2 报参数错误。
    """
    try:
        timeout = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"无效超时秒数: {value!r}")
    if timeout < 1:
        raise argparse.ArgumentTypeError(
            f"超时秒数 {timeout} 必须为正整数（0/负数会瞬时超时误报挂起）"
        )
    return timeout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="有界全量套件入口（fix-run-hang-amplification）")
    parser.add_argument(
        "--timeout",
        type=_positive_int,
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
        "hanging_test": current.get("hanging_test"),
        "exit_code": current.get("exit_code"),
        "elapsed_seconds": current.get("elapsed_seconds"),
        # 失败清单对非基线模式同样透出（code-review item 9df86151381a）：
        # run_suite 已在截断前自完整输出提取 failed_tests，--json 消费方
        # 不必重新解析套件输出。键名与基线分支对齐（基线分支下方对同键
        # 的重复赋值同源同值，行为不变）。
        "current_failures": current.get("failed_tests", []),
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
