"""test_crossday_recurrence_fingerprint.py — 跨日复发指纹归一化与记忆持久化测试
（evo-fix-crossday-recurrence-fingerprint-normalization tasks 3.1/3.2）

覆盖：
- 3.1: 「小数+单位字母」归一——10-02/10-03 两夜 api_timeout 死亡 ERROR 行
  形态（仅延迟数值 23.4s/5.3s 与 run_id 不同）指纹相等；非数值部分（不同
  根因的 stderr_tail）不同则指纹不同不误聚；同形两夜在 _detect_daemon_errors
  判定跨日同刻连发并触发升级告警。
- 3.2: 记忆持久化——扫描后快照落盘（原子形态、淘汰后有界）；daemon 重启
  场景（新实例经 __init__/_load_crossday_memory 加载）仅凭持久化记忆即可
  检出同刻连发；状态文件缺失/损坏时降级（损坏场景走 ≥24h 定向回退检索，
  突破 256KB 尾读窗），主扫描不抛错。

MUST NOT 真跑 agent——admin_monitor 经 __new__/最小实参直构 + 日志 fixture
驱动。
"""

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


class _RecLogger:
    """记录 debug/info/warning 文案的假 logger（检索成本与命中留痕断言用）。"""

    def __init__(self):
        self.debugs = []
        self.infos = []
        self.warnings = []

    def debug(self, component, msg, *a, **k):
        self.debugs.append(msg)

    def info(self, component, msg, *a, **k):
        self.infos.append(msg)

    def warning(self, component, msg, *a, **k):
        self.warnings.append(msg)


# 10-02/10-03 两夜 api_timeout 死亡 ERROR 行的真实形态模板（主树 fenixd.log
# 实录：code-fix 终局失败行，跨夜漂移仅 run_id 与 median/p90/max 延迟小数）。
def _death_msg(run_id: int, latency: str) -> str:
    return (
        f"code-fix run 失败（run code-fix-{run_id}）: claude CLI failed: "
        f"Exit code: 1 | latency: run code-fix-{run_id}: 1 rounds, "
        f"median {latency}, p90 {latency}, max {latency}, stalls>60s=1 (100%) "
        f'[api_timeout=True exit_code=1 stderr_tail: '
        f'[claude-code:unrecognized_model] {{"model":"glm-5.3-flash",'
        f'"query_source":"sdk"}}]'
    )


def _make_monitor(tmp_path, logger=None):
    """__new__ 直构 AdminMonitor（对齐既有 crossday 测试形态）。"""
    from core.admin_monitor import AdminMonitor
    from core.admin_store import AdminStore

    mon = AdminMonitor.__new__(AdminMonitor)
    mon.project_root = Path(tmp_path)
    mon.logger = logger if logger is not None else _RecLogger()
    mon.store = AdminStore(Path(tmp_path), None)
    mon._started_at = time.time()
    mon._daemon_fp_escalated_at = {}
    mon._daemon_fp_last_failure = {}
    return mon


def _write_log(tmp_path, entries):
    """写入 fenixd.log 形态的单行 JSON 序列（entries: [(level, msg, ts_epoch)]）。"""
    log = Path(tmp_path) / ".fenix" / "logs" / "fenixd.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for level, msg, ts in entries:
        lines.append(json.dumps({
            "level": level,
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "component": "code-fix",
            "message": msg,
        }, ensure_ascii=False))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


class TestFingerprintNormalizationDecimalUnit(unittest.TestCase):
    """「数字.数字+单位字母」归一（tasks 1.1 / 3.1）。"""

    def test_two_nights_same_shape_same_fingerprint(self):
        """两夜死亡行仅延迟数值（23.4s vs 5.3s）与 run_id 不同 → 指纹相等。"""
        from core.admin_monitor import _error_fingerprint, _normalize_error_message

        night1 = _death_msg(1790627269, "23.4s")
        night2 = _death_msg(1790991234, "5.3s")
        fp1 = _error_fingerprint("code-fix", night1)
        fp2 = _error_fingerprint("code-fix", night2)
        self.assertEqual(fp1, fp2, "同形夜间死亡行（仅延迟小数不同）MUST 同指纹")
        normalized = _normalize_error_message(night1)
        self.assertIn("#s", normalized, "延迟小数+单位 MUST 整体归一（单位保留）")
        self.assertNotIn("#.4s", normalized)
        self.assertNotIn("#.3s", normalized)

    def test_non_numeric_difference_distinct_fingerprint(self):
        """非数值部分不同（不同根因的 stderr_tail）→ 指纹不同不误聚。"""
        from core.admin_monitor import _error_fingerprint

        timeout = _death_msg(1790627269, "23.4s")
        other_cause = (
            "code-fix run 失败（run code-fix-1790627269）: claude CLI failed: "
            "Exit code: 1 | latency: run code-fix-1790627269: 1 rounds, "
            "median 23.4s, p90 23.4s, max 23.4s, stalls>60s=1 (100%) "
            "[api_timeout=False exit_code=1 stderr_tail: "
            "[Connection error] socket hang up (ENOTFOUND api.bigmodel.cn)]"
        )
        fp_timeout = _error_fingerprint("code-fix", timeout)
        fp_other = _error_fingerprint("code-fix", other_cause)
        self.assertNotEqual(
            fp_timeout, fp_other, "非数值骨架差异 MUST 产出不同指纹"
        )

    def test_identifier_decimal_not_normalized(self):
        """标识符/无单位形态不受新规则影响（保守集边界）。"""
        from core.admin_monitor import _normalize_error_message

        # 标识符内小数（版本号片段，前后被字母包围）→ 不按新规则整体归一
        self.assertEqual(
            _normalize_error_message("artifact v1.2b mismatch"),
            "artifact v1.2b mismatch",
        )
        # 单位前无小数点（纯整数+单位）维持既有不归一行为
        # （design Risks：整数+单位形态本 SPEC 不扩大占位符范围）
        self.assertEqual(_normalize_error_message("wait 4s"), "wait 4s")


class TestCrossdayEscalationWithNormalizedFingerprint(unittest.TestCase):
    """同形两夜死亡行 → 跨日同刻连发升级（tasks 3.1 后半）。"""

    def test_two_nights_delay_only_difference_escalates(self):
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("xday-fp1-"))
        now = time.time()
        fp = _error_fingerprint("code-fix", _death_msg(1790627269, "23.4s"))
        mon = _make_monitor(tmp)
        _write_log(tmp, [
            ("ERROR", _death_msg(1790627269, "23.4s"), now - 24 * 3600 + 30),
            ("ERROR", _death_msg(1790991234, "5.3s"), now - 60),
        ])

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(len(signals), 1, "同形两夜连发 MUST 判跨日同刻复发升级")
        sig = signals[0]
        self.assertEqual(sig["_fp"], fp, "归一化后两夜 MUST 共享同一指纹")
        self.assertIn("跨日同刻复发", sig["description"])
        self.assertIn("跨日同刻复发", str(sig.get("evidence") or ""))
        self.assertIn(fp[:8], sig["description"], "指纹前缀对账子串 MUST 保留")


class TestCrossdayMemoryPersistence(unittest.TestCase):
    """跨日指纹记忆持久化与重启加载（tasks 2.1 / 3.2）。"""

    def _state_path(self, tmp) -> Path:
        from core.admin_monitor import CROSSDAY_FP_MEMORY_REL

        return Path(tmp) / CROSSDAY_FP_MEMORY_REL

    def test_scan_persists_memory_snapshot(self):
        """扫描更新记忆后快照落盘：原子形态 JSON、fp→epoch 条目在案。"""
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("xday-persist-"))
        now = time.time()
        msg = _death_msg(1790627269, "23.4s")
        mon = _make_monitor(tmp)
        _write_log(tmp, [("ERROR", msg, now - 60)])

        self.assertEqual(mon._detect_daemon_errors(now), [])  # 单条不升级
        path = self._state_path(tmp)
        self.assertTrue(path.exists(), "扫描 MUST 落盘记忆快照")
        data = json.loads(path.read_text(encoding="utf-8"))
        fp = _error_fingerprint("code-fix", msg)
        self.assertIn(fp, data["memory"])
        self.assertAlmostEqual(data["memory"][fp], now - 60, delta=5)

    def test_eviction_snapshot_bounded(self):
        """超限淘汰最早一半后快照落盘，文件条目数有界（2.1）。"""
        from core.admin_monitor import (
            DAEMON_ERROR_FP_MEMORY_LIMIT,
            _error_fingerprint,
        )

        tmp = Path(_mkdtemp("xday-evict-"))
        now = time.time()
        mon = _make_monitor(tmp)
        # 预置超限记忆（假指纹占位，注入序即淘汰序）
        for i in range(DAEMON_ERROR_FP_MEMORY_LIMIT + 8):
            mon._daemon_fp_last_failure[f"fake{i:04x}"] = float(i)
        msg = _death_msg(1790627269, "23.4s")
        _write_log(tmp, [("ERROR", msg, now - 60)])

        mon._detect_daemon_errors(now)

        data = json.loads(self._state_path(tmp).read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(data["memory"]),
            DAEMON_ERROR_FP_MEMORY_LIMIT,
            "持久化快照 MUST 继承内存淘汰语义（体量有界）",
        )
        self.assertIn(
            _error_fingerprint("code-fix", msg),
            data["memory"],
            "本扫活跃指纹 MUST 留在淘汰后快照中",
        )

    def test_restart_loaded_memory_detects_crossday_without_log_history(self):
        """重启场景：新实例从状态文件加载记忆，仅凭记忆检出同刻连发（3.2）。

        次夜日志只含当晚死亡行（前夜历史不在日志/tail 窗内）——命中只能来自
        持久化记忆，构成持久化生效的最强判据。
        """
        from core.admin_monitor import AdminMonitor, _error_fingerprint

        tmp = Path(_mkdtemp("xday-restart-"))
        now = time.time()
        night1 = _death_msg(1790627269, "23.4s")
        night2 = _death_msg(1790991234, "5.3s")
        fp = _error_fingerprint("code-fix", night1)

        # 「第一夜」：实例 A 扫描后记忆落盘
        mon_a = _make_monitor(tmp)
        _write_log(tmp, [("ERROR", night1, now - 60)])
        self.assertEqual(mon_a._detect_daemon_errors(now), [])
        self.assertTrue(self._state_path(tmp).exists())

        # 「重启」：实例 B 经真实 __init__ 加载持久化记忆
        rec = _RecLogger()
        mon_b = AdminMonitor({}, None, tmp, rec)
        self.assertEqual(
            mon_b._daemon_fp_last_failure.get(fp),
            mon_a._daemon_fp_last_failure.get(fp),
            "重启后实例 MUST 从状态文件加载记忆",
        )
        # 次夜同刻：日志被截断只剩当晚条目
        ts2 = now + 24 * 3600
        _write_log(tmp, [("ERROR", night2, ts2)])
        signals = mon_b._detect_daemon_errors(ts2 + 60)
        self.assertEqual(len(signals), 1, "重启后仅凭持久化记忆 MUST 仍可检出")
        self.assertIn("跨日同刻复发", signals[0]["description"])
        self.assertEqual(signals[0]["_fp"], fp)

    def test_missing_state_file_degrades_to_log_fallback(self):
        """状态文件缺失：降级空记忆 + 日志回退对账，主扫描不抛错（3.2）。"""
        tmp = Path(_mkdtemp("xday-missing-"))
        now = time.time()
        night1 = _death_msg(1790627269, "23.4s")
        night2 = _death_msg(1790991234, "5.3s")
        mon = _make_monitor(tmp)
        _write_log(tmp, [
            ("ERROR", night1, now - 24 * 3600 + 30),
            ("ERROR", night2, now - 60),
        ])

        signals = mon._detect_daemon_errors(now)  # MUST NOT raise
        self.assertEqual(len(signals), 1, "缺记忆文件时 tail 内次新条目对账仍应命中")
        self.assertIn("跨日同刻复发", signals[0]["description"])

    def test_corrupt_state_file_degrades_to_targeted_search(self):
        """状态文件损坏：降级到 ≥24h 定向检索（突破 256KB 尾读窗），不抛错。

        前夜死亡行被 INFO 填充推出 256KB 尾读窗外——命中只能来自定向检索，
        构成 2.2 检索能力 ≥24h 的直接判据；检索成本与命中留痕写 debug 日志。
        """
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("xday-corrupt-"))
        now = time.time()
        night1 = _death_msg(1790627269, "23.4s")
        night2 = _death_msg(1790991234, "5.3s")
        fp = _error_fingerprint("code-fix", night1)
        self._state_path(tmp).parent.mkdir(parents=True, exist_ok=True)
        self._state_path(tmp).write_text('{"memory": broken{{{', encoding="utf-8")
        rec = _RecLogger()
        mon = _make_monitor(tmp, logger=rec)
        # 400KB INFO 填充：把前夜行推出 tail 窗（mtime/时间戳均在当下，不落检索窗）
        filler = "INFO heartbeat padding " + "x" * 48
        entries = [("ERROR", night1, now - 24 * 3600 + 30)]
        entries += [("INFO", f"{filler} #{i}", now - 300 + i) for i in range(6000)]
        entries += [("ERROR", night2, now - 60)]
        _write_log(tmp, entries)

        signals = mon._detect_daemon_errors(now)  # MUST NOT raise

        self.assertEqual(len(signals), 1, "损坏降级后定向检索 MUST 检出前夜同签名")
        sig = signals[0]
        self.assertEqual(sig["_fp"], fp)
        self.assertIn("跨日同刻复发", sig["description"])
        debugs = "\n".join(rec.debugs)
        self.assertIn("跨日回退定向检索", debugs, "检索成本/命中 MUST 留 debug 痕迹")
        self.assertIn("命中", debugs)


if __name__ == "__main__":
    unittest.main()
