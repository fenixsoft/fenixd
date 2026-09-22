## Why

框架在实现/验证循环耗尽、评审否决达上限、预算耗尽等场景冻结 spec 等待人工裁决，但告警只「提示人去裁决」：人必须登录 claude code 手工改 STATE.md/清计数/推状态，且处置是开放性的（无结构化选项）。历史 08-29~09-22 全部真实裁决事后复盘均为「在既有选项里挑一个」（继续修 / 人工修完重验 / 接受现状推进 / 撤销 / 知情），证明裁决本质是选择题。本 SPEC 把裁决收敛为「告警内嵌下拉选择，选完即完整闭环」。

## What Changes

- 告警记录新增 `choices` 字段：桶 2（真需人决策）信号发射点写告警时按静态注册表携带裁决选项集（`{id, label, desc, action}`）；桶 0（知情/噪音类）不携带，前端只出「知道了」
- 新增静态裁决选项注册表（按 signal_type 映射），覆盖：验证循环耗尽族（verify_fail_rounds 升级闸门 / judge_rerun_cap / impl_budget_exhausted / redispatch_loop_detected）、评审否决达上限、评审器连坏（spec-review-incomplete）、token_budget、配置裁决类
- 新增端点 `POST /api/alert-resolve`：一次选择 = 执行映射的后端动作 + 状态机推进做完 + markHandled + 处置留痕（choice_id + note），不需要再进 claude code
- 新增 3 个裁决动词（其余复用 `admin_actions.py` 既有动词）：`reset_verification`（清场景文件+清 judge/验证计数器+重出题重验）、`force_advance`（人工豁免推进 blocked→done 等，留裁决依据）、`skip_review_gate`（评审器持续坏时人工授权放行，留痕）
- 前端告警渲染（spec 详情页告警区 + overview AlertBanner）对带 `choices` 的记录渲染下拉框+执行按钮，替代单纯「提示人去裁决」文案
- Administrator agent 处置契约改造：优先从同一 choices 注册表选 `choice_id`+依据，开放处置仅作注册表未覆盖时的兜底，并把用到的处置回填为注册表新选项建议（写进处置记录供自省消费）

## Capabilities

### New Capabilities
- `adjudication-choices-registry`: 裁决选项静态注册表与告警 choices 字段契约（哪些 signal_type 必须携带 choices、choices 结构、桶 0 不携带的边界）
- `alert-resolve`: alert-resolve 端点与处置闭环语义（一次选择触发动作执行+状态推进+handled+留痕；失败回滚与幂等）
- `adjudication-actions`: 三个新裁决动词的行为契约（reset_verification / force_advance / skip_review_gate 各自的前置校验、执行内容、留痕格式）
- `adjudication-ui`: 前端告警选择题交互（带 choices 的告警渲染下拉+执行、执行中/成功/失败态、桶 0 只有「知道了」）
- `admin-choices-contract`: Administrator agent 处置与 choices 注册表共用同一裁决空间的契约

### Modified Capabilities

## Impact

- `core/admin_store.py`：告警记录新增可选 `choices` 字段（append/去重/read 路径兼容）
- `core/pm_engine/budget.py`、`core/pm_engine/family.py`、`core/pm_engine/spec_review.py`、`core/pm_engine/verification/judge_gate.py`：发射点接线 choices
- `core/dashboard/data/adjudication_choices.py`（新建）：静态注册表
- `core/dashboard/data/admin_actions.py`：新增 3 个裁决动词
- `core/dashboard/routes/alert_routes.py`：新增 `POST /api/alert-resolve`
- `core/dashboard/static/src/services/dashboard.ts`、`pages/projects/detail.tsx`、`pages/overview/components/AlertBanner.tsx`：前端交互
- `agents/administrator.md`：处置输出契约段落
- 构建产物 `core/dashboard/static/dist/` 需 `npm run build` 重建（reference）
