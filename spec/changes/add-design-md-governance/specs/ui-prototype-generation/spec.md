## MODIFIED Requirements

### Requirement: 真组件高保真生成
对画像识别成功的栈，原型 MUST 为每个界面生成单文件 HTML，MUST 使用工程真实组件库渲染（经本地 vendored 缓存或 CDN 加载），视觉约束（主题、间距、字号）MUST 来自画像注入，数据 MUST 全部为假数据。原型关键区块 MUST 打语义化 `data-proto-id` 稳定锚，批注 MUST 引用锚点而非裸 CSS selector。生成阶段 MUST 注入设计候选约束：当画像 `design_doc`（DESIGN.md 摘录）未覆盖目标界面的版式/组件形态时，候选设计 MUST 遵循 frontend-design skill 两遍式流程产出（紧凑 token 系统 + 反模板自批判），且仅填补宪法空白；候选与 DESIGN.md 摘录冲突时 MUST 以宪法为准，MUST NOT 用生成器建议覆盖已定稿设计语言。

#### Scenario: React+antd 原型渲染真组件
- **WHEN** 对 React+antd 工程生成原型并在浏览器打开
- **THEN** 页面渲染出真实 antd 组件（DOM 含 antd 组件标记），布局与画像主题一致，数据为假数据

#### Scenario: 原型自包含可打开
- **WHEN** 用户直接用浏览器打开原型 HTML 文件或经原型服务器访问
- **THEN** 无需工程本体构建即可完整渲染

#### Scenario: 宪法空白处产出候选
- **WHEN** 目标界面的版式或组件形态在 DESIGN.md 摘录中无既定约束
- **THEN** 生成遵循 frontend-design 两遍式产出候选（token 系统 + 反模板自批判），原型按候选渲染并在生成说明中注明候选来源

#### Scenario: 候选与宪法冲突时宪法赢
- **WHEN** 生成器候选建议（如新配色/动画效果）与 DESIGN.md 摘录既定条款冲突（如静态渲染红线）
- **THEN** 原型按宪法条款渲染，生成说明中指出冲突点及采纳宪法的理由
