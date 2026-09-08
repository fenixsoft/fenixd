# Proposal: fix-run-cancel-retry-flag-miss

## Why

人工取消原语（add-run-cancel）对「原地瞬态重试」的 run 失效。事故实证（2026-09-08，verify-draft-fixture 夹具收口）：judge run 经瞬态重试后 run_id 为 `planner-judge-<spec>-<ts>-a1-r1`，dashboard 走 `POST /api/run-cancel` 登记取消旗标后，日志显示「已登记旗标、命中活跃 attempt」，但轮询环永不消费——进程继续烧钱，只能等自然超时。

根因：`AgentRunner._normalize_run_id`（core/agent_runner/runner.py）只剥尾部 `-a\d+` 一组后缀，而瞬态重试子循环自拼 `-r{N}` 后缀（runner.py 瞬态重试处 `sub_run_id = f"{attempt_run_id}-r{transient_retries}"`）。登记键（剥尾 base）与消费键（`-a1-r1` 原样）精确匹配永远失配，取消旗标对全部带 `-r<N>` 后缀的 run 静默失明。

## What Changes

- `AgentRunner._normalize_run_id`：归一化改为可剥离**连续多组**尾部 `-a<N>` / `-r<N>` 后缀（如 `...-a1-r1` → `...`），保持无后缀输入幂等不变。
- `AgentRunner._cancel_is_requested`：判定前先对入参做同一归一化，使 attempt 循环顶（传 run 级 id）与轮询环（传 attempt/子 run id）两类消费点与 cancel_run 登记键收敛到同一 base 键。
- 补齐 `tests/test_run_cancel.py` 用例：`-r` 后缀轮的旗标命中、attempt 顶阻断、既有语义回归。

## Capabilities

### New Capabilities

（无——本变更修复既有 run-cancel 能力的缺陷，不引入新能力）

### Modified Capabilities

- `run-cancel`: 取消旗标对带 `-r<N>` 瞬态重试后缀的 run 同样生效；消费键归一化与登记键一致。

## Impact

- `core/agent_runner/runner.py`（`_normalize_run_id` / `_cancel_is_requested` 两个函数，纯内存判定，无状态迁移、无接口变更）
- `tests/test_run_cancel.py`（新增用例）
- 风险面：spec 名若以 `-a<N>`/`-r<N>` 形态结尾会被过度剥离——与既有 `-a\d+$` 剥离同级风险，本项目 kebab-case spec 名无此形态，设计中登记缓解。
