"""tests/test_git_env.py — fix-push-credential-env-and-retry-rearm 任务 1.2

core/git_env.py 单源解析器：
- HOME 三级解析序：进程 env 非空 HOME → pwd.getpwuid(uid).pw_dir → 配置
  ``pm.push.credential_home``；
- process_env 注入语义（有 HOME 注入/覆盖、三级全空原样拷贝不注入）；
- credential_file：默认 HOME 下 ``.git-credentials``、配置覆盖、显式置空
  字符串关断；
- 解析全程不触碰文件系统上的凭证文件（无文件不产生假路径，不抛异常）。
"""
import os

import pytest

from core.git_env import (
    DEFAULT_CREDENTIAL_FILE_NAME,
    GitEnv,
    credential_helper_args,
    resolve_git_env,
)


# ── HOME 三级解析 ─────────────────────────────────────────────────────────


def test_env_home_taken_directly():
    """进程 env 有非空 HOME → 直取，不查 pwd。"""
    git_env = resolve_git_env(config=None, env={"HOME": "/custom/home", "A": "1"})
    assert git_env.resolved_home == "/custom/home"
    assert git_env.process_env["HOME"] == "/custom/home"
    # 其余 env 键原样保留（env 拷贝语义）
    assert git_env.process_env["A"] == "1"


def test_no_env_home_falls_back_to_pwd(monkeypatch):
    """env 无 HOME → 走 pwd.getpwuid(uid).pw_dir。"""
    monkeypatch.delenv("HOME", raising=False)

    class _FakePwd:
        pw_dir = "/pwd/home"

    import core.git_env as ge

    monkeypatch.setattr(ge.pwd, "getpwuid", lambda uid: _FakePwd())
    git_env = resolve_git_env(config=None, env={"PATH": "/usr/bin"})
    assert git_env.resolved_home == "/pwd/home"
    assert git_env.process_env["HOME"] == "/pwd/home"


def test_empty_env_home_not_taken(monkeypatch):
    """env HOME 为空字符串视同缺失 → 走 pwd（非空判定）。"""
    import core.git_env as ge

    class _FakePwd:
        pw_dir = "/pwd/home"

    monkeypatch.setattr(ge.pwd, "getpwuid", lambda uid: _FakePwd())
    git_env = resolve_git_env(config=None, env={"HOME": ""})
    assert git_env.resolved_home == "/pwd/home"


def test_pwd_failure_falls_back_to_config(monkeypatch):
    """pwd 解析失败（KeyError）→ 配置 pm.push.credential_home 覆盖。"""
    monkeypatch.delenv("HOME", raising=False)

    import core.git_env as ge

    def _raise(uid):
        raise KeyError(uid)

    monkeypatch.setattr(ge.pwd, "getpwuid", _raise)
    config = {"pm": {"push": {"credential_home": "/config/home"}}}
    git_env = resolve_git_env(config=config, env={"PATH": "/usr/bin"})
    assert git_env.resolved_home == "/config/home"
    assert git_env.process_env["HOME"] == "/config/home"


def test_all_three_levels_empty_safe_fallback(monkeypatch):
    """三级全空 → resolved_home=None、env 原样拷贝不注入 HOME、不抛异常。"""
    monkeypatch.delenv("HOME", raising=False)

    import core.git_env as ge

    def _raise(uid):
        raise KeyError(uid)

    monkeypatch.setattr(ge.pwd, "getpwuid", _raise)
    git_env = resolve_git_env(config=None, env={"PATH": "/usr/bin"})
    assert git_env.resolved_home is None
    assert "HOME" not in git_env.process_env
    assert git_env.process_env["PATH"] == "/usr/bin"


def test_resolve_never_raises_on_config_exception(monkeypatch):
    """配置读取异常（结构畸形抛错）→ fail-open 落到下一级，不抛异常。"""
    monkeypatch.delenv("HOME", raising=False)

    import core.git_env as ge

    class _ExplodingConfig(dict):
        def get(self, key, default=None):
            raise RuntimeError("config backend down")

    def _raise(uid):
        raise KeyError(uid)

    monkeypatch.setattr(ge.pwd, "getpwuid", _raise)
    # ConfigLoader.get(config, ...) 对非 dict config 直接返回 default；
    # 这里用会抛错的自定义 dict 覆盖 get，验证 except 分支兜底
    git_env = resolve_git_env(
        config=_ExplodingConfig({"pm": {"push": {"credential_home": "/x"}}}),
        env={"PATH": "/usr/bin"},
    )
    assert isinstance(git_env, GitEnv)
    assert git_env.resolved_home is None


# ── credential_file 解析 ──────────────────────────────────────────────────


def test_credential_file_defaults_to_resolved_home(monkeypatch):
    """未配置覆盖 → 默认解析后 HOME 下 .git-credentials。"""
    import core.git_env as ge

    class _FakePwd:
        pw_dir = "/pwd/home"

    monkeypatch.setattr(ge.pwd, "getpwuid", lambda uid: _FakePwd())
    monkeypatch.delenv("HOME", raising=False)
    git_env = resolve_git_env(config=None, env={})
    assert git_env.credential_file == os.path.join("/pwd/home", DEFAULT_CREDENTIAL_FILE_NAME)


def test_credential_file_config_override(tmp_path, monkeypatch):
    """配置 pm.push.credential_file 覆盖默认路径（~ 展开）。"""
    target = tmp_path / "creds"
    config = {"pm": {"push": {"credential_file": str(target)}}}
    git_env = resolve_git_env(config=config, env={"HOME": "/h"})
    assert git_env.credential_file == str(target)


def test_credential_file_explicit_empty_disables(monkeypatch):
    """配置显式置空字符串 → credential_file=None（helper 兜底关断）。"""
    config = {"pm": {"push": {"credential_file": ""}}}
    git_env = resolve_git_env(config=config, env={"HOME": "/h"})
    assert git_env.credential_file is None


def test_credential_file_none_when_home_unresolvable_and_unconfigured(monkeypatch):
    """HOME 三级全空且未配置覆盖 → credential_file=None（无假路径）。"""
    monkeypatch.delenv("HOME", raising=False)

    import core.git_env as ge

    def _raise(uid):
        raise KeyError(uid)

    monkeypatch.setattr(ge.pwd, "getpwuid", _raise)
    git_env = resolve_git_env(config=None, env={})
    assert git_env.credential_file is None


# ── 解析器不触碰文件系统 / helper 参数构造 ────────────────────────────────


def test_resolve_does_not_create_credential_file(monkeypatch, tmp_path):
    """解析路径不存在时不产生假路径（不 touch 文件系统）。"""
    home = tmp_path / "no-such-home"
    import core.git_env as ge

    class _FakePwd:
        pw_dir = str(home)

    monkeypatch.setattr(ge.pwd, "getpwuid", lambda uid: _FakePwd())
    monkeypatch.delenv("HOME", raising=False)
    git_env = resolve_git_env(config=None, env={})
    assert git_env.credential_file == str(home / DEFAULT_CREDENTIAL_FILE_NAME)
    assert not home.exists()  # 解析未创建目录/文件


def test_helper_args_absent_when_file_missing(tmp_path):
    """凭证文件缺席 → 不追加 helper 参数（空清单）。"""
    git_env = GitEnv(
        resolved_home=str(tmp_path),
        process_env={"HOME": str(tmp_path)},
        credential_file=str(tmp_path / DEFAULT_CREDENTIAL_FILE_NAME),
    )
    assert credential_helper_args(git_env) == []


def test_helper_args_single_argv_element_when_file_present(tmp_path):
    """凭证文件在场 → 单元素 -c helper 参数（MUST NOT 拆多元素）。"""
    cred = tmp_path / DEFAULT_CREDENTIAL_FILE_NAME
    cred.write_text("https://user:token@example.com\n", encoding="utf-8")
    git_env = GitEnv(
        resolved_home=str(tmp_path),
        process_env={"HOME": str(tmp_path)},
        credential_file=str(cred),
    )
    args = credential_helper_args(git_env)
    assert len(args) == 2
    assert args[0] == "-c"
    # helper 值内 --file= 属 credential.helper 配置串（单元素内空白切分）
    assert args[1] == f"credential.helper=store --file={cred}"


def test_helper_args_empty_when_credential_file_none():
    """credential_file=None（关断）→ 恒空参数清单。"""
    git_env = GitEnv(resolved_home="/h", process_env={"HOME": "/h"}, credential_file=None)
    assert credential_helper_args(git_env) == []


@pytest.mark.parametrize("bad_cred", [None, ""])
def test_helper_args_tolerates_missing_values(bad_cred):
    git_env = GitEnv(resolved_home="/h", process_env={}, credential_file=bad_cred)
    assert credential_helper_args(git_env) == []
