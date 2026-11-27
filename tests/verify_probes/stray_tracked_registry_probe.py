#!/usr/bin/env python3
"""evo-persist-stray-tracked-registry 验证探针（快车道场景执行用）。

在进程内真实 git 仓库夹具上驱动 MainTreeStrayWipSweeper（生产实现，
WorktreeManager 以 mixin 探针壳最小装配，同 tests/test_maintree_stray_wip_
sweep.py 装配口径），逐子命令验证 tracked 注册表落盘与同指纹 24h 静默窗。
输出单行 JSON（--json）：{"subcommand","ok","checks":[[名称,是否通过,详情]]}，
全过退出码 0、任一失败退出码 1——场景断言消费 exit_code 与 json_output。

用法：python3 tests/verify_probes/stray_tracked_registry_probe.py <sub> --json
子命令：persist-roundtrip | restart-continuity | silence-window-suppression |
realert-after-window | fingerprint-evolution | attribution-pop-keeps-history |
load-oserror-no-overwrite | corruption-failopen-selfheal | history-eviction
"""

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

# 脚本目录两级上＝仓库根（sys.path[0] 是脚本目录，import core 需显式注入；
# 兼容从验证树根/仓根任意 cwd 调用）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from core.admin_store import AdminStore, SIGNAL  # noqa: E402
from core.worktree_manager import stray_wip  # noqa: E402
from core.worktree_manager.stray_wip import (  # noqa: E402
    ALERT_SILENCE_WINDOW_SECONDS,
    SIGNAL_TYPE,
    TRACKED_REGISTRY_RELPATH,
    MainTreeStrayWipSweeper,
)

_TMP_ROOT = _REPO_ROOT / ".history" / "tmp"


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )


def _make_repo():
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="stray-probe-", dir=str(_TMP_ROOT)))
    repo = base / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "a.tsx").write_text("main wip", encoding="utf-8")  # 散件 WIP
    return repo


class _WmProbe:
    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _sweeper(repo):
    return MainTreeStrayWipSweeper(
        repo,
        _WmProbe(repo),
        config={"admin": {"maintree_stray_wip_grace_minutes": 0}},
    )


def _alerts(repo):
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL and r.get("signal_type") == SIGNAL_TYPE
    ]


def _payload(repo):
    return json.loads((repo / TRACKED_REGISTRY_RELPATH).read_text("utf-8"))


def _run(name, checks, repo=None):
    import shutil

    if repo is not None:
        shutil.rmtree(repo.parent, ignore_errors=True)
    ok = all(c[1] for c in checks)
    print(
        json.dumps(
            {
                "subcommand": name,
                "ok": ok,
                "failed": [c[0] for c in checks if not c[1]],
                "checks": [
                    {"name": c[0], "pass": bool(c[1]), "detail": str(c[2])}
                    for c in checks
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


def _backdate(sw, fp, delta):
    sw._alert_history[fp]["last_alert_at"] = (
        time.time() - ALERT_SILENCE_WINDOW_SECONDS - delta
    )


def cmd_persist_roundtrip():
    repo = _make_repo()
    sw = _sweeper(repo)
    r1 = sw.sweep()
    regf = repo / TRACKED_REGISTRY_RELPATH
    checks = [("首启告警(grace=0)", r1["status"] == "alerted", r1["status"])]
    payload = _payload(repo) if regf.exists() else {}
    fp = r1["fingerprint"]
    checks += [
        ("注册表文件存在", regf.exists(), str(regf)),
        ("顶层两分区", sorted(payload.keys()) == ["alert_history", "tracked"],
         sorted(payload.keys())),
        ("计时条目字段白名单", sorted(payload.get("tracked", {}).get(fp, {}))
         == ["escalated_at", "files", "first_seen", "first_seen_iso"],
         sorted(payload.get("tracked", {}).get(fp, {}))),
        ("台账条目字段白名单", sorted(payload.get("alert_history", {}).get(fp, {}))
         == ["last_alert_at", "suppressed_count"],
         sorted(payload.get("alert_history", {}).get(fp, {}))),
        ("无半程临时文件", list((repo / ".fenix").glob(".stray_tracked*")) == [],
         "tmp+replace 原子写"),
    ]
    return _run("persist-roundtrip", checks, repo)


def cmd_restart_continuity():
    repo = _make_repo()
    sw = _sweeper(repo)
    r1 = sw.sweep()
    fp = r1["fingerprint"]
    first_seen = sw._registry[fp]["first_seen"]
    escalated_at = sw._registry[fp]["escalated_at"]
    last_alert_at = sw._alert_history[fp]["last_alert_at"]
    # 重启模拟：全新实例从盘上注册表恢复（内存态清零）。
    sw2 = _sweeper(repo)
    pre_empty = sw2._registry == {} and sw2._alert_history == {}
    r2 = sw2.sweep()
    checks = [
        ("首启告警", r1["status"] == "alerted", r1["status"]),
        ("重启后内存态清零", pre_empty, "fresh instance"),
        ("重启后窗内抑制(不重告)", r2["status"] == "orphan-timed"
         and len(_alerts(repo)) == 1, r2["status"]),
        ("first_seen 跨重启连续", sw2._registry[fp]["first_seen"] == first_seen,
         "未以当轮时刻重登记"),
        ("escalated_at 随盘存活", sw2._registry[fp]["escalated_at"] == escalated_at,
         escalated_at),
        ("台账 last_alert_at 跨重启连续",
         sw2._alert_history[fp]["last_alert_at"] == last_alert_at,
         "静默窗跨重启连续"),
        ("抑制计数持久化", _payload(repo)["alert_history"][fp]["suppressed_count"] == 1,
         "suppressed_count=1"),
    ]
    return _run("restart-continuity", checks, repo)


def cmd_silence_window_suppression():
    repo = _make_repo()
    sw = _sweeper(repo)
    r1 = sw.sweep()
    fp = r1["fingerprint"]
    keys0 = set()
    counts = []
    statuses = []
    for _ in range(3):
        r = sw.sweep()
        statuses.append(r["status"])
        counts.append(sw._alert_history[fp]["suppressed_count"])
        keys0 = set(r.keys())
    checks = [
        ("首启告警恰一条", r1["status"] == "alerted" and len(_alerts(repo)) == 1,
         len(_alerts(repo))),
        ("抑制轮 status=orphan-timed", statuses == ["orphan-timed"] * 3, statuses),
        ("返回键集稳定(含抑制轮)", len(keys0) >= 6 and "fingerprint" in keys0,
         sorted(keys0)),
        ("suppressed_count 累计 1/2/3", counts == [1, 2, 3], counts),
        ("抑制轮零 AdminStore 写入", len(_alerts(repo)) == 1, len(_alerts(repo))),
        ("抑制计数落盘", _payload(repo)["alert_history"][fp]["suppressed_count"] == 3,
         "persisted"),
    ]
    return _run("silence-window-suppression", checks, repo)


def cmd_realert_after_window():
    repo = _make_repo()
    sw = _sweeper(repo)
    fp = sw.sweep()["fingerprint"]
    sw.sweep()
    sw.sweep()  # 抑制两轮
    _backdate(sw, fp, 60)  # 满 24h（回拨 last_alert_at）
    r = sw.sweep()
    alerts = _alerts(repo)
    newest = alerts[0].get("evidence") if alerts else ""
    checks = [
        ("满窗重告", r["status"] == "alerted", r["status"]),
        ("AdminStore 恰两条", len(alerts) == 2, len(alerts)),
        ("重告 evidence 携带静默窗抑制轮数=2",
         "静默窗抑制轮数=2" in (newest or ""), "新记录在前"),
        ("首次告警无抑制轮数注记",
         "静默窗抑制轮数" not in ((alerts[-1].get("evidence") or "") if alerts else ""),
         "分列不混"),
        ("重告后台账刷新归零", sw._alert_history[fp]["suppressed_count"] == 0
         and sw._alert_history[fp]["last_alert_at"] > time.time() - 5,
         "last_alert_at 刷新"),
    ]
    return _run("realert-after-window", checks, repo)


def cmd_fingerprint_evolution():
    repo = _make_repo()
    sw = _sweeper(repo)
    r1 = sw.sweep()
    fp1 = r1["fingerprint"]
    sw.sweep()  # fp1 抑制一轮
    (repo / "a.tsx").write_text("main wip evolved", encoding="utf-8")
    r2 = sw.sweep()
    checks = [
        ("指纹演进＝新 fp", r2["fingerprint"] != fp1, "diff 字节级演进"),
        ("新指纹按常规宽限正常告警", r2["status"] == "alerted"
         and len(_alerts(repo)) == 2, r2["status"]),
        ("计时复位(新条目重新起算)", fp1 not in sw._registry
         and sw._registry[r2["fingerprint"]]["first_seen"] > time.time() - 5,
         "clock reset"),
        ("旧指纹台账保留至淘汰", fp1 in sw._alert_history
         and r2["fingerprint"] in sw._alert_history, "evolution 不清台账"),
    ]
    return _run("fingerprint-evolution", checks, repo)


def cmd_attribution_pop_keeps_history():
    repo = _make_repo()
    base = repo.parent
    ts = 1700000000
    _git(repo, "worktree", "add", "-b", f"fenix/holder-{ts}",
         str(base / f"impl-holder-{ts}"), "HEAD")
    wtf = base / f"impl-holder-{ts}" / "a.tsx"
    wtf.write_text("branch change", encoding="utf-8")
    _git(base / f"impl-holder-{ts}", "commit", "-aqm", "branch wip")
    sw = _sweeper(repo)
    r1 = sw.sweep(running_run_ids=[])
    fp = r1["fingerprint"]
    r2 = sw.sweep(running_run_ids=[f"impl-holder-{ts}-a1"])  # 车道命中 → pop
    popped = fp not in sw._registry  # 即时捕获（r3 会重登记同 fp）
    r3 = sw.sweep(running_run_ids=[])  # 归因消失 → 重登记
    checks = [
        ("无主建档告警", r1["status"] == "alerted", r1["status"]),
        ("车道命中 pop 计时条目", r2["status"] == "holder" and popped,
         r2["status"]),
        ("pop 不清静默窗台账", fp in sw._alert_history, "ledger kept"),
        ("归因消失重登记窗内不重告", r3["status"] == "orphan-timed"
         and len(_alerts(repo)) == 1
         and sw._alert_history[fp]["suppressed_count"] == 1, r3["status"]),
    ]
    return _run("attribution-pop-keeps-history", checks, repo)


def cmd_load_oserror_no_overwrite():
    repo = _make_repo()
    _sweeper(repo).sweep()  # 建档落盘
    regf = repo / TRACKED_REGISTRY_RELPATH
    original = regf.read_bytes()
    real_read_text = Path.read_text

    def _boom(self, *a, **k):
        if self == regf:
            raise OSError(5, "EIO (simulated)")
        return real_read_text(self, *a, **k)

    sw2 = _sweeper(repo)
    with mock.patch.object(Path, "read_text", _boom):
        r = sw2.sweep()  # 载入失败 → 空表重新建档告警，禁写保盘
    checks = [
        ("载入 OSError 轮照常告警(fail-open)", r["status"] == "alerted"
         and len(_alerts(repo)) == 2, r["status"]),
        ("禁写哨兵置位", sw2._tracked_persist_suppressed is True, "sentinel"),
        ("盘上完好注册表未被覆写", regf.read_bytes() == original,
         "本进程不回写"),
    ]
    return _run("load-oserror-no-overwrite", checks, repo)


def cmd_corruption_failopen_selfheal():
    # 字节层损坏：禁写保盘
    repo1 = _make_repo()
    _sweeper(repo1).sweep()
    reg1 = repo1 / TRACKED_REGISTRY_RELPATH
    reg1.write_bytes(b"\xff\xfe\x00broken-utf8")
    sw1 = _sweeper(repo1)
    r1 = sw1.sweep()
    checks1 = [
        ("字节层损坏：盘点不阻断照常告警", r1["status"] == "alerted"
         and len(_alerts(repo1)) == 2, r1["status"]),
        ("字节层损坏：禁写保盘", sw1._tracked_persist_suppressed
         and reg1.read_bytes() == b"\xff\xfe\x00broken-utf8", "kept"),
    ]
    if not all(c[1] for c in checks1):
        return _run("corruption-failopen-selfheal", checks1, repo1)
    # JSON 层真损坏：回退空表 + 覆写自愈
    reg1.write_text("{not json", encoding="utf-8")
    sw2 = _sweeper(repo1)
    r2 = sw2.sweep()
    payload = _payload(repo1)
    checks2 = checks1 + [
        ("JSON 层损坏：回退空表不阻断", r2["status"] == "alerted", r2["status"]),
        ("JSON 层损坏：覆写自愈恢复合法两分区",
         sorted(payload.keys()) == ["alert_history", "tracked"]
         and r2["fingerprint"] in payload["tracked"]
         and r2["fingerprint"] in payload["alert_history"], "self-healed"),
        ("JSON 层损坏不禁写", sw2._tracked_persist_suppressed is False,
         "覆写自愈通道"),
    ]
    return _run("corruption-failopen-selfheal", checks2, repo1)


def cmd_history_eviction():
    repo = _make_repo()
    sw = _sweeper(repo)
    fp = sw.sweep()["fingerprint"]
    _backdate(sw, fp, 60)
    sw.sweep()  # 在场 + 超窗 → 重告（不淘汰：缺席条件不成立）
    kept_after_realert = fp in sw._alert_history
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "commit stray")  # 散件提交 → 指纹消失
    _backdate(sw, fp, 60)
    sw.sweep()  # clean 轮：不在场 + 超窗 → 淘汰
    evicted = fp not in sw._alert_history
    payload_empty = _payload(repo)["alert_history"] == {}
    # 对照：不在场但窗内 → 保留
    (repo / "a.tsx").write_text("reset content", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline shift")
    (repo / "a.tsx").write_text("main wip again", encoding="utf-8")
    sw2 = _sweeper(repo)
    r = sw2.sweep()
    fp2 = r["fingerprint"]
    (repo / "a.tsx").write_text("reset content", encoding="utf-8")  # clean
    sw2.sweep()
    kept_in_window = fp2 in sw2._alert_history
    checks = [
        ("在场+超窗：重告且不淘汰", kept_after_realert, "conjunct guard"),
        ("不在场+超窗：台账淘汰", evicted and payload_empty, "evicted"),
        ("不在场+窗内：台账保留(对照)", kept_in_window, "control"),
        ("对照轮新指纹照常告警", r["status"] == "alerted", r["status"]),
    ]
    return _run("history-eviction", checks, repo)


SUBCOMMANDS = {
    "persist-roundtrip": cmd_persist_roundtrip,
    "restart-continuity": cmd_restart_continuity,
    "silence-window-suppression": cmd_silence_window_suppression,
    "realert-after-window": cmd_realert_after_window,
    "fingerprint-evolution": cmd_fingerprint_evolution,
    "attribution-pop-keeps-history": cmd_attribution_pop_keeps_history,
    "load-oserror-no-overwrite": cmd_load_oserror_no_overwrite,
    "corruption-failopen-selfheal": cmd_corruption_failopen_selfheal,
    "history-eviction": cmd_history_eviction,
}


def main(argv):
    if len(argv) < 2 or argv[1] not in SUBCOMMANDS:
        print(
            json.dumps(
                {
                    "subcommand": argv[1] if len(argv) > 1 else "",
                    "ok": False,
                    "failed": ["unknown-subcommand"],
                    "checks": [],
                    "usage": sorted(SUBCOMMANDS),
                },
                ensure_ascii=False,
            )
        )
        return 2
    return SUBCOMMANDS[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
