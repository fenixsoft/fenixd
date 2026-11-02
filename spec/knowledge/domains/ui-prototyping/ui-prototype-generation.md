# 界面原型生成

<!-- knowledge: capability=ui-prototype-generation rev=1
     sources=spec/archive/2026-11-02-fenix-prototype -->

fenix-new 在 SPEC 起草阶段生成「真组件、假数据」高保真界面原型的机制：触发判定、栈画像侦察、真组件渲染与资源降级、稳定锚，为界面意图提供用户与 agent 的共同视觉基准。

## 规则

- 原型由独立 skill `skills/fenix-prototype/` 生成：fenix-new 检测到大范围界面改动时主动提议并衔接调用，也可单独调用以迭代既有原型。
- 触发判定无硬性数值阈值，由 agent 判断：新页面、新大面板、布局重构、多区块联动视为大范围改动，MUST 主动提议进入原型确认环；既有界面的小范围局部修改（改文案、调按钮位置等）MUST 跳过原型环节直接起草 SPEC。
- 用户对触发判定拥有双向一票否：可对大改豁免原型，也可对小改主动要求原型；以用户决定为准，agent MUST NOT 二次劝阻或追问。
- 生成前 MUST 先侦察目标工程产出栈画像：从依赖清单（如 package.json）识别组件库与版本，从主题/设计 token 文件与 DESIGN.md 提取视觉约束，必要时采样现有页面样例；画像 MUST 注入原型生成 prompt。画像识别当前内置 React+antd 支持，画像接口保留扩展位。
- 识别不出的栈 MUST 降级为纯 HTML/CSS 仿样，并在 SPEC 与原型页头显式标注「视觉参照、无约束力」。
- 画像识别成功的栈，每个界面生成单文件 HTML 原型：MUST 使用工程真实组件库渲染（经本地 vendored 缓存或 CDN 加载），视觉约束（主题、间距、字号）MUST 来自画像注入，数据 MUST 全部为假数据；不要求工程本体可构建，浏览器直接打开或经原型服务器访问均可完整渲染。
- 组件库资源加载按三级降级：skill 自维护的预打包 vendor 缓存（按组件库版本精确缓存、与工程无关）→ CDN ESM 兜底 → 纯 HTML/CSS 仿样（显式标注无约束力）。bootstrap MUST 先做环境自检；node 是优先条件而非硬假设；每一级降级 MUST 对用户可见（生成时说明所用层级），降级到底时 MUST 告知用户该原型不具约束力。
- vendor 缓存落 `.fenix/prototype-vendor/`（gitignore 运行时目录），不入库。
- 原型关键区块 MUST 打语义化 `data-proto-id` 稳定锚；批注 MUST 引用锚点而非裸 CSS selector。
- 重生成 MUST 解析旧原型的锚集合：未被需求变更波及的区块 MUST 沿用原锚名，保证旧批注仍指向对应区块；被波及的区块允许换锚，批注附带的元素文本快照辅助人工核对。

## 溯源

- 2026-11-02 fenix-prototype（spec/archive/2026-11-02-fenix-prototype） — 新增本能力：fenix-new 触发判定与用户双向一票否、栈画像侦察与未知栈降级、真组件单文件原型生成、资源三级降级阶梯、data-proto-id 稳定锚与重生成锚保持。
