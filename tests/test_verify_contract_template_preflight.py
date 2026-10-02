"""验证契约模板态前置预检测试（add-verify-contract-preflight 2.1）。

覆盖：
- contract_file_unresolvable 只读判定的四种文件形态（缺失/全注释模板/
  有效契约/顶层非映射）；
- _detect_verify_contract_unresolved 检测器：ready/implementing 触发、
  testing 及之后不触发、有效契约与文件缺失不触发、项目级单例、
  description/evidence 契约、loader 异常 fail-open；
- PREPROBE 既有探测在「信号在途期间契约被修正为可解析」时判满足免唤起。

语义基线：ADR-080「契约文件缺失=合法无契约回退」——前置预检只收窄
「模板态文件挂着却从未裁决」的缺口，不扩大触发面。
"""

import time

import pytest

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore
from core.verify_contract import contract_file_unresolvable, load_verify_contract
from tests.helpers import FakeLogger, iso_ago

# 与 SIGNAL_RECOMMENDATION["verify_contract_missing"]（:346 起草指引）比对用
DRAFT_GUIDANCE_SUBSTR = "起草 .fenix/verify.yaml 验证契约"

# 全注释模板 = fenix-init 写入的初始形态（core/verify_contract_template.yaml
# 非注释行数为 0），yaml.safe_load 解析为 None
TEMPLATE_YAML = "# 全注释模板\n# prepare:\n#   - run: npm run build\n"

VALID_YAML = (
    "prepare:\n"
    "  - run: npm run build\n"
    "serve:\n"
    "  kind: static\n"
    "  root: dist\n"
    "regression:\n"
    "  cmd: python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml\n"
    "  output: .fenix/regression/junit.xml\n"
)


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


def make_monitor(tmp_path, specs: dict):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix").mkdir(exist_ok=True)
    mon = AdminMonitor(
        {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
    )
    return proot, mon


def write_contract(proot, text: str):
    (proot / ".fenix" / "verify.yaml").write_text(text, encoding="utf-8")


def preflight_signals(mon, specs: dict):
    return mon._detect_verify_contract_unresolved(specs)


# ── 1.1 只读判定函数 ────────────────────────────────────────


class TestContractFileUnresolvable:
    def test_missing_file_returns_false(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        # 文件缺失 = 合法无契约回退（ADR-080），不判定为模板态
        assert contract_file_unresolvable(proot) is False

    def test_all_comment_template_returns_true(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        write_contract(proot, TEMPLATE_YAML)
        assert contract_file_unresolvable(proot) is True

    def test_valid_contract_returns_false(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        write_contract(proot, VALID_YAML)
        assert contract_file_unresolvable(proot) is False
        # 与既有 loader 同源：可解析出契约对象
        assert load_verify_contract(proot, None) is not None

    def test_top_level_non_mapping_returns_true(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        write_contract(proot, "- a\n- b\n")
        assert contract_file_unresolvable(proot) is True

    def test_read_only_no_side_files(self, tmp_path):
        """判定过程只读：不写任何文件（自证快照/状态文件均不落盘）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        write_contract(proot, TEMPLATE_YAML)
        before = sorted(p.name for p in (proot / ".fenix").iterdir())
        contract_file_unresolvable(proot)
        after = sorted(p.name for p in (proot / ".fenix").iterdir())
        assert before == after == ["verify.yaml"]


# ── 1.2 / 2.1 检测器 ────────────────────────────────────────


class TestDetectVerifyContractUnresolved:
    def test_ready_spec_with_template_fires_signal(self, tmp_path):
        """(a) 全注释模板 + ready spec → 产出 verify_contract_missing 信号。"""
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "ready"}})
        write_contract(proot, TEMPLATE_YAML)
        signals = preflight_signals(mon, {"spec-a": {"status": "ready"}})
        assert len(signals) == 1
        sig = signals[0]
        assert sig["signal_type"] == "verify_contract_missing"
        assert sig["spec"] == "spec-a"
        # description 注明前置预检与勿复位 spec 状态（防 Administrator 沿用
        # 消费期「复位 ready」收尾把进行中的实现打回重做）
        assert "前置预检" in sig["description"]
        assert "勿复位 spec 状态" in sig["description"]
        # evidence 含项目根与契约路径
        assert str(proot) in sig["evidence"]
        assert ".fenix/verify.yaml" in sig["evidence"]
        # recommended_action 沿用既有起草指引，不另写一套
        assert DRAFT_GUIDANCE_SUBSTR in sig["recommended_action"]

    def test_implementing_spec_with_template_fires_signal(self, tmp_path):
        """(g) 全注释模板 + implementing 状态 spec → 产出信号。"""
        proot, mon = make_monitor(tmp_path, {"spec-b": {"status": "implementing"}})
        write_contract(proot, TEMPLATE_YAML)
        signals = preflight_signals(mon, {"spec-b": {"status": "implementing"}})
        assert len(signals) == 1
        assert signals[0]["signal_type"] == "verify_contract_missing"
        assert signals[0]["spec"] == "spec-b"

    def test_valid_contract_no_signal(self, tmp_path):
        """(b) 有效契约（含实质 prepare/regression 段）+ ready spec → 不产出。"""
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "ready"}})
        write_contract(proot, VALID_YAML)
        assert preflight_signals(mon, {"spec-a": {"status": "ready"}}) == []

    def test_missing_contract_no_signal(self, tmp_path):
        """(c) 契约文件缺失 + ready spec → 不产出（无契约回退语义不变）。"""
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "ready"}})
        assert (proot / ".fenix" / "verify.yaml").exists() is False
        assert preflight_signals(mon, {"spec-a": {"status": "ready"}}) == []

    def test_testing_spec_no_signal(self, tmp_path):
        """(d) 模板态但 spec 已 testing → 不触发（消费期 fail-fast 负责该形态）。"""
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "testing"}})
        write_contract(proot, TEMPLATE_YAML)
        assert preflight_signals(mon, {"spec-a": {"status": "testing"}}) == []

    def test_multiple_specs_single_signal(self, tmp_path):
        """(h) 多个 ready/implementing spec 命中 → 仅一条信号，不放大唤起。"""
        proot, mon = make_monitor(
            tmp_path,
            {
                "spec-1": {"status": "implementing"},
                "spec-2": {"status": "ready"},
                "spec-3": {"status": "testing"},
            },
        )
        write_contract(proot, TEMPLATE_YAML)
        signals = preflight_signals(
            mon,
            {
                "spec-1": {"status": "implementing"},
                "spec-2": {"status": "ready"},
                "spec-3": {"status": "testing"},
            },
        )
        assert len(signals) == 1
        # spec 字段取首个命中 spec（testing 的 spec-3 不参与命中）
        assert signals[0]["spec"] == "spec-1"

    def test_no_qualifying_specs_no_probe(self, tmp_path, monkeypatch):
        """无 ready/implementing spec 时不触碰契约文件（只读判定零调用）。"""
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "testing"}})
        write_contract(proot, TEMPLATE_YAML)
        calls = []

        def spy(root):
            calls.append(root)
            return False

        monkeypatch.setattr("core.verify_contract.contract_file_unresolvable", spy)
        assert preflight_signals(mon, {"spec-a": {"status": "testing"}}) == []
        assert calls == []

    def test_fail_open_on_loader_exception(self, tmp_path, monkeypatch):
        """(f) loader 抛异常时 fail-open：不阻断其余检测器执行。"""
        proot, mon = make_monitor(
            tmp_path,
            {
                "spec-a": {"status": "ready"},
                "blocked-spec": {
                    "status": "blocked",
                    "updated": iso_ago(120),
                    "error": "x" * 10,
                },
            },
        )
        write_contract(proot, TEMPLATE_YAML)

        def boom(root):
            raise RuntimeError("preflight probe exploded")

        monkeypatch.setattr("core.verify_contract.contract_file_unresolvable", boom)
        # _detect 全链不抛异常；blocked_stuck 等其余检测器信号照常产出
        signals = mon._detect(mon.state_machine.read_all(), now=time.time())
        assert any(s["signal_type"] == "blocked_stuck" for s in signals)
        assert all(
            s["signal_type"] != "verify_contract_missing" for s in signals
        )


# ── (e) PREPROBE：信号在途期间契约被修正 → 判满足免唤起 ──────────


class TestPreprobeSatisfiedAfterFix:
    def test_template_not_satisfied_then_fix_satisfied(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {"spec-a": {"status": "ready"}})
        write_contract(proot, TEMPLATE_YAML)
        # 模板态：诉求未满足（探测返回 False → 照常唤起 Administrator）
        assert mon._preprobe_signal_satisfied("verify_contract_missing") is False
        # 信号在途期间契约被修正为可解析：既有 PREPROBE 判满足 → 免唤起
        write_contract(proot, VALID_YAML)
        assert mon._preprobe_signal_satisfied("verify_contract_missing") is True

    def test_missing_file_not_satisfied(self, tmp_path):
        proot, _mon = make_monitor(tmp_path, {"spec-a": {"status": "ready"}})
        mon = _mon
        # 文件缺失同样不满足（防把「无契约回退」误判为已裁决）
        assert mon._preprobe_signal_satisfied("verify_contract_missing") is False
