# 验证准备失败 infra-retry 廉价重试车道

<!-- knowledge: capability=verify-infra-retry rev=1
     sources=spec/archive/2026-10-28-evo-verify-infra-retry-lane -->

验证准备阶段的宿主/环境失败廉价重试车道：prepare 失败与可达性 fail-fast（0 场景执行即短路）不再直接烧全价升级，先按限次预算廉价重派验证，超预算才恢复既有全价升级；宿主预检以项目 prepare 步骤表达并有模板样板可抄。

## 规则

- 触发面：verify prepare 步骤失败或应用可达性 fail-fast（0 场景执行即短路）归类为 infra-retry——不计 env 冻结轮（`_env_block_rounds` 不递增）、不写 blocked/status/error、不落 `verify_env_blocked` 信号、不呼叫 Administrator。车道只覆盖 0 场景执行的确定性短路轮。
- 限次决议：infra-retry 专用连续重派计数（`_verify_infra_retry_streak`，与纯观测的 `_verify_infra_rounds` 严格分离、互不递增对方判定）+1 后与预算比较；预算读 `verify_engine.infra_retry_max`（缺省 2；None/非数字/bool/非正值一律回退缺省）。计数 ≤ 预算 → 「重派」决议；计数 > 预算 → 恢复既有全价升级（计冻结轮、连续 2 轮按 ENV_BLOCK_FREEZE_THRESHOLD 冻结转人工）。
- 重派机械路径：经既有 verifier 派发入口重新入队，不绕派发队列直调；接线缺失或派发异常回落 context 直接入队（本轮记账/决议已在上游完成，不因机械路径故障升级为全价轮），二次回落仍失败则保持 testing 由 recovery 兜底重排。
- 决策点单点：可达性 fail-fast 调用点保持调用 `_escalate_env_blocked`（infra_retry 标记全仓唯一传点，该分支同时覆盖 prepare 失败与可达性失败两条汇入路径），由升级通道入口先经 `_record_infra_failure(retry_gate=True)` 咨询决议；该调用兼任唯一入账点（预算退款、`_verify_infra_rounds` 观测轮、infra 失败台账照常），escalate 决议后禁二次记账，调用点禁绕开该函数另起入账路径（双决策点双重入账、口径漂移）。
- 保守升级：专用计数失败或决议中途异常 → 保守按「达预算」落全价升级，不无限廉价重试。
- 计数清零点：验证 PASS（与 `_verify_fail_rounds` 唯一归零点对齐）+ 人工解冻 unfreeze_spec 清零清单（同一原子写）；其余中间转换不清零——保证解冻后「缺省 2 次廉价重派」预算可再得。
- env 语义零污染：场景执行后的 env 阻塞分类（env_gate/engine 探针后置分类）不带 infra_retry 标记，仍走既有 blocked→升级全价路径；`_verify_infra_rounds` 保持纯观测语义，两车道照常递增、归零点不变；infra-retry 轮不污染 env 冻结计数与豁免语义。
- 同因重派熔断隔离：infra-retry 车道不经通用失败重派分支，不增减 `_redispatch_same_cause_streak` / `_redispatch_cause_fp`。
- user_blocked 守卫：需用户参与的可达性失败（user_blocked=True，预留判定位）不进短路分支，不得被 infra-retry 短路自动重派。
- 宿主预检样板：verify 契约模板 prepare 段提供宿主预检示例步骤（注释形态，全注释即整段不生效）——① 无主 qemu/emulator 进程扫描清理：只清 ppid=1 且可归属到已完成 run 的进程，清理前记录被杀 pid，MUST NOT 全量清杀（同宿主可能有其它活跃 run 的模拟器，归属不了的不动）；② 残留 AVD 锁清理：只删明确属于本项目 AVD 目录的锁文件；③ KVM/内存水位检查：不可用/过低尽早失败；④ 场景特异冒烟探针（如 OpenCV init）：依赖缺失/版本不兼容前移到构建前暴露。
- 预检纪律：宿主预检作为 prepare 首个步骤声明在构建命令之前；命令须幂等（每轮验证都执行）且失败非零退出；可自动修复的环境问题在宿主侧修掉，修不掉的以非零退出如实上报，禁吞错退 0（假绿把环境故障推迟到场景执行期，错过廉价重试窗口）。
- 预检边界：框架不做场景特异预检词表、不做框架级「自动杀无主进程」执行器——清理动作留项目 prepare 步骤自治；被杀 pid 留痕沿 prepare 既有日志通道（样板步骤写 `.fenix/preflight-killed.log`），框架不为预检新增留痕结构。

## 关键行为

1. prepare 失败/可达性 fail-fast（0 场景执行）→ 调 `_escalate_env_blocked(infra_retry=True)`。
2. 升级入口先 `_record_infra_failure(retry_gate=True)`：专用计数 +1 并与预算比较，同时照常 infra 记账（退款/观测轮/台账）。
3. 未达预算 → 旁路早退返回 "redispatch"（全部全价写点均不经过），调用点经既有 verifier 派发入口廉价重派，本轮按 aborted 收口。
4. 达预算 → 落穿既有全价路径：env 冻结轮 +1、blocked 落盘、Administrator 自动呼叫、连续 2 轮冻结转人工。

## 溯源

- 2026-10-28 evo-verify-infra-retry-lane（spec/archive/2026-10-28-evo-verify-infra-retry-lane） — 新增 prepare/可达性 fail-fast 的 infra-retry 廉价重试车道（专用限次计数、决策点单点化、重派走既有派发入口）与契约模板宿主预检样板；此前该路径只有全价升级一条通道，唯一 infra 让步是预算退款。
