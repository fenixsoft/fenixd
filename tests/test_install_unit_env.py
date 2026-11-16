"""install_unit env 注入注册表形态与服务环境自检契约（任务 1.5，覆盖 6.1/6.2）。

D5/A7：AppEnvironmentExtra REG_MULTI_SZ 直写（read-modify-write 合并——
同键 K=V 覆盖、异键保留，install.md §8 手工服务 PATH 最小集不被整值替换
清除）；幂等重跑与安装完成路径服务环境自检（claude/git/python 服务 PATH
视角解析，缺失报 env_defect，ok 仍 True）。注册表面经 seam 替身测试
（winreg 仅 win32，Linux 消费方 fail-open）。
"""

import sys
import unittest.mock as mock

import pytest

from core.platform import win32 as w


# ── 6.1 read-modify-write 合并（纯函数面）────────────────────────────


class TestMergeServiceEnv:
    def test_same_key_overridden(self):
        out = w._merge_service_env(
            ["PATH=C:\\manual-minimal", "DSH_HOME=D:\\dsh"],
            {"PATH": "C:\\new-minimal"})
        assert out == ["DSH_HOME=D:\\dsh", "PATH=C:\\new-minimal"]

    def test_other_keys_preserved(self):
        # §8 手工 PATH 最小集/DSH_HOME 不得被整值替换清除
        out = w._merge_service_env(
            ["PATH=C:\\manual-minimal"], {"DSH_HOME": "D:\\dsh"})
        assert out == ["PATH=C:\\manual-minimal", "DSH_HOME=D:\\dsh"]

    def test_new_keys_appended_in_order(self):
        out = w._merge_service_env([], {"B": "2", "A": "1"})
        assert out == ["B=2", "A=1"]

    def test_no_equals_entries_kept_verbatim(self):
        # 无 '=' 非法元素原样保留（手工数据容错，不静默丢弃）
        out = w._merge_service_env(["stray-entry"], {"K": "V"})
        assert out == ["stray-entry", "K=V"]

    def test_empty_env_and_none(self):
        assert w._merge_service_env(["PATH=x"], None) == ["PATH=x"]
        assert w._merge_service_env(["PATH=x"], {}) == ["PATH=x"]
        assert w._merge_service_env(None, None) == []

    def test_identical_value_not_duplicated(self):
        out = w._merge_service_env(["PATH=x"], {"PATH": "x"})
        assert out == ["PATH=x"]


# ── 6.1 seam 面：winreg 缺席 Linux fail-open ─────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="Linux seam 层（winreg 缺席 fail-open 语义仅 Linux 可跑；Windows 会话真写注册表——win32 契约两层形制的 Linux 可跑层）")
class TestRegistrySeamLinux:
    def test_read_fail_open_empty_on_linux(self):
        # Linux 无 winreg：读恒 []（seam 替身测试注入面，真值读取不触达）
        assert w._service_env_registry_read("svc") == []

    def test_write_fail_open_false_on_linux(self):
        assert w._service_env_registry_write("svc", ["K=V"]) is False

    def test_apply_service_env_none_is_noop(self):
        assert w._apply_service_env("svc", None) is True
        assert w._apply_service_env("svc", {}) is True


# ── 6.1/6.2 install_unit 接线（fake registry writer + 全平台 seam 替身）──


class _FakeRegistry:
    """内存注册表替身：记录合并写入形态（REG_MULTI_SZ 元素列表）。"""

    def __init__(self, initial=None):
        self.values = list(initial or [])
        self.writes = []

    def write(self, name, values):
        self.writes.append(list(values))
        self.values = list(values)
        return True


def _patch_install_chain(state=4):
    """install_unit 全链替身：状态查询/nssm/启动全假，仅环境 seam 真走。"""
    return [
        mock.patch.object(w, "_service_state_ex",
                          return_value=(state, None)),
        mock.patch.object(w, "start", return_value=None),
    ]


class TestInstallUnitEnvInjection:
    def _enter_chain(self, st, state):
        for patch in _patch_install_chain(state=state):
            st.enter_context(patch)

    def _patch_userprofile_seams(self, st, profile="C:\\Users\\admin",
                                 account="LocalSystem"):
        # 缺省 USERPROFILE 锚定与服务账户双 seam 替身（跨宿主确定性）
        st.enter_context(mock.patch.object(
            w, "_resolve_caller_userprofile", return_value=profile))
        st.enter_context(mock.patch.object(
            w, "_service_object_name", return_value=account))

    def test_fresh_install_writes_merged_env(self, tmp_path):
        import contextlib

        # 播种 supervisor 脚本（install_unit 缺席守卫要求真实在位）
        sup = tmp_path / ".fenix" / "bin" / "fenixd_supervisor.py"
        sup.parent.mkdir(parents=True)
        sup.write_text("# supervisor stub", encoding="utf-8")

        reg = _FakeRegistry(["PATH=C:\\manual-minimal"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=None)
            self._patch_userprofile_seams(st)
            st.enter_context(mock.patch.object(
                w, "_require_nssm", return_value="nssm"))
            # nssm install 直呼 + _nssm_set 七连：全部替身（只验 env seam 形态）
            st.enter_context(mock.patch(
                "core.platform.win32.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr="")))
            st.enter_context(mock.patch.object(w, "_nssm_set"))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_read",
                side_effect=lambda name: reg.values))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_write", side_effect=reg.write))
            r = w.install_unit(tmp_path, env={"PATH": "C:\\new",
                                              "DSH_HOME": "D:\\dsh"})
        assert r["ok"] is True and r["already"] is False
        # 合并写入：手工 PATH 最小集不被清除（同键覆盖、异键保留）；
        # 显式 env 未指定 USERPROFILE 时缺省并入调用者 profile（本 SPEC）
        assert reg.writes[-1] == ["USERPROFILE=C:\\Users\\admin",
                                  "PATH=C:\\new", "DSH_HOME=D:\\dsh"]
        assert "env_defect" in r
        assert r["userprofile_skip"] is None

    def test_already_running_path_applies_env_and_reports_defects(self):
        import contextlib

        reg = _FakeRegistry(["PATH=C:\\has-claude-only"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            self._patch_userprofile_seams(st)
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_read",
                side_effect=lambda name: reg.values))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_write", side_effect=reg.write))
            st.enter_context(mock.patch.object(
                w, "_service_env_defects",
                return_value=[{"tool": "git", "hint": "h"}]))
            r = w.install_unit("R:\\proj", env={"DSH_HOME": "D:\\dsh"})
        # already=True：ok 仍 True，env_defect 预警面在场 + 缺省注入无跳过
        assert r == {"ok": True, "error": None, "already": True,
                     "unit": r["unit"],
                     "env_defect": [{"tool": "git", "hint": "h"}],
                     "userprofile_skip": None}
        assert reg.writes[-1] == ["PATH=C:\\has-claude-only",
                                  "USERPROFILE=C:\\Users\\admin",
                                  "DSH_HOME=D:\\dsh"]

    def test_env_defect_absent_when_write_fails_gracefully(self):
        import contextlib

        # 写失败不阻塞安装主链（ok 仍 True，WARNING 留对账锚）
        reg = _FakeRegistry()
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            self._patch_userprofile_seams(st)
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_read", return_value=[]))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_write", return_value=False))
            st.enter_context(mock.patch.object(
                w, "_service_env_defects", return_value=[]))
            r = w.install_unit("R:\\proj", env={"K": "V"})
        assert r["ok"] is True
        assert reg.writes == []


# ── fix-windows-service-userprofile：缺省 USERPROFILE 注入三态与守卫 ──


class TestDefaultUserprofileInjection:
    """缺省调用注入调用者 USERPROFILE / 显式 env 覆盖 / 解析失败跳过 /
    LocalSystem 守卫（spec delta 五 Scenario 中 Linux 可跑层）。"""

    def _enter_chain(self, st, state):
        for patch in _patch_install_chain(state=state):
            st.enter_context(patch)

    def _install(self, st, reg, root="R:\\proj", env=None):
        st.enter_context(mock.patch.object(
            w, "_service_env_registry_read",
            side_effect=lambda name: reg.values))
        st.enter_context(mock.patch.object(
            w, "_service_env_registry_write", side_effect=reg.write))
        st.enter_context(mock.patch.object(
            w, "_service_env_defects", return_value=[]))
        return w.install_unit(root, env=env)

    def test_default_call_injects_caller_profile_keeping_existing(self):
        # 缺省调用（spec delta「缺省调用注入调用者 USERPROFILE」）：
        # 既有手工条目保留 + USERPROFILE 合并写入
        import contextlib

        reg = _FakeRegistry(["PATH=C:\\manual-minimal"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile",
                return_value="C:\\Users\\admin"))
            st.enter_context(mock.patch.object(
                w, "_service_object_name", return_value="LocalSystem"))
            r = self._install(st, reg)
        assert r["ok"] is True
        assert reg.writes[-1] == ["PATH=C:\\manual-minimal",
                                  "USERPROFILE=C:\\Users\\admin"]
        assert r["userprofile_skip"] is None

    def test_explicit_env_userprofile_overrides_default(self):
        # 显式 env 覆盖默认注入（spec delta「显式 env 覆盖默认注入」）：
        # 显式值优先，锚定解析不触达
        import contextlib

        reg = _FakeRegistry()
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            resolve = st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile"))
            st.enter_context(mock.patch.object(
                w, "_service_object_name", return_value="LocalSystem"))
            r = self._install(st, reg,
                              env={"USERPROFILE": "C:\\custom\\profile"})
        resolve.assert_not_called()
        assert reg.writes[-1] == ["USERPROFILE=C:\\custom\\profile"]
        assert r["userprofile_skip"] is None

    def test_explicit_env_other_keys_still_gets_default_profile(self):
        # 显式 env 未指定 USERPROFILE 时缺省并入仍生效（同键显式优先语义）
        import contextlib

        reg = _FakeRegistry()
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile",
                return_value="C:\\Users\\admin"))
            st.enter_context(mock.patch.object(
                w, "_service_object_name", return_value="LocalSystem"))
            r = self._install(st, reg, env={"DSH_HOME": "D:\\dsh"})
        assert reg.writes[-1] == ["USERPROFILE=C:\\Users\\admin",
                                  "DSH_HOME=D:\\dsh"]
        assert r["userprofile_skip"] is None

    def test_resolve_failure_skips_without_failing_install(self):
        # 解析失败跳过（双读皆 systemprofile/皆空）：不注入、附提示、不 fail
        import contextlib

        reg = _FakeRegistry(["PATH=C:\\manual-minimal"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile", return_value=None))
            st.enter_context(mock.patch.object(
                w, "_service_object_name", return_value="LocalSystem"))
            r = self._install(st, reg)
        assert r["ok"] is True
        assert reg.writes == []  # 空集不写注册表（既有条目原样不动）
        assert r["userprofile_skip"]
        assert "systemprofile" in r["userprofile_skip"]

    def test_non_localsystem_account_skips_default_injection(self):
        # LocalSystem 守卫（spec delta「非 LocalSystem 专用账户跳过默认
        # 注入」）：SCM 已为专用账户提供真实 profile，注入反成覆写
        import contextlib

        reg = _FakeRegistry(["PATH=C:\\manual-minimal"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            resolve = st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile",
                return_value="C:\\Users\\admin"))
            st.enter_context(mock.patch.object(
                w, "_service_object_name",
                return_value="NT AUTHORITY\\NetworkService"))
            r = self._install(st, reg)
        resolve.assert_not_called()  # 守卫短路，锚定解析不触达
        assert reg.writes == []  # 既有条目不受影响，零写入
        assert r["ok"] is True
        assert r["userprofile_skip"]
        assert "NetworkService" in r["userprofile_skip"]

    def test_fresh_install_path_bypasses_account_guard(self, tmp_path):
        # 新装路径无既存服务（NSSM 缺省 LocalSystem）→ 恒注入（守卫不触发）
        import contextlib

        sup = tmp_path / ".fenix" / "bin" / "fenixd_supervisor.py"
        sup.parent.mkdir(parents=True)
        sup.write_text("# supervisor stub", encoding="utf-8")

        reg = _FakeRegistry()
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=None)
            st.enter_context(mock.patch.object(
                w, "_resolve_caller_userprofile",
                return_value="C:\\Users\\admin"))
            obj_name = st.enter_context(mock.patch.object(
                w, "_service_object_name"))
            st.enter_context(mock.patch.object(
                w, "_require_nssm", return_value="nssm"))
            st.enter_context(mock.patch(
                "core.platform.win32.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr="")))
            st.enter_context(mock.patch.object(w, "_nssm_set"))
            r = self._install(st, reg, root=str(tmp_path))
        obj_name.assert_not_called()  # 新装路径账户守卫不触达
        assert r["ok"] is True and r["already"] is False
        assert reg.writes[-1] == ["USERPROFILE=C:\\Users\\admin"]

    def test_is_systemprofile_path_forms(self):
        assert w._is_systemprofile_path(
            "C:\\WINDOWS\\system32\\config\\systemprofile")
        assert w._is_systemprofile_path(
            "c:/windows/system32/config/systemprofile")
        assert w._is_systemprofile_path(
            '"C:\\Windows\\System32\\config\\systemprofile"')
        assert not w._is_systemprofile_path("C:\\Users\\admin")
        assert not w._is_systemprofile_path("")

    def test_resolve_caller_userprofile_dual_read(self):
        # 双读锚定：env 侧非 systemprofile 优先；env 漂移时回落 home 侧；
        # 两读皆 systemprofile → None。home 侧一律 mock（Path.home() 在
        # Windows 走 USERPROFILE env——patch.dict 生效期内真读会被污染，
        # 过机复验实录），跨平台确定性。
        from pathlib import Path as _P

        with mock.patch.dict(w.os.environ, {"USERPROFILE": "C:\\Users\\admin"}):
            assert w._resolve_caller_userprofile() == "C:\\Users\\admin"
        with mock.patch.dict(w.os.environ, {
                "USERPROFILE": "C:\\WINDOWS\\system32\\config\\systemprofile"}), \
             mock.patch.object(w, "Path") as path_mock:
            path_mock.home.return_value = _P("C:\\Users\\realhome")
            assert w._resolve_caller_userprofile() == "C:\\Users\\realhome"
        with mock.patch.dict(w.os.environ, {
                "USERPROFILE": "C:\\WINDOWS\\system32\\config\\systemprofile"}), \
             mock.patch.object(w, "Path") as path_mock:
            path_mock.home.return_value = _P(
                "C:\\WINDOWS\\system32\\config\\systemprofile")
            assert w._resolve_caller_userprofile() is None

    def test_localsystem_account_equivalence_forms(self):
        for ok in ("LocalSystem", ".\\LocalSystem", "localsystem",
                   "NT AUTHORITY\\System"):
            assert w._is_localsystem_account(ok)
        for no in ("NT AUTHORITY\\NetworkService", "NT AUTHORITY\\LocalService",
                   "DOMAIN\\alice", "", None):
            assert not w._is_localsystem_account(no)


# ── 6.2 服务环境自检 ─────────────────────────────────────────────────


class TestServiceEnvDefects:
    def test_all_resolvable_no_defects(self):
        with mock.patch.object(w, "_service_env_registry_read",
                               return_value=["PATH=C:\\tools"]):
            out = w._service_env_defects(
                "svc", _resolve=lambda tool, path: True)
        assert out == []

    def test_missing_tools_reported_with_hint(self):
        with mock.patch.object(w, "_service_env_registry_read",
                               return_value=["PATH=C:\\tools"]):
            out = w._service_env_defects(
                "svc", _resolve=lambda tool, path: tool != "git")
        assert [d["tool"] for d in out] == ["git"]
        assert out[0]["hint"]  # 缺失目录指引非空

    def test_service_path_preferred_over_system(self):
        seen = {}

        def fake_resolve(tool, path_value):
            seen[tool] = path_value
            return True

        with mock.patch.object(w, "_service_env_registry_read",
                               return_value=["PATH=C:\\svc-minimal"]):
            w._service_env_defects("svc", _resolve=fake_resolve)
        assert seen["claude"] == "C:\\svc-minimal"

    def test_fallback_to_system_path_when_unconfigured(self):
        seen = {}

        def fake_resolve(tool, path_value):
            seen[tool] = path_value
            return True

        with mock.patch.object(w, "_service_env_registry_read",
                               return_value=[]):
            w._service_env_defects("svc", _resolve=fake_resolve)
        assert seen["git"]  # 回退系统 PATH（非空）

    def test_probes_cover_three_tools(self):
        assert [t for t, _ in w._SERVICE_ENV_PROBES] == [
            "claude", "git", "python"]

    def test_env_map_parses_kv_entries(self):
        with mock.patch.object(w, "_service_env_registry_read",
                               return_value=["PATH=a=b\\c", "stray"]):
            assert w._service_env_map("svc") == {"PATH": "a=b\\c"}
