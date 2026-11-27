"""timelib 守卫 — 时间原语唯一化静态棘轮（add-timelib-consolidation-layer 2.2/2.3）。

AST 扫描 core/**/*.py（排除 node_modules vendored 代码）与 fenixd.py，
锁定 5 类禁用模式（时间产出/解析必须走 core/timelib.py 唯一原语）：

- 零参 ``datetime.now()``（naive 本地产出）
- ``datetime.utcnow()``（已废弃且产出 naive）
- 零/单参 ``datetime.fromtimestamp()``（未显式指定 tz，本地时区歧义）
- ``datetime.utcfromtimestamp()``（已废弃）
- ``datetime.fromisoformat()``（解析未收拢）出现在 core/timelib.py 之外

棘轮机制（design D2/D3）：
- 白名单语义键 `(仓库相对路径, 模式名)`，**不含行号**（arity-guard
  2026-09-15 行漂移回归教训）；豁免粒度=文件×模式，同文件同模式全部现存
  违例一并豁免，迁移消除后整组收缩该键。
- 上线时白名单=扫描当日全部存量违例（68 处 / 30 键）；此后条目**只许收缩**。
- 僵尸条目检测：白名单键无任何对应违例 → **报失败**（不是警告）——无失败
  信号的收缩会被遗忘，名单虚胖后棘轮退化为摆设。
- core/timelib.py 全豁免（它就是唯一原语）；tests/ 不在扫描范围；
  `.astimezone()` 不列入首批禁用模式（dashboard 展示路由合法在用，design D2）。

首跑核对（2.3，2026-09-30）：AST 扫描 68 处违例（now 33 / fromisoformat 33 /
fromtimestamp 2 / utcnow 0 / utcfromtimestamp 0），与 grep 口径逐条交叉比对：

- 零参 now：grep 40 处 − 5 处注释/docstring（evolution.py:362、
  self_review.py:201/539/1319/1504）− 2 处 timelib 豁免 = 33，与 AST 一致。
- fromisoformat：grep 41 处 − 6 处注释/docstring（latency.py:12/37、
  alert_routes.py:71、evolution.py:365、recovery.py:869、regression.py:488）
  − 2 处 timelib（66 注释 + 70 实现）= 33，与 AST 一致。
- fromtimestamp：grep 16 处 − 12 处显式带 tz 的合法形态（admin_monitor.py:
  2636/4144、liveness.py:671、provider_circuit.py:965、runner.py:3427/3440/
  3446、artifacts.py:141、runs.py:497、dispatch/backoff.py:82、
  pipeline.py:1559、fenixd.py:1603，双参/tz 关键字逐个核验）− 2 处
  timelib 豁免 = 2（self_review.py:724/966），与 AST 一致。

proposal「裸 now() 72 处」为全仓 grep 大数（含 tests/ 与注释行）；本守卫
扫描范围（core/ + fenixd.py，排除 tests/ 与 vendored、只计真实调用点）内
为 33 处，口径差异已逐条归因如上。接收者别名按文件 import 绑定通配
（`datetime`/`dt` 缺省 + `from datetime import X as Y` 动态收集，覆盖
timeline.py 曾有的 `_dt.fromisoformat`），AST 无一漏报（「AST 有 / grep 无」
恒空）。
"""

import ast
import tempfile
import unittest
from pathlib import Path

from core import timelib
from fenix_guards import (
    TIME_GUARD_EXEMPT_FILES,
    TIME_PATTERN_LABELS,
    is_vendored,
    repo_relative,
    scan_time_primitives,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _prod_files() -> list:
    return [
        f for f in sorted((REPO_ROOT / "core").rglob("*.py"))
        if not is_vendored(f)
    ] + [REPO_ROOT / "fenixd.py"]


def _rel(path: Path) -> str:
    return repo_relative(path, REPO_ROOT)


# ── 存量违例白名单（上线基线=扫描当日全部 68 处 / 30 键，2026-09-30）──────
# 键 = (仓库相对路径, 模式名)。SPEC-B 逐批迁移后整组收缩对应键；
# 守卫对无对应违例的键报失败（僵尸检测），收缩是迁移的收尾动作。
# SPEC-B 批①-④（add-timelib-callsite-migration）已全部迁移：白名单清零
# （2026-09-30），棘轮进入零豁免稳态——新违例一律直接报失败。
TIME_WHITELIST: list = []


# ── 已知红基线（add-timelib-guard-red-streak 2.1，design D3）──────────────
# 临时登记清单：条目 = (仓库相对路径, 模式名, 理由, 到期日 "YYYY-MM-DD")。
# 与 TIME_WHITELIST 棘轮正交、互不混用：守卫红期内确属短期容忍的违例登记
# 在此（带理由与回绿到期日），新违例**禁止**回填 TIME_WHITELIST（零豁免
# 稳态棘轮只许收缩）。判定规则（主断言改造）：
# - 基线条目命中的违例不计入失败分桶（基线外违例非空才失败）；
# - 条目到期日早于今日 → 失败并列出超期条目（回绿时限，豁免惯性终点）；
# - 条目对应违例已消失 → 失败提示收缩（僵尸检测同款语义）。
# 初始空表：本案五处违例已随外部 code-fix 4fec3994c 收拢回绿（2026-11-27
# 复评实测守卫 18 passed、零豁免稳态保持）。
KNOWN_RED_BASELINE: list = []


def _violation_key(violation: str) -> tuple:
    """违例串 ``rel:行 接收者 模式标签`` → (rel, 模式名)，基线分桶用。

    模式名经 TIME_PATTERN_LABELS 反查：五类标签含互异方法名，逐字包含
    唯一命中；多命中/零命中都说明标签词表被改动，直接抛错暴露。
    """
    rel = violation.rsplit(":", 1)[0]
    hits = [p for p, label in TIME_PATTERN_LABELS.items() if label in violation]
    if len(hits) != 1:
        raise ValueError(f"违例串模式标签反查不唯一: {violation!r} → {hits}")
    return (rel, hits[0])


def _baseline_triage(violations, keys, baseline, today: str):
    """按 KNOWN_RED_BASELINE 对扫描结果分桶，返回 (outside, expired, shrunken)。

    - outside: 基线外违例串（基线条目命中的违例不计失败）；
    - expired: 到期日早于 today 的基线条目（回绿时限失守；"YYYY-MM-DD"
      ISO 形态字典序即时间序）；
    - shrunken: 对应违例已消失（(rel, 模式名) 不在 keys）的基线条目。
    """
    baseline_hits = {
        (rel, pattern) for rel, pattern, _reason, _expiry in baseline
        if (rel, pattern) in keys}
    outside = [v for v in violations if _violation_key(v) not in baseline_hits]
    expired = [entry for entry in baseline if entry[3] < today]
    shrunken = [entry for entry in baseline if (entry[0], entry[1]) not in keys]
    return outside, expired, shrunken


def _write_temp_py(root: Path, rel: str, source: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


class TestTimePatternDetection(unittest.TestCase):
    """单测：注入样例 → 五类禁用模式判定符合预期。"""

    def _scan(self, source: str, rel="core/_sample.py", whitelist=()):
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), rel, source)
            violations, _keys = scan_time_primitives([f], Path(td), whitelist)
        return violations

    def test_zero_arg_now_flagged(self):
        v = self._scan("import datetime\ndatetime.now()\n")
        self.assertEqual(len(v), 1)
        self.assertIn("零参 datetime.now()", v[0])  # 报告含人读描述
        self.assertIn("_sample.py:2", v[0])

    def test_aware_now_not_flagged(self):
        v = self._scan(
            "import datetime\n"
            "from datetime import datetime as dt, timezone\n"
            "datetime.now(timezone.utc)\n"
            "dt.now(timezone.utc)\n")
        self.assertEqual(v, [])

    def test_alias_and_chained_receiver_flagged(self):
        v = self._scan(
            "from datetime import datetime as dt\n"
            "import datetime\n"
            "dt.now()\n"
            "datetime.datetime.now()\n")
        self.assertEqual(len(v), 2)

    def test_unrelated_receiver_not_flagged(self):
        v = self._scan(
            "class S:\n"
            "    def now(self):\n"
            "        return 1\n"
            "s = S()\n"
            "s.now()\n")
        self.assertEqual(v, [])

    def test_utcnow_and_utcfromtimestamp_flagged(self):
        v = self._scan(
            "import datetime\n"
            "datetime.utcnow()\n"
            "datetime.utcfromtimestamp(1)\n")
        self.assertEqual(len(v), 2)

    def test_fromtimestamp_without_tz_flagged(self):
        v = self._scan(
            "import datetime\n"
            "datetime.fromtimestamp(1)\n"
            "datetime.fromtimestamp()\n")
        self.assertEqual(len(v), 2)

    def test_fromtimestamp_with_explicit_tz_allowed(self):
        v = self._scan(
            "import datetime\n"
            "from datetime import timezone\n"
            "datetime.fromtimestamp(1, tz=timezone.utc)\n"
            "datetime.fromtimestamp(1, timezone.utc)\n")
        self.assertEqual(v, [])

    def test_fromisoformat_flagged_outside_timelib(self):
        v = self._scan("import datetime\ndatetime.fromisoformat('2026-01-01')\n")
        self.assertEqual(len(v), 1)

    def test_timelib_file_exempt(self):
        v = self._scan(
            "import datetime\n"
            "datetime.fromisoformat('2026-01-01')\n"
            "datetime.now()\n",
            rel="core/timelib.py")
        self.assertEqual(v, [])

    def test_import_derived_alias_flagged(self):
        """`from datetime import datetime as _dt` 的绑定名动态收集。"""
        v = self._scan(
            "from datetime import datetime as _dt\n"
            "_dt.fromisoformat('2026-01-01')\n")
        self.assertEqual(len(v), 1)

    def test_syntax_error_file_skipped(self):
        v = self._scan("def broken(:\n")
        self.assertEqual(v, [])

    def test_whitelist_key_exempts_all_sites_of_same_pattern(self):
        src = "import datetime\ndatetime.now()\ndatetime.now()\n"
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), "core/_sample.py", src)
            wl = [("core/_sample.py", "now-zero-arg")]
            violations, keys = scan_time_primitives([f], Path(td), wl)
        self.assertEqual(violations, [])
        self.assertIn(("core/_sample.py", "now-zero-arg"), keys)


class TestRatchetMechanics(unittest.TestCase):
    """棘轮：白名单收缩合法、僵尸条目报失败。"""

    def test_zombie_whitelist_entry_detected(self):
        """白名单键无对应违例 → 扫描返回的命中键集合不含它 → 守卫失败。"""
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), "core/_clean.py", "x = 1\n")
            wl = [("core/_clean.py", "now-zero-arg")]
            violations, keys = scan_time_primitives([f], Path(td), wl)
        self.assertEqual(violations, [])
        # 僵尸键：白名单里有、违例里没有
        zombie = [k for k in wl if k not in keys]
        self.assertEqual(zombie, wl)

    def test_non_zombie_whitelist_key_alive(self):
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), "core/_dirty.py", "import datetime\ndatetime.now()\n")
            wl = [("core/_dirty.py", "now-zero-arg")]
            violations, keys = scan_time_primitives([f], Path(td), wl)
        self.assertEqual(violations, [])
        self.assertIn(wl[0], keys)


class TestKnownRedBaseline(unittest.TestCase):
    """基线机制单测（add-timelib-guard-red-streak 2.2）：超期失败 /
    命中分桶正确 / 违例消失报收缩。today 注入，用例确定性不随日历漂移。"""

    DIRTY_SRC = "import datetime\ndatetime.now()\n"  # now-zero-arg @ _dirty.py:2

    def _scan_dirty(self, baseline, today):
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), "core/_dirty.py", self.DIRTY_SRC)
            violations, keys = scan_time_primitives([f], Path(td), ())
        return _baseline_triage(violations, keys, baseline, today)

    def test_expired_baseline_entry_fails(self):
        """到期日早于今日 → expired 非空（回绿时限失守，即使违例仍命中）。"""
        outside, expired, _shrunken = self._scan_dirty(
            [("core/_dirty.py", "now-zero-arg", "遗留待迁移", "2020-01-01")],
            today="2026-11-27")
        self.assertEqual(outside, [])  # 命中基线的违例不计失败分桶
        self.assertEqual(
            expired,
            [("core/_dirty.py", "now-zero-arg", "遗留待迁移", "2020-01-01")])

    def test_hit_baseline_entry_buckets_out_of_failure(self):
        """未超期且命中 → 基线内违例不计失败分桶，三桶全空。"""
        outside, expired, shrunken = self._scan_dirty(
            [("core/_dirty.py", "now-zero-arg", "短期容忍", "2999-12-31")],
            today="2026-11-27")
        self.assertEqual((outside, expired, shrunken), ([], [], []))

    def test_vanished_violation_reports_shrink(self):
        """违例已消失（干净文件）→ shrunken 非空（收缩提示）。"""
        with tempfile.TemporaryDirectory() as td:
            f = _write_temp_py(Path(td), "core/_clean.py", "x = 1\n")
            violations, keys = scan_time_primitives([f], Path(td), ())
        outside, _expired, shrunken = _baseline_triage(
            violations, keys,
            [("core/_clean.py", "now-zero-arg", "已修复待收缩", "2999-12-31")],
            today="2026-11-27")
        self.assertEqual(outside, [])
        self.assertEqual(
            shrunken,
            [("core/_clean.py", "now-zero-arg", "已修复待收缩", "2999-12-31")])


class TestTimeGuardOnRepo(unittest.TestCase):
    """落地实证：当前 core/ + fenixd.py 白名单外违例 = 0，白名单无僵尸。"""

    # [fenix-ignore:4b216478bc98] 回归失败不复现：本轮违例 state_machine.py:494 的 datetime.fromisoformat 已随基线提交 c4d2d713 收拢为 parse_utc（内核 timelib.parse_ts；早期轮次 knowledge.py:96/knowledge_backfill.py:731 亦随 bfb98d61 迁移），生产代码 fromisoformat 调用仅剩全豁免的 core/timelib.py，TIME_WHITELIST 保持零豁免、当前 0 违例
    def test_current_production_zero_non_whitelist_violations(self):
        violations, keys = scan_time_primitives(
            _prod_files(), REPO_ROOT, TIME_WHITELIST)
        today = timelib.now_utc().astimezone().date().isoformat()
        outside, expired, shrunken = _baseline_triage(
            violations, keys, KNOWN_RED_BASELINE, today)
        self.assertEqual(
            outside, [],
            "生产代码出现基线外时间禁用模式（走 core/timelib.py 原语；"
            "确属短期已知红则登记 KNOWN_RED_BASELINE 并带理由与到期日，"
            "禁止回填 TIME_WHITELIST）:\n" + "\n".join(outside))
        self.assertEqual(
            expired, [],
            "KNOWN_RED_BASELINE 存在超期条目（回绿时限已过）：请修复对应"
            "违例并收缩基线（临时登记不得无期限延续）:\n"
            + "\n".join(f"  {f}  {p}  {reason}  到期 {expiry}"
                        for f, p, reason, expiry in expired))
        self.assertEqual(
            shrunken, [],
            "KNOWN_RED_BASELINE 存在违例已消失的条目：请从基线收缩这些条目"
            "（无失败信号的收缩会被遗忘，僵尸检测同款语义）:\n"
            + "\n".join(f"  {f}  {p}" for f, p, _r, _e in shrunken))

    def test_whitelist_has_no_zombie_entries(self):
        """僵尸条目检测：白名单键必须至少对应一处现存违例（只许收缩）。"""
        _violations, keys = scan_time_primitives(_prod_files(), REPO_ROOT, TIME_WHITELIST)
        zombies = [k for k in TIME_WHITELIST if k not in keys]
        self.assertEqual(
            zombies, [],
            "白名单存在僵尸条目（对应违例已消除）：请从 TIME_WHITELIST 收缩这些键"
            "（棘轮只许收缩，无失败信号的收缩会被遗忘）:\n"
            + "\n".join(f"  {f}  {p}" for f, p in zombies))

    def test_timelib_exempt_file_actually_exists(self):
        self.assertTrue(
            (REPO_ROOT / "core" / "timelib.py").exists(),
            "core/timelib.py 不存在——豁免清单指向失效应修正")
        self.assertIn("core/timelib.py", TIME_GUARD_EXEMPT_FILES)

    def test_scan_targets_non_empty(self):
        self.assertTrue(_prod_files(), "生产扫描目标为空，守卫已失效")


if __name__ == "__main__":
    unittest.main()
