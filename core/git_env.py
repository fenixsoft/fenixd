"""git_env.py — 推送 git 子进程环境与凭证单源解析器。

fix-push-credential-env-and-retry-rearm 1.1（design D1）：推送车道的 git
子进程不再裸继承 daemon 进程环境——systemd 承载的 daemon env 无 ``HOME``
时 git 找不到 ``~/.git-credentials``/``~/.gitconfig``（2026-11-09 cloud-phone
事故实证 ``could not read Username`` / ``fatal: $HOME not set``），凭证只剩
remote URL 内嵌 token 一条腿。本模块为 ``_git_push_ref``（engine 推送）与
启动凭证自检（fenixd）两个消费点提供同一套判定，防双源漂移：

- HOME 三级解析：进程 env 非空 ``HOME`` → ``pwd.getpwuid(uid).pw_dir`` →
  配置 ``pm.push.credential_home``（可选覆盖）；前两级经 pal.home_dir
  单源（platform-abstraction E 组，W3 起转发，公开行为不变）；
- 产出显式注入版子进程 env（``process_env``）；
- credential helper 文件路径解析（默认解析后 HOME 下 ``.git-credentials``，
  配置 ``pm.push.credential_file`` 覆盖；显式置空字符串关断兜底）。

三级皆不可用时不注入 HOME（行为回退现状）且不抛异常——解析器逐级
fail-open，由启动自检就该状态发 WARNING 告警。
"""

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from core.platform import api as pal

# 模块级裸 WARNING 通道（core/ 既有先例：archive_commit / proc_utils 等），
# 用于解析层 fail-closed 降级留痕——daemon 注入式 logger 仅消费点可达。
logger = logging.getLogger("fenixd.git_env")

# 既有测试缝（零修改契约）：test_git_env 以 monkeypatch.setattr(ge.pwd,
# "getpwuid", ...) 打桩——此处与 pal 后端（linux.py）引用同一份共享 pwd
# 模块对象，桩随 pal.home_dir 的模块属性读取生效。经 sys.modules 取引用
# 而非 ``import pwd``：core/ 侧该词面的唯一豁免位在 core/platform/linux.py
# （6.1 守卫）。pal 导入链已加载 linux 后端，Linux 恒非 None。
pwd = sys.modules.get("pwd")

# credential helper 配置串（design D2）：helper 值内的 ``--file=`` 属
# credential.helper 配置串，git 按空白切分为 helper 子参数——argv 侧 MUST
# 保持单元素（见 credential_helper_args）。
CREDENTIAL_HELPER_CONFIG = "credential.helper=store"
DEFAULT_CREDENTIAL_FILE_NAME = ".git-credentials"

# 配置键（proposal Impact）：缺省不写＝默认解析序/默认凭证文件。
CFG_CREDENTIAL_HOME = "pm.push.credential_home"
CFG_CREDENTIAL_FILE = "pm.push.credential_file"


@dataclass
class GitEnv:
    """resolve_git_env 产出：HOME、注入版子进程 env 与凭证文件路径。

    resolved_home 为 None 表示三级解析全空（不注入 HOME，行为回退现状）；
    credential_file 为 None 表示 helper 兜底关断（配置显式置空字符串，或
    解析后 HOME 不可用且未配置覆盖路径）。
    """

    resolved_home: str | None
    process_env: dict
    credential_file: str | None


def _resolve_home(config, env: dict) -> str | None:
    """HOME 三级解析（design D1 解析序）：env → pwd → 配置覆盖。

    任一级拿到非空值即返回（``~`` 形态经 expanduser 展开）；级内异常
    （pwd 条目缺失、配置读取异常）fail-open 落到下一级；三级皆空返回 None。

    前两级（env 非空 HOME → pwd 条目）W3 起经 pal.home_dir 单源（E 组
    平移，判定口径逐位等价）；配置覆盖级属业务语义留本模块。
    """
    resolved = pal.home_dir(env)
    if resolved:
        return resolved
    try:
        from core.config import ConfigLoader

        cfg_home = ConfigLoader.get(config, CFG_CREDENTIAL_HOME, None)
        if isinstance(cfg_home, str) and cfg_home.strip():
            return os.path.expanduser(cfg_home)
    except Exception:  # noqa: BLE001 — 配置读取异常不中断解析链
        pass
    return None


def resolve_git_env(config=None, env=None) -> GitEnv:
    """推送 git 子进程环境与凭证路径单源解析。

    Args:
        config: daemon 配置 dict（None 合法——跳过配置级，仅 env/pwd 解析）。
        env: 参与解析的进程 env（缺省 ``os.environ``；测试注入用）。

    Returns:
        GitEnv：resolved_home（三级解析结果，可 None）、process_env（env
        拷贝；resolved_home 可用时注入/覆盖 ``HOME`` 键，不可用时原样拷贝
        不注入）、credential_file（凭证文件路径；配置显式置空字符串或无法
        解析时为 None＝helper 兜底关断）。

    本函数不触碰文件系统上的凭证文件本身（不创建、不改写）——存在性判定
    是消费点（credential_helper_args / 启动自检）的职责，避免解析器产生
    「有凭证」假象（spec：凭证文件缺席不产生假象）。
    """
    if env is None:
        env = os.environ
    resolved_home = _resolve_home(config, env)
    process_env = dict(env)
    if resolved_home:
        process_env["HOME"] = resolved_home

    # credential_file 解析：配置显式置空字符串 → None（关断兜底，design
    # Risks「配置显式置空字符串可关断兜底」）；配置非空 → 该路径（expanduser）；
    # 未配置 → 解析后 HOME 下的默认文件名（HOME 不可用 → None）。
    credential_file = None
    cfg_file = None
    try:
        from core.config import ConfigLoader

        cfg_file = ConfigLoader.get(config, CFG_CREDENTIAL_FILE, None)
    except Exception:  # noqa: BLE001 — 配置读取异常按未配置处理
        cfg_file = None
    if isinstance(cfg_file, str):
        if cfg_file.strip():
            credential_file = os.path.expanduser(cfg_file)
        # 置空字符串：保持 None（显式关断）
    elif resolved_home:
        credential_file = str(Path(resolved_home) / DEFAULT_CREDENTIAL_FILE_NAME)
    return GitEnv(
        resolved_home=resolved_home if resolved_home else None,
        process_env=process_env,
        credential_file=credential_file,
    )


def credential_helper_args(git_env: GitEnv) -> list:
    """凭证文件在场时的 git credential helper 追加参数（design D2）。

    返回 ``["-c", "credential.helper=store --file=<abs>"]``——helper 参数
    MUST 为单一 argv 元素：helper 值内的 ``--file=`` 属 credential.helper
    配置串，git 按空白切分为 helper 子参数；拆成两个元素会让 ``--file=``
    被 git 解析为顶层未知选项，推送必败。解析路径不存在时返回 ``[]``——
    不追加参数，避免 git 静默创建空凭证文件造成「有凭证」假象（spec）。

    路径含空白字符（``\\s``：空格/制表符等）时 fail-closed 返回 ``[]`` 并
    发 WARNING：git 对 credential.helper 值的空白切分**无引号转义机制**
    （无法在配置串内表达含空白的路径），直接内插会让 ``--file=`` 的路径
    从空白处截断成两个 helper 子参数，credential-store 收到错误路径、推送
    凭证读取静默失败。拒绝追加即回退既有无 helper 腿（URL 内嵌 token 兜底），
    不产生「路径可用却推不动」的无指向报错。
    """
    cred = git_env.credential_file if git_env else None
    if not cred:
        return []
    if re.search(r"\s", cred):
        logger.warning(
            "推送凭证文件路径含空白字符，git credential.helper 配置串按空白"
            "切分且无引号转义机制，无法表达该路径；拒绝追加 helper 参数，"
            "推送回退 URL 内嵌 token 单腿。请改用无空白路径"
            "（pm.push.credential_file / credential_home）： %s",
            cred,
        )
        return []
    try:
        if not Path(cred).is_file():
            return []
    except OSError:
        return []
    return ["-c", f"{CREDENTIAL_HELPER_CONFIG} --file={cred}"]
