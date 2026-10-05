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

只依赖 stdlib，任何 core 模块均可安全导入。
"""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path, content: str, inherit_existing_mode: bool = False) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子写（单点实现）。

    固定 ``<name>.tmp`` 临时名在并发写同一目标时会互相截断：进程 A 完成
    write_text 后、进程 B 在同一 .tmp 上截断改写，随后任一方的 replace 都
    可能把截断内容落盘。唯一临时名保证并发写不可能产生截断产物——rename
    前目标不变，rename 后内容完整。

    mkstemp 以 0600 建临时文件，rename 前按 ``inherit_existing_mode`` 修复
    权限（语义见模块 docstring）；chmod 失败不阻断写入（权限是尽力而为的
    附属属性）。
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
                mode = os.stat(path).st_mode & 0o777 if path.exists() else 0o644
            else:
                mode = 0o644
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
