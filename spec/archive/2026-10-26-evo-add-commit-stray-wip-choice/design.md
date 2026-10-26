## Context

注册表单源：core/dashboard/data/adjudication_choices.py:90-267 _ADJUDICATION_REGISTRY（9 桶 15 选项，:27「全量 8 类」注释陈旧）。执行分派：core/dashboard/data/admin_actions.py:2700 execute_adjudication_choice（resolve_choice :386、全局信号守卫 :2757 附近——spec_scoped=True 对 spec=None 信号必拒）。发射点：core/worktree_manager/stray_wip.py:700-722 _write_alert（记录无 choices 键；recommended_action 静态文案 :714-720），同文副本 core/admin_monitor.py:436 SIGNAL_RECOMMENDATION。快照先例：core/worktree_manager/mergeback.py:732-737。消费契约：agents/administrator.md:110-115。前端通用渲染：AlertBanner.tsx:192/detail.tsx:1793，缺键回退 core/dashboard/routes/alert_routes.py:437。

## Goals / Non-Goals

- Goals：同型信号裁决标准化、可一键执行、留痕提交 hash；建议-消费回路闭环（两次回填建议终于被消费）。
- Non-Goals：不做 stash/discard 姊妹项；不改摄取唤起策略；不动前端。

## Decisions

- D1 spec_scoped=False 硬约束：maintree_stray_wip_stale 是全局信号（spec 恒 None），全局信号守卫会拒 spec_scoped 选项——漏声明则选项永远执行不了。
- D2 清单约束守卫：这是 admin_actions 首个对主树执行 git 写的执行器（现存执行器只动 spec 状态机/配置），文件来源 MUST 限信号记录 evidence 的「文件清单(N):」段（stray_wip.py:625 内嵌 prose，按段解析）与当刻 `git status --porcelain` 的交集，拒任意路径；清单中已不在当刻 status 的文件跳过不报错（同指纹一次性告警，清单会陈旧），交集为空时返回明确 error、不产生空提交；非 destructive（提交可回溯），无需确认门。
- D4 signal_type 绑定守卫（评审修补）：resolve_choice 对「signal_type 未注册」存在非 spec_scoped 动作全表反查放行通道（adjudication_choices.py:405-417；既有经该通道可达的非作用域动作 ack_self_heal/ignore/open_config/declare_no_artifacts 全为纯留痕类，无 git 写）。commit_stray_wip 注册为非作用域动作后将成首个经该通道可达的 git 写动作——任意未注册信号（含 info 级「不派生任何自动处置」的姊妹信号 maintree_untracked_stray_stale，stray_wip.py:640-641）都可触达。执行器 MUST 校验 signal_type == "maintree_stray_wip_stale"，其余一律拒绝，文件清单也只从该类型信号记录解析——把 git 写暴露面收口到本信号。
- D3 choices 快照照 mergeback 先例放发射点，注册表仍为单源（缺键回退） ；SIGNAL_RECOMMENDATION 同文同步防双处漂移。

## Risks / Trade-offs

- 归属核对不可完全委托：自动唤起会话仍需判断改动归属（交互会话遗留 vs 车道漏提交），选项只把「执行+留痕」标准化，不替代判断——口径已在 proposal 标明。
- 主树 git 写的新暴露面：以清单约束+非 destructive+提交 hash 留痕三重兜底。