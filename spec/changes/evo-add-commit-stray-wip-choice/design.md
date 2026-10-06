## Context

注册表单源：core/dashboard/data/adjudication_choices.py:90-267 _ADJUDICATION_REGISTRY（9 桶 15 选项，:27「全量 8 类」注释陈旧）。执行分派：core/dashboard/data/admin_actions.py:2700 execute_adjudication_choice（resolve_choice :386、全局信号守卫 :2757 附近——spec_scoped=True 对 spec=None 信号必拒）。发射点：core/worktree_manager/stray_wip.py:700-722 _write_alert（记录无 choices 键；recommended_action 静态文案 :714-720），同文副本 core/admin_monitor.py:436 SIGNAL_RECOMMENDATION。快照先例：core/worktree_manager/mergeback.py:732-737。消费契约：agents/administrator.md:110-115。前端通用渲染：AlertBanner.tsx:192/detail.tsx:1793，缺键回退 core/dashboard/routes/alert_routes.py:437。

## Goals / Non-Goals

- Goals：同型信号裁决标准化、可一键执行、留痕提交 hash；建议-消费回路闭环（两次回填建议终于被消费）。
- Non-Goals：不做 stash/discard 姊妹项；不改摄取唤起策略；不动前端。

## Decisions

- D1 spec_scoped=False 硬约束：maintree_stray_wip_stale 是全局信号（spec 恒 None），全局信号守卫会拒 spec_scoped 选项——漏声明则选项永远执行不了。
- D2 清单约束守卫：这是 admin_actions 首个对主树执行 git 写的执行器（现存执行器只动 spec 状态机/配置），文件来源 MUST 限信号 evidence 清单或当刻 git status 匹配项，拒任意路径；非 destructive（提交可回溯），无需确认门。
- D3 choices 快照照 mergeback 先例放发射点，注册表仍为单源（缺键回退） ；SIGNAL_RECOMMENDATION 同文同步防双处漂移。

## Risks / Trade-offs

- 归属核对不可完全委托：自动唤起会话仍需判断改动归属（交互会话遗留 vs 车道漏提交），选项只把「执行+留痕」标准化，不替代判断——口径已在 proposal 标明。
- 主树 git 写的新暴露面：以清单约束+非 destructive+提交 hash 留痕三重兜底。