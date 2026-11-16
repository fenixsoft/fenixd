"""install_unit env 注入注册表形态与服务环境自检契约（任务 1.5，覆盖 6.1/6.2）。

D5/A7：AppEnvironmentExtra REG_MULTI_SZ 直写（read-modify-write 合并——
同键 K=V 覆盖、异键保留，install.md §8 手工服务 PATH 最小集不被整值替换
清除）；幂等重跑与安装完成路径服务环境自检（claude/git/python 服务 PATH
视角解析，缺失报 env_defect，ok 仍 True）。注册表面经 seam 替身测试
（winreg 仅 win32，Linux 消费方 fail-open）。
"""

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

    def test_fresh_install_writes_merged_env(self, tmp_path):
        import contextlib

        # 播种 supervisor 脚本（install_unit 缺席守卫要求真实在位）
        sup = tmp_path / ".fenix" / "bin" / "fenixd_supervisor.py"
        sup.parent.mkdir(parents=True)
        sup.write_text("# supervisor stub", encoding="utf-8")

        reg = _FakeRegistry(["PATH=C:\\manual-minimal"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=None)
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
        # 合并写入：手工 PATH 最小集不被清除（同键覆盖、异键保留）
        assert reg.writes[-1] == ["PATH=C:\\new", "DSH_HOME=D:\\dsh"]
        assert "env_defect" in r

    def test_already_running_path_applies_env_and_reports_defects(self):
        import contextlib

        reg = _FakeRegistry(["PATH=C:\\has-claude-only"])
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_read",
                side_effect=lambda name: reg.values))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_write", side_effect=reg.write))
            st.enter_context(mock.patch.object(
                w, "_service_env_defects",
                return_value=[{"tool": "git", "hint": "h"}]))
            r = w.install_unit("R:\\proj", env={"DSH_HOME": "D:\\dsh"})
        # already=True：ok 仍 True，env_defect 预警面在场
        assert r == {"ok": True, "error": None, "already": True,
                     "unit": r["unit"],
                     "env_defect": [{"tool": "git", "hint": "h"}]}
        assert reg.writes[-1] == ["PATH=C:\\has-claude-only",
                                  "DSH_HOME=D:\\dsh"]

    def test_env_defect_absent_when_write_fails_gracefully(self):
        import contextlib

        # 写失败不阻塞安装主链（ok 仍 True，WARNING 留对账锚）
        reg = _FakeRegistry()
        with contextlib.ExitStack() as st:
            self._enter_chain(st, state=4)
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_read", return_value=[]))
            st.enter_context(mock.patch.object(
                w, "_service_env_registry_write", return_value=False))
            st.enter_context(mock.patch.object(
                w, "_service_env_defects", return_value=[]))
            r = w.install_unit("R:\\proj", env={"K": "V"})
        assert r["ok"] is True
        assert reg.writes == []


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
