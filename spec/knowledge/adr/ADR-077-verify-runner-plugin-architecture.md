# ADR-077：验证引擎 Runner 插件化，调度与断言契约对 kind 无感

date: 2026-09-12
status: accepted

## Context

验证链最初以 web 为唯一形态：引擎无条件启动浏览器、断言全绑 Playwright DOM、契约 serve 仅「起 HTTP 服务」一种形态——纯 CLI spec 在验收门被整体拒绝，API 验证靠 web 场景 GET 凑合。引擎单文件 642 行，浏览器专属逻辑与通用调度耦合；按 kind 堆 if/else 分支会重演「门面漏改分支」的事故模式，per-kind 独立管线则三份复制。

## Decision

- 引擎瘦身为纯调度（验收门收集、拓扑分批 + 信号量、结果组装、状态判定、进度、报告、环境门骨架），执行形态抽为 Runner 接口（`kind`/`validate`/`setup`/`execute`/`teardown`/`probe_env`）插件，web/cli/api 三实现独立模块；未来新形态只加 Runner。
- 调度器不认识 kind：按本轮场景集实际出现的 kind 查注册表分派，Runner lazy setup/teardown——纯 CLI/API 轮次不启动浏览器。
- kind 是场景级字段（缺省 web），混合 spec = 场景集混排，跨 kind 流程用既有 `depends_on` 表达；不做 spec 级 kind 声明、不做单场景内跨 kind 步骤混排、不做自由脚本逃生舱（破坏确定性不变量）。
- 三套词表共用断言分层语义（第 1 层存在/状态、第 3 层内容、第 4 层启发式；CLI/API 无第 2 层交互），断言结果恒为带 `pass`/`layer` 的 dict——裁决链、报告、dashboard 全部按字段驱动，零 kind 分支。
- 契约形态按场景集 kind 组成反推：纯 cli 全省 serve/ready，含 web/api 必须（缺失=验收错误打回）；不新增契约字段。BASE_URL 铁律覆盖 `http_request`/`sse_connect` origin 改写与 CLI env 注入（框架值优先），不引入第二套 URL 规则。

## Consequences

- 词表权威源单点在 `scenarios.py` VALID 常量，planner prompt 只做摘要（防枚举双源漂移）。
- CLI 特异执行语义：非零退出码不判步骤失败（由 `exit_code` 断言仲裁）、超时=步骤失败且杀进程组、信号死亡=`error` 不进 product-bug 管道。
- 新增验证形态的成本收敛为「实现一个 Runner + 一套词表」，引擎调度与下游消费零改动。
