## Why

带界面的需求靠语言描述难以精确定义边界：fenix-new 的交流-头脑风暴-SPEC 流程对无 UI 需求运转良好，但界面意图在语言转述中损耗，agent 猜出的界面与用户预期偏差要到实现之后才暴露，返工代价最高。需要把「界面确认」前移到 SPEC 起草阶段——用一张「真组件、假数据」的高保真原型作为用户与 agent 的共同视觉基准，并让批准的原型对后续 AI 实现产生**实际约束力**（纯视觉参照无约束力 = 白做，这是本立项的立身之本）。

## What Changes

- 新增独立 skill `skills/fenix-prototype/`：按栈画像生成高保真单文件 HTML 原型——真实组件库渲染（React+antd 真用 antd）、主题 token 来自工程约束注入、数据全是假数据；关键区块打 `data-proto-id` 稳定锚
- 新增栈画像侦察与三级降级：识别不出组件库/资源不可达时按「预打包缓存 → CDN ESM → 纯 HTML/CSS 仿样（显式标注无约束力）」降级
- 新增与栈无关的注入式批注器 JS 资产：hover 高亮、点选元素、意见输入、`POST /feedback` 落盘；批注挂锚点不挂裸 selector
- 新增 python 标准库独立简易 HTTP 服务器脚本：静态伺服原型 + 接收批注写 `feedback.json`，PID 文件生命周期管理，**不依赖 dashboard、不改 daemon**
- fenix-new skill 增加触发判定与衔接：新页面/新大面板/布局重构/多区块联动视为大改→提议原型；小修小补跳过；用户可随时反向操作（主动要原型/豁免）
- **修改** `agents/implementer.md`、`agents/code-review.md`：新增条件式契约段——仅当 SPEC 声明原型为 UI 真相源时生效（实现前必读 `specs/<spec>/prototype/`、评审对照原型、冲突即升级用户），对无原型 SPEC 零影响

## Capabilities

### New Capabilities

- `ui-prototype-generation`: 触发判定、栈画像侦察、真组件原型生成、三级降级阶梯、`data-proto-id` 稳定锚与重生成锚保持
- `prototype-annotation-loop`: 独立 HTTP 服务器生命周期、批注器交互、`feedback.json` 回流、会话内迭代闭环、批准入库与冻结语义
- `prototype-binding-contract`: 绑定力双通道——SPEC Scenario UI 真相源声明（与数值纪律同通道）+ 派发提示词条件式契约段

### Modified Capabilities

（无——归档 430 变更与活跃变更中不存在原型/派发提示词契约类既有能力，`agents/*.md` 改动由新能力 `prototype-binding-contract` 承载）

## Impact

- 新增：`skills/fenix-prototype/`（SKILL.md、批注器 JS、服务器脚本、vendor bootstrap、栈画像侦察）
- 修改：`skills/fenix-new/SKILL.md`（触发判定与调用衔接段）
- 修改：`agents/implementer.md`、`agents/code-review.md`（条件式契约段）
- 运行时（gitignore，非交付物）：`.fenix/prototypes/<spec>/` 草稿目录、vendor 缓存目录
- 依赖：node 为优先条件非硬假设（降级阶梯兜底）；CDN 兜底抓取走本机代理；服务器纯 python 标准库，零新增第三方依赖
- 不改 fenixd daemon 代码；无界面 SPEC 的既有链路零影响
- 设计依据：`docs/superpowers/specs/2026-10-29-ui-prototype-loop-design.md`（brainstorm 定稿，含用户五项拍板与验收场景）
