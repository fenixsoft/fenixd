"""fs_utils.py — 文件产物原子写公共助手。

verify_report 与 verify_scenarios 此前各持一份近乎相同的 ``_atomic_write``
拷贝（注释互称「同款」）且权限策略已漂移（code-review item 8b26fd7980ce）：
本模块收口为单一实现，mkstemp 唯一临时文件 + fsync + os.replace 的纪律一处
维护，两模块曾有差异的权限口径以参数显式表达：

- ``inherit_existing_mode=True``（verify_report 口径）：替换**既有**文件时
  继承其原权限——运维刻意收紧为 0600 的产物不被框架重合成静默放宽；
  **新**文件放宽到 0644，与常规 write_text 的 umask 缺省一致。
- ``inherit_existing_mode=False``（verify_scenarios 口径，缺省）：无条件
  chmod 0644，产物对非 root 辅助进程/人工其它账号可读。

另收口跨模块共用的 flock 互斥原语 ``with_file_lock``：evolution 与
self_review 写 ``todo.md`` 须同一把锁，原语原为 evolution 私有
``_with_lock`` 被外部 import，提升于此公共归属（item 1a8a9328767b）。

只依赖 stdlib，任何 core 模块均可安全导入。
"""

import fcntl
import logging
import os
import tempfile
from pathlib import Path

_logger = logging.getLogger("fenixd.fs_utils")


def atomic_write_text(path, content: str, inherit_existing_mode: bool = False) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子写（单点实现）。

    固定 ``<name>.tmp`` 临时名在并发写同一目标时会互相截断：进程 A 完成
    write_text 后、进程 B 在同一 .tmp 上截断改写，随后任一方的 replace 都
    可能把截断内容落盘。唯一临时名保证并发写不可能产生截断产物——rename
    前目标不变，rename 后内容完整。

    mkstemp 以 0600 建临时文件，rename 前按 ``inherit_existing_mode`` 修复
    权限（语义见模块 docstring）；chmod 失败不阻断写入（权限是尽力而为的
    附属属性）。

    rename 后尽力而为 fsync 父目录（code-review item f19b8ef57ce6）：fsync
    临时文件只保证文件内容持久，目录项改动（rename 本身）须 fsync 父目录
    才在整机断电/内核崩溃后有持久化保证，否则可能出现「写成功但重启后回到
    旧内容」。进程被 kill 的场景 page cache 仍在、无影响；目录 fsync 失败
    不阻断写入（与 chmod 同为尽力而为的附属纪律）。
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            if inherit_existing_mode:
                # 单次 os.stat，以 FileNotFoundError 区分「不存在→0644」与
                # 「其他 OSError→跳过 chmod 留 debug 日志」；先 exists() 再
                # stat() 的双探测在两步间目标被并发删除时会连带跳过 chmod，
                # 产物静默保持 0600（item 7b94b65d0f0c）
                try:
                    mode = os.stat(path).st_mode & 0o777
                except FileNotFoundError:
                    mode = 0o644
            else:
                mode = 0o644
            os.chmod(tmp_path, mode)
        except OSError as exc:
            _logger.debug("atomic_write_text: best-effort chmod skipped for %s: %s", path, exc)
        os.replace(tmp_path, path)
        # 尽力而为 fsync 父目录（rename 目录项持久化，item f19b8ef57ce6）；
        # 失败不阻断主流程
        try:
            dir_fd = os.open(str(parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def with_file_lock(path: Path, fn):
    """在 path 同目录的 ``.<name>.lock`` 文件上加 flock 互斥后执行 fn。

    调用方（daemon 主线程 / dashboard server 线程）可能同时写同一存储；
    flock 提供跨进程与跨线程互斥（与 StateMachine.write_all 同范式）。
    MUST NOT 在 fn 内再次加同一把锁（同进程二次 flock 自阻塞）。

    原 evolution 私有 ``_with_lock``，self_review 三处跨模块 import 以共用
    todo.md 锁，提升于此公共归属（item 1a8a9328767b）；evolution 侧以
    ``as _with_lock`` 别名引用，内部调用面与锁文件布局不变。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
