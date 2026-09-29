# 草稿晋升门控（drafted→ready 自动晋升开关）
<!-- knowledge: capability=draft-promotion-gate rev=1
     sources=spec/archive/2026-09-14-add-draft-promotion-gate -->

控制 drafted SPEC 是否被自动晋升：`manual` 档下草稿停留待人工阅读与放行，`auto` 档保持全自动晋升链。

## 规则

- 配置键 `gates.promote_mode`，枚举 `auto` / `manual`，缺省 `auto`（与无此键时行为一致）；配置校验拒绝非枚举值并在加载时报错；纳入 Dashboard 受管配置键白名单，支持设置页读写与配置热更新（30s mtime 原地重载）。
- `auto`（或缺省）：晋升链全量执行——软化不可满足声明 + 声明 lint + tasks 可解析性 lint + transition ready + 派发。
- `manual`：晋升闸口关闭——不软化、不 lint、不 transition、不派发；不向 STATE 写 `error`（等待人工放行是设计行为而非故障）；记 info 日志说明该 SPEC 停留 drafted 等待人工放行。
- 闸口覆盖全部 drafted 晋升触发路径：`spec_drafted` 事件、`start_after` 到期唤起、full_scan recovery re-trigger、外部 drafted 写入。
- manual 期间不提前执行晋升 lint，因此 lint 违规不会在 drafted 阶段暴露为 error；违规在人工放行时按 manual-spec-promotion 的 lint 规则拦截。
- 从 `manual` 切回 `auto` 后，存量 drafted SPEC 在下一次 full_scan recovery（或新的 drafted 触发）时走完整晋升链自动晋升，无需人工逐个干预。
- 设置页「审批」页签提供「草稿晋升模式」单选（manual/auto，与 approve_mode 单选同构），位于审批模式设置项上方；说明文字注明 manual 下可经 `/fenix-ready`、项目页按钮或 CLI promote 放行。
- 治理文档（docs/help/06-governance.md）记录人工放行流程；配置文档（docs/help/08-config.md）登记该键取值、缺省与热更新属性。

## 溯源

- [2026-09-14 2026-09-14-add-draft-promotion-gate](spec/archive/2026-09-14-add-draft-promotion-gate/) — 新增草稿晋升门控：`gates.promote_mode` 配置、manual 闸口全路径覆盖与零副作用语义、切回 auto 的存量恢复、设置页单选
