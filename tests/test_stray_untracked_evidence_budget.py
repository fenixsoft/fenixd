"""evo-fix-stray-escalation-evidence-budget 契约测试（tasks 3.1）。

覆盖（对应 spec R1/R2/R3 与 tasks 1.1/1.2/2.1/3.1）：

- 1.1/R1 体积明细段预算：「条目体积(字节)」段头部 50 项截断＋「等 N 项」
  ＋体积合计聚合；万项级清单信号 evidence 总量有界；截断与
  parse_stray_wip_manifest 写读成对（manifest 段不受体积段影响）
- 1.2/R2 注入侧防御性体量上限：51054 项形态 evidence 注入后提示词长度
  有界（fail-open 截断＋「已截断」注记，截断发生在单趟填充之前）
- 2.1/R3 处置失败限次重派：prompt_too_long/api 400 终态（final failed 组）
  触发限次重派且重派携带瘦身 evidence；daemon 级失配形态（SIGNAL
  spec=None ＋ 处置组 spec=<项目名>）下重派/升级判定仍可达；限次用尽
  产生 severity=critical 升级信号；用尽升级记录不带 next_retry_at 且
  不被 ``_retry_due_dispatch_failures`` 选中
"""

import json
import time
from types import SimpleNamespace

import pytest

from core.admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition
from core.agent_runner.prompt_builder import (
    ADMIN_SIGNAL_EVIDENCE_MAX_CHARS,
    PromptBuilder,
    _bounded_evidence,
)
from core.worktree_manager.stray_wip import (
    EVIDENCE_MANIFEST_PREVIEW_LIMIT,
    UNTRACKED_ESCALATED_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
    _evidence_file_manifest,
    _evidence_size_manifest,
)
from core.dashboard.data.admin_stray_wip import parse_stray_wip_manifest
from tests.helpers import FakeLogger, iso_ago


# ── 1.1 体积明细段预算（stray_wip） ─────────────────────────────


class TestEvidenceSizeManifest:
    def test_threshold_shape_unchanged(self):
        """阈值内（≤50 项）形态与既有输出逐字节一致。"""
        sizes = {f"a{i}.js": i for i in range(EVIDENCE_MANIFEST_PREVIEW_LIMIT)}
        expected = (
            "条目体积(字节): "
            + ", ".join(f"{k}={v}" for k, v in sorted(sizes.items()))
        )
        assert _evidence_size_manifest(sizes) == expected

    def test_empty_sizes_placeholder(self):
        assert _evidence_size_manifest({}) == "条目体积(字节): 无"

    def test_51054_items_truncated_with_total(self):
        """51054 项形态（2026-10-24 事故）：头部 50 项＋「等 N 项」＋合计聚合，
        段长有界（不随条目数线性放大）。"""
        n = 51054
        sizes = {f"node_modules/pkg{i}/f.js": i for i in range(n)}
        seg = _evidence_size_manifest(sizes)
        assert len(seg) < 5000  # 全量 join 形态约 1.3MB，截断后恒有界
        assert f"等{n}项" in seg
        assert f"合计={sum(sizes.values())}字节" in seg
        # 头部 50 项在场（按路径排序取前 50）
        head = sorted(sizes.items())[:EVIDENCE_MANIFEST_PREVIEW_LIMIT]
        for k, v in head:
            assert f"{k}={v}" in seg
        # 第 51 项起不再内联
        _, v51 = sorted(sizes.items())[EVIDENCE_MANIFEST_PREVIEW_LIMIT]
        assert f"={v51}" not in seg
        # 全量体积单源指引（注册表 sizes_bytes）
        assert "sizes_bytes" in seg

    def test_total_is_registry_aggregate_not_partial_sum(self):
        """截断态下合计是注册表全量聚合（非前 50 项部分和）。"""
        sizes = {f"f{i}.txt": 100 for i in range(200)}
        seg = _evidence_size_manifest(sizes)
        assert "合计=20000字节" in seg  # 200×100，而非 50×100


def _make_sweeper(repo):
    return MainTreeStrayWipSweeper(repo, None, config={}, logger=None)


class TestEscalatedEvidenceBounded:
    def test_51054_entry_signal_evidence_bounded(self, tmp_path):
        """万项级清单信号 evidence 总量有界（写侧集成）：51054 项 entry 构造
        升级信号，evidence 不再逐项内联全量体积。"""
        repo = tmp_path / "proj"
        repo.mkdir()
        n = 51054
        files = [f"node_modules/pkg{i}/f.js" for i in range(n)]
        entry = {
            "files": files,
            "first_seen_iso": "2026-10-24T00:00:00+00:00",
            "sizes_bytes": {f: i for i, f in enumerate(files)},
        }
        sw = _make_sweeper(repo)
        ok = sw._write_untracked_escalated_alert(
            entry, "ab" * 16, threshold=n + 1, total_bytes=sum(range(n)),
            size_threshold=500 * 1024 * 1024, elapsed_min=1500.0,
            stale_hit=True, size_hit=False,
        )
        assert ok is True
        recs = [r for r in AdminStore(repo).read_all()
                if r.get("kind") == SIGNAL
                and r.get("signal_type") == UNTRACKED_ESCALATED_SIGNAL_TYPE]
        assert len(recs) == 1
        evidence = recs[0].get("evidence") or ""
        # 事故形态 evidence 达 6.6MB；预算后恒有界（远小于 1MB）
        assert len(evidence) < 200_000
        assert f"等{n}项" in evidence
        assert "sizes_bytes" in evidence
        # 文件清单段保持原样（头部 50 项截断形态不变）
        assert _evidence_file_manifest(files) in evidence


class TestManifestParsePairing:
    def test_parse_pairs_with_truncated_size_segment(self):
        """体积段截断不破坏 manifest 解析写读成对：parse_stray_wip_manifest
        仍按「文件清单(N):」段解析出头部 50 条，体积段「等 N 项」注记不被
        当作路径拼进清单。"""
        files = [f"pkg{i}.js" for i in range(120)]
        sizes = {f: i for i, f in enumerate(files)}
        evidence = (
            "项目名=fenixd; "
            + _evidence_file_manifest(files)
            + "; 升级触发: 无; "
            + _evidence_size_manifest(sizes)
            + "; 豁免注记: x"
        )
        parsed = parse_stray_wip_manifest(evidence)
        assert parsed == files[:EVIDENCE_MANIFEST_PREVIEW_LIMIT]
        # 体积段在场且自成一段（含 ; 分隔），不影响清单段解析
        assert "条目体积(字节): " in evidence
        assert "等120项" in evidence


# ── 1.2 注入侧防御性体量上限（prompt_builder） ──────────────────


class TestEvidenceInjectionBound:
    def test_within_cap_unchanged(self):
        """上限内原样返回（逐字节一致）。"""
        text = "a" * 1000
        assert _bounded_evidence(text) == text

    def test_over_cap_truncated_with_note(self):
        """超限 fail-open 截断＋「已截断」注记；注记不含占位符字面量。"""
        fat = "x" * (ADMIN_SIGNAL_EVIDENCE_MAX_CHARS + 5000)
        out = _bounded_evidence(fat)
        assert len(out) == ADMIN_SIGNAL_EVIDENCE_MAX_CHARS + len(
            f" [evidence 已截断：原 {len(fat)} 字符]"
        )
        assert f"[evidence 已截断：原 {len(fat)} 字符]" in out
        import re

        from core.agent_runner.prompt_builder import _PLACEHOLDER_RE

        note = out[ADMIN_SIGNAL_EVIDENCE_MAX_CHARS:]
        assert not _PLACEHOLDER_RE.search(note)

    def test_51054_entry_evidence_prompt_bounded(self, tmp_path):
        """51054 项形态注入不撑爆处置提示词：装配 administrator 提示词时
        {evidence} 超限截断，注入后提示词长度有界。"""
        n = 51054
        fat_evidence = "条目体积(字节): " + ", ".join(
            f"node_modules/pkg{i}/f.js={i}" for i in range(n)
        )
        assert len(fat_evidence) > ADMIN_SIGNAL_EVIDENCE_MAX_CHARS
        pb = PromptBuilder(SimpleNamespace(project_root=tmp_path))
        template = pb._load_agent_template("administrator")
        sig = {
            "signal_type": UNTRACKED_ESCALATED_SIGNAL_TYPE,
            "spec": None,
            "severity": "major",
            "description": "主树 untracked 散件滞留升级",
            "evidence": fat_evidence,
            "recommended_action": "核对后执行裁决",
        }
        prompt = pb._fill_placeholders(template, "administrator", "global", sig)
        # 提示词长度有界：模板 + 截断预算 + 注记余量
        assert len(prompt) < len(template) + ADMIN_SIGNAL_EVIDENCE_MAX_CHARS + 500
        assert "已截断" in prompt
        assert f"原 {len(fat_evidence)} 字符" in prompt


# ── 2.1 处置失败限次重派（admin_monitor） ───────────────────────

STRAY_SIG_TYPE = UNTRACKED_ESCALATED_SIGNAL_TYPE
PROJECT_NAME = "fenixd"


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


class StrayRescheduleRunner:
    """run_administrator 替身：先落 pending disposition，再返回最终处置。"""

    def __init__(self, store: AdminStore, result: str = "resolved"):
        self.store = store
        self.result = result
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        run_id = f"admin-{signal.get('spec') or 'global'}-ptl-{len(self.calls)}"
        self.store.append(
            {
                "kind": DISPOSITION,
                "status": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "admin_run_id": run_id,
                "result": "pending",
                "description": f"Administrator 处置中（run {run_id}）",
            }
        )
        return AdminDisposition(
            run_id=run_id,
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result=self.result,
            summary="诊断结论：测试；处置时间线：测试处置；结果：已解决。",
        )


def make_monitor(tmp_path, specs=None, runner=None, config=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = AdminStore(proot, FakeLogger())
    runner_inst = runner(store) if runner is not None else None
    mon = AdminMonitor(
        config or {},
        FakeSM(specs or {}),
        proot,
        FakeLogger(),
        store=store,
        agent_runner=runner_inst,
    )
    return proot, mon, store


def _append_stray_signal(store, *, evidence=None, escalated=True, handled=False):
    """落 daemon 级散件升级 SIGNAL 记录：spec=None（stray_wip 落盘形态）。"""
    if evidence is None:
        evidence = (
            f"项目名={PROJECT_NAME}; 文件清单(2): a.js, b.js; "
            "条目体积(字节): a.js=1, b.js=2"
        )
    return store.append(
        {
            "kind": SIGNAL,
            "signal_type": STRAY_SIG_TYPE,
            "spec": None,
            "severity": "major",
            "description": "主树 untracked 散件滞留升级",
            "evidence": evidence,
            "recommended_action": "核对后执行裁决",
            "escalated": escalated,
            "handled": handled,
        }
    )


def _append_ptl_group(store, *, run_id="admin-fenixd-1", spec=PROJECT_NAME,
                      created_ago_minutes=30):
    """落 final failed 处置组（pending + failed，_worker 落账形态），并拨回
    created 超 grace。error/failure_evidence 仅 generic 文案（事故实证：
    终态判据不得依赖处置记录文本）。"""
    recs = []
    for payload in (
        {
            "kind": DISPOSITION,
            "status": "pending",
            "signal_type": STRAY_SIG_TYPE,
            "spec": spec,
            "admin_run_id": run_id,
            "result": "pending",
            "description": "Administrator 处置中",
        },
        {
            "kind": DISPOSITION,
            "signal_type": STRAY_SIG_TYPE,
            "spec": spec,
            "admin_run_id": run_id,
            "result": "failed",
            "error": "claude CLI failed: Exit code: 1",
            "description": "处置失败",
        },
    ):
        recs.append(store.append(payload))
    alerts_path = store.alerts_path
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    ids = {r["id"] for r in recs}
    for r in alerts:
        # 拨回本组全部记录（含既有记录——替身 run 在重派轮已写 final 记录，
        # 真实场景新 run 死于派发后很久，grace 门按组内最新记录时刻判定）
        if r.get("id") in ids or r.get("admin_run_id") == run_id:
            r["created"] = iso_ago(created_ago_minutes)
    alerts_path.write_text(json.dumps(alerts), encoding="utf-8")
    return recs


def _write_ptl_run(proot, run_id, *, terminal_reason="prompt_too_long",
                   api_error_status=400):
    """写入 prompt_too_long/api 400 终态签名的 run 转录（事故实录形态）。"""
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    ev = {
        "type": "result",
        "is_error": True,
        "num_turns": 1,
        "result": "Prompt is too long",
        "terminal_reason": terminal_reason,
    }
    if api_error_status is not None:
        ev["api_error_status"] = api_error_status
    (runs / f"{run_id}.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": []}}) + "\n"
        + json.dumps(ev) + "\n",
        encoding="utf-8",
    )


def _escalations(store):
    return [r for r in store.read_all() if r.get("kind") == ESCALATION]


def _revert_signal_handled(store, sig_id):
    """还原信号 handled 回写（真实死亡场景回写不会发生，替身保真）。"""
    alerts_path = store.alerts_path
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    for r in alerts:
        if r.get("kind") == SIGNAL and r.get("id") == sig_id:
            r["handled"] = False
            r["handled_at"] = None
    alerts_path.write_text(json.dumps(alerts), encoding="utf-8")


class TestPromptTooLongReschedule:
    def test_final_failed_group_reschedules(self, tmp_path):
        """prompt_too_long 终态（final failed 组）触发限次重派：superseded
        审计携带 reschedule_count=1、重派携带瘦身 evidence、spec 归属与首次
        摄取同源（项目名）、无升级。"""
        fat = "项目名=fenixd; " + "x" * (ADMIN_SIGNAL_EVIDENCE_MAX_CHARS + 1000)
        proot, mon, store = make_monitor(
            tmp_path,
            config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=StrayRescheduleRunner,
        )
        sig = _append_stray_signal(store, evidence=fat)
        # daemon 级失配形态：SIGNAL spec=None，处置组 spec=<项目名>
        assert sig["spec"] is None
        group = _append_ptl_group(store, run_id="admin-fenixd-1")
        assert group[1]["spec"] == PROJECT_NAME
        # 严格相等口径恒不命中（失配形态实证——修复前重派不可达的根因）
        assert store.unhandled_signal_for(PROJECT_NAME, STRAY_SIG_TYPE) is None
        _write_ptl_run(proot, "admin-fenixd-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        # 原 run 追加 superseded 审计（reschedule_count=1）
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        assert len(superseded) == 1
        assert superseded[0]["admin_run_id"] == "admin-fenixd-1"
        assert superseded[0]["reschedule_count"] == 1
        assert superseded[0]["spec"] == PROJECT_NAME
        # 重派产生新 run 的 pending（admin_run_id 变更，spec 与首次摄取同源）
        new_pending = [r for r in recs
                       if (r.get("status") or r.get("result")) == "pending"
                       and r["admin_run_id"] != "admin-fenixd-1"]
        assert len(new_pending) == 1
        assert new_pending[0]["spec"] == PROJECT_NAME
        # 重派携带瘦身 evidence（runner 收到的信号 evidence 有界＋注记）
        assert len(mon.agent_runner.calls) == 1
        redispatch_evidence = mon.agent_runner.calls[0].get("evidence") or ""
        assert len(redispatch_evidence) <= ADMIN_SIGNAL_EVIDENCE_MAX_CHARS + 200
        assert "已截断" in redispatch_evidence
        # 无升级（限次未用尽）
        assert _escalations(store) == []

    def test_exhaustion_escalates_critical_without_next_retry(self, tmp_path):
        """限次用尽 → severity=critical 升级（不带 next_retry_at），escalate=True
        终结记录防双升，且不被 _retry_due_dispatch_failures 选中。"""
        proot, mon, store = make_monitor(
            tmp_path,
            config={"admin": {"escalation_cooldown_minutes": 15,
                              "reschedule_max": 0}},
            runner=StrayRescheduleRunner,
        )
        sig = _append_stray_signal(store)
        _append_ptl_group(store, run_id="admin-fenixd-1")
        _write_ptl_run(proot, "admin-fenixd-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        # 不重派（额度 0）
        assert mon.agent_runner.calls == []
        assert not any((r.get("status") or r.get("result")) == "superseded"
                       for r in recs)
        # critical 升级落盘，不带 next_retry_at / retry_count
        esc = _escalations(store)
        assert len(esc) == 1
        assert esc[0]["severity"] == "critical"
        assert esc[0]["signal_type"] == STRAY_SIG_TYPE
        assert esc[0].get("spec") is None  # daemon 级落归一后 None
        assert not esc[0].get("next_retry_at")
        assert not esc[0].get("retry_count")
        assert "prompt_too_long" in esc[0]["evidence"]
        # escalate=True 终结记录（本组进入 ② 豁免，与收敛升级共用去重）
        assert any(r.get("admin_run_id") == "admin-fenixd-1"
                   and r.get("escalate") is True
                   and (r.get("status") or r.get("result")) == "escalated"
                   for r in recs)

        # 升级记录不被派发失败自动重试扫描选中（无 next_retry_at 不入扫描）
        mon._retry_due_dispatch_failures(time.time())
        assert mon.agent_runner.calls == []
        esc_after = _escalations(store)
        assert len(esc_after) == 1
        assert not esc_after[0].get("retry_count")

        # 再次巡检：不重复升级、不再重派
        mon._recover_orphaned_dispositions()
        assert len(_escalations(store)) == 1
        assert mon.agent_runner.calls == []

    def test_daemon_mismatch_form_reachable_for_escalation(self, tmp_path):
        """daemon 级失配形态下升级判定可达：SIGNAL spec=None ＋ 组记录
        spec=<项目名>，严格相等不命中仍能走到升级出口（46h 悬空根因修复）。"""
        proot, mon, store = make_monitor(
            tmp_path,
            config={"admin": {"escalation_cooldown_minutes": 15,
                              "reschedule_max": 0}},
            runner=StrayRescheduleRunner,
        )
        sig = _append_stray_signal(store)  # spec=None
        _append_ptl_group(store, run_id="admin-fenixd-9", spec=PROJECT_NAME)
        _write_ptl_run(proot, "admin-fenixd-9")
        # 失配形态锚定：项目名口径与 None 口径互不命中（严格相等）
        assert store.unhandled_signal_for(PROJECT_NAME, STRAY_SIG_TYPE) is None
        assert store.unhandled_signal_for(None, STRAY_SIG_TYPE) is not None

        mon._recover_orphaned_dispositions()

        esc = _escalations(store)
        assert len(esc) == 1
        assert esc[0]["severity"] == "critical"
        assert esc[0]["admin_run_id"] == "admin-fenixd-9"

    def test_non_400_death_falls_back_to_convergence(self, tmp_path):
        """非 400 终态（429 瞬态归因形态）不入本通道：不重派、不升级——
        防对限流/计费类错误重派烧钱（design 边界）。"""
        proot, mon, store = make_monitor(
            tmp_path,
            config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=StrayRescheduleRunner,
        )
        _append_stray_signal(store)
        _append_ptl_group(store, run_id="admin-fenixd-1")
        _write_ptl_run(proot, "admin-fenixd-1", terminal_reason="api_error",
                       api_error_status=429)

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        assert mon.agent_runner.calls == []
        assert not any((r.get("status") or r.get("result")) == "superseded"
                       for r in recs)
        assert _escalations(store) == []

    def test_reschedule_cap_counts_across_runs(self, tmp_path):
        """重派额度跨 run 累计（reschedule_max=1：第 1 次重派、第 2 次死亡
        即超限升级），计数按 (spec, signal_type) 聚合自洽。"""
        proot, mon, store = make_monitor(
            tmp_path,
            config={"admin": {"escalation_cooldown_minutes": 15,
                              "reschedule_max": 1}},
            runner=StrayRescheduleRunner,
        )
        sig = _append_stray_signal(store)
        _append_ptl_group(store, run_id="admin-fenixd-1")
        _write_ptl_run(proot, "admin-fenixd-1")
        mon._recover_orphaned_dispositions()
        assert len(mon.agent_runner.calls) == 1
        _revert_signal_handled(store, sig["id"])

        # 重派后的新 run 再次死于同签名 → 超限（1+1 > 1）升级，不再重派
        rid2 = f"admin-{PROJECT_NAME}-ptl-1"
        _append_ptl_group(store, run_id=rid2)
        _write_ptl_run(proot, rid2)
        mon._recover_orphaned_dispositions()
        assert len(mon.agent_runner.calls) == 1  # 未再重派
        esc = _escalations(store)
        assert len(esc) == 1
        assert esc[0]["severity"] == "critical"
        assert not esc[0].get("next_retry_at")
