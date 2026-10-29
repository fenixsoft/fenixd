# prototype-annotation-loop 规格

## ADDED Requirements

### Requirement: 独立简易 HTTP 服务器
原型伺服 MUST 使用独立进程的 python 标准库简易 HTTP 服务器（零第三方依赖、零 dashboard 依赖）：静态伺服原型目录 + `POST /feedback` 接收批注落盘 `feedback.json`。MUST 满足：启动时打印完整访问 URL；绑定地址显式可配；端口随机高端口且冲突重试；PID 文件管理生命周期；同目录已有存活实例 MUST 复用而非重复启动；异常残留实例 MUST 在下次启动时探测并接管或清理；原型批准或会话结束后回收。

#### Scenario: 启动与批注落盘
- **WHEN** 会话内启动原型服务器，用户在浏览器批注并提交
- **THEN** 服务器把批注（锚点 + 意见文本 + 时间戳 + 轮次）写入原型目录下 `feedback.json`，agent 可直接读取

#### Scenario: 存活实例复用
- **WHEN** 同一原型目录已存在存活服务器时再次启动
- **THEN** 复用既有实例与端口，不报端口冲突

#### Scenario: 残留实例接管
- **WHEN** PID 文件存在但对应进程已死（或为陈旧 PID）
- **THEN** 新启动探测到残留后清理并接管，不留僵尸、不误杀无辜进程

### Requirement: 批注器交互
注入式批注器 JS MUST 与组件栈无关（纯 DOM 操作）：hover 高亮元素、点选元素、意见输入面板、意见列表、提交批注。服务器不可达时 MUST 降级为本地导出 JSON 文件。批注 MUST 记录目标元素的 `data-proto-id` 锚点。

#### Scenario: 点选批注提交
- **WHEN** 用户点选原型中某元素并输入意见提交
- **THEN** 批注以该元素锚点为主键 POST 到 `/feedback` 并成功落盘

#### Scenario: 服务器不可达降级
- **WHEN** 批注器无法连通 `/feedback`（如用户以 file:// 直接打开原型）
- **THEN** 批注器提供本地导出 JSON 文件路径，用户可把文件交给 agent

### Requirement: 会话内迭代闭环
批注回流后 agent MUST 读取 `feedback.json` 修订原型，用户刷新浏览器复看，循环直到用户明示认可。每轮修订 MUST 遵守锚保持要求（见 ui-prototype-generation）。迭代全部发生在当前会话内，MUST NOT 依赖异步审批流。

#### Scenario: 批注驱动的修订轮
- **WHEN** 用户提交批注并告知 agent 查看意见
- **THEN** agent 读取 feedback.json、修订原型、保留未波及锚点，用户刷新即见新版

### Requirement: 批准入库与冻结
仅当用户在会话中明示认可（如「原型定了」）才视为批准。批准后 MUST：原型文件连同整页截图落入 `specs/<spec>/prototype/` 并入库提交；截图为**尽力而为**——无头浏览器不可用或抓取失败时批准 MUST NOT 阻塞，SPEC 显式记录「无渲染凭证」降级。批准后原型视为冻结，任何再修改 MUST 视为新一轮确认。

#### Scenario: 批准入库
- **WHEN** 用户说「原型定了」
- **THEN** 原型与截图落 `specs/<spec>/prototype/` 并随 SPEC 流程入库，草稿目录清理

#### Scenario: 截图失败不阻塞批准
- **WHEN** 批准时无头浏览器不可用或整页截图失败
- **THEN** 批准流程继续，SPEC 记录「无渲染凭证」，HTML 仍为真相源主体

#### Scenario: 冻结后再改
- **WHEN** 已批准入库的原型又被要求修改
- **THEN** 视为新一轮原型确认（重新迭代、重新批准），不得静默改动已入库原型
