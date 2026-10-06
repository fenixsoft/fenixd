## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_global_signal_choice_guard.py
  kind: modify
- path: tests/test_maintree_stray_wip_sweep.py
  kind: modify
```

## 1. 注册表登记

- [ ] 1.1 core/dashboard/data/adjudication_choices.py：_ADJUDICATION_REGISTRY 新增 maintree_stray_wip_stale 桶与选项 commit_stray_wip（id/label/desc/action 齐备，MUST spec_scoped=False——该信号 spec 恒 None，全局信号守卫会拒 spec_scoped 动作），语义按处置记录 4a1464085660 的 suggested_choice 原文：核对归属后直接提交散件 WIP、与 stash 类动作互斥、处置记录附提交 hash；顺带修正 ：27 陈旧的「全量 8 类」注释。

## 2. 执行器与信号带出

- [ ] 2.1 core/dashboard/data/admin_actions.py：execute_adjudication_choice（:2700 附近）新增 commit_stray_wip 分支与执行函数——只提交信号清单内文件（清单解析自 maintree_stray_wip_stale 信号记录 evidence 的「文件清单(N):」段、与当刻 `git status --porcelain` 求交；已不在当刻 status 的文件跳过不报错，交集为空返回明确 error 不空提交；拒任意路径），提交后在处置结果附提交 hash；MUST 校验 signal_type=="maintree_stray_wip_stale"，其余信号类型（含未注册信号与姊妹信号 maintree_untracked_stray_stale）一律拒绝（防 resolve_choice 非作用域全表反查通道把本 git 写动作暴露给任意未注册信号，见 design D4）。
- [ ] 2.2 core/worktree_manager/stray_wip.py：_write_alert（:700-722）记录补 choices 快照（照 core/worktree_manager/mergeback.py:732 先例 choices_for(...)），recommended_action 文案带出 commit_stray_wip。
- [ ] 2.3 core/admin_monitor.py：SIGNAL_RECOMMENDATION（:436）同文同步，防止双处漂移。

## 3. 测试

- [ ] 3.1 tests/test_adjudication_choices.py：新桶/选项注册、resolve_choice、is_adjudicable(maintree_stray_wip_stale) 为真。
- [ ] 3.2 tests/test_global_signal_choice_guard.py：全局信号（spec=None）与 commit_stray_wip 的执行路径放行；清单外路径拒绝、清单内执行附提交 hash；非 maintree_stray_wip_stale 的 signal_type（含未注册信号与姊妹信号 maintree_untracked_stray_stale）请求 commit_stray_wip 被拒且零 git 写（design D4 绑定守卫）。
- [ ] 3.3 tests/test_maintree_stray_wip_sweep.py：发射侧记录含 choices 快照、recommended_action 带出选项 id。