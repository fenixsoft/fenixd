"""
fenix_status / fenix_process TUI 报告脚本测试。

TUI 技能脚本（bin/fenix_status.py、bin/fenix_process.py）与 Dashboard 共用
core/dashboard/data.py 数据层（tui-triage-revamp D1）：本文件验证报告脚本的
裁剪契约（活跃全列+终态折叠）、信号汇总（供 LLM 分诊）与详情页区块。

夹具注意：用户级 config 泄漏防护——patch 双常量
（core.dashboard.data.USER_CONFIG_PATH + core.config.USER_CONFIG_DIR，
先例：用户级配置敏感测试三次复发）。
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore
from core import config as core_config
from core.dashboard import data as dash_data

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_bin(name: str):
    """按路径加载 bin/ 下脚本为模块（脚本必须 import 安全，main 走 __main__ guard）。"""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "bin" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class TuiReportTestBase(unittest.TestCase):
    """公共夹具：临时项目 + 用户级配置泄漏防护。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        (self.proot / "spec" / "changes").mkdir(parents=True)
        # 用户级配置泄漏防护（patch 双常量）
        patcher = patch.object(dash_data, "USER_CONFIG_PATH", self.proot / "user-config-does-not-exist.yaml")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = patch.object(core_config, "USER_CONFIG_DIR", self.proot / ".user-fenix")
        patcher2.start()
        self.addCleanup(patcher2.stop)

    # ── 夹具构造 ──────────────────────────────────────────────

    def write_state(self, entries: dict):
        lines = ["# Fenix Project State", "## Specs", ""]
        for name, kv in entries.items():
            lines.append(f"### {name}")
            for k, v in kv.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
        (self.proot / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")

    def spec_entry(self, status, *, priority=1, error=None, extra=None):
        entry = {
            "status": status,
            "priority": priority,
            "created": _iso(datetime.now(timezone.utc) - timedelta(days=1)),
            "updated": _iso(datetime.now(timezone.utc)),
            "implementer_run": None,
            "tester_run": None,
            "branch": None,
            "error": error,
            "depends_on": None,
            "frozen": "False",
            "start_after": "null",
            "frozen_until": "null",
        }
        entry.update(extra or {})
        return entry

    def make_spec_dir(self, name, *, tasks=None, mode=None):
        d = self.proot / "spec" / "changes" / name
        (d / "specs").mkdir(parents=True, exist_ok=True)
        if tasks is not None:
            (d / "tasks.md").write_text(tasks, encoding="utf-8")
        if mode is not None:
            (d / ".spec.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")

    def make_verify_pointer(self, spec, done, total, *, age_minutes=0, current=""):
        vp = self.proot / ".fenix" / "verify-progress"
        vp.mkdir(parents=True, exist_ok=True)
        f = vp / f"{spec}.json"
        f.write_text(json.dumps({"done": done, "total": total, "current": current}), encoding="utf-8")
        if age_minutes:
            old = time.time() - age_minutes * 60
            os.utime(f, (old, old))

    def make_report_json(self, spec, scenarios, summary=None):
        d = self.proot / ".fenix" / "verify-progress" / spec
        d.mkdir(parents=True, exist_ok=True)
        payload = {"timestamp": _iso(datetime.now(timezone.utc)),
                   "summary": summary or {}, "scenarios": scenarios}
        (d / "report.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def make_verification_md(self, spec, body):
        d = self.proot / "spec" / "changes" / spec
        d.mkdir(parents=True, exist_ok=True)
        (d / "verification-report.md").write_text(body, encoding="utf-8")

    def make_run(self, run_id, *, last_type=None, extra_events=(), age_seconds=0):
        """构造 run 产物；last_type 给出则追加末行终态/非终态事件。

        ≤3 行保证 classify_run 的首 3 行窗口覆盖末行（现状口径）。
        """
        d = self.proot / ".fenix" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        start_ts = 1789000000
        events = [{"timestamp": _iso(datetime.fromtimestamp(start_ts, tz=timezone.utc))}]
        events.extend(extra_events)
        if last_type:
            events.append({"type": last_type})
        f = d / f"{run_id}.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        mtime = start_ts + 2100 - age_seconds  # 35 分钟寿命
        os.utime(f, (mtime, mtime))

    def make_log_transition(self, spec, frm, to):
        d = self.proot / ".fenix" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
                 "component": "state_machine",
                 "message": f"Transition: {spec} {frm} → {to}"}
        with (d / "fenixd2026-09-09.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def write_project_config(self, gates: dict):
        cfg = self.proot / ".fenix" / "config.yaml"
        lines = ["gates:"] + [f"  {k}: {v}" for k, v in gates.items()]
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestFenixStatusReport(TuiReportTestBase):
    """bin/fenix_status.py — 状态面板报告。"""

    def setUp(self):
        super().setUp()
        self.mod = _load_bin("fenix_status")

    def test_active_listed_terminal_folded(self):
        """活跃 SPEC 逐行列出；done/pushed 折叠为统计行，名字不外显。"""
        self.write_state({
            "feat-a": self.spec_entry("implementing", extra={"priority": 1}),
            "feat-b": self.spec_entry("ready", extra={"priority": 2}),
            "done-x": self.spec_entry("done"),
            "push-y": self.spec_entry("pushed"),
            "push-z": self.spec_entry("pushed"),
            "push-w": self.spec_entry("pushed"),
        })
        self.make_spec_dir("feat-a", tasks="## 1 组\n- [x] 1.1 a\n- [x] 1.2 b\n- [ ] 1.3 c\n## 2 组\n- [ ] 2.1 d\n- [ ] 2.2 e\n")
        report = self.mod.render_report(self.proot)
        # 活跃全列
        self.assertIn("feat-a", report)
        self.assertIn("feat-b", report)
        self.assertIn("implementing", report)
        # tasks.md 进度 2/5
        self.assertIn("2/5", report)
        # 终态折叠：统计行出现，终态名字不出现
        self.assertIn("pushed 3", report)
        self.assertIn("done 1", report)
        for terminal_name in ("push-y", "push-z", "push-w", "done-x"):
            self.assertNotIn(terminal_name, report)

    def test_signals_error_budget_stall(self):
        """错误/预算耗尽/验证停滞三类问题进入信号汇总。"""
        self.write_state({
            "err-spec": self.spec_entry("implementing", error="网关 401 unauthorized"),
            "budget-spec": self.spec_entry("implementing", extra={"_impl_run_budget_used": 6}),
            "stall-spec": self.spec_entry("testing"),
        })
        for n in ("err-spec", "budget-spec", "stall-spec"):
            self.make_spec_dir(n)
        self.make_verify_pointer("stall-spec", 3, 10, age_minutes=40, current="scenario-x")
        report = self.mod.render_report(self.proot)
        # 错误信号
        self.assertIn("err-spec", report)
        self.assertIn("网关 401", report)
        # 预算耗尽（默认 4 次，used 6）
        self.assertIn("budget-spec", report)
        self.assertIn("预算耗尽", report)
        # 验证停滞（>30 分钟）
        self.assertIn("stall-spec", report)
        self.assertIn("验证停滞", report)

    def test_fix_parent_not_stalled(self):
        """活跃 fix- 子 SPEC 存在时，父 SPEC 的验证停滞豁免。"""
        self.write_state({
            "feat-p": self.spec_entry("testing"),
            "fix-feat-p": self.spec_entry("bug-found"),
        })
        for n in ("feat-p", "fix-feat-p"):
            self.make_spec_dir(n)
        self.make_verify_pointer("feat-p", 0, 5, age_minutes=45)
        report = self.mod.render_report(self.proot)
        stall_lines = [ln for ln in report.split("\n") if "验证停滞" in ln]
        self.assertFalse(any("feat-p" in ln and "fix-feat-p" not in ln for ln in stall_lines),
                         f"父 SPEC 不应报停滞：{stall_lines}")

    def test_alerts_and_daemon_signals(self):
        """未处理 escalation 告警与守护进程停止进入信号；已处理告警不出现。"""
        store = AdminStore(self.proot)
        store.append({"kind": "escalation", "severity": "critical",
                      "spec": "demo", "description": "困境信号：连续重试失败"})
        store.append({"kind": "escalation", "severity": "major",
                      "spec": "demo2", "description": "已处理的老告警"})
        # 把第二条标记已处理
        for rec in store.read_all():
            if rec.get("description") == "已处理的老告警":
                store.mark_handled(rec["id"])
        self.write_state({"feat-a": self.spec_entry("ready")})
        self.make_spec_dir("feat-a")
        report = self.mod.render_report(self.proot)
        self.assertIn("critical", report)
        self.assertIn("连续重试失败", report)
        self.assertNotIn("已处理的老告警", report)
        # 临时项目无 daemon → 停止信号
        self.assertIn("守护进程", report)

    def test_planned_waits_not_problems(self):
        """frozen / start_after 是有意等待：进「已知等待」行，不算问题信号。"""
        future = _iso(datetime.now(timezone.utc) + timedelta(hours=2))
        self.write_state({
            # 冻结真实语义：status=blocked + error 冻结前缀（is_spec_frozen）
            "ice-spec": self.spec_entry("blocked", error="用户指令冻结：原状态 ready",
                                        extra={"frozen": "True", "frozen_until": future}),
            "timer-spec": self.spec_entry("ready", extra={"start_after": future}),
        })
        for n in ("ice-spec", "timer-spec"):
            self.make_spec_dir(n)
        report = self.mod.render_report(self.proot)
        self.assertIn("已知等待", report)
        self.assertIn("ice-spec", report)
        self.assertIn("timer-spec", report)
        # 不得出现在 ⚠️/🔴 问题行
        for ln in report.split("\n"):
            if ("⚠️" in ln or "🔴" in ln) and "ice-spec" in ln:
                self.fail(f"冻结 spec 被误报为问题：{ln}")

    def test_pending_push_and_promotion(self):
        """done 待推送提示 /fenix-approve；drafted 待晋升提示 /fenix-ready。"""
        self.write_project_config({"approve_mode": "manual", "promote_mode": "manual"})
        self.write_state({
            "done-a": self.spec_entry("done"),
            "done-b": self.spec_entry("done"),
            "draft-a": self.spec_entry("drafted"),
        })
        for n in ("done-a", "done-b", "draft-a"):
            self.make_spec_dir(n)
        report = self.mod.render_report(self.proot)
        self.assertIn("/fenix-approve", report)
        self.assertIn("2", report)  # 待推送计数
        self.assertIn("/fenix-ready", report)


class TestFenixProcessReport(TuiReportTestBase):
    """bin/fenix_process.py — SPEC 详情报告。"""

    def setUp(self):
        super().setUp()
        self.mod = _load_bin("fenix_process")

    def test_header_budget_mode_and_tasks(self):
        """头部含状态/模式；预算三字段与 tasks.md 分组明细齐全。"""
        self.write_state({
            "demo-spec": self.spec_entry("implementing", extra={
                "impl_run_budget_override": 3,
                "_impl_run_budget_used": 3,
                "_tokens_in": 1200000,
                "_tokens_out": 300000,
                "_cost_usd": 1.234,
            }),
        })
        self.make_spec_dir("demo-spec", mode="fast-track", tasks=(
            "## 1 后端\n- [x] 1.1 api\n- [x] 1.2 db\n## 2 前端\n- [ ] 2.1 ui\n"))
        report = self.mod.render_report(self.proot, "demo-spec")
        self.assertIn("demo-spec", report)
        self.assertIn("implementing", report)
        self.assertIn("fast-track", report)
        # 预算：override 3 / used 3 → 耗尽
        self.assertIn("3/3", report)
        self.assertIn("耗尽", report)
        # tasks.md 分组
        self.assertIn("后端", report)
        self.assertIn("2.1", report)
        # 成本/token
        self.assertIn("$1.23", report)
        self.assertIn("1.2M", report)

    def test_verdict_bugs_and_scenarios(self):
        """验证结论 + 产品 Bug 列表 + 非产品失败计数。"""
        self.write_state({"demo-spec": self.spec_entry("bug-found")})
        self.make_spec_dir("demo-spec")
        self.make_verification_md("demo-spec", (
            "## 结论: ❌ 未通过（Bug Found）\n"
            "**状态:** 验证失败\n"
            "| 通过 | 3 |\n"
            "| 失败 | 2 |\n"
            "| 产品 Bug | 1 |\n"))
        self.make_report_json("demo-spec", [
            {"scenario_id": "S1", "description": "登录成功", "status": "pass", "screenshots": []},
            {"scenario_id": "S2", "description": "下单金额不符", "status": "fail",
             "classification": "product-bug",
             "assertion_results": [{"type": "text", "label": "金额", "pass": False}],
             "screenshots": []},
            # env 分类真实枚举值为 "env"（VERDICT_CLASSES）
            {"scenario_id": "S3", "description": "环境超时", "status": "fail",
             "classification": "env", "screenshots": []},
        ], summary={"passed": 3, "failed": 2, "errors": 0})
        report = self.mod.render_report(self.proot, "demo-spec")
        self.assertIn("未通过", report)
        self.assertIn("下单金额不符", report)
        self.assertIn("S2", report)
        # report 来源 bug 的 severity 由场景状态推导（fail → major）
        self.assertIn("major", report)
        # 非产品失败（env 被过滤）计数可见，且 S3 不进 Bug 列表
        bug_lines = [ln for ln in report.split("\n") if "🐛" in ln]
        self.assertFalse(any("S3" in ln for ln in bug_lines),
                         f"env 分类场景不应进 Bug 列表：{bug_lines}")

    def test_run_history_and_timeline(self):
        """运行历史（含状态/耗时）与时间轴状态转换可见。"""
        self.write_state({"demo-spec": self.spec_entry("implementing")})
        self.make_spec_dir("demo-spec")
        self.make_run("impl-demo-spec-1789000000", last_type="result")
        self.make_run("impl-demo-spec-1789000500-a2")  # 无终态末行 → running
        self.make_log_transition("demo-spec", "ready", "implementing")
        report = self.mod.render_report(self.proot, "demo-spec")
        self.assertIn("impl-demo-spec-1789000000", report)
        self.assertIn("impl-demo-spec-1789000500-a2", report)
        self.assertIn("35m", report)  # 时长格式化
        # 时间轴
        self.assertIn("ready", report)
        self.assertIn("implementing", report)

    def test_frozen_and_start_after(self):
        """冻结与定时拾取在头部可见。"""
        future = _iso(datetime.now(timezone.utc) + timedelta(hours=3))
        self.write_state({
            # 冻结真实语义：status=blocked + error 冻结前缀（is_spec_frozen）
            "demo-spec": self.spec_entry("blocked", error="用户指令冻结：原状态 ready", extra={
                "frozen": "True", "frozen_until": future, "start_after": future}),
        })
        self.make_spec_dir("demo-spec")
        report = self.mod.render_report(self.proot, "demo-spec")
        self.assertIn("冻结", report)
        self.assertIn("start_after", report.replace("⏰", ""))

    def test_unknown_spec_exits(self):
        """未知 SPEC：非零退出 + 明确报错。"""
        self.write_state({})
        with self.assertRaises(SystemExit) as ctx:
            self.mod.render_report(self.proot, "no-such-spec")
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
