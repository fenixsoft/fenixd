"""tests/test_self_update_apply.py — add-auto-update 任务 2.8

core/self_update_apply.py 应用编排测试：
- staging 完整性断言（package.sh 清单缺项拦截）；
- 三段式换装状态机推进与失败回滚（stop/start/rename 全部注入 fake）；
- 在飞 run 预检拒绝（活跃 run 记录判读）与 apply.lock 互斥；
- 幂等恢复（残留 staging / 根缺失 .old 场景）与代际清理；
- 插件重注册（dsh CLI 调用注入，desktop 排除、非 fenix 插件不碰、
  框架根内 link 检出跳过）；
- CLI 三子命令退出码（bin/fenix_update.py）。

全程临时目录沙箱：框架根/插件目录/profiles/update 状态目录全部落
tmp_path，不触真实框架根与真实 ~/.dsh；网络交互经 http_get /
download_impl 注入缝全 mock。
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from core.self_update import (
    APPLY_PHASE_FAILED,
    APPLY_PHASE_QUEUED,
    APPLY_PHASE_RUNNING,
    APPLY_PHASE_SUCCESS,
    UpdateConfig,
    read_status,
)
from datetime import timedelta
from core.self_update_apply import (
    INTEGRITY_REQUIRED,
    ApplyContext,
    ApplyError,
    assert_integrity,
    extract_to_staging,
    find_inflight_runs,
    recover_interrupted,
    rollback_swap,
    run_apply_orchestration,
    spawn_apply,
    update_plugins,
    verify_plugin_exports,
)

FW_REPO = "fenixsoft/fenixd"
PLUGINS_REPO = "fenixsoft/dsh-plugins"

# 供 CLI 直测的模块（bin/fenix_update.py 非包内模块，经 sys.path 导入）
BIN_DIR = Path(__file__).resolve().parents[1] / "bin"


# ── 夹具构造助手 ──────────────────────────────────────────────────────


def make_artifact_tree(root: Path, version: str) -> Path:
    """按完整性清单构造一个最小制品形态框架根。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(version, encoding="utf-8")
    required_files = [p for p in INTEGRITY_REQUIRED if p != "VERSION"]
    dirs = {str(Path(p).parent) for p in required_files}
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    for p in required_files:
        (root / p).write_text(f"stub:{p}\n", encoding="utf-8")
    return root


def make_tarball(content_root: Path, top_dir: str, dest: Path) -> Path:
    """把 content_root 打包为带顶层目录的 tar.gz（模拟 GitHub release 制品）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tf:
        for p in sorted(content_root.rglob("*")):
            arcname = str(Path(top_dir) / p.relative_to(content_root))
            tf.add(str(p), arcname=arcname)
    return dest


def make_zip(content_root: Path, top_dir: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as zf:
        for p in sorted(content_root.rglob("*")):
            if p.is_file():
                zf.write(str(p), str(Path(top_dir) / p.relative_to(content_root)))
    return dest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def sha256sum_two_lines(tar: Path, zzip: Path) -> bytes:
    return (f"{sha256_file(tar)}  {tar.name}\n"
            f"{sha256_file(zzip)}  {zzip.name}\n").encode("utf-8")


class FakeRelease:
    """fetch_latest_release 注入替身（duck-typing ReleaseInfo）。"""

    def __init__(self, repo, tag_name, assets):
        self.repo = repo
        self.tag_name = tag_name
        self.assets = assets


@pytest.fixture()
def sandbox(tmp_path):
    """编排沙箱：旧制品框架根 v0.1.7 + 隔离 update 状态目录 + 空 profiles。"""
    root = tmp_path / "fenixd"
    make_artifact_tree(root, "v0.1.7")
    update_dir = tmp_path / "update-state"
    update_dir.mkdir()
    profiles_dir = tmp_path / ".dsh" / "profiles"
    profiles_dir.mkdir(parents=True)
    return {"tmp": tmp_path, "root": root, "update_dir": update_dir,
            "profiles_dir": profiles_dir}


def make_ctx(sb, **overrides) -> ApplyContext:
    """构造全注入的 ApplyContext（不触真实网络 / systemd / ~/.dsh）。"""
    defaults = dict(
        framework_root=sb["root"],
        source="test",
        update_dir=sb["update_dir"],
        profiles_dir=sb["profiles_dir"],
        config=UpdateConfig(),
        http_get=fake_http_factory(),
        download_impl=lambda url, dest: (_ for _ in ()).throw(
            AssertionError(f"unexpected download: {url}")),
        project_roots_fn=lambda: [sb["root"]],
        injected_daemon_roots=[],
        injected_dashboard=False,
    )
    defaults.update(overrides)
    return ApplyContext(**defaults)


def fake_http_factory(framework_tar=None, framework_zip=None,
                      plugins_zip=None, responses=None):
    """http_get 注入缝：API 查询与 sha256 资产全部 canned。

    - releases/latest 两个仓库各返回 canned release JSON（含资产名）；
    - `<pkg>.sha256` 资产按包级双行形态返回（package.sh 实际产物形态）。
    """
    calls = []

    def http_get(url, headers=None, timeout_s=30.0):
        calls.append(url)
        if responses and url in responses:
            return responses[url]
        if "/releases/latest" in url:
            repo = "fenixsoft/fenixd" if "fenixd/releases" in url else PLUGINS_REPO
            if repo == FW_REPO:
                assets = [Path(n).name for n in (framework_tar, framework_zip) if n]
                assets.append("fenixd-v0.1.8.sha256")  # package.sh 包级双行校验文件
                body = {"tag_name": "v0.1.8", "assets": [
                    {"name": n, "browser_download_url":
                     f"https://github.com/{repo}/releases/download/v0.1.8/{n}"}
                    for n in assets]}
            else:
                assets = [Path(n).name for n in (plugins_zip,) if n]
                assets.append("dsh-plugins-v0.1.3.sha256")
                body = {"tag_name": "v0.1.3", "assets": [
                    {"name": n, "browser_download_url":
                     f"https://github.com/{repo}/releases/download/v0.1.3/{n}"}
                    for n in assets]}
            return 200, json.dumps(body).encode("utf-8")
        if url.endswith(".sha256"):
            if "dsh-plugins" in url:
                return 200, (
                    f"{sha256_file(plugins_zip)}  {Path(plugins_zip).name}\n").encode()
            return 200, sha256sum_two_lines(framework_tar, framework_zip)
        raise AssertionError(f"unexpected HTTP GET: {url}")

    http_get.calls = calls
    return http_get


# ── 2.2 staging 完整性断言 / 解压 ─────────────────────────────────────


class TestIntegrity:
    def test_complete_tree_passes(self, tmp_path):
        root = make_artifact_tree(tmp_path / "content", "v0.1.8")
        assert_integrity(root)

    def test_missing_file_rejected(self, tmp_path):
        root = make_artifact_tree(tmp_path / "content", "v0.1.8")
        (root / "schemas" / "spec-driven" / "schema.yaml").unlink()
        with pytest.raises(ApplyError) as ei:
            assert_integrity(root)
        assert "schema.yaml" in str(ei.value)
        assert ei.value.stage == "staging"

    def test_unsafe_archive_members_rejected(self, tmp_path):
        root = make_artifact_tree(tmp_path / "content", "v0.1.8")
        dest = tmp_path / "evil.tar.gz"
        with tarfile.open(dest, "w:gz") as tf:
            info = tarfile.TarInfo(name="../escape.txt")
            info.size = 3
            tf.addfile(info, io.BytesIO(b"bad"))
        with pytest.raises(ApplyError):
            extract_to_staging(dest, tmp_path / "staging")

    def test_tar_extract_single_content_root(self, tmp_path):
        root = make_artifact_tree(tmp_path / "content", "v0.1.8")
        dest = make_tarball(root, "fenixd-v0.1.8", tmp_path / "pkg.tar.gz")
        content = extract_to_staging(dest, tmp_path / "staging")
        assert content.name == "fenixd-v0.1.8"
        assert (content / "VERSION").read_text(encoding="utf-8").strip() == "v0.1.8"


# ── 下载重试与阶段归位（2026-11-28 实证：读停滞超时裸上穿记 unexpected）


class _FakeResp:
    """urlopen 返回的极小上下文管理器（供 _download_file 流式读取）。"""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if not self._payload:
            return b""
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk


class TestDownloadRetry:
    """真实下载路径（无 download_impl 注入）的失败收口与重试行为。"""

    def _patch_urlopen(self, monkeypatch, outcomes):
        """按序注入 urlopen 结果（异常实例或 bytes payload）；记录调用数。"""
        import urllib.request
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            idx = min(calls["n"], len(outcomes) - 1)
            outcome = outcomes[idx]
            calls["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return _FakeResp(outcome)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        return calls

    def test_retry_recovers_after_stalled_reads(self, tmp_path, monkeypatch):
        import socket
        import urllib.error

        dest = tmp_path / "dl" / "asset.tar.gz"
        calls = self._patch_urlopen(monkeypatch, [
            socket.timeout("The read operation timed out"),
            urllib.error.URLError("Connection reset by peer"),
            b"payload-ok",
        ])
        from core.self_update_apply import _download_file
        out = _download_file("https://github.com/x/y/releases/download/v/a.gz", dest)
        assert out.read_bytes() == b"payload-ok"
        assert calls["n"] == 3

    def test_exhausted_retries_raise_download_stage(self, tmp_path, monkeypatch):
        import socket

        dest = tmp_path / "dl" / "asset.tar.gz"
        self._patch_urlopen(monkeypatch, [
            socket.timeout("The read operation timed out"),
        ])
        from core.self_update_apply import _download_file
        with pytest.raises(ApplyError) as ei:
            _download_file("https://github.com/x/y/releases/download/v/a.gz", dest)
        assert ei.value.stage == "download"
        assert "重试" in str(ei.value)
        assert "update.mirror" in str(ei.value)
        # 半截产物已清理
        assert not dest.exists()

    def test_sha256_fetch_network_error_lands_verify_stage(
            self, tmp_path, monkeypatch):
        """download_and_verify 内 sha256 资产网络裸异常归位 verify 阶段。"""
        from core.self_update import ReleaseInfo
        from core.self_update_apply import download_and_verify

        release = ReleaseInfo(
            repo="fenixsoft/fenixd", tag_name="v0.1.8",
            assets={"a.tar.gz": "https://github.com/o/r/releases/download/v0.1.8/a.tar.gz"},
        )

        def exploding_get(url, headers=None, timeout_s=30.0):
            raise OSError("boom")

        with pytest.raises(ApplyError) as ei:
            download_and_verify(
                release, "a.tar.gz", tmp_path,
                download_impl=lambda url, dest: dest.write_bytes(b"data"),
                http_get=exploding_get,
            )
        assert ei.value.stage == "verify"


# ── 2.3 在飞 run 预检 / apply.lock 互斥 / spawn ───────────────────────


class TestInflightRuns:
    def test_fresh_run_record_is_inflight(self, tmp_path):
        proot = tmp_path / "proj"
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        (runs / "run-a.jsonl").write_text('{"type":"init"}', encoding="utf-8")
        inflight = find_inflight_runs([proot])
        assert len(inflight) == 1
        assert inflight[0]["run"].name == "run-a.jsonl"

    def test_stale_run_record_not_inflight(self, tmp_path):
        proot = tmp_path / "proj"
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        f = runs / "run-crash.jsonl"
        f.write_text("{}", encoding="utf-8")
        old = time.time() - 7 * 3600  # 超 6h 空闲 = 崩溃残留
        os.utime(f, (old, old))
        assert find_inflight_runs([proot]) == []

    def test_archived_runs_ignored(self, tmp_path):
        proot = tmp_path / "proj"
        arc = proot / ".fenix" / "runs" / "archive"
        arc.mkdir(parents=True)
        (arc / "done.jsonl").write_text("{}", encoding="utf-8")
        assert find_inflight_runs([proot]) == []

    def test_apply_rejected_with_inflight(self, sandbox):
        runs = sandbox["root"] / ".fenix" / "runs"
        runs.mkdir(parents=True)
        (runs / "active.jsonl").write_text("{}", encoding="utf-8")
        ctx = make_ctx(sandbox)
        from core.self_update_apply import apply_framework

        with pytest.raises(ApplyError) as ei:
            apply_framework(ctx)
        assert ei.value.stage == "preflight"
        assert "在飞" in str(ei.value)


class TestApplyLockAndSpawn:
    def test_orchestration_exits_when_lock_held(self, sandbox):
        from core.self_update import UpdateLock
        from core.self_update import APPLY_LOCK_STALE_S

        lock = UpdateLock(sandbox["update_dir"] / "apply.lock",
                          stale_s=APPLY_LOCK_STALE_S)
        assert lock.acquire() is True
        ctx = make_ctx(sandbox)
        result = run_apply_orchestration(ctx)
        assert result["status"] == "failed"
        assert "apply.lock 被占" in result["error"]
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["phase"] == APPLY_PHASE_FAILED
        lock.release()

    def test_spawn_conflict_on_running_phase(self, sandbox):
        from core.self_update import mark_apply_phase

        mark_apply_phase(APPLY_PHASE_RUNNING, {"trigger": "other"},
                         status_path=sandbox["update_dir"] / "status.json")
        result = spawn_apply(framework_root=sandbox["root"],
                             status_path=sandbox["update_dir"] / "status.json",
                             apply_lock_path=sandbox["update_dir"] / "apply.lock")
        assert result["ok"] is False
        assert result["conflict"] is True

    def test_spawn_waives_stale_running_phase(self, sandbox, monkeypatch):
        # running 孤儿豁免（2026-11-28 客户端实证：编排被硬杀未收尾，
        # status 永久停留 running 楔死更新通道）——超龄放行重触发
        import core.self_update_apply as sua
        from core.self_update import APPLY_LOCK_STALE_S, mark_apply_phase
        from core.timelib import now_utc, to_storage

        old = to_storage(now_utc() - timedelta(seconds=APPLY_LOCK_STALE_S + 60))
        mark_apply_phase(APPLY_PHASE_RUNNING,
                         {"trigger": "other", "started_at": old},
                         status_path=sandbox["update_dir"] / "status.json")

        class FakeProc:
            pid = 424242

        monkeypatch.setattr(sua.pal, "spawn_detached",
                            lambda cmd, cwd=None, env=None, **kw: FakeProc())
        result = spawn_apply(framework_root=sandbox["root"], source="test",
                             status_path=sandbox["update_dir"] / "status.json",
                             apply_lock_path=sandbox["update_dir"] / "apply.lock")
        assert result["ok"] is True
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["phase"] == APPLY_PHASE_QUEUED

    def test_running_orphaned_timestamp_semantics(self):
        from core.self_update import APPLY_LOCK_STALE_S
        from core.self_update_apply import apply_running_orphaned
        from core.timelib import now_utc, to_storage

        # 时间缺失/不可解析 → 宁拒不误清
        assert apply_running_orphaned({"phase": "running"}) is False
        assert apply_running_orphaned({}) is False
        fresh = to_storage(now_utc() - timedelta(minutes=5))
        old = to_storage(now_utc() - timedelta(seconds=APPLY_LOCK_STALE_S + 60))
        assert apply_running_orphaned({"started_at": fresh}) is False
        assert apply_running_orphaned({"started_at": old}) is True
        # stages[-1].ts 晚于 started_at → 按较新者判存活（下载中段不误杀）
        assert apply_running_orphaned({
            "started_at": old,
            "stages": [{"stage": "download", "ok": True, "ts": fresh}],
        }) is False

    def test_spawn_conflict_on_lock(self, sandbox):
        from core.self_update import UpdateLock, APPLY_LOCK_STALE_S

        lock = UpdateLock(sandbox["update_dir"] / "apply.lock",
                          stale_s=APPLY_LOCK_STALE_S)
        assert lock.acquire() is True
        result = spawn_apply(framework_root=sandbox["root"],
                             status_path=sandbox["update_dir"] / "status.json",
                             apply_lock_path=sandbox["update_dir"] / "apply.lock")
        assert result["conflict"] is True
        lock.release()

    def test_spawn_marks_queued_and_detaches(self, sandbox, monkeypatch):
        import core.self_update_apply as sua

        spawned = []

        class FakeProc:
            pid = 424242

        def fake_spawn(cmd, cwd=None, env=None, **kw):
            spawned.append({"cmd": cmd, "cwd": cwd, "env": env})
            return FakeProc()

        monkeypatch.setattr(sua.pal, "spawn_detached", fake_spawn)
        result = spawn_apply(framework_root=sandbox["root"], source="test",
                             status_path=sandbox["update_dir"] / "status.json",
                             apply_lock_path=sandbox["update_dir"] / "apply.lock")
        assert result["ok"] is True
        assert result["pid"] == 424242
        assert spawned[0]["cmd"][:3] == [sys.executable, "-m",
                                         "core.self_update_apply"]
        # 编排进程 cwd 绝不能落在框架根内：Windows 禁止重命名存活进程 CWD
        # 所在目录，编排自身占坑会让 swap 的旧根 rename 必败（2026-11-28
        # dockur/windows 容器实证）。中性落点=框架根父目录。
        assert spawned[0]["cwd"] == str(sandbox["root"].parent)
        # `-m core.self_update_apply` 靠 CWD 找 core 包——cwd 离开框架根后
        # PYTHONPATH 必须显式补包路径，否则编排进程启动即 ImportError
        # （v0.2.7 初版修复漏掉这半边，同容器实测 pid 秒死卡 queued）。
        pp = spawned[0]["env"]["PYTHONPATH"].split(os.pathsep)
        assert str(sandbox["root"]) in pp
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["phase"] == APPLY_PHASE_QUEUED
        assert st["apply"]["trigger"] == "test"


# ── 2.4 三段式换装 + 2.5 回滚 / 幂等恢复 ──────────────────────────────


class TestFullApply:
    def _prepare(self, sb):
        """构造 v0.1.8 假 release 资产 + 全注入 http/download。"""
        new_root = sb["tmp"] / "new-build"
        make_artifact_tree(new_root, "v0.1.8")
        tar = make_tarball(new_root, "fenixd-v0.1.8",
                           sb["tmp"] / "dist" / "fenixd-v0.1.8.tar.gz")
        zzip = make_zip(new_root, "fenixd-v0.1.8",
                        sb["tmp"] / "dist" / "fenixd-v0.1.8.zip")
        http = fake_http_factory(framework_tar=tar, framework_zip=zzip)

        def download_impl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tar.read_bytes())

        return http, download_impl

    def test_success_end_to_end(self, sandbox):
        http, download_impl = self._prepare(sandbox)
        calls = {"stop": [], "start": []}

        ctx = make_ctx(
            sandbox,
            http_get=http,
            download_impl=download_impl,
            stop_units_fn=lambda roots, dash: (calls["stop"].append(
                (list(roots), dash)) or {"errors": []}),
            start_units_fn=lambda roots, dash: (calls["start"].append(
                (list(roots), dash)) or {"errors": []}),
        )
        result = run_apply_orchestration(ctx)
        assert result["status"] == "success", result
        # 换装后 VERSION 读回为目标 tag
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.8"
        # 旧根保留为回滚副本（一代）
        olds = list(sandbox["root"].parent.glob("fenixd.old-*"))
        assert len(olds) == 1
        assert (olds[0] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.7"
        # 未服务化场景：停步跳过并注明（无 unit 被停/起）
        assert calls["stop"] == [([], False)]
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["phase"] == APPLY_PHASE_SUCCESS
        stage_names = [s["stage"] for s in st["apply"]["stages"]]
        assert "stop" in stage_names and "swap" in stage_names and "start" in stage_names
        assert "未服务化" in json.dumps(st["apply"]["stages"], ensure_ascii=False)
        # 审计留痕
        audits = (sandbox["update_dir"] / "audits.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        entry = json.loads(audits[-1])
        assert entry["kind"] == "apply"
        assert entry["result"] == "success"

    def test_start_failure_rolls_back(self, sandbox):
        http, download_impl = self._prepare(sandbox)

        def start_fail(roots, dash):
            return {"errors": ["simulated start failure"]}

        ctx = make_ctx(sandbox, http_get=http, download_impl=download_impl,
                       start_units_fn=start_fail)
        result = run_apply_orchestration(ctx)
        assert result["status"] == "failed"
        assert "simulated start failure" in result["framework_error"]
        # 回滚：旧版本恢复为框架根
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.7"
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["phase"] == APPLY_PHASE_FAILED
        assert st["apply"]["failed_stage"] == "start"
        assert st["apply"]["rollback"] is True
        assert st["apply"]["rollback_restored"] is True

    def test_stop_failure_no_changes(self, sandbox):
        http, download_impl = self._prepare(sandbox)

        def stop_fail(roots, dash):
            return {"errors": ["simulated stop failure"]}

        ctx = make_ctx(sandbox, http_get=http, download_impl=download_impl,
                       stop_units_fn=stop_fail)
        result = run_apply_orchestration(ctx)
        assert result["status"] == "failed"
        # 本地安装不受任何改动（spec 硬门）
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.7"
        assert not list(sandbox["root"].parent.glob("fenixd.old-*"))
        st = read_status(sandbox["update_dir"] / "status.json")
        assert st["apply"]["failed_stage"] == "stop"

    def test_source_form_rejected(self, tmp_path):
        src_root = tmp_path / "src-tree"
        src_root.mkdir()
        sb = {"tmp": tmp_path, "root": src_root,
              "update_dir": tmp_path / "u", "profiles_dir": tmp_path / "p"}
        sb["update_dir"].mkdir()
        sb["profiles_dir"].mkdir(parents=True)
        ctx = make_ctx(sb)
        result = run_apply_orchestration(ctx)
        assert result["status"] == "failed"
        assert "源码形态" in result["framework_error"]

    def test_target_not_newer_rejected(self, sandbox):
        # 本地已是最新（= 远端 latest）→ 拒绝换装（目标解析回退 latest 后仍不新）
        http, download_impl = self._prepare(sandbox)
        (sandbox["root"] / "VERSION").write_text("v0.1.8", encoding="utf-8")
        ctx = make_ctx(sandbox, http_get=http, download_impl=download_impl)
        result = run_apply_orchestration(ctx)
        assert result["status"] == "failed"
        assert "不新于本地" in result["framework_error"]
        # 本地安装不受任何改动
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.8"

    def test_dashboard_unit_included_in_stop(self, sandbox):
        http, download_impl = self._prepare(sandbox)
        calls = {}

        ctx = make_ctx(
            sandbox,
            http_get=http, download_impl=download_impl,
            injected_daemon_roots=[sandbox["root"].parent / "proj-a"],
            injected_dashboard=True,
            stop_units_fn=lambda roots, dash: (
                calls.update(stop=(list(roots), dash)) or {"errors": []}),
            start_units_fn=lambda roots, dash: (
                calls.update(start=(list(roots), dash)) or {"errors": []}),
            drain_poll_fn=lambda roots: [],  # 排水即时完成
        )
        # injected daemon root 不存在不影响编排（stop 为注入函数）
        result = run_apply_orchestration(ctx)
        assert result["status"] == "success"
        assert calls["stop"] == ([sandbox["root"].parent / "proj-a"], True)
        assert calls["start"] == ([sandbox["root"].parent / "proj-a"], True)


class TestRecovery:
    def test_root_missing_rolls_back_from_old(self, sandbox):
        # 模拟换装②完成③前进程死亡：根缺失 + .old 在位
        old = sandbox["root"].parent / "fenixd.old-20260101-000000"
        os.rename(sandbox["root"], old)
        note = recover_interrupted(make_ctx(sandbox))
        assert "恢复" in note
        assert sandbox["root"].exists()
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.7"

    def test_recovered_then_apply_succeeds(self, sandbox):
        old = sandbox["root"].parent / "fenixd.old-20260101-000000"
        os.rename(sandbox["root"], old)
        ctx = make_ctx(sandbox)
        recover_interrupted(ctx)
        # 恢复后继续走完整 apply
        new_root = sandbox["tmp"] / "new-build"
        make_artifact_tree(new_root, "v0.1.8")
        tar = make_tarball(new_root, "fenixd-v0.1.8",
                           sandbox["tmp"] / "dist" / "fenixd-v0.1.8.tar.gz")
        zzip = make_zip(new_root, "fenixd-v0.1.8",
                        sandbox["tmp"] / "dist" / "fenixd-v0.1.8.zip")
        http = fake_http_factory(framework_tar=tar, framework_zip=zzip)

        def download_impl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tar.read_bytes())

        ctx2 = make_ctx(sandbox, http_get=http, download_impl=download_impl)
        result = run_apply_orchestration(ctx2)
        assert result["status"] == "success"
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.8"

    def test_incomplete_staging_cleaned(self, sandbox):
        stale = sandbox["root"].parent / "fenixd-update-staging-20260101-000000"
        (stale / "fenixd-v0.1.6").mkdir(parents=True)
        (stale / "fenixd-v0.1.6" / "README.md").write_text("half", encoding="utf-8")
        note = recover_interrupted(make_ctx(sandbox))
        assert "不完整" in note
        assert not stale.exists()

    def test_complete_staging_taken_over(self, sandbox):
        # 完整 staging → 编排接管（不再下载——download_impl 被调用即失败）
        new_root = sandbox["tmp"] / "new-build"
        make_artifact_tree(new_root, "v0.1.8")
        stale = sandbox["root"].parent / "fenixd-update-staging-20260101-000000"
        stale.mkdir(parents=True)
        os.rename(new_root, stale / "fenixd-v0.1.8")
        tar = make_tarball(stale / "fenixd-v0.1.8", "fenixd-v0.1.8",
                           sandbox["tmp"] / "dist" / "fenixd-v0.1.8.tar.gz")
        zzip = make_zip(stale / "fenixd-v0.1.8", "fenixd-v0.1.8",
                        sandbox["tmp"] / "dist" / "fenixd-v0.1.8.zip")
        ctx = make_ctx(sandbox, http_get=fake_http_factory(
            framework_tar=tar, framework_zip=zzip))
        # download_impl 缺省：被调用即抛断言（接管路径 MUST 零下载）
        note = recover_interrupted(ctx)
        assert "接管" in note
        assert ctx.recovered_staging is not None
        result = run_apply_orchestration(ctx)
        assert result["status"] == "success"
        assert (sandbox["root"] / "VERSION").read_text(
            encoding="utf-8").strip() == "v0.1.8"

    def test_generation_cleanup_keeps_one(self, sandbox):
        # 两代 .old 残留 + 本轮成功 → 仅保留本次一代
        for ts in ("20250101-000000", "20250202-000000"):
            old = sandbox["root"].parent / f"fenixd.old-{ts}"
            old.mkdir()
            (old / "VERSION").write_text("v0.1.6", encoding="utf-8")
        new_root = sandbox["tmp"] / "new-build"
        make_artifact_tree(new_root, "v0.1.8")
        tar = make_tarball(new_root, "fenixd-v0.1.8",
                           sandbox["tmp"] / "dist" / "fenixd-v0.1.8.tar.gz")
        zzip = make_zip(new_root, "fenixd-v0.1.8",
                        sandbox["tmp"] / "dist" / "fenixd-v0.1.8.zip")
        http = fake_http_factory(framework_tar=tar, framework_zip=zzip)

        def download_impl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tar.read_bytes())

        result = run_apply_orchestration(
            make_ctx(sandbox, http_get=http, download_impl=download_impl))
        assert result["status"] == "success"
        olds = list(sandbox["root"].parent.glob("fenixd.old-*"))
        assert len(olds) == 1  # 仅本轮一代


# ── 2.6 插件更新编排 ──────────────────────────────────────────────────


def _plugins_fixture(sb):
    """旧插件 v0.1.2（含两个 fenix 插件 + lib）+ 新版 v0.1.3 zip 假资产。"""
    plugins_parent = sb["tmp"] / "tools"
    old_root = plugins_parent / "dsh-plugins-v0.1.2"
    for plug in ("fenix-dsh-auth", "fenix-dsh-chat-polish"):
        pdir = old_root / plug
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "name": plug, "exports": {"import": "./lib/index.js"},
        }), encoding="utf-8")
        (pdir / "lib").mkdir()
        (pdir / "lib" / "index.js").write_text("module.exports={};", encoding="utf-8")
    new_root = sb["tmp"] / "new-plugins"
    for plug in ("fenix-dsh-auth", "fenix-dsh-chat-polish"):
        pdir = new_root / plug
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "name": plug, "exports": {"import": "./lib/index.js"},
        }), encoding="utf-8")
        (pdir / "lib").mkdir()
        (pdir / "lib" / "index.js").write_text("module.exports={};", encoding="utf-8")
    zzip = make_zip(new_root, "dsh-plugins-v0.1.3",
                    sb["tmp"] / "dist" / "dsh-plugins-v0.1.3.zip")
    return old_root, zzip


def _write_profile(profiles_dir, name, deps):
    pdir = profiles_dir / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "package.json").write_text(
        json.dumps({"dependencies": deps}), encoding="utf-8")
    return pdir


class TestPluginsUpdate:
    def _ctx(self, sb, old_root, zzip, dsh_calls):
        http = fake_http_factory(plugins_zip=zzip)

        def download_impl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zzip.read_bytes())

        def dsh_runner(argv):
            dsh_calls.append(argv)
            return 0, "", ""

        return make_ctx(sb, http_get=http, download_impl=download_impl,
                        dsh_runner=dsh_runner)

    def test_reregistration_flow(self, sandbox):
        old_root, zzip = _plugins_fixture(sandbox)
        old_abs = old_root.resolve()
        _write_profile(sandbox["profiles_dir"], "fenix", {
            "fenix-dsh-auth": f"link:{old_abs}/fenix-dsh-auth",
            "fenix-dsh-chat-polish": f"link:{old_abs}/fenix-dsh-chat-polish",
            "dsh-plugin-loopback-trust": "link:/opt/other/loopback-trust",
        })
        dsh_calls = []
        ctx = self._ctx(sandbox, old_root, zzip, dsh_calls)
        result = update_plugins(ctx, target_tag="v0.1.3")
        assert result["status"] == "success"
        assert result["version"] == "v0.1.3"
        # remove + add 各两次，指向新目录
        adds = [a for a in dsh_calls if a[:2] == ["plugin", "--profile"]
                and "add" in a]
        removes = [a for a in dsh_calls if a[:2] == ["plugin", "--profile"]
                   and "remove" in a]
        assert len(adds) == 2 and len(removes) == 2
        for a in adds:
            assert a[2] == "fenix"
            assert a[-1].startswith("link:")
            assert "dsh-plugins-v0.1.3" in a[-1]
        # 非 fenix 插件零触碰
        assert not any("loopback" in json.dumps(a) for a in dsh_calls)
        # 新目录在位、旧版本根清理
        new_root = old_root.parent / "dsh-plugins-v0.1.3"
        assert (new_root / "fenix-dsh-auth" / "lib" / "index.js").exists()
        assert not old_root.exists()

    def test_desktop_profile_not_touched(self, sandbox):
        old_root, zzip = _plugins_fixture(sandbox)
        old_abs = old_root.resolve()
        _write_profile(sandbox["profiles_dir"], "fenix", {
            "fenix-dsh-auth": f"link:{old_abs}/fenix-dsh-auth",
        })
        dsh_calls = []
        ctx = self._ctx(sandbox, old_root, zzip, dsh_calls)
        # desktop profile 有 fenix link → 检出降级指引、不被改写
        desktop_pkg = _write_profile(sandbox["profiles_dir"], "desktop", {
            "fenix-dsh-auth": f"link:{old_abs}/fenix-dsh-auth",
        })
        result = update_plugins(ctx, target_tag=None)
        assert result["status"] == "success"
        assert any("desktop" in d for d in result["detail"].split("；"))
        # profile 名判定（tmp 路径含测试名 "desktop" 子串，勿做全文匹配）
        assert not any(a[2] == "desktop" for a in dsh_calls)
        # desktop profile 的 package.json 未被改写
        deps = json.loads((desktop_pkg / "package.json").read_text(
            encoding="utf-8"))["dependencies"]
        assert "dsh-plugins-v0.1.2" in deps["fenix-dsh-auth"]

    def test_framework_internal_links_skipped(self, sandbox):
        old_root, zzip = _plugins_fixture(sandbox)
        # dsh-bundle 已随制品夹具建好（INTEGRITY_REQUIRED 覆盖），直接引用
        fw_link = sandbox["root"] / "dsh-bundle"
        _write_profile(sandbox["profiles_dir"], "fenix", {
            "fenix-dsh-bundle": f"link:{fw_link}",
            "fenix-dsh-auth": f"link:{old_root.resolve()}/fenix-dsh-auth",
        })
        dsh_calls = []
        ctx = self._ctx(sandbox, old_root, zzip, dsh_calls)
        result = update_plugins(ctx, target_tag=None)
        assert result["status"] == "success"
        assert "随框架换装" in result["detail"]
        # 框架根内插件不参与重注册（只有 fenix-dsh-auth 被动）
        assert len(dsh_calls) == 2  # 1 remove + 1 add

    def test_plugins_inside_framework_root_skipped(self, sandbox):
        # 插件目录位于框架根内（源码形态）→ 整体跳过
        fw_plugins = sandbox["root"] / "dsh-plugins-v0.1.2" / "fenix-dsh-auth"
        fw_plugins.mkdir(parents=True)
        (fw_plugins / "package.json").write_text("{}", encoding="utf-8")
        _write_profile(sandbox["profiles_dir"], "fenix", {
            "fenix-dsh-auth": f"link:{fw_plugins}",
        })
        ctx = make_ctx(sandbox)
        result = update_plugins(ctx, target_tag=None)
        assert result["status"] == "skipped"
        assert "框架根内" in result["detail"]

    def test_no_plugins_state_skipped(self, sandbox):
        ctx = make_ctx(sandbox)  # 空 profiles
        result = update_plugins(ctx, target_tag=None)
        assert result["status"] == "skipped"

    def test_missing_export_detected(self, sandbox):
        old_root, zzip = _plugins_fixture(sandbox)
        old_abs = old_root.resolve()
        _write_profile(sandbox["profiles_dir"], "fenix", {
            "fenix-dsh-auth": f"link:{old_abs}/fenix-dsh-auth",
        })
        # 新版缺 lib/index.js → exports 校验拦截
        new_root = sandbox["tmp"] / "bad-plugins"
        pdir = new_root / "fenix-dsh-auth"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "name": "fenix-dsh-auth", "exports": {"import": "./lib/index.js"},
        }), encoding="utf-8")
        bad_zip = make_zip(new_root, "dsh-plugins-v0.1.3",
                           sandbox["tmp"] / "dist2" / "dsh-plugins-v0.1.3.zip")
        dsh_calls = []
        ctx = self._ctx(sandbox, old_root, bad_zip, dsh_calls)
        # plugins_zip 参数需与 sha256 对应——重建 http
        ctx.http_get = fake_http_factory(plugins_zip=bad_zip)

        def download_impl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(bad_zip.read_bytes())

        ctx.download_impl = download_impl
        with pytest.raises(ApplyError) as ei:
            update_plugins(ctx, target_tag=None)
        assert "exports" in str(ei.value)


class TestVerifyExports:
    def test_missing_paths_listed(self, tmp_path):
        pdir = tmp_path / "plug"
        pdir.mkdir()
        (pdir / "package.json").write_text(json.dumps({
            "exports": {"import": "./lib/index.js", "types": "./index.d.ts"},
        }), encoding="utf-8")
        missing = verify_plugin_exports(pdir)
        assert sorted(missing) == ["index.d.ts", "lib/index.js"]

    def test_ok_when_files_exist(self, tmp_path):
        pdir = tmp_path / "plug"
        (pdir / "lib").mkdir(parents=True)
        (pdir / "lib" / "index.js").write_text("x", encoding="utf-8")
        (pdir / "package.json").write_text(json.dumps({
            "exports": {"import": "./lib/index.js"},
        }), encoding="utf-8")
        assert verify_plugin_exports(pdir) == []


# ── 2.7 CLI 三子命令退出码 ────────────────────────────────────────────


class TestCli:
    def _run_cli(self, argv, env_home=None):
        env = dict(os.environ)
        if env_home:
            env["FENIX_HOME"] = str(env_home)
        return subprocess.run(
            [sys.executable, str(BIN_DIR / "fenix_update.py"), *argv],
            capture_output=True, text=True, env=env, timeout=60)

    def test_status_no_record_exit_ok(self, tmp_path):
        r = self._run_cli(["status"], env_home=tmp_path)
        assert r.returncode == 0
        assert "尚无更新检查记录" in r.stdout

    def test_status_json_with_record(self, tmp_path):
        update_dir = tmp_path / ".fenix" / "update"
        update_dir.mkdir(parents=True)
        (update_dir / "status.json").write_text(json.dumps({
            "framework": {"form": "artifact", "local_version": "v0.1.7",
                          "remote_version": "v0.1.8", "update_available": True},
            "plugins": {}, "last_check_at": "2026-01-01T00:00:00Z",
            "apply": {"phase": "idle"},
        }), encoding="utf-8")
        r = self._run_cli(["status", "--json"], env_home=tmp_path)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["framework"]["update_available"] is True

    def test_help_zero(self):
        r = self._run_cli(["--help"])
        assert r.returncode == 0


class TestCliExitCodes:
    """CLI 退出码语义（进程内直调 main，引擎函数 monkeypatch 控制分支）。"""

    @classmethod
    def setup_class(cls):
        if str(BIN_DIR) not in sys.path:
            sys.path.insert(0, str(BIN_DIR))
        import fenix_update  # noqa: F401 — 装载 CLI 模块

        cls.cli = fenix_update

    def test_check_success_with_update(self, monkeypatch, capsys):
        import core.self_update as su

        monkeypatch.setattr(su, "run_check", lambda *a, **k: {
            "framework": {"form": "artifact", "local_version": "v0.1.7",
                          "remote_version": "v0.1.8", "update_available": True},
            "plugins": {}, "last_error": None,
        })
        assert self.cli.main(["check"]) == self.cli.EXIT_OK

    def test_check_no_update(self, monkeypatch, capsys):
        import core.self_update as su

        monkeypatch.setattr(su, "run_check", lambda *a, **k: {
            "framework": {"form": "artifact", "local_version": "v0.1.7",
                          "remote_version": "v0.1.7", "update_available": False},
            "plugins": {}, "last_error": None,
        })
        assert self.cli.main(["check"]) == self.cli.EXIT_NO_UPDATE

    def test_check_failure(self, monkeypatch, capsys):
        import core.self_update as su

        monkeypatch.setattr(su, "run_check", lambda *a, **k: {
            "framework": {}, "plugins": {}, "last_error": "GitHub API 限流",
        })
        assert self.cli.main(["check"]) == self.cli.EXIT_FAILURE

    def test_apply_source_form_rejected(self, monkeypatch, capsys):
        import core.self_update as su
        from core.self_update import LocalVersion

        monkeypatch.setattr(su, "read_framework_version",
                            lambda *a, **k: LocalVersion(None, "source"))
        assert self.cli.main(["apply"]) == self.cli.EXIT_FAILURE

    def test_apply_no_update(self, monkeypatch, capsys):
        import core.self_update as su
        from core.self_update import LocalVersion

        monkeypatch.setattr(su, "read_framework_version",
                            lambda *a, **k: LocalVersion("v0.1.7", "artifact"))
        monkeypatch.setattr(su, "read_status", lambda *a, **k: {})
        assert self.cli.main(["apply"]) == self.cli.EXIT_NO_UPDATE

    def test_apply_accepted(self, monkeypatch, capsys):
        import core.self_update as su
        import core.self_update_apply as sua
        from core.self_update import LocalVersion

        monkeypatch.setattr(su, "read_framework_version",
                            lambda *a, **k: LocalVersion("v0.1.7", "artifact"))
        monkeypatch.setattr(su, "read_status", lambda *a, **k: {
            "framework": {"update_available": True}})
        monkeypatch.setattr(sua, "spawn_apply",
                            lambda **k: {"ok": True, "pid": 1})
        assert self.cli.main(["apply"]) == self.cli.EXIT_OK

    def test_apply_conflict_failure(self, monkeypatch, capsys):
        import core.self_update as su
        import core.self_update_apply as sua
        from core.self_update import LocalVersion

        monkeypatch.setattr(su, "read_framework_version",
                            lambda *a, **k: LocalVersion("v0.1.7", "artifact"))
        monkeypatch.setattr(su, "read_status", lambda *a, **k: {
            "framework": {"update_available": True}})
        monkeypatch.setattr(sua, "spawn_apply",
                            lambda **k: {"ok": False, "conflict": True,
                                         "error": "已有更新编排进行中"})
        assert self.cli.main(["apply"]) == self.cli.EXIT_FAILURE


class _HeaderResp:
    """带响应头的流式假响应（Content-Length 进度断言用）。"""

    def __init__(self, payload: bytes, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if not self._payload:
            return b""
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk


class TestDownloadProgress:
    """下载进度写面（progress.json）：字节/总数/阶段与终态清理。"""

    def _patch_urlopen(self, monkeypatch, outcomes):
        import urllib.request
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            idx = min(calls["n"], len(outcomes) - 1)
            outcome = outcomes[idx]
            calls["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        return calls

    def _writer(self, tmp_path):
        from core.self_update_apply import UpdateProgressWriter
        return UpdateProgressWriter(tmp_path / "progress.json")

    def test_bytes_total_percent_recorded(self, tmp_path, monkeypatch):
        payload = b"x" * (256 * 1024 + 100)  # 两个 chunk
        self._patch_urlopen(monkeypatch, [
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
        ])
        from core.self_update_apply import _download_file
        w = self._writer(tmp_path)
        dest = tmp_path / "dl" / "asset.tar.gz"
        _download_file("https://github.com/x/y/releases/download/v/a.gz",
                       dest, progress=w)
        raw = json.loads((tmp_path / "progress.json").read_text())
        assert raw["asset"] == "asset.tar.gz"
        assert raw["stage"] == "download"
        assert raw["downloaded"] == len(payload)
        assert raw["total"] == len(payload)
        assert raw["percent"] == 100.0
        assert raw["attempt"] == 1
        assert raw["updated_at"]

    def test_unknown_length_degrades_to_null_percent(self, tmp_path, monkeypatch):
        payload = b"y" * 5000
        self._patch_urlopen(monkeypatch, [_HeaderResp(payload)])  # 无 Content-Length
        from core.self_update_apply import _download_file
        dest = tmp_path / "dl" / "asset.tar.gz"
        _download_file("https://github.com/x/y/releases/download/v/a.gz",
                       dest, progress=self._writer(tmp_path))
        raw = json.loads((tmp_path / "progress.json").read_text())
        assert raw["downloaded"] == len(payload)
        assert raw["total"] is None
        assert raw["percent"] is None

    def test_attempt_counter_resets_progress(self, tmp_path, monkeypatch):
        import socket
        payload = b"z" * 1000
        self._patch_urlopen(monkeypatch, [
            socket.timeout("The read operation timed out"),
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
        ])
        from core.self_update_apply import _download_file
        dest = tmp_path / "dl" / "asset.tar.gz"
        _download_file("https://github.com/x/y/releases/download/v/a.gz",
                       dest, progress=self._writer(tmp_path))
        raw = json.loads((tmp_path / "progress.json").read_text())
        assert raw["attempt"] == 2
        assert raw["downloaded"] == len(payload)

    def test_verify_failure_keeps_progress_file(self, tmp_path, monkeypatch):
        payload = b"q" * 64
        self._patch_urlopen(monkeypatch, [
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
        ])
        from core.self_update_apply import download_and_verify
        rel = FakeRelease(repo="fenixsoft/fenixd", tag_name="v9.9.9",
                          assets={"asset.tar.gz": "https://github.com/x/y/releases/download/v9.9.9/asset.tar.gz",
                                  "asset.sha256": "https://github.com/x/y/releases/download/v9.9.9/asset.sha256"})
        bad_sha = "0" * 64

        def fake_http_get(url, headers=None, timeout_s=30.0):
            return 200, f"{bad_sha}  asset.tar.gz\n".encode()

        with pytest.raises(ApplyError) as ei:
            download_and_verify(rel, "asset.tar.gz", tmp_path / "dl",
                                http_get=fake_http_get,
                                progress=self._writer(tmp_path))
        assert ei.value.stage == "verify"
        raw = json.loads((tmp_path / "progress.json").read_text())
        assert raw["stage"] == "verify"
        assert raw["asset"] == "asset.tar.gz"

    def test_verify_success_deletes_progress_file(self, tmp_path, monkeypatch):
        import hashlib
        payload = b"ok-bytes"
        good_sha = hashlib.sha256(payload).hexdigest()
        self._patch_urlopen(monkeypatch, [
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
        ])
        from core.self_update_apply import download_and_verify
        rel = FakeRelease(repo="fenixsoft/fenixd", tag_name="v9.9.9",
                          assets={"asset.tar.gz": "https://github.com/x/y/releases/download/v9.9.9/asset.tar.gz",
                                  "asset.sha256": "https://github.com/x/y/releases/download/v9.9.9/asset.sha256"})

        def fake_http_get(url, headers=None, timeout_s=30.0):
            return 200, f"{good_sha}  asset.tar.gz\n".encode()

        out = download_and_verify(rel, "asset.tar.gz", tmp_path / "dl",
                                  http_get=fake_http_get,
                                  progress=self._writer(tmp_path))
        assert out.read_bytes() == payload
        assert not (tmp_path / "progress.json").exists()

    def test_finish_is_idempotent(self, tmp_path):
        from core.self_update_apply import UpdateProgressWriter
        w = UpdateProgressWriter(tmp_path / "progress.json")
        w.start("a.gz", 10)
        assert (tmp_path / "progress.json").exists()
        w.finish()
        w.finish()  # 缺席再次删除不报错
        assert not (tmp_path / "progress.json").exists()


class TestChannelFallback:
    """双通道下载（2026-11-28 默认镜像通道）：镜像优先、直连兜底。"""

    # sha256 硬门是真的：期望值必须等于下载载荷的真实哈希
    GOOD_SHA = hashlib.sha256(b"payload").hexdigest()

    @staticmethod
    def _rel():
        return FakeRelease(
            repo="fenixsoft/fenixd", tag_name="v9.9.9",
            assets={"a.bin": "https://github.com/o/r/releases/download/v9.9.9/a.bin",
                    "a.bin.sha256": "https://github.com/o/r/releases/download/v9.9.9/a.bin.sha256"})

    @staticmethod
    def _sha_http():
        def fake_http_get(url, headers=None, timeout_s=30.0):
            return 200, f"{TestChannelFallback.GOOD_SHA}  a.bin\n".encode()
        return fake_http_get

    def test_mirror_fails_direct_fallback_succeeds(self, tmp_path):
        """镜像通道失败 → 直连兜底成功；URL 顺序 = [镜像, 官方]。"""
        seen = []

        def download_impl(url, dest):
            seen.append(url)
            if len(seen) == 1:
                raise ApplyError("download", "mirror 通道失败")
            dest.write_bytes(b"payload")

        from core.self_update_apply import download_and_verify
        out = download_and_verify(
            self._rel(), "a.bin", tmp_path / "dl",
            mirror="https://m.example.com", http_get=self._sha_http(),
            download_impl=download_impl)
        assert out.read_bytes() == b"payload"
        assert seen == [
            "https://m.example.com/o/r/releases/download/v9.9.9/a.bin",
            "https://github.com/o/r/releases/download/v9.9.9/a.bin",
        ]

    def test_all_channels_exhausted_raises_download(self, tmp_path):
        calls = []

        def download_impl(url, dest):
            calls.append(url)
            raise ApplyError("download", f"down: {url}")

        from core.self_update_apply import download_and_verify
        with pytest.raises(ApplyError) as ei:
            download_and_verify(
                self._rel(), "a.bin", tmp_path / "dl",
                mirror="https://m.example.com", http_get=self._sha_http(),
                download_impl=download_impl)
        assert ei.value.stage == "download"
        assert "双通道" in str(ei.value)
        assert "update.mirror" in str(ei.value)
        # 每通道一次（download_impl 面不套 _download_file 重试）
        assert len(calls) == 2
        assert not (tmp_path / "dl" / "a.bin").exists()

    def test_explicit_official_skips_mirror(self, tmp_path):
        """显式官方（mirror=""）仅直连通道，不静默绕道镜像。"""
        seen = []

        def download_impl(url, dest):
            seen.append(url)
            dest.write_bytes(b"payload")

        from core.self_update_apply import download_and_verify
        download_and_verify(
            self._rel(), "a.bin", tmp_path / "dl",
            mirror="", http_get=self._sha_http(), download_impl=download_impl)
        assert seen == ["https://github.com/o/r/releases/download/v9.9.9/a.bin"]

    def test_sha256_fetch_channel_fallback(self, tmp_path):
        """sha256 资产同样双通道：镜像通道失败 → 直连取回。"""
        from core.self_update_apply import _fetch_expected_sha256
        seen = []

        def fake_http_get(url, headers=None, timeout_s=30.0):
            seen.append(url)
            if "m.example.com" in url:
                raise OSError("mirror sha fetch failed")
            return 200, f"{TestChannelFallback.GOOD_SHA}  a.bin\n".encode()

        got = _fetch_expected_sha256(
            self._rel(), "a.bin", mirror="https://m.example.com",
            http_get=fake_http_get)
        assert got == TestChannelFallback.GOOD_SHA
        assert seen[0].startswith("https://m.example.com/")
        assert seen[1].startswith("https://github.com/")


class TestDownloadHardening:
    """下载加固（2026-11-28 客户端实证两形态）：干净截断与慢速滴流。"""

    def _patch_urlopen(self, monkeypatch, outcomes):
        import urllib.request
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            idx = min(calls["n"], len(outcomes) - 1)
            outcome = outcomes[idx]
            calls["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        return calls

    def test_clean_truncation_retries_via_size_assert(self, tmp_path, monkeypatch):
        """Content-Length 已知时 EOF 短读判截断进重试（不等 sha256 拦）。"""
        full = b"full-payload-bytes"
        dest = tmp_path / "dl" / "a.gz"
        calls = self._patch_urlopen(monkeypatch, [
            _HeaderResp(full[:5], headers={"Content-Length": str(len(full))}),
            _HeaderResp(full, headers={"Content-Length": str(len(full))}),
        ])
        from core.self_update_apply import _download_file
        out = _download_file("https://github.com/x/y/releases/download/v/a.gz", dest)
        assert out.read_bytes() == full
        assert calls["n"] == 2

    def test_truncation_exhausted_raises_download_stage(self, tmp_path, monkeypatch):
        dest = tmp_path / "dl" / "a.gz"
        self._patch_urlopen(monkeypatch, [
            _HeaderResp(b"abc", headers={"Content-Length": "100"}),
        ])
        from core.self_update_apply import _download_file
        with pytest.raises(ApplyError) as ei:
            _download_file("https://github.com/x/y/releases/download/v/a.gz", dest)
        assert ei.value.stage == "download"
        assert not dest.exists()

    def test_wall_clock_deadline_cuts_slow_drip(self, tmp_path, monkeypatch):
        """socket 空闲超时不触发的慢速滴流，由墙钟硬上限切进重试。"""
        import itertools
        monotonic_values = iter([0.0, 10 ** 9])  # attempt1: deadline=0+600，读循环即超限

        def fake_monotonic():
            return next(itertools.chain(monotonic_values, itertools.repeat(0.0)))

        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        payload = b"drip"
        calls = self._patch_urlopen(monkeypatch, [
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
            _HeaderResp(payload, headers={"Content-Length": str(len(payload))}),
        ])
        from core.self_update_apply import _download_file
        dest = tmp_path / "dl" / "a.gz"
        out = _download_file("https://github.com/x/y/releases/download/v/a.gz", dest)
        assert out.read_bytes() == payload
        assert calls["n"] == 2


class TestWindowsDashboardHosting:
    """Windows NSSM/sc dashboard 承载兜底（2026-11-28 用户实证：自建 NSSM
    服务工作目录=旧框架根，不停导致换装 rename 句柄锁失败）。"""

    def test_windows_probe_fallback_in_collect(self, monkeypatch):
        import core.self_update_apply as sua
        import core.systemd_hosting as sh

        monkeypatch.setattr(sh, "systemctl_available", lambda: False)
        calls = {"n": 0}

        def fake_installed(service=sh.DASHBOARD_WINDOWS_SERVICE):
            calls["n"] += 1
            return True

        monkeypatch.setattr(sh, "windows_service_installed", fake_installed)
        monkeypatch.setattr(sh, "windows_service_active", lambda service=None: True)
        # pal D 组 daemon 判定走注入缝外的真实 pal——沙箱路径无服务，异常吞掉
        daemon_roots, dashboard = sua.collect_hosted_targets([])
        assert dashboard is True
        assert calls["n"] == 1

    def test_systemd_hit_skips_windows_probe(self, monkeypatch):
        import core.self_update_apply as sua
        import core.systemd_hosting as sh

        monkeypatch.setattr(sh, "systemctl_available", lambda: True)
        monkeypatch.setattr(sh, "unit_installed", lambda unit: True)
        monkeypatch.setattr(sh, "unit_active", lambda unit: True)
        probe = {"n": 0}

        def fail_probe(service=None):
            probe["n"] += 1
            raise AssertionError("systemd 命中后不应再探测 Windows 服务")

        monkeypatch.setattr(sh, "windows_service_installed", fail_probe)
        _, dashboard = sua.collect_hosted_targets([])
        assert dashboard is True
        assert probe["n"] == 0

    def test_stop_start_units_platform_dispatch(self, monkeypatch):
        import core.platform.api as pal
        import core.self_update_apply as sua
        import core.systemd_hosting as sh

        ops = []
        monkeypatch.setattr(sh, "windows_service_stop",
                            lambda service=None: ops.append("sc-stop"))
        monkeypatch.setattr(sh, "windows_service_start",
                            lambda service=None: ops.append("sc-start"))
        monkeypatch.setattr(sh, "windows_service_wait_stopped",
                            lambda service=None, timeout_s=30.0,
                            poll_interval=0.5: ops.append("sc-wait-stopped")
                            or True)
        monkeypatch.setattr(sh, "stop_unit_no_block",
                            lambda unit: ops.append(f"systemd-stop:{unit}"))
        monkeypatch.setattr(sh, "start_unit_no_block",
                            lambda unit: ops.append(f"systemd-start:{unit}"))

        monkeypatch.setattr(pal, "IS_WINDOWS", True)
        assert sua._default_stop_units([], True) == {"errors": []}
        assert sua._default_start_units([], True) == {"errors": []}
        monkeypatch.setattr(pal, "IS_WINDOWS", False)
        assert sua._default_stop_units([], True) == {"errors": []}
        assert sua._default_start_units([], True) == {"errors": []}
        assert ops == ["sc-stop", "sc-wait-stopped", "sc-start",
                       "systemd-stop:fenix-dashboard.service",
                       "systemd-start:fenix-dashboard.service"]

    def test_sc_query_text_parsing(self, monkeypatch):
        import subprocess
        import core.systemd_hosting as sh

        def fake_sc(args, timeout=15):
            return subprocess.CompletedProcess(
                ["sc", *args], 0,
                stdout="STATE              : 4  RUNNING\n", stderr="")

        monkeypatch.setattr(sh, "_run_sc", fake_sc)
        monkeypatch.setattr(sh.pal, "IS_WINDOWS", True)
        assert sh.windows_service_installed() is True
        assert sh.windows_service_active() is True

        def fake_sc_pending(args, timeout=15):
            return subprocess.CompletedProcess(
                ["sc", *args], 0,
                stdout="STATE              : 3  STOP_PENDING\n", stderr="")

        monkeypatch.setattr(sh, "_run_sc", fake_sc_pending)
        assert sh.windows_service_active() is False

        def fake_sc_missing(args, timeout=15):
            return subprocess.CompletedProcess(["sc", *args], 1060, stdout="", stderr="failed")

        monkeypatch.setattr(sh, "_run_sc", fake_sc_missing)
        assert sh.windows_service_installed() is False
        assert sh.windows_service_active() is False

    def test_non_windows_gates_short_circuit(self, monkeypatch):
        import subprocess
        import core.systemd_hosting as sh

        monkeypatch.setattr(sh.pal, "IS_WINDOWS", False)
        boomed = {"n": 0}

        def boom(args, timeout=15):
            boomed["n"] += 1
            raise AssertionError("非 Windows 不应触达 sc")

        monkeypatch.setattr(sh, "_run_sc", boom)
        assert sh.windows_service_installed() is False
        assert sh.windows_service_active() is False
        sh.windows_service_stop()   # no-op，不触 sc
        sh.windows_service_start()  # no-op，不触 sc
        assert boomed["n"] == 0
