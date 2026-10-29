## Context

fenix-new 的交流-头脑风暴-SPEC 流程对无 UI 需求运转良好，但界面意图靠语言转述损耗大，偏差在实现后才暴露。本变更把「界面确认」前移为 SPEC 起草阶段的原型确认环。完整动机、用户五项拍板、调研结论见设计定稿：`docs/superpowers/specs/2026-10-29-ui-prototype-loop-design.md`（本文件是其工程化压缩，冲突时以 SPEC Scenario 为准）。

关键环境事实：fenix 系 skill 以符号链接从 `/root/.claude/skills/` 指向本仓 `skills/` 目录（如 `fenix-new -> /root/fenixd/skills/fenix-new`），因此 skill 层交付物全部是仓内路径；`agents/*.md` 为仓内派发提示词配置。v1 目标栈画像为本仓自身（dashboard：React 19 + antd ^6），吃狗粮实证。本机出网走代理；本机有 node 与 playwright-cli。

## Goals / Non-Goals

**Goals:**
- 约束力 > 保真度 > 便利性：批准原型对实现产生双通道约束（SPEC 声明 + 派发提示词契约段）
- 通用机制建立在栈画像上，不绑定 antd；v1 只实证 React+antd
- 会话内迭代闭环：独立简易 HTTP 服务器（python 标准库），不依赖 dashboard、不改 daemon

**Non-Goals:**
- 文件级代码搬移（复用含义 = 组件选型/props/布局结构照搬）
- Freehand 画笔批注、实现后自动视觉回归、移动端批注硬适配
- 非浏览器栈高保真（降级仿样 + 标注无约束力）
- 把原型建进工程本体（不要求工程可构建）

## Decisions

1. **独立 skill `skills/fenix-prototype/`**：fenix-new 检测到大改时调用，也可单独调用迭代既有原型。备选「并入 fenix-new」被否：职责膨胀且无法单独重放迭代。
2. **栈画像先行**：侦察依赖清单/主题文件/DESIGN.md → 画像注入生成 prompt；识别失败降级。画像数据结构留扩展位。
3. **真组件加载三级降级**：skill 自维护与工程无关的预打包 vendor 缓存（node 打包 react+antd 按版本缓存；antd 5+ 无浏览器全局构建，必须打包）→ CDN ESM 兜底 → 纯 HTML/CSS 仿样（标无约束力）。node 是优先条件非硬假设。不触碰「不要求工程本体可构建」反目标。
4. **`data-proto-id` 稳定锚**：批注挂锚不挂裸 selector；重生成解析旧锚集合、未波及区块沿用原锚，防批注错位。
5. **独立简易服务器**：python 标准库（http.server），静态 + `POST /feedback` 落 `feedback.json`；PID 文件生命周期（存活复用/残留接管/结束回收）；随机高端口避让；绑定与 URL 显式。备选「复用 dashboard 路由」被用户否决。
6. **批注器为注入式通用 JS**：与栈无关的 DOM 操作（hover 高亮/点选/意见面板/POST），服务器不可达降级本地导出。
7. **绑定力双通道**：SPEC Scenario 声明（用户定调：v1 同时改派发提示词）+ `agents/implementer.md`、`agents/code-review.md` 条件式契约段（开关 = SPEC 内 UI 真相源声明）。契约段遵循 agents/*.md 现有契约段惯例。
8. **存放与冻结**：草稿期 `.fenix/prototypes/<spec>/`（gitignore，运行时目录）；批准落 `specs/<spec>/prototype/` 入库；截图尽力而为（失败不阻塞批准、记「无渲染凭证」）；冻结后再改 = 新一轮确认。

## Risks / Trade-offs

- [vendor 缓存版本与工程钉版偏差] → bootstrap 按画像侦察到的版本精确缓存；不命中时回退打包或 CDN，降级路径对用户可见
- [CDN 兜底依赖代理可达] → 缓存命中后离线可用；bootstrap 环境自检先行，失败逐级降级不硬崩
- [契约段改动对所有项目的所有 SPEC 生效] → 条件式措辞（开关 = SPEC 内声明），任务含无原型 SPEC 零影响验证项
- [锚保持启发式不完全] → 未波及区块沿用原锚为 MUST，波及区块允许换锚；批注含元素文本快照辅助人工核对
- [原型服务器僵尸进程] → PID 复用/接管/回收三态 + 生命周期测试钉死
- [node 缺失环境下高保真不可达] → 三级降级阶梯显式降级为仿样并声明无约束力，不静默假冒

## Migration Plan

全新能力，无存量迁移。回滚 = 删除 `skills/fenix-prototype/` 与 `skills/fenix-new/SKILL.md` 衔接段、还原 `agents/implementer.md`、`agents/code-review.md` 两处契约段；运行时目录 `.fenix/prototypes/` 由人工清理。

## Open Questions

留给实现阶段的决策点（不影响契约）：栈画像 JSON 具体字段；vendor bootstrap 的抓取与缓存落盘细节；批注 JSON schema 细节；锚生成与保持的启发式实现；fenix-new 衔接段落点（需读现有 prompt 结构）；批注器面板交互细节。
