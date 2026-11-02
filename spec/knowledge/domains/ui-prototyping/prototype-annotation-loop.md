# 原型批注环

<!-- knowledge: capability=prototype-annotation-loop rev=1
     sources=spec/archive/2026-11-02-fenix-prototype -->

原型草稿的会话内批注迭代闭环：独立 HTTP 服务器伺服原型、注入式批注器收集意见、`feedback.json` 回流驱动修订，直到用户明示批准入库并冻结。

## 规则

- 原型伺服使用独立进程的 python 标准库简易 HTTP 服务器（零第三方依赖、零 dashboard 依赖）：静态伺服原型目录 + `POST /feedback` 接收批注落盘 `feedback.json`，agent 可直接读取。
- 服务器生命周期：启动时打印完整访问 URL；绑定地址显式可配；端口取随机高端口且冲突重试；PID 文件管理生命周期——同目录已有存活实例 MUST 复用而非重复启动；PID 文件残留而进程已死（或为陈旧 PID）MUST 在下次启动时探测并接管或清理，不留僵尸、不误杀无辜进程；原型批准或会话结束后回收。对空 body、非法 JSON、错误方法等异常请求 MUST 保持存活可服务，不崩溃。
- 批注器为注入式通用 JS，与组件栈无关（纯 DOM 操作）：hover 高亮元素、点选元素、意见输入面板、意见列表、提交批注；批注 MUST 记录目标元素的 `data-proto-id` 锚点，并以锚点为主键 POST 到 `/feedback`，同时记录时间戳与轮次。
- 批注器连不通 `/feedback` 时（如以 file:// 直接打开原型）MUST 降级为本地导出 JSON 文件，用户可把文件交给 agent。
- 批注回流后 agent 读取 `feedback.json` 修订原型，用户刷新浏览器复看，循环直到用户明示认可；每轮修订 MUST 遵守重生成锚保持要求；迭代全部发生在当前会话内，MUST NOT 依赖异步审批流。
- 仅当用户在会话中明示认可（如「原型定了」）才视为批准。批准后原型文件连同整页截图落入 `specs/<spec>/prototype/` 入库提交，草稿目录（`.fenix/prototypes/<spec>/`，gitignore 运行时目录）清理。
- 整页截图为尽力而为：无头浏览器不可用或抓取失败时批准 MUST NOT 阻塞，SPEC 显式记录「无渲染凭证」降级，HTML 仍为真相源主体。
- 批准后原型视为冻结：任何再修改 MUST 视为新一轮确认（重新迭代、重新批准），MUST NOT 静默改动已入库原型。

## 溯源

- 2026-11-02 fenix-prototype（spec/archive/2026-11-02-fenix-prototype） — 新增本能力：独立简易服务器与 PID 三态生命周期、注入式批注器与本地导出降级、feedback.json 会话内迭代闭环、批准入库与冻结语义。
