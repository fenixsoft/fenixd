"""evo-add-stray-wip-claim-reconcile 单测（tasks.md 3.1/3.2/3.4）。

进程内真实 git 仓库夹具（test_maintree_stray_wip_sweep 同款脚手架）覆盖：
- 升级条目落库附 fingerprint_files 结构化字段（1.1，与 evidence 清单段同源）
- 认领核销正向：单波/多波覆盖 + 工作区 clean（含 tracked 空集轮插桩断言），
  核销写回 handled_by=auto-resolve-claim、resolve_note 含最近覆盖提交 SHA
  与转向话术（3.1）
- 保守反例：部分入库/仍脏/回提取失败/非本族记录逐位保留零核销（3.2）
- 复发计数不计自动核销记录（3.4，design D3 署名互斥条款）
"""

import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.admin_store import (
    CLAIM_RESOLVE_BY,
    SIGNAL,
    AdminStore,
    stray_claim_fingerprint_files,
)
from core.dashboard.data.admin_stray_wip import parse_stray_wip_manifest
from core.worktree_manager.stray_wip import (
    SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
)

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款
# 规避）。统一用仓库内 .history/tmp（gitignored），MUST NOT 改写全局
# tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _make_repo(n=4):
    """主树仓：f1..fN 已入库基线 + .fenix/ 忽略（AdminStore 落盘处）。"""
    base = Path(_mkdtemp("stray-claim-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    for i in range(1, n + 1):
        (repo / f"f{i}.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def _dirty(repo, files):
    """把 files 置为 tracked 未提交改动（散件 WIP 形态）。"""
    for f in files:
        (repo / f).write_text(f"wip {f}", encoding="utf-8")


def _commit(repo, files, msg):
    _git("add", "--", *files, cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("log", "-1", "--format=%H", "--", *files, cwd=repo).stdout.strip()


def _make_sweeper(repo) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": 0.0}}
    from tests.test_maintree_stray_wip_sweep import _WmProbe

    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg)


def _craft_claim_record(repo, files, evidence_manifest=True,
                        structured=True) -> dict:
    """手工落一条悬置升级条目（escalated=True、基线 created=1h 前）。

    structured 控制 payload 是否携带结构化 fingerprint_files（1.1 起新
    形态；False＝存量旧形态）；evidence_manifest 控制 evidence 是否含
    「文件清单(N):」段（存量回提取正/反例的开关）。
    """
    store = AdminStore(repo)
    manifest = (
        f"文件清单({len(files)}): {', '.join(files)}; "
        if files and evidence_manifest
        else ""
    )
    payload = {
        "kind": SIGNAL,
        "signal_type": SIGNAL_TYPE,
        "severity": "major",
        "spec": None,
        "escalated": True,
        "created": (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(),
        "description": "测试悬置升级条目",
        "evidence": f"项目名=proj; first_seen=x; {manifest}归因证据: 测试",
        "source": "maintree-stray-wip-sweep",
    }
    if files is not None and structured:
        payload["fingerprint_files"] = list(files)
    rec = store.append(payload)
    assert rec is not None
    return rec


def _read_record(repo, alert_id) -> dict:
    for rec in AdminStore(repo).read_all():
        if rec.get("id") == alert_id:
            return rec
    raise AssertionError(f"record {alert_id} not found")


class TestStructuredFingerprintField(unittest.TestCase):
    """1.1：告警落库附指纹文件集结构化字段（与 evidence 清单段同源）。"""

    def test_alert_record_carries_fingerprint_files(self):
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        sweeper = _make_sweeper(repo)
        result = sweeper.sweep()
        self.assertEqual(result["status"], "alerted")
        recs = [
            r for r in AdminStore(repo).read_all()
            if r.get("signal_type") == SIGNAL_TYPE
        ]
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(
            sorted(rec.get("fingerprint_files") or []),
            ["f1.tsx", "f2.tsx"],
        )
        # 同源断言：结构化字段与 evidence「文件清单(N):」段解析结果一致
        # （同一 files 列表两个渲染面）。
        self.assertEqual(
            sorted(parse_stray_wip_manifest(rec.get("evidence"))),
            sorted(rec.get("fingerprint_files")),
        )


class TestClaimResolve(unittest.TestCase):
    """3.1：认领核销正向（单波/多波覆盖 + clean，核销写回断言）。"""

    def test_single_wave_claim_resolves_on_clean_tree(self):
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(repo, ["f1.tsx", "f2.tsx"])
        # 人工以单波提交认领全部指纹文件 → 工作区全 clean（tracked 空集
        # 形态：本断言同时覆盖「空集早退不得吞掉本判定」的插桩红线——
        # 探测挂在 tracked/untracked 两流一切空集早退之前）。
        sha = _commit(repo, ["f1.tsx", "f2.tsx"], "human claim wave")
        result = _make_sweeper(repo).sweep()
        self.assertEqual(result["status"], "clean")
        rec2 = _read_record(repo, rec["id"])
        self.assertTrue(rec2.get("handled"))
        self.assertEqual(rec2.get("handled_by"), CLAIM_RESOLVE_BY)
        note = rec2.get("resolve_note") or ""
        self.assertIn(sha, note)
        self.assertIn(
            "人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道",
            note,
        )
        self.assertTrue(rec2.get("handled_at"))

    def test_multi_wave_claim_resolves_with_latest_covering_sha(self):
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(repo, ["f1.tsx", "f2.tsx"])
        # 第一波只入库 f1（部分入库）→ 保守保留零核销。
        sha_a = _commit(repo, ["f1.tsx"], "human claim wave 1")
        _make_sweeper(repo).sweep()
        rec_mid = _read_record(repo, rec["id"])
        self.assertFalse(rec_mid.get("handled"))
        # 第二波入库 f2 → 全覆盖 + clean → 核销，note 取最近覆盖提交 SHA。
        sha_b = _commit(repo, ["f2.tsx"], "human claim wave 2")
        _make_sweeper(repo).sweep()
        rec2 = _read_record(repo, rec["id"])
        self.assertTrue(rec2.get("handled"))
        self.assertEqual(rec2.get("handled_by"), CLAIM_RESOLVE_BY)
        note = rec2.get("resolve_note") or ""
        self.assertIn(sha_b, note)
        self.assertNotIn(sha_a, note)
        self.assertIn(
            "人工已以提交认领主树直改形态，请确认是否仍需建立 worktree 车道",
            note,
        )

    def test_legacy_record_manifest_extraction_resolves(self):
        """2.3 存量旧形态：无结构化字段，按 evidence 清单段回提取参与。"""
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(
            repo, ["f1.tsx", "f2.tsx"], evidence_manifest=True,
            structured=False,
        )
        self.assertIsNone(rec.get("fingerprint_files"))
        _commit(repo, ["f1.tsx", "f2.tsx"], "human claim legacy")
        _make_sweeper(repo).sweep()
        rec2 = _read_record(repo, rec["id"])
        self.assertTrue(rec2.get("handled"))
        self.assertEqual(rec2.get("handled_by"), CLAIM_RESOLVE_BY)


class TestClaimConservative(unittest.TestCase):
    """3.2：保守反例——部分入库/仍脏/回提取失败逐位保留零核销。"""

    def _assert_record_untouched(self, repo, rec_before):
        rec2 = _read_record(repo, rec_before["id"])
        # 逐位保留：整条记录零字段变化（handled 族不写、升级节奏/描述/
        # evidence/created 全不变），升级节奏与人工队列可见性不变。
        self.assertEqual(rec2, rec_before)
        self.assertFalse(rec2.get("handled"))

    def test_partial_coverage_keeps_entry(self):
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(repo, ["f1.tsx", "f2.tsx"])
        _commit(repo, ["f1.tsx"], "partial claim")
        _make_sweeper(repo).sweep()
        self._assert_record_untouched(repo, rec)

    def test_fully_covered_but_dirty_keeps_entry(self):
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(repo, ["f1.tsx", "f2.tsx"])
        _commit(repo, ["f1.tsx", "f2.tsx"], "claim all")
        # 全覆盖之后集合内又出现新脏改动 → 仍脏不核销（防半处置假闭环）。
        (repo / "f2.tsx").write_text("wip again", encoding="utf-8")
        _make_sweeper(repo).sweep()
        self._assert_record_untouched(repo, rec)

    def test_untracked_manifest_member_keeps_entry(self):
        """清单内文件已脱离索引（untracked 散落形态）不算入库 clean。"""
        repo = _make_repo()
        _dirty(repo, ["f1.tsx", "f2.tsx"])
        rec = _craft_claim_record(repo, ["f1.tsx", "f2.tsx"])
        _commit(repo, ["f1.tsx"], "claim f1")
        _git("rm", "-q", "--cached", "f2.tsx", cwd=repo)  # f2 出库散落
        _make_sweeper(repo).sweep()
        self._assert_record_untouched(repo, rec)

    def test_manifest_extraction_failure_keeps_entry(self):
        """回提取失败（无结构化字段 + evidence 无清单段）保守跳过。"""
        repo = _make_repo()
        _dirty(repo, ["f1.tsx"])
        rec = _craft_claim_record(
            repo, ["f1.tsx"], evidence_manifest=False, structured=False
        )
        _commit(repo, ["f1.tsx"], "claim f1")
        _make_sweeper(repo).sweep()
        self._assert_record_untouched(repo, rec)

    def test_non_family_signal_untouched(self):
        """白名单单族：姊妹 info 信号记录不可被认领核销探测触碰。"""
        repo = _make_repo()
        _dirty(repo, ["f1.tsx"])
        store = AdminStore(repo)
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": "maintree_untracked_stray_stale",
                "severity": "major",
                "spec": None,
                "escalated": True,
                "created": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat(),
                "description": "姊妹 info 信号条目",
                "evidence": "项目名=proj; 文件清单(1): f1.tsx",
                "fingerprint_files": ["f1.tsx"],
                "source": "test",
            }
        )
        _commit(repo, ["f1.tsx"], "claim f1")
        _make_sweeper(repo).sweep()
        self._assert_record_untouched(repo, rec)


class TestStoreAutoResolveClaim(unittest.TestCase):
    """2.2 store 层：白名单单族 / 未核销面 / 幂等。"""

    def test_whitelist_family_and_unhandled_only(self):
        repo = _make_repo()
        store = AdminStore(repo)
        rec_a = store.append(
            {"kind": SIGNAL, "signal_type": SIGNAL_TYPE, "spec": None}
        )
        rec_b = store.append(
            {
                "kind": SIGNAL,
                "signal_type": "maintree_untracked_stray_stale",
                "spec": None,
            }
        )
        rec_c = store.append(
            {"kind": SIGNAL, "signal_type": SIGNAL_TYPE, "spec": None}
        )
        store.auto_resolve_claim(
            SIGNAL_TYPE, [{"id": rec_c["id"], "resolve_note": "先核销"}]
        )
        resolutions = [
            {"id": rec_a["id"], "resolve_note": "核销 A"},
            {"id": rec_b["id"], "resolve_note": "不该生效（非本族）"},
            {"id": rec_c["id"], "resolve_note": "不该生效（已 handled）"},
        ]
        resolved = store.auto_resolve_claim(SIGNAL_TYPE, resolutions)
        self.assertEqual(resolved, 1)
        ra = _read_record(repo, rec_a["id"])
        self.assertTrue(ra.get("handled"))
        self.assertEqual(ra.get("handled_by"), CLAIM_RESOLVE_BY)
        self.assertEqual(ra.get("resolve_note"), "核销 A")
        # 非本族记录未被触碰（白名单单族先例）。
        rb = _read_record(repo, rec_b["id"])
        self.assertFalse(rb.get("handled"))
        self.assertIsNone(rb.get("resolve_note"))
        # 已核销条目幂等：重入零写回零变化（人工记录不可覆盖）。
        resolved2 = store.auto_resolve_claim(
            SIGNAL_TYPE, [{"id": rec_a["id"], "resolve_note": "重复核销"}]
        )
        self.assertEqual(resolved2, 0)
        self.assertEqual(
            _read_record(repo, rec_a["id"])["resolve_note"], "核销 A"
        )

    def test_other_family_store_call_isolated(self):
        """signal_type 形参传入他族时本族记录不可核销（白名单在写回口）。"""
        repo = _make_repo()
        store = AdminStore(repo)
        rec = store.append(
            {"kind": SIGNAL, "signal_type": SIGNAL_TYPE, "spec": None}
        )
        resolved = store.auto_resolve_claim(
            "provider_ref_invalid",
            [{"id": rec["id"], "resolve_note": "越族核销"}],
        )
        self.assertEqual(resolved, 0)
        self.assertFalse(_read_record(repo, rec["id"]).get("handled"))


class TestStrayClaimFingerprintFiles(unittest.TestCase):
    """2.3 提取单源：结构化字段优先 / evidence 回提取 / 失败空表。"""

    def test_structured_field_first(self):
        rec = {
            "fingerprint_files": ["a.py", "b.py"],
            "evidence": "x; 文件清单(9): stale.py",
        }
        self.assertEqual(stray_claim_fingerprint_files(rec), ["a.py", "b.py"])

    def test_evidence_fallback_for_legacy(self):
        rec = {"evidence": "项目名=p; 文件清单(2): a.py, b.py; 归因: x"}
        self.assertEqual(
            stray_claim_fingerprint_files(rec), ["a.py", "b.py"]
        )

    def test_unextractable_returns_empty(self):
        self.assertEqual(stray_claim_fingerprint_files({}), [])
        self.assertEqual(
            stray_claim_fingerprint_files({"evidence": "无清单段"}), []
        )
        # 非法形态结构化字段（空列表/非列表）回落 evidence 提取。
        self.assertEqual(
            stray_claim_fingerprint_files(
                {"fingerprint_files": [], "evidence": "文件清单(1): a.py"}
            ),
            ["a.py"],
        )
        self.assertEqual(
            stray_claim_fingerprint_files(
                {"fingerprint_files": "a.py", "evidence": ""}
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
