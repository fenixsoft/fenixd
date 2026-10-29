# ui-prototype-generation 规格

## ADDED Requirements

### Requirement: 触发判定（fenix-new 衔接）
fenix-new MUST 在需求交流过程中判定界面改动范围：新页面、新大面板、布局重构、多区块联动视为**大范围改动**，MUST 主动提议进入原型确认环；无界面改动或界面小范围局部修改 MUST 跳过原型环节直接起草 SPEC。判定无硬性数值阈值，由 agent 判断；用户 MUST 拥有双向一票否：可对大改豁免原型，也可对小改主动要求原型。

#### Scenario: 大范围界面改动触发提议
- **WHEN** 需求包含新页面或布局重构级改动
- **THEN** fenix-new 主动提议生成原型并等待用户确认后调用 fenix-prototype

#### Scenario: 小范围修改跳过
- **WHEN** 需求仅涉及既有界面的小范围局部修改（如改文案、调按钮位置）
- **THEN** 不提议原型，直接进入 SPEC 起草

#### Scenario: 用户双向一票否
- **WHEN** 用户对大改说「不用出原型」或对小改说「先出个原型看看」
- **THEN** 以用户决定为准，agent 不再二次劝阻或追问

### Requirement: 栈画像侦察
生成原型前 MUST 先侦察目标工程产出栈画像：从依赖清单（如 package.json）识别组件库与版本，从主题/设计 token 文件与 DESIGN.md 提取视觉约束，必要时采样现有页面样例。画像 MUST 注入原型生成 prompt。识别不出的栈 MUST 降级为纯 HTML/CSS 仿样，且 SPEC 中 MUST 显式标注「视觉参照、无约束力」。v1 MUST 实现 React+antd 画像，画像接口 MUST 留扩展位。

#### Scenario: React+antd 工程画像
- **WHEN** 目标工程依赖含 react 与 antd（含版本号）
- **THEN** 画像输出组件库标识、版本、主题 token 约束，注入生成 prompt

#### Scenario: 未知栈降级
- **WHEN** 依赖清单无法识别出受支持的浏览器组件库
- **THEN** 生成纯 HTML/CSS 仿样原型，并在 SPEC 与原型页头显式标注「视觉参照、无约束力」

### Requirement: 真组件高保真生成
对画像识别成功的栈，原型 MUST 为每个界面生成单文件 HTML，MUST 使用工程真实组件库渲染（经本地 vendored 缓存或 CDN 加载），视觉约束（主题、间距、字号）MUST 来自画像注入，数据 MUST 全部为假数据。原型关键区块 MUST 打语义化 `data-proto-id` 稳定锚，批注 MUST 引用锚点而非裸 CSS selector。

#### Scenario: React+antd 原型渲染真组件
- **WHEN** 对 React+antd 工程生成原型并在浏览器打开
- **THEN** 页面渲染出真实 antd 组件（DOM 含 antd 组件标记），布局与画像主题一致，数据为假数据

#### Scenario: 原型自包含可打开
- **WHEN** 用户直接用浏览器打开原型 HTML 文件或经原型服务器访问
- **THEN** 无需工程本体构建即可完整渲染

### Requirement: 资源三级降级
组件库资源加载 MUST 按三级降级：skill 自维护的预打包 vendor 缓存（按组件库版本缓存，与工程无关）→ CDN ESM 兜底 → 纯 HTML/CSS 仿样（显式标注无约束力）。bootstrap MUST 先做环境自检；node 为优先条件而非硬假设；每一级降级 MUST 对用户可见（生成时说明所用层级）。

#### Scenario: vendor 缓存命中离线渲染
- **WHEN** vendor 缓存中存在匹配版本的预打包产物
- **THEN** 原型引用本地缓存资源，无外网也能完整渲染

#### Scenario: 全部降级到底
- **WHEN** 无缓存且 CDN 不可达（或 node 缺失无法打包）
- **THEN** 生成纯 HTML/CSS 仿样并标注无约束力，用户被告知该原型不具约束力

### Requirement: 重生成锚保持
原型迭代修订 MUST 尽最大可能保留既有 `data-proto-id` 锚：重新生成时 MUST 解析旧原型的锚集合，未被需求变更波及的区块 MUST 沿用原锚名。

#### Scenario: 修订后旧批注锚仍解析
- **WHEN** 用户已对 v1 原型批注，agent 按 feedback 生成 v2 原型
- **THEN** v1 中未被改动波及区块的 `data-proto-id` 在 v2 中保持不变，旧批注仍指向对应区块
