# Design

## 上下文

core/wip_checkpoint.py:34-37 为锚点常量区（既有 ANCHOR_FREEZE_HOLD 等）；core/agent_runner/runner.py:2327 _wip_checkpoint_commit_safe 为 checkpoint 单点内核（None 跳过→worktree 校验→commit→WARNING 兜底），既有调用先例：freeze runner.py:5981、turn-limit :6072、extension-tail :6108、瞬态退避 :4312。取消路径现状：runner.py:1050 cancel_run 按 base_run_id 登记旗标，:3305-3324 RunCancelledError 分支直接 success=False 收口。dashboard 侧：QualityTab.tsx:776-793 handleCancel 直连 cancelRun、:1157「取消」按钮无确认；同文件 :1180 附近「生成修复 SPEC」已有 Modal.confirm 先例；runs 列表取消已有 RunCancelModal 确认框（不动）。worktree 生命周期：lifecycle.py:658,700-712 失败 implementer 分支走 register_legacy 保留（宽限期 LEGACY_GRACE_SECONDS）。

## 方案

1. 锚点：core/wip_checkpoint.py 新增 ANCHOR_CANCEL = "cancel"；checkpoint 消息沿用 fenix(wip): checkpoint <anchor> <spec> 契约，便于审计区分「用户取消但现场已保全」。
2. 接入点：优先选轮询环内取消旗标命中确认处（worktree 路径尚在作用域）调用 _wip_checkpoint_commit_safe；RunCancelledError 收口分支作兜底（wt_path 可得则补一次）。attempt 间隙（not_running 分支）无 worktree，跳过即可。失败仅 WARNING 降级，绝不阻断取消收口（对齐既有三锚点语义）。
3. 文案修正：runner.py:1125 附近取消审计告警 recommended_action 改为「失败 implementer worktree 将登记为 legacy 保留（宽限期后回收），未提交改动不进入分支提交」。
4. QualityTab：handleCancel 前加 Modal.confirm（danger），确认后才调 cancelRun；错误处理沿用 ApiError.code 稳定错误码分支先例，不做文案子串匹配。runs 列表「终止」已有 Modal，不再叠加。
5. 不立项「链级取消确认/分列」——该操作不存在；本 spec 不改变取消语义、不新增取消端点。

## 测试

- tests/test_impl_wip_checkpoint.py：取消锚点 checkpoint 写入、失败 WARNING 降级不阻断、attempt 间隙跳过。
- tests/test_run_cancel.py：取消收口前已产 checkpoint 的集成用例、审计文案断言。
- 回滚：改动集中在接入点与常量，回滚即移除调用与锚点。