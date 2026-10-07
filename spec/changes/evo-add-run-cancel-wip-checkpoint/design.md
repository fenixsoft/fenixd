# Design

## 上下文

core/wip_checkpoint.py:34-37 为锚点常量区（既有 ANCHOR_FREEZE_HOLD 等）；core/agent_runner/runner.py:2327 _wip_checkpoint_commit_safe 为 checkpoint 单点内核（None 跳过→worktree 校验→commit→WARNING 兜底），既有调用先例：freeze runner.py:5981、turn-limit :6072、extension-tail :6108、瞬态退避 :4312。取消路径现状：runner.py:1050 cancel_run 按 base_run_id 登记旗标，:3305-3324 RunCancelledError 分支直接 success=False 收口。dashboard 侧：QualityTab.tsx:776-793 handleCancel 直连 cancelRun、:1157「取消」按钮无确认；同文件 :1180 附近「生成修复 SPEC」已有 Modal.confirm 先例；runs 列表取消已有 RunCancelModal 确认框（不动）。worktree 生命周期：失败终态 worktree 分型收口在 runner.py `_finalize_failure_keep`（:4899，单调用点 :3558）——fast-track/transient 走 keep_for_reuse（底层 core/worktree_manager/legacy_registry.py:22 `register_legacy`，宽限期 LEGACY_GRACE_SECONDS 见 core/worktree_manager/constants.py:23），implementer 等其余终态落 else `cleanup(success=False)` 删除，无取消专属保留分支；RunCancelledError 异常 break 路径（runner.py:3304）不经过该分型，worktree 无登记保留。（注：原稿引用 lifecycle.py:658,700-712 系笔误，该文件不存在。）

## 方案

1. 锚点：core/wip_checkpoint.py 新增 ANCHOR_CANCEL = "cancel"；checkpoint 消息沿用 fenix(wip): checkpoint <anchor> <spec> 契约，便于审计区分「用户取消但现场已保全」。
2. 接入点：轮询环内取消旗标命中确认处（runner.py:6006 附近，cwd 与 spec_name 均在作用域，freeze :5982 / 判停 :6072 强杀先例同位），在 terminate→grace→kill 序列完成后、构造 cancel_error 与 break 之前，调用 `self._wip_checkpoint_on_forced_kill(spec_name, cwd, anchor=ANCHOR_CANCEL)`。MUST NOT 直连 `_wip_checkpoint_commit_safe` 裸调：该内核默认 exclude_main_tree=False，spec-review/dispute-judge 等无 worktree 车道（cwd=主树）被取消时会把主树无关脏状态卷进主分支提交（fix-main-tree-wip-checkpoint 修过的问题回归）；forced_kill 助手自带 exclude_main_tree=True。时序对齐 turn-limit 语义：agent 已被 terminate/kill、可证明不再写盘后再提交（不复刻 freeze 在 terminate 前的有意竞态）。RunCancelledError 收口分支（runner.py:3304）作兜底：此处 wt_path 尚在作用域且早于循环后任何分型清理，wt_path 可得则补一次（同 exclude_main_tree 语义，主树跳过）。attempt 间隙（not_running 分支）无 worktree，跳过即可。失败仅 WARNING 降级，绝不阻断取消收口（对齐既有锚点语义）。
3. 文案修正：runner.py:1141-1148 取消审计告警 recommended_action 中「注意：取消路径不做 WIP checkpoint（与 freeze/超时/turn-limit 强杀路径不同），attempt 的未提交工作将随 cleanup(success=False) 丢弃——需保全现场请先在 worktree 提交或改用 freeze」失实句替换为如实表述，旗标登记/收口描述句（「run 已登记取消旗标……按既有节奏接管」）原样保留。替换文本要点：取消收口前已尽力执行 WIP checkpoint（未提交改动以 fenix(wip): checkpoint cancel <spec> 提交进入 attempt 分支，可从分支恢复；无 worktree 载体或主树车道则无保全）；worktree 目录去向按车道——fast-track/transient 等车道经 keep_for_reuse 登记为复用遗产保留（宽限期后回收），其余车道维持既有收口处置，分支与 wip 提交不受影响。原拟「失败 implementer worktree 将登记为 legacy 保留」经实测失实（implementer 取消终态无 legacy 登记分支，见上下文段），不得如此表述；「未提交改动不进入分支提交」与本 spec 自身 checkpoint 行为（提交进分支）矛盾，一并废除。
4. QualityTab：handleCancel 前加 Modal.confirm（danger），确认后才调 cancelRun；错误处理沿用 ApiError.code 稳定错误码分支先例，不做文案子串匹配。runs 列表「终止」已有 Modal，不再叠加。
5. 不立项「链级取消确认/分列」——该操作不存在；本 spec 不改变取消语义、不新增取消端点。

## 测试

- tests/test_impl_wip_checkpoint.py：取消锚点 checkpoint 写入、失败 WARNING 降级不阻断、attempt 间隙跳过、主树车道跳过（exclude_main_tree 经 forced_kill 助手生效）。
- tests/test_run_cancel.py：取消收口前已产 checkpoint 的集成用例、审计文案断言。
- 回滚：改动集中在接入点与常量，回滚即移除调用与锚点。