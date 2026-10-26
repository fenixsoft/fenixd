<!-- knowledge: capability=adjudication-actions rev=2 sources=spec/archive/2026-09-27-add-human-adjudication-choices,spec/archive/2026-10-26-evo-add-commit-stray-wip-choice -->

# 人工裁决动词

dashboard 侧的裁决动词与选择执行器（`core/dashboard/data/admin_actions.py`），承载告警选择题处置中动作层的执行语义。

## 现行规则

- `reset_verification(project_root, spec)`：人工裁定验证链输入已失真，重置验证重跑。前置校验 spec 存在且处于冻结或 blocked 态、冻结原因属验证链信号（judge_rerun_cap / 验证失败升级闸门 / env 阻塞族），否则拒绝并说明。执行序列：删除该 spec 的冻结场景与验证进度运行时文件（`.fenix/verify-progress/<spec>/` 下场景集文件）→ 清零 judge 重跑计数与验证失败轮计数（生命周期累计审计字段不清零）→ 解除冻结并按既有复位路径推进（实现分支已合并走 testing 直通道重验，否则回 ready 重实现，复用 `resolve_env_blocked_reset_path` 判定）→ 返回结构化结果（执行步骤明细与目标状态）。
- `force_advance(project_root, spec, target_status="done", note="")`：人工裁定接受现状，豁免剩余缺口推进。前置校验 spec 存在且处于冻结或 blocked 态。执行序列：解除冻结 → 推进到 target_status（缺省 done）并清 error 字段 → 裁决依据 note 写入推进留痕。blocked→done 不在状态机合法迁移表内（blocked 仅可达 ready/reviewing），推进必须走 `StateMachine.update_spec` 显式豁免通道（updates 同时携带 `frozen=False` 与 `status`，冻结剥离守卫对自带 frozen 键的更新放行），禁止为达成推进直写 STATE.md；留痕必须可追溯「人工豁免推进而非自然达成」；不触碰实现分支内容与主树工作区文件。该动词是 `/fenix-approve` 人工豁免语义在 dashboard 侧的最小等价物。
- `skip_review_gate(project_root, spec, note="")`：评审器持续基础设施失败时人工授权跳过评审门。仅对 `spec-review-incomplete` 冻结（状态 reviewing + frozen）开放；执行序列：解除冻结并将 spec 从 reviewing 推进到 ready（跳过评审门），留痕标注「人工授权跳过评审」与 note，返回结构化结果。评审否决（方向不成立）类冻结必须拒绝，不得跳过。
- `execute_adjudication_choice` 选择执行器：告警选择题的动作层统一入口，经 `resolve_choice` 解析选项后分派执行，受作用域守卫与结果前置回写纪律约束（见 [adjudication-choice-scope-guard](adjudication-choice-scope-guard.md)）。其 `commit_stray_wip` 分支（提交散件 WIP）是本模块首个对主树执行 git 写的执行器：语义为核对归属后提交主树信号清单内的散件改动（与 stash 类动作互斥，提交后清单内文件不再滞留）；执行前守卫仅受理 `signal_type=maintree_stray_wip_stale`，其余信号类型（含未注册信号与姊妹 info 信号）一律拒绝且零 git 写；文件来源限于该信号记录 evidence「文件清单(N):」段与当刻 `git status --porcelain` 的交集，拒绝任意路径；清单中已不在当刻 status 的陈旧条目静默跳过不报错（同指纹一次性告警，清单会陈旧）；交集为空返回明确 error、不产生空提交；属非 destructive（提交可回溯）不设确认门；执行结果在处置记录附提交 hash。归属判断（交互会话遗留 vs 车道漏提交）由处置程序承担，本执行器只标准化提交与留痕。

## 溯源

- 2026-09-27 add-human-adjudication-choices（spec/archive/2026-09-27-add-human-adjudication-choices） — 建立三个裁决动词的前置校验、执行序列、留痕格式与豁免通道约束
- 2026-10-26 evo-add-commit-stray-wip-choice（spec/archive/2026-10-26-evo-add-commit-stray-wip-choice） — 选择执行器新增 commit_stray_wip 分支：signal_type 绑定守卫、清单∩当刻 status 文件约束、陈旧条目跳过、空交集拒绝空提交、处置记录附提交 hash（本模块首个主树 git 写执行器）
