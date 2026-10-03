"""core.pm_engine.verification — 门面（facade）re-export。

refactor-verification-module D8/D9：`verification.py` 单文件模块拆分为
`verification/` 子包。本模块作为薄门面逐条 re-export `_legacy` 的全部既有
公开与私有名字，保证既有调用路径（`from core.pm_engine.verification import X`
与测试字符串路径 patch）零改动。

_D9 约定_：`subprocess` / `probe_ready` / `ensure_main_tree_deps` /
`run_prepare_steps` / `load_verify_contract` / `rewrite_scenarios_origin`
六个可 patch 名绑定在本门面；`_legacy` 内对它们的调用点 MUST 经本门面延迟解析（`import
core.pm_engine.verification as _facade; _facade.<name>(...)`），使
`patch("core.pm_engine.verification.<name>")` 继续命中。
"""

from core.pm_engine.verification.context import PipelineContext

# D9 patch 缝隙：可 patch 名保留在本门面绑定（tests 以字符串路径 patch）。
# - subprocess / time：stdlib 模块，_legacy 顶层 import 同一对象，
#   patch `.run` / `.sleep` 等属性全仓生效（同模块对象引用）
# - probe_ready / ensure_main_tree_deps / run_prepare_steps /
#   load_verify_contract / rewrite_scenarios_origin：_legacy 调用点经
#   _facade 延迟解析（见 D9），或为 module-level import 供
#   patch.object(_vmod, "probe_ready") 断言
import subprocess
import time
from core.verify_contract import (
    ensure_main_tree_deps,
    load_verify_contract,
    probe_ready,
    rewrite_scenarios_origin,
    run_prepare_steps,
)

from core.pm_engine.verification.pipeline import (
    ENV_BLOCK_SIGNAL_TYPES,
    LEGACY_START_PROBE_ATTEMPTS,
    LEGACY_START_PROBE_INTERVAL_SECONDS,
    POST_READY_SETTLE_SECONDS,
    VerificationPipeline,
    _MAX_JUDGE_RERUNS,
    _SCENARIO_REPAIR_MAX_ROUNDS,
)
from core.pm_engine.verification.branch_guard import (
    ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS,
    _branch_merged_into_tree,
    resolve_env_blocked_reset_path,
)
from core.pm_engine.verification.infra_classify import (
    RECLASSIFY_SIGNAL_TYPE,
    reclassify_infra_rounds,
)
from core.pm_engine.verification.report_gate import VerdictReadResult

__all__ = [
    "PipelineContext",
    "VerdictReadResult",
    "VerificationPipeline",
    "reclassify_infra_rounds",
    "resolve_env_blocked_reset_path",
    "_branch_merged_into_tree",
    "_SCENARIO_REPAIR_MAX_ROUNDS",
    "_MAX_JUDGE_RERUNS",
    "RECLASSIFY_SIGNAL_TYPE",
    "POST_READY_SETTLE_SECONDS",
    "LEGACY_START_PROBE_ATTEMPTS",
    "LEGACY_START_PROBE_INTERVAL_SECONDS",
    "ENV_BLOCK_SIGNAL_TYPES",
    "ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS",
    # D9 patch 缝隙（保留引用使 patch 路径可解析）
    "subprocess",
    "time",
    "probe_ready",
    "ensure_main_tree_deps",
    "run_prepare_steps",
    "load_verify_contract",
    "rewrite_scenarios_origin",
]
