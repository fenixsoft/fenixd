"""tests/test_self_update.py — add-auto-update 任务 1.6

core/self_update.py 检查引擎单元测试：
- 本地版本解析（制品根 VERSION / 缺失 source 形态 / 目录名解析 / 双源优先级）；
- 语义化版本 tuple 比较（数值逐段，非字典序）；
- releases/latest 双腿查询回退（HTTP 层全 mock，不触真实 GitHub）；
- status.json 原子写与 check.lock 互斥、陈锁清扫；
- audits.jsonl 审计追加；
- update.enabled=false 跳过、退避窗与 interval 到期判定。

网络交互全部经 ``http_get`` 注入缝 / token_provider 注入缝 mock。
"""

import json

import pytest
import yaml

import core.self_update as self_update_mod
from core.self_update import (
    APPLY_LOCK_PATH,
    AUDITS_PATH,
    CHECK_LOCK_PATH,
    CHECK_LOCK_STALE_S,
    FORM_ARTIFACT,
    FORM_SOURCE,
    QueryError,
    ReleaseInfo,
    STATUS_PATH,
    UpdateConfig,
    UpdateLock,
    apply_mirror_url,
    compare_versions,
    detect_plugins_state,
    detect_plugins_version,
    download_channel_urls,
    fetch_latest_release,
    is_update_available,
    load_update_config,
    plugins_version_from_dirname,
    read_framework_version,
    read_status,
    run_check,
    run_scheduled_check,
    _fallback_github_token,
)
from core.timelib import from_epoch, now_utc, to_storage


# ── 测试缝 ────────────────────────────────────────────────────────────


def _fake_http(responses):
    """构造 http_get 注入缝：responses = {url: (status, body_dict|bytes)}。

    未登记的 URL 视为测试缺陷（断言失败），防测试静默放过意外请求。
    """
    calls = []

    def http_get(url, headers=None, timeout_s=15.0):
        calls.append({"url": url, "headers": headers or {}})
        if url not in responses:
            raise AssertionError(f"unexpected HTTP GET: {url}")
        status, body = responses[url]
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")
        return status, body

    http_get.calls = calls
    return http_get


def _write_status(update_dir, payload):
    path = update_dir / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def update_dir(tmp_path):
    return tmp_path / "fenix-update"


@pytest.fixture()
def framework_root(tmp_path):
    """制品形态框架根：VERSION=v0.1.7 + 最小骨架。"""
    root = tmp_path / "fenixd"
    root.mkdir()
    (root / "VERSION").write_text("v0.1.7\n", encoding="utf-8")
    return root


# ── 1.1 配置段 ────────────────────────────────────────────────────────


class TestUpdateConfig:
    def test_defaults_on_missing_segment(self):
        # mirror 键缺失 → 缺省镜像通道（2026-11-28 默认镜像语义）
        cfg = load_update_config(config={})
        assert cfg.enabled is True
        assert cfg.interval_hours == 24.0
        assert cfg.mirror == self_update_mod.UPDATE_MIRROR_DEFAULT

    def test_valid_values_taken(self):
        cfg = load_update_config(config={"update": {
            "enabled": False, "interval_hours": 12, "mirror": "https://m.example.com",
        }})
        assert cfg.enabled is False
        assert cfg.interval_hours == 12.0
        assert cfg.mirror == "https://m.example.com"

    def test_invalid_values_fall_back(self):
        # 非字符串垃圾值 = 用户未表达通道选择 → 缺省镜像（不落直连）
        cfg = load_update_config(config={"update": {
            "enabled": "yes",           # 非布尔
            "interval_hours": -3,       # 非正数
            "mirror": 123,              # 非字符串
        }})
        assert cfg.enabled is True
        assert cfg.interval_hours == 24.0
        assert cfg.mirror == self_update_mod.UPDATE_MIRROR_DEFAULT

    def test_explicit_empty_mirror_is_official(self):
        # 显式 ""（设置页选官方持久化形态）= 官方直连，≠ 键缺失
        cfg = load_update_config(config={"update": {"mirror": ""}})
        assert cfg.mirror == ""

    def test_whole_segment_wrong_type(self):
        cfg = load_update_config(config={"update": ["a", "b"]})
        assert cfg == UpdateConfig(mirror=self_update_mod.UPDATE_MIRROR_DEFAULT)

    def test_lenient_load_never_raises(self, monkeypatch, tmp_path):
        # 用户级 config.yaml 缺失/损坏 → 缺省兜底，不抛异常
        import core.self_update as su

        def bad_load(path, label):
            raise ValueError("simulated yaml corruption")

        monkeypatch.setattr(su.ConfigLoader, "_load_optional_yaml", bad_load)
        assert load_update_config() == UpdateConfig(
            mirror=self_update_mod.UPDATE_MIRROR_DEFAULT)


class TestDefaultMirrorChannel:
    """缺省镜像通道（2026-11-28）：三态加载 + 双通道候选列表。"""

    def test_load_tri_state(self):
        # 缺键/显式 null/垃圾 → 缺省镜像；显式 "" → 官方；字符串 → 原样
        assert load_update_config(config={}).mirror == self_update_mod.UPDATE_MIRROR_DEFAULT
        assert load_update_config(
            config={"update": {"mirror": None}}).mirror == self_update_mod.UPDATE_MIRROR_DEFAULT
        assert load_update_config(
            config={"update": {"mirror": ""}}).mirror == ""
        assert load_update_config(config={"update": {
            "mirror": "https://ghproxy.net/https://github.com"}}).mirror \
            == "https://ghproxy.net/https://github.com"

    def test_channel_urls_mirror_first_direct_fallback(self):
        url = "https://github.com/o/r/releases/download/v/a.tar.gz"
        assert download_channel_urls(url, self_update_mod.UPDATE_MIRROR_DEFAULT) == [
            "https://ghfast.top/https://github.com/o/r/releases/download/v/a.tar.gz",
            url,
        ]

    def test_channel_urls_explicit_official_direct_only(self):
        url = "https://github.com/o/r/releases/download/v/a.tar.gz"
        # 显式官方不静默绕道镜像（用户显式选择必须尊重）
        assert download_channel_urls(url, "") == [url]

    def test_channel_urls_custom_mirror(self):
        url = "https://github.com/o/r/releases/download/v/a.tar.gz"
        assert download_channel_urls(url, "https://m.example.com") == [
            "https://m.example.com/o/r/releases/download/v/a.tar.gz", url,
        ]

    def test_channel_urls_non_download_prefix_passthrough(self):
        # 非 GitHub 制品前缀 URL（apply_mirror_url 不替换）→ 单元素列表
        url = "https://example.com/a.tar.gz"
        assert download_channel_urls(url, self_update_mod.UPDATE_MIRROR_DEFAULT) == [url]
        assert download_channel_urls(None, "https://m.example.com") == []


# ── 1.2 版本解析与比较 ────────────────────────────────────────────────


class TestFrameworkVersion:
    def test_artifact_form_reads_version(self, framework_root):
        lv = read_framework_version(framework_root)
        assert lv.version == "v0.1.7"
        assert lv.form == FORM_ARTIFACT

    def test_missing_version_is_source(self, tmp_path):
        root = tmp_path / "src-tree"
        root.mkdir()
        lv = read_framework_version(root)
        assert lv.version is None
        assert lv.form == FORM_SOURCE

    def test_unreadable_version_is_source(self, tmp_path):
        root = tmp_path / "broken"
        root.mkdir()
        (root / "VERSION").write_bytes(b"\xff\xfe\x00")
        lv = read_framework_version(root)
        assert lv.form == FORM_SOURCE

    def test_blank_version_is_source(self, tmp_path):
        root = tmp_path / "blank"
        root.mkdir()
        (root / "VERSION").write_text("  \n", encoding="utf-8")
        assert read_framework_version(root).form == FORM_SOURCE


class TestPluginsVersion:
    def test_dirname_parse(self):
        assert plugins_version_from_dirname("dsh-plugins-v0.1.2") == "v0.1.2"
        assert plugins_version_from_dirname("dsh-plugins-0.2.0") == "0.2.0"
        assert plugins_version_from_dirname("cc-import") is None
        assert plugins_version_from_dirname("dsh-plugins") is None

    def test_root_version_takes_priority(self, tmp_path):
        root = tmp_path / "dsh-plugins-v0.1.1"
        root.mkdir()
        (root / "VERSION").write_text("v0.1.9", encoding="utf-8")
        lv = detect_plugins_version(root)
        assert lv.version == "v0.1.9"  # 制品根 VERSION 优先于目录名
        assert lv.form == FORM_ARTIFACT

    def test_dirname_fallback(self, tmp_path):
        root = tmp_path / "dsh-plugins-v0.1.2"
        root.mkdir()
        lv = detect_plugins_version(root)
        assert lv.version == "v0.1.2"

    def test_unresolvable_is_unknown(self, tmp_path):
        root = tmp_path / "my-plugins"
        root.mkdir()
        assert detect_plugins_version(root).form == "unknown"


class TestDetectPluginsState:
    def test_scan_profiles_link_deps(self, tmp_path):
        home = tmp_path / ".dsh"
        pdir = home / "profiles" / "fenix"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "name": "dsh-profile-fenix",
            "dependencies": {
                "fenix-dsh-auth": "link:/opt/plugins/dsh-plugins-v0.1.2/fenix-dsh-auth",
                "dsh-plugin-loopback-trust": "link:/opt/other/loopback-trust",
            },
        }), encoding="utf-8")
        state = detect_plugins_state(profiles_dir=home / "profiles")
        assert state["form"] == FORM_ARTIFACT
        assert state["version"] == "v0.1.2"
        fenix = state["profiles"]["fenix"]
        assert fenix["version"] == "v0.1.2"
        # dsh 手册（dsh-plugins 仓 docs/install-dsh-plugins.md）§4 逐插件注册形态：link 指向插件包目录，版本从其父目录解析
        assert fenix["plugin_root"].endswith("dsh-plugins-v0.1.2/fenix-dsh-auth")

    def test_link_direct_to_version_root(self, tmp_path):
        home = tmp_path / ".dsh"
        pdir = home / "profiles" / "fenix"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "dependencies": {
                "fenix-dsh-auth": "link:/opt/plugins/dsh-plugins-v0.1.3",
            },
        }), encoding="utf-8")
        state = detect_plugins_state(profiles_dir=home / "profiles")
        assert state["version"] == "v0.1.3"  # spec Scenario：link 直指版本根

    def test_dev_checkout_without_tag_is_unknown(self, tmp_path):
        home = tmp_path / ".dsh"
        pdir = home / "profiles" / "fenix"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "dependencies": {"fenix-dsh-bundle": "link:/repo/dsh-plugins"},
        }), encoding="utf-8")
        state = detect_plugins_state(profiles_dir=home / "profiles")
        assert state["version"] is None

    def test_no_profiles_is_unknown(self, tmp_path):
        state = detect_plugins_state(profiles_dir=tmp_path / "absent")
        assert state["profiles"] == {}
        assert state["version"] is None

    def test_corrupt_package_json_skipped(self, tmp_path):
        home = tmp_path / ".dsh"
        pdir = home / "profiles" / "broken"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text("{not json", encoding="utf-8")
        state = detect_plugins_state(profiles_dir=home / "profiles")
        assert state["profiles"]["broken"]["version"] is None


class TestVersionCompare:
    def test_numeric_not_lexicographic(self):
        assert compare_versions("v0.1.7", "v0.1.10") == -1
        assert compare_versions("v0.1.10", "v0.1.7") == 1
        assert compare_versions("0.1.10", "0.1.9") == 1

    def test_equal_forms(self):
        assert compare_versions("v0.1.7", "0.1.7") == 0
        assert compare_versions("1.2", "1.2.0") == 0

    def test_major_minor_ordering(self):
        assert compare_versions("v1.0.0", "v0.9.9") == 1
        assert compare_versions("v0.2.0", "v0.1.99") == 1

    def test_non_numeric_segments_string_compare(self):
        assert compare_versions("v0.1.7-beta", "v0.1.7") == 1  # 字符串段排在数字段后
        assert compare_versions("v0.1.7-beta", "v0.1.7-alpha") == 1

    def test_is_update_available(self):
        assert is_update_available("v0.1.7", "v0.1.8") is True
        assert is_update_available("v0.1.7", "v0.1.7") is False
        assert is_update_available("v0.1.7", "v0.1.6") is False
        assert is_update_available(None, "v0.1.8") is False
        assert is_update_available("v0.1.7", None) is False


# ── 1.3 双腿远端查询 ──────────────────────────────────────────────────


def _release_body(repo, tag, assets):
    return {
        "tag_name": tag,
        "assets": [{"name": n, "browser_download_url":
                    f"https://github.com/{repo}/releases/download/{tag}/{n}"}
                   for n in assets],
    }


class TestFetchLatestRelease:
    def test_anonymous_query_public_repo(self):
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8",
                                    ["fenixd-v0.1.8.tar.gz", "fenixd-v0.1.8.zip"])),
        })
        info = fetch_latest_release("fenixsoft/fenixd", http_get=http)
        assert info.tag_name == "v0.1.8"
        assert info.tarball_url.endswith("fenixd-v0.1.8.tar.gz")
        assert info.zip_url.endswith("fenixd-v0.1.8.zip")
        assert http.calls[0]["headers"].get("Authorization") is None

    def test_private_repo_falls_back_to_token(self):
        url = "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/latest"
        http = _fake_http({
            url: (200, _release_body("fenixsoft/dsh-plugins", "v0.1.3",
                                     ["dsh-plugins-v0.1.3.zip"])),
        })
        tokens = iter(["tok-1"])

        def token_provider():
            return next(tokens)

        info = fetch_latest_release("fenixsoft/dsh-plugins",
                                    http_get=http, token_provider=token_provider)
        assert info.tag_name == "v0.1.3"
        # 第二次调用才带凭证？不——匿名 200 成功即不再取凭证
        assert len(http.calls) == 1

    def test_401_then_credential_retry(self):
        url = "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/latest"
        http = _fake_http({
            url: (200, _release_body("fenixsoft/dsh-plugins", "v0.1.3",
                                     ["dsh-plugins-v0.1.3.zip"])),
        })
        # 首次匿名返回 401：动态切换 responses
        real_get = http

        def http_get(url_, headers=None, timeout_s=15.0):
            real_get.calls.append({"url": url_, "headers": headers or {}})
            if len(real_get.calls) == 1:
                return 401, b'{"message":"Requires authentication"}'
            return real_get(url_, headers, timeout_s)

        info = fetch_latest_release("fenixsoft/dsh-plugins",
                                    http_get=http_get,
                                    token_provider=lambda: "tok")
        assert info.tag_name == "v0.1.3"
        assert real_get.calls[0]["headers"].get("Authorization") is None
        assert real_get.calls[1]["headers"]["Authorization"] == "Bearer tok"

    def test_both_legs_fail_raises_query_error(self):
        def http_get(url_, headers=None, timeout_s=15.0):
            return 401, b"unauthorized"

        with pytest.raises(QueryError) as ei:
            fetch_latest_release("fenixsoft/dsh-plugins", http_get=http_get,
                                 token_provider=lambda: None)
        assert "凭证" in str(ei.value)

    def test_rate_limit_no_retry(self):
        calls = []

        def http_get(url_, headers=None, timeout_s=15.0):
            calls.append(1)
            return 403, b"rate limited"

        with pytest.raises(QueryError):
            fetch_latest_release("fenixsoft/fenixd", http_get=http_get,
                                 token_provider=lambda: "tok")
        assert len(calls) == 1  # 403 不走凭证腿、不重试

    def test_bad_json_raises(self):
        with pytest.raises(QueryError):
            fetch_latest_release(
                "fenixsoft/fenixd",
                http_get=lambda u, h=None, t=15.0: (200, b"<html>not json"),
            )

    def test_missing_tag_raises(self):
        with pytest.raises(QueryError):
            fetch_latest_release(
                "fenixsoft/fenixd",
                http_get=lambda u, h=None, t=15.0: (200, b'{"assets": []}'),
            )


class TestMirror:
    def test_replaces_download_prefix_only(self):
        url = "https://github.com/fenixsoft/fenixd/releases/download/v0.1.8/x.tar.gz"
        assert apply_mirror_url(url, "https://mirror.example.com") == (
            "https://mirror.example.com/fenixsoft/fenixd/releases/download/v0.1.8/x.tar.gz"
        )

    def test_api_domain_never_replaced(self):
        api = "https://api.github.com/repos/fenixsoft/fenixd/releases/latest"
        assert apply_mirror_url(api, "https://mirror.example.com") == api

    def test_empty_mirror_passthrough(self):
        url = "https://github.com/a/b/releases/download/v1/x.zip"
        assert apply_mirror_url(url, "") == url
        assert apply_mirror_url(url, "  ") == url

    def test_none_passthrough(self):
        assert apply_mirror_url(None, "https://m.example.com") is None


class TestCredentialLegs:
    def test_gh_cli_token(self, monkeypatch):
        import core.self_update as su

        class R:
            returncode = 0
            stdout = "ghs_token_123\n"

        monkeypatch.setattr(su.subprocess, "run",
                            lambda *a, **k: R(), raising=False)
        assert _fallback_github_token() == "ghs_token_123"

    def test_gh_cli_missing_falls_to_git_credential(self, monkeypatch):
        import core.self_update as su

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["gh", "auth"]:
                raise FileNotFoundError("no gh")

            class R:
                returncode = 0
                stdout = "protocol=https\nhost=github.com\npassword=git_tok\n"

            return R()

        monkeypatch.setattr(su.subprocess, "run", fake_run)
        assert _fallback_github_token() == "git_tok"

    def test_both_missing_returns_none(self, monkeypatch):
        import core.self_update as su

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("none")

        monkeypatch.setattr(su.subprocess, "run", fake_run)
        assert _fallback_github_token() is None


# ── 1.4 锁 / 状态 / 审计 ──────────────────────────────────────────────


class TestUpdateLock:
    def test_acquire_release(self, tmp_path):
        lock = UpdateLock(tmp_path / "l.lock", stale_s=60)
        assert lock.acquire() is True
        assert UpdateLock.is_locked(tmp_path / "l.lock")
        lock.release()
        assert not UpdateLock.is_locked(tmp_path / "l.lock")

    def test_mutual_exclusion(self, tmp_path):
        first = UpdateLock(tmp_path / "l.lock", stale_s=3600)
        second = UpdateLock(tmp_path / "l.lock", stale_s=3600)
        assert first.acquire() is True
        assert second.acquire() is False  # 他方持锁
        first.release()
        assert second.acquire() is True

    def test_stale_lock_swept(self, tmp_path):
        import os
        import time

        path = tmp_path / "l.lock"
        path.write_text("{}", encoding="utf-8")
        # 把 mtime 拨回超龄（陈锁 = 持锁进程已死）
        old = time.time() - CHECK_LOCK_STALE_S - 10
        os.utime(path, (old, old))
        latecomer = UpdateLock(path, stale_s=CHECK_LOCK_STALE_S)
        assert latecomer.acquire() is True  # 陈锁被清扫后占位成功
        latecomer.release()


class TestStatusAndAudit:
    def test_read_status_missing_is_none(self, update_dir):
        assert read_status(update_dir / "status.json") is None

    def test_write_and_read_roundtrip(self, update_dir):
        path = update_dir / "status.json"
        from core.self_update import write_status

        write_status({"framework": {"local_version": "v0.1.7"}}, path)
        assert read_status(path)["framework"]["local_version"] == "v0.1.7"

    def test_update_status_merges(self, update_dir):
        path = update_dir / "status.json"
        from core.self_update import update_status

        update_status({"framework": {"a": 1}}, path)
        update_status({"plugins": {"b": 2}}, path)
        st = read_status(path)
        assert st["framework"] == {"a": 1}
        assert st["plugins"] == {"b": 2}

    def test_corrupt_status_reads_none(self, update_dir):
        path = update_dir / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json{", encoding="utf-8")
        assert read_status(path) is None

    def test_audit_appended(self, update_dir):
        audits = update_dir / "audits.jsonl"
        from core.self_update import append_audit

        append_audit({"kind": "check", "result": "success"}, audits)
        append_audit({"kind": "apply", "result": "success"}, audits)
        lines = audits.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["kind"] == "check"
        assert json.loads(lines[1])["kind"] == "apply"


# ── 1.4/1.5 检查编排 ──────────────────────────────────────────────────


class TestRunCheck:
    def test_artifact_check_success(self, framework_root, update_dir):
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8",
                                    ["fenixd-v0.1.8.tar.gz", "fenixd-v0.1.8.zip"])),
        })
        st = run_check("test", framework_root=framework_root,
                       profiles_dir=framework_root / "no-profiles",
                       update_dir=update_dir, http_get=http,
                       config=UpdateConfig())
        assert st["framework"]["local_version"] == "v0.1.7"
        assert st["framework"]["remote_version"] == "v0.1.8"
        assert st["framework"]["update_available"] is True
        # 插件面无安装态（无 profiles）属正常 absent，不计失败
        assert st["last_error"] is None
        assert st["failure_count"] == 0
        assert st["next_check_after"] is None

    def test_single_leg_failure_isolated(self, framework_root, update_dir):
        # 插件面有安装态但远端查询双腿全败 → 插件边失败、框架边不受影响
        home = update_dir / ".dsh"
        pdir = home / "profiles" / "fenix"
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({
            "dependencies": {"fenix-dsh-auth": "link:/opt/dsh-plugins-v0.1.2/cc-x"},
        }), encoding="utf-8")
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8", ["x.tar.gz"])),
            "https://api.github.com/repos/fenixsoft/dsh-plugins/releases/latest":
                (404, b"not found"),
        })
        st = run_check("test", framework_root=framework_root,
                       profiles_dir=home / "profiles", update_dir=update_dir,
                       http_get=http, config=UpdateConfig())
        assert st["framework"]["remote_version"] == "v0.1.8"  # 框架边成功
        assert st["last_error"] is not None  # 插件边双腿全败
        assert st["failure_count"] == 1
        assert st["next_check_after"] is not None  # 进入退避

    def test_source_form_skips_remote_query(self, tmp_path, update_dir):
        src_root = tmp_path / "src"
        src_root.mkdir()
        http = _fake_http({})  # 零网络请求
        st = run_check("test", framework_root=src_root,
                       profiles_dir=src_root, update_dir=update_dir,
                       http_get=http, config=UpdateConfig())
        assert st["framework"]["form"] == FORM_SOURCE
        assert st["framework"]["update_available"] is False
        assert st["last_error"] is None
        assert st["failure_count"] == 0

    def test_up_to_date_no_update(self, framework_root, update_dir):
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.7", ["x.tar.gz"])),
        })
        st = run_check("test", framework_root=framework_root,
                       profiles_dir=framework_root / "absent",
                       update_dir=update_dir, http_get=http,
                       config=UpdateConfig())
        # 框架侧成功 → 即便插件侧无安装态也不计失败
        assert st["framework"]["update_available"] is False
        assert st["last_error"] is None
        assert st["last_success_at"] is not None

    def test_concurrent_check_lock_short_circuits(self, framework_root, update_dir):
        # 预占检查锁 → run_check 跳过并返回现有状态
        lock = UpdateLock(update_dir / "check.lock", stale_s=3600)
        assert lock.acquire() is True
        _write_status(update_dir, {"framework": {"local_version": "v0.1.7"}})
        st = run_check("test", framework_root=framework_root,
                       update_dir=update_dir, http_get=_fake_http({}),
                       config=UpdateConfig())
        assert st["skipped"] == "locked"
        assert st["status"]["framework"]["local_version"] == "v0.1.7"
        lock.release()

    def test_audit_written_for_check(self, framework_root, update_dir):
        run_check("cli", framework_root=framework_root,
                  profiles_dir=framework_root / "absent",
                  update_dir=update_dir, http_get=_fake_http({}),
                  config=UpdateConfig())
        audits = update_dir / "audits.jsonl"
        lines = audits.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[-1])
        assert entry["kind"] == "check"
        assert entry["source"] == "cli"
        assert entry["result"] in ("success", "failure")

    def test_mirror_flows_into_asset_urls(self, framework_root, update_dir):
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8",
                                    ["fenixd-v0.1.8.tar.gz"])),
        })
        st = run_check("test", framework_root=framework_root,
                       profiles_dir=framework_root / "absent",
                       update_dir=update_dir, http_get=http,
                       config=UpdateConfig(mirror="https://m.example.com"))
        assert st["framework"]["tarball_url"].startswith("https://m.example.com/")


class TestScheduledCheck:
    def _status_with_last_check(self, update_dir, **extra):
        base = {"last_check_at": to_storage(now_utc()), "last_success_at":
                to_storage(now_utc()), "last_error": None, "failure_count": 0}
        base.update(extra)
        return _write_status(update_dir, base)

    def test_disabled_short_circuits(self, framework_root, update_dir):
        st = run_scheduled_check(
            framework_root=framework_root, update_dir=update_dir,
            config=UpdateConfig(enabled=False), http_get=_fake_http({}),
        )
        assert st == {"skipped": "disabled"}

    def test_not_due_within_interval(self, framework_root, update_dir):
        self._status_with_last_check(update_dir)
        st = run_scheduled_check(
            framework_root=framework_root, update_dir=update_dir,
            config=UpdateConfig(interval_hours=24.0), http_get=_fake_http({}),
        )
        assert st == {"skipped": "not-due"}

    def test_due_after_interval_runs_check(self, framework_root, update_dir):
        from core.timelib import from_epoch

        stale = to_storage(from_epoch(now_utc().timestamp() - 25 * 3600))
        _write_status(update_dir, {"last_check_at": stale})
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8", ["x.tar.gz"])),
        })
        st = run_scheduled_check(
            framework_root=framework_root, update_dir=update_dir,
            config=UpdateConfig(interval_hours=24.0), http_get=http,
        )
        assert "framework" in st  # 真正执行了检查
        assert st["framework"]["remote_version"] == "v0.1.8"

    def test_backoff_window_blocks_retry(self, framework_root, update_dir):
        future = now_utc() + __import__("datetime").timedelta(hours=1)
        _write_status(update_dir, {
            "last_check_at": to_storage(now_utc()),
            "next_check_after": to_storage(future),
            "failure_count": 1,
        })
        st = run_scheduled_check(
            framework_root=framework_root, update_dir=update_dir,
            config=UpdateConfig(), http_get=_fake_http({}),
        )
        assert st == {"skipped": "backoff"}

    def test_first_check_when_no_status(self, framework_root, update_dir):
        http = _fake_http({
            "https://api.github.com/repos/fenixsoft/fenixd/releases/latest":
                (200, _release_body("fenixsoft/fenixd", "v0.1.8", ["x.tar.gz"])),
        })
        st = run_scheduled_check(
            framework_root=framework_root, update_dir=update_dir,
            config=UpdateConfig(), http_get=http,
        )
        assert "framework" in st

    def test_never_raises_on_engine_bug(self, framework_root, update_dir, monkeypatch):
        import core.self_update as su

        def boom(*a, **k):
            raise RuntimeError("engine bug")

        monkeypatch.setattr(su, "load_update_config", boom)
        st = run_scheduled_check(framework_root=framework_root,
                                 update_dir=update_dir)
        assert "error" in st  # 顶层自吞，绝不抛告警

    def test_backoff_grows_with_failures(self, framework_root, update_dir):
        from core.self_update import _backoff_hours

        assert _backoff_hours(1, 24.0) == 1.0
        assert _backoff_hours(2, 24.0) == 2.0
        assert _backoff_hours(3, 24.0) == 4.0
        assert _backoff_hours(10, 24.0) == 24.0  # 封顶 interval


class TestMirrorSourceSelect:
    """下载源自选（2026-11-28 dashboard 设置页）：镜像值校验单源在引擎。

    落盘单源在 dashboard 侧 ``config_admin.write_update_mirror``（与设置页
    保存同锁），本文件只测引擎侧语义（normalize/预设形态）与跨层回读。
    """

    def test_normalize_official_empty(self):
        assert self_update_mod.normalize_mirror("") == ""
        assert self_update_mod.normalize_mirror("   ") == ""

    def test_normalize_accepts_host_and_ghproxy_tail(self):
        assert self_update_mod.normalize_mirror("https://ghfast.top/https://github.com") \
            == "https://ghfast.top/https://github.com"
        # 尾斜杠归一剥除
        assert self_update_mod.normalize_mirror("https://kkgithub.com/") == "https://kkgithub.com"
        assert self_update_mod.normalize_mirror("https://m.local:8443/gh") == "https://m.local:8443/gh"

    def test_normalize_rejects_loose_injection_surface(self):
        # mirror 是下载 URL 前缀拼接值：用户信息/查询/片段/编码字符/非 https 一律拒
        for bad in ("http://x.com", "ftp://x", "https://u:p@h.com/x",
                    "https://h.com/a?b=c", "https://h.com/a#f",
                    "https://h.com/%2f", "a b", "https://h.com/<x>",
                    None, 123):
            assert self_update_mod.normalize_mirror(bad) is None, bad

    def test_presets_shape_and_values_valid(self):
        ids = [p["id"] for p in self_update_mod.UPDATE_MIRROR_PRESETS]
        assert ids == ["official", "ghfast", "ghproxy"]
        for p in self_update_mod.UPDATE_MIRROR_PRESETS:
            assert self_update_mod.normalize_mirror(p["url"]) == p["url"]
