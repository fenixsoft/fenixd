# 快车道执行模式（fast-track 单 run 全包）
<!-- knowledge: capability=fast-track-mode rev=2
     sources=spec/archive/2026-09-09-add-fast-track-mode,spec/archive/2026-09-18-fix-fasttrack-resultfile-missing-redispatch -->

`mode=fast-track` 的 SPEC 由单个 agent run 在同一上下文中依次完成实现、验证场景设计、场景验证与结果判定，不拆 planner/verifier 流水线。

## 规则

- fast-track SPEC 进入 `ready` 后派发单个 fast-track agent run（同一 agent 进程、同一上下文、同一 worktree）；框架不得为它派发独立 planner run 或 verifier run。
- 状态机不变：仍沿 `ready → implementing → implemented → testing → verified` 推进，复用既有 `VALID_TRANSITIONS`，无新增状态。
- agent 不直接操作状态机；run 结束输出统一结果文件（实现产物清单、设计场景、逐场景验证结果、最终判定），daemon 读取并校验后推进状态。
- 结果文件缺失按分支处置：
  - run 正常收工（exit 0、`result.success` 为真、`result.branch` 非空）且实现分支相对 main 有提交（`git rev-list --count main..branch` > 0）：不判死亡——不回退预算、不 reset ready、不重派实现；merge 实现分支（复用 `_reconcile_and_merge`），改写 `.spec.yaml` mode 为 `full` 并 enqueue 完整模式 verifier 补齐缺失 verdict（升级语义、触发因不同），后续走既有 verified→done 门；spec entry 记录升级原因。
  - 结果文件缺失且分支零提交、或 `result.branch` 为空（失败/中断 run）：判死亡并豁免预算 + reset ready + 自动重派 fast-track，entry 记录原因。
- 结果文件存在但格式非法或未通过框架硬校验：不推进状态，按失败处理（重派或累计 fail 计数），entry 记录原因。
- 判定硬校验兜底：最终判定必须通过框架侧确定性校验——报告结构完整性、设计场景全量执行（无静默遗漏/豁免逃逸）、逐场景证据存在性；agent 文本宣称（「验证通过」「测试全绿」）不作为通过依据；豁免按既有 verdict_check 规则复核，非法豁免视为 bug 未修复。
- 护栏对单 run 生效，语义从「run 间」适配为「run 内」，阻断行为与完整模式一致：零变更哨（宣称成功但分支零新提交且零 Edit/Write 调用 → 不合并、不推进、重派，连续 3 次 blocked 交人工）、交付物存在性守卫（缺件清单带出重派）、fail 预算与 token 预算。
- bug 在 run 内修复：验证发现 bug 时同一上下文修复并重验，修复轮次计入 fix 预算；预算耗尽仍有未修复 bug 时，框架自动把 mode 改写为 `full`（保留 worktree/分支成果）按完整流水线继续，记录升级原因，不静默丢弃也不直接 blocked。
- worktree 全生命周期复用：实现与验证在同一 worktree（验证直接在该 worktree 运行被测应用，无跨 worktree 同步步骤）；成功路径 merge 语义与完整模式一致（含派发前 `ensure_spec_committed` 的 spec 目录提交前提）。

## 溯源

- 2026-09-09 2026-09-09-add-fast-track-mode — 新增快车道：单 run 全包执行、统一结果文件驱动状态推进、护栏与硬校验适配单 run、run 内修复与超预算升级、worktree 复用与合并语义
- 2026-09-18 2026-09-18-fix-fasttrack-resultfile-missing-redispatch — 结果文件缺失不再一律判死重派：分支有提交时 merge 后升级 full 补验证，零提交/无分支才判死亡重派
