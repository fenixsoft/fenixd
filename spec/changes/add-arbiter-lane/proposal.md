## Why

冻结族事故两次验尸（10-26/27 add-command-center、10-30/31 evo-refine-midflight-outlier-dims）实证：阻塞升级人类时，自主恢复工具箱只有「复位重试」一招（对持久化状态污染无效），验尸知识碎片化在归档转录/STATE/源码契约/git 历史/记忆五处无人同时持有，人类被降格为验尸官。守卫按例打补丁追不上组合爆炸。需要把「框架外验尸者」的四个结构性优势（全链视野、跨车道权限、记忆、知情违规权）制度化为常设角色：冻结→人类的升级边改道为 冻结→Arbiter→（大多数）自主处置 /（少数）带完整裁决包升级。

设计真相源：`docs/superpowers/specs/2026-10-31-arbiter-lane-design.md`（commit fbeb3f104，含用户四项裁定：mode=full 立即执行、纯提示词红线、裁决包挂原告警静默更新、自主处置零用户可感知告警）。

## What Changes

- 新增 `arbiter` agent 车道（dsh harness、bigmodel 网关、model 钉 glm-5.3-flash）：冻结/升级事件自动派发全局决策者 run，自主调查（日志/转录归档/STATE/源码契约/git/记忆全链视野）并自主处置。
- 升级边改道：`freeze_for_human` 与 `_send_human_escalation_alert` 两个咽喉层注册 Arbiter 派发（dedup 同 spec 同签名一次、全局单飞队列、死人开关连败 2/预算耗尽→半成品包升级）；人工冻结（freeze_spec）、定时冻结（frozen_until）、token 预算/spec_integrity/queue 异常类**不进触发面**。
- 权限边界以提示词红线+台账审计实现（用户裁定，不做机械强制）：白名单 6 类知情违规（显式 status 解冻/端点直执行/计数清零/删无主坏产物/复位重派/主树 spec 目录提交），永不可碰 5 类（证据源只读/禁伪造 run 产物/禁 push 禁改 main/禁绕过 flock/禁动进程管理面）。
- 首期五类可自主处置白名单：冻结场景文件拯救、裁决落位/verdict 缺失考古、验证侧计数复位、worktree 陈锁清扫、WIP 门分拣提交（实现者可按成本降级为「先落 1/3/4 三类，2/5 只产升级包」）。
- 告警面零噪音分层：自主处置成功 → 原告警由处置结果直接终态化（resolved_by=arbiter，运维界面仅存一条已处理记录，不推送不进 pending）；处置不了 → 裁决包（报告+选项+推荐）同 alert_id 原位静默更新并推 pending 人工队列。
- 立项节流：同主题 drafted 在池不重复立项、单次调查至多 2 条 SPEC、周配额缺省 5。
- 配置四键（arbiter.enabled / budget_wallclock_s / budget_tokens / max_consecutive_failures），每键必带 Dashboard 设置页 UI。
- admin 告警 narrative 车道中 blocked/frozen 类调查内容由 Arbiter 报告替代，narrative 保留给非阻塞类。

## Capabilities

### New Capabilities

- `arbiter-lane`: 全局决策者车道——触发面（双咽喉改道+排除表+dedup+单飞+死人开关）、车道注册（arbiter 类型/provider/指标行/互斥守卫跨类型核查）、权限红线与许可清单、首期五类处置白名单与鉴定逻辑、裁决包与告警终态化、立项节流、配置四键与 Dashboard 设置页。

### Modified Capabilities

- `human-escalation-alerts`（归档于 spec/archive/2026-09-02-add-administrator-agent/specs/human-escalation-alerts）：升级边的首选消费者从「人工」改为「Arbiter 优先、人工终审」——机器发起的冻结/升级先经 Arbiter 调查，自主处置成功的告警直接终态化（零用户可感知），仅白名单外/处置失败/连败/预算耗尽才以裁决包形式到达人类。人工冻结与定时冻结路径行为不变。

## Impact

- 新增：`core/pm_engine/arbiter.py`（触发注册/dedup/单飞/死人开关/处置执行/台账）、`agents/arbiter.md`、`tests/test_arbiter_*.py`。
- 修改：`core/agent_runner/runner.py`（arbiter 类型注册：车道表、--add-dir 注入白名单、`_log_lane_run_metrics` 指标行、互斥守卫摄取/重派匹配面核查）、`core/state_machine.py`（freeze_for_human 咽喉挂派发回调）、`core/pm_engine/family.py`（`_send_human_escalation_alert` 改道注册）、`core/adjudication_narrative.py`（blocked 类叙事让位）、Dashboard 设置页与数据层（arbiter 配置段）、`.fenix/config.template.yaml`（运行时 reference）。
- 依赖：choices 注册表与 alert-resolve 闭环（已落地）、`StateMachine.unfreeze_spec(name, status=...)`（已落地，`state_machine.py:2351`）。
- 行为基线：`arbiter.enabled: false` 时升级边行为与现状逐字节一致（s8）。
- 生效方式：SPEC 合并不自动重启 daemon——交付项含 restart_request 信号落位（实际重启由 supervisor 消费）。
