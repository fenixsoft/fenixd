"""improve-spec-topology-pipeline-view 1.2：spec-review run 归属（uuid 段剥除）。

run_spec_part（core/agent_runner/run_files.py，全仓归属单源）对需求评审
run_id 形态 ``spec-review-<spec>-<6hex>-<unix秒>`` 剥除 uuid 段（specs/
topology-derivation「spec-review run 归属」Requirement）：

- spec-review 形态（含多段 attempt/transient 后缀组合）剥离断言；
- 非 spec-review 形态快照零回归——以修复前逻辑的逐字副本（``_legacy_``
  run_spec_part）为快照基准，对全部样本对账「返回值与修复前完全一致」
  （含 9-10 位数字保护样本 code-review item 6c089e65a080、fix 家族递归
  前缀、``-a<n>``/``-r<n>`` 链形态）。
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_runner.run_files import (  # noqa: E402
    RUN_ID_AGENT_PREFIXES,
    infer_run_agent_type,
    run_spec_part,
    strip_run_id_suffixes,
)

TS = "1792938331"
UUID6 = "8e869d"
SPEC = "add-collab-graph-bigscreen"


# ── 修复前逻辑逐字副本（快照基准：唯一用途是对账非 spec-review 形态零回归） ──


def _legacy_run_spec_part(run_id: str) -> str:
    _agent_type, spec_part = infer_run_agent_type(run_id)
    spec_part = strip_run_id_suffixes(spec_part)
    m = re.match(r"^(.*)-\d{9,10}$", spec_part)
    if m:
        spec_part = m.group(1)
    return spec_part


# ── Scenario「spec-review run_id 推断 spec 名全等」 ─────────────────────────


class TestSpecReviewUuidStripping:
    def test_field_sample_strips_uuid(self):
        # 实测样本形态：spec-review-add-collab-graph-bigscreen-8e869d-1792938331
        assert run_spec_part(f"spec-review-{SPEC}-{UUID6}-{TS}") == SPEC

    def test_short_spec_name_strips_uuid(self):
        assert run_spec_part(f"spec-review-demo-{UUID6}-{TS}") == "demo"

    def test_attempt_suffix_combos(self):
        # attempt / transient 后缀任意组合，uuid 段仍被剥除
        base = f"spec-review-{SPEC}-{UUID6}-{TS}"
        assert run_spec_part(f"{base}-a2") == SPEC
        assert run_spec_part(f"{base}-r1") == SPEC
        assert run_spec_part(f"{base}-a1-r2") == SPEC
        assert run_spec_part(f"{base}-a2-r3-a3") == SPEC

    def test_mixed_case_hex_not_stripped(self):
        # uuid 段生成方（uuid4().hex[:6]）恒小写 hex；大写形态不在剥除值域，
        # 保持不剥（严格限定既有写入方形态，不放大语义）
        assert (
            run_spec_part(f"spec-review-demo-ABCDEF-{TS}") == f"demo-ABCDEF"
        )

    def test_non_hex_tail_not_stripped(self):
        # 6 位非 hex 段（如 9-10 位数字时间戳已被上层剥掉、残余非 hex 尾巴）
        assert run_spec_part(f"spec-review-demo-xyz123-{TS}") == f"demo-xyz123"

    def test_uuid_only_segment_not_over_strip(self):
        # 「剥后非空才生效」守卫：畸形形态（前缀+空 spec 段+uuid+ts，双连字符）
        # 时间戳剥离后余 ``-<6hex>``，正则可命中但剥后为空 → 不剥，维持原样
        assert run_spec_part(f"spec-review--{UUID6}-{TS}") == f"-{UUID6}"
        # 裸 uuid 段（无前置连字符）：正则不命中，不剥
        assert run_spec_part(f"spec-review-{UUID6}-{TS}") == UUID6

    def test_no_timestamp_uuid_still_stripped(self):
        # 无时间戳段（锚点解析回落形态）：uuid 段仍剥除
        assert run_spec_part(f"spec-review-demo-{UUID6}") == "demo"

    def test_archive_path_form(self):
        # 归档产物文件名（.stem）同形态：拓扑 _family_run_paths 全等预过滤受益
        stem = f"spec-review-{SPEC}-{UUID6}-{TS}"
        assert run_spec_part(stem) == SPEC
        assert run_spec_part(stem) == SPEC  # 幂等

    def test_agent_prefix_table_still_spec_review(self):
        # 前缀表（唯一真源）spec-review 条目未被本改动漂移
        assert ("spec-review-", "spec-review") in RUN_ID_AGENT_PREFIXES
        assert infer_run_agent_type(f"spec-review-{SPEC}-{UUID6}-{TS}")[0] == "spec-review"


# ── Scenario「非 spec-review 形态推断行为不变」（快照对账） ─────────────────


NON_SPEC_REVIEW_SAMPLES = [
    # impl 家族 + attempt/transient 链
    f"impl-demo-{TS}",
    f"impl-demo-{TS}-a2",
    f"impl-demo-{TS}-a1-r2",
    f"impl-demo-{TS}-r1",
    f"impl-fix-demo-{TS}",
    # fix 家族递归前缀
    f"fix-fix-demo-{TS}",
    f"impl-fix-fix-demo-{TS}",
    # planner 家族
    f"planner-plan-{SPEC}-{TS}",
    f"planner-judge-{SPEC}-{TS}",
    f"planner-{SPEC}-{TS}",
    # spec-review 相邻前缀（review- 独立前缀，不得被吞并/误剥）
    f"review-20260101-{TS}",
    # 其它前缀
    f"code-review-demo-{TS}",
    f"code-fix-demo-{TS}",
    f"verify-demo-{TS}",
    f"tester-demo-{TS}",
    f"dispute-judge-demo-{TS}",
    f"admin-demo-{TS}",
    f"maintenance-scope-{TS}",
    f"evo-1772000001-{TS}",
    # 9-10 位数字保护样本（code-review item 6c089e65a080）：spec 名以
    # 9-10 位数字结尾时时间戳剥离本就不剥（无前置连字符语义不变），
    # uuid 剥除更不得新增误剥
    "impl-spec123456789-1772000000",
    "impl-spec1234567890-1772000000",
    "impl-demo-123456789",
    "impl-demo-1234567890",
    # 6 位数字尾巴的 impl 形态（uuid 剥除 MUST NOT 波及非 spec-review 前缀）
    "impl-demo-123456-1772000000",
    "planner-plan-demo-abcdef-1772000000",
    # 未知前缀/裸 run_id
    f"demo-{TS}",
    f"demo-{TS}-a1",
]


class TestNonSpecReviewSnapshotZeroRegression:
    @pytest.mark.parametrize("run_id", NON_SPEC_REVIEW_SAMPLES)
    def test_matches_pre_fix_behavior(self, run_id):
        # 快照对账：非 spec-review 形态返回值与修复前逐例一致
        assert run_spec_part(run_id) == _legacy_run_spec_part(run_id)

    def test_sample_list_nonempty_and_all_non_spec_review(self):
        assert NON_SPEC_REVIEW_SAMPLES
        assert all(not rid.startswith("spec-review-") for rid in NON_SPEC_REVIEW_SAMPLES)
