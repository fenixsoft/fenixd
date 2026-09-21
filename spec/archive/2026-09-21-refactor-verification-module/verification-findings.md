# 疑点清单：refactor-verification-module

本文件登记拆分重构过程中**发现但不修复**的疑点（tasks 1.3 / 1.5 基线，
proposal「不顺手修 bug（只记疑点清单）」；spec「拆分零行为变化」）。
记录格式：`[<日期>] <模块>:<符号> — <疑点描述>（<影响评估>）`。

## 已登记疑点

- [2026-09-16] `core/pm_engine/verification.py`:`_serve_command_in_worktree` —
  `_port_responds` 串行探测 51 个端口（每个 `urlopen` timeout=1.0），当
  `legacy_hint` 存在时最坏 51s 阻塞。**影响**：serving 路径选择时的延迟尖峰，
  对用户可见（验证阶段2 前的等待）。已知 legacy_hint 场景在当前版本已大幅减少，
  但保留逻辑未清理。

- [2026-09-16] `core/pm_engine/verification.py`:`_ensure_serving_worktree` —
  `import subprocess`（第15行全局 import）在模块顶部导入后于多处调用
  `subprocess.run(..., shell=True)`（594行、668行、1046行）执行用户配置的
  `serve.cmd`。**影响**：`shell=True` 是有意设计（用户配置命令需 shell 展开），
  但配合 `env` 字典注入端口（589行 `env={**os.environ, "FENIX_VERIFY_PORT": ...}`）
  存在潜在的注入放大面——`serve.cmd` 来自 `.fenix/verify.yaml` 的
  trusted 配置，安全边界依赖 `verify.yaml` 写入权限。

- [2026-09-16] `core/pm_engine/verification.py` — 文件内 3 处
  `import re as _re`（569行、642行、3324行）重复 late-import 同一 stdlib 模块，
  分别在 `_serve_command_in_worktree`、`_serve_command_in_main`、
  `_normalize_fail_signature` 中。**影响**：仅代码整洁度（late import 可
  统一移至模块顶部或 `__init__` 内一次导入），不影响运行时行为。

- [2026-09-16] `core/pm_engine/verification.py`:`_apply_scenario_freeze` —
  实例属性 `_last_freeze_rejected` / `_last_freeze_rejected_covers`
  （1380行、1390行）在方法体内赋值，未在 `__init__` 或 `__slots__` 中声明，
  由 `_apply_interaction_contract`（1643行 `getattr`）消费。**影响**：若
  `_apply_interaction_contract` 先于 `_apply_scenario_freeze` 执行，
  `getattr(..., None)` 兜底安全；当前调用顺序（freeze 在 interaction_contract
  之前）确保正确。

- [2026-09-16] `core/pm_engine/verification.py`:`_handle_env_blocked_inconclusive` —
  `_verify_parallel_override` 降档公式 `max(1, base >> (attempts - 1))`
  用位移做除法（等价于 `base // 2**(attempts-1)`，向下取整），当 `base`
  为奇数时与除法有差异（`5>>1=2` vs `5//2=2`；`7>>1=3` vs `7//2=3`；无实际
  差异，位移与除法在正整数上等价）。**影响**：无实质行为差异，仅风格选型。

- [2026-09-16] `core/pm_engine/verification.py`:docstring (第1行) —
  文件 docstring 引用 `design D3 规则 3` 来自 `refactor-core-packages`
  阶段5，本变更（refactor-verification-module）完成后该引用需更新为
  本变更的 design D1（PipelineContext）。**影响**：仅文档准确性，
  不影响运行时行为；重构完成后 docstring 应刷新为当前 design 编号。

- [2026-09-16] `core/pm_engine/verification.py`:`_env_whitewash_gate` —
  `whitewash_violations` 返回值直接传给 `_escalate_env_blocked`，
  后者内部做 `violations[:3]` 截断后拼入 `error_msg[:300]`。**影响**：
  超长违规列表不会导致错误消息溢出，但 violation 原文超过 300 字符时
  管理员看到的 evidence 信息不完整——可通过截断点前加 `...` 标注截断
  来改善可读性（不在本变更范围内）。

- [2026-09-16] `core/pm_engine/verification.py`:`_record_verdict_adoption` —
  `prev_raw = entry.get("_judge_token_baseline")` 从 STATE.md 读出的
  JSON 字符串，若之前写入时 `json.dumps(cur)` 含不可序列化值，
  这里 `json.loads` 会抛 `TypeError`（被外层 except 捕获，prev=None）。
  **影响**：当前 `_sum_verify_chain_tokens` 返回 `{input: int, output: int}`
  结构，JSON 序列化安全；但如果未来 token 统计扩展字段类型，此处
  静默 fallback 为 None 会导致 delta 计算基于全零基线——不致命但可能
  导致 STATE.md 中 `_judge_token_delta` 首轮值偏大。

- [2026-09-16] `core/pm_engine/verification.py`:`_run_legacy_verification` —
  legacy 路径读取共享文件时（5524-5527行），当 primary `.fenix-run-result.json`
  不存在时 fallback 到主树共享文件，该 fallback 与 `_read_verdict`（5945行）
  的共享文件读取逻辑有代码重复。**影响**：当前 `_read_verdict` 已承担
  统一读取入口（R1 重构），legacy 路径经 `_read_verdict` 调用后仍保留
  自己的 `run_result_path` fallback 计算用于 `_verifier_result_is_stale`
  的 `result_path` 参数——两者取同一文件，路径重复但语义一致。

- [2026-09-16] `core/pm_engine/verification.py`:`_ensure_serving_worktree` —
  `_unregister_serving_instance` 在 `old_server.stop()` 之前调用（471-475行），
  但 `stop()` 的 except 仅 `pass`（474行）。若 `stop()` 抛异常但
  `_unregister_serving_instance` 已清理注册，后续复用逻辑可能看到
  残留的旧进程。**影响**：低概率（stop 异常通常为进程已死），
  且 `CommandVerifyServer.ok` 属性会检测进程存活。

## 最终汇报（tasks 7.2，阶段6）

重构完成（2026-09-16）：`core/pm_engine/verification.py`（6304 行）已按 D2
分组拆为 `core/pm_engine/verification/` 子包（9 个职责子模块 + `pipeline.py`
门面 + `context.py`），全量 pytest 存量回归零引入。疑点清单最终态：

- 全部疑点**仅记录不修复**，随重构保持原样（`_serve_command_in_worktree`
  串行端口探测、`shell=True` 注入面、late-import `re`、`_last_freeze_rejected*`
  未在 `__init__` 声明、位移降档公式、docstring 引用过时、白名单截断
  evidence、token 基线 JSON fallback、legacy fallback 路径重复、
  `_unregister_serving_instance` 先于 `stop()`）。修复一律另立任务/SPEC。

- 重构期新引入问题（非疑点，已修复收口）：
  1. `runner.py` 格式化后 3799→4090 行，将破坏上一 spec 行数契约
     （≤3800）——已在 `scripts/format_code.sh` 显式排除
     `core/agent_runner/runner.py`（见 formatting-report.md）；
  2. 拆分初期薄委托签名与模块函数签名偶发不匹配（`_resynthesis_*`
     族漏传 pipeline 等）——已逐项修复并全量回归确认。

- 收尾验证（tasks 7.2）：全量 `bin/run_full_suite.py --timeout 3600
  --baseline 5bcf029c` → 分类「存量」，6 失败全部为基线现存
  （dashboard×2 + task_track×4），零本次引入。

## 使用说明

- 只记录、不修复；修复一律另立任务/SPEC。
- 本清单随重构推进持续更新：新增疑点追加，任务书显式修复项在完成时标注。
- 阶段 6（tasks 7.2）向用户汇报疑点清单最终态。
