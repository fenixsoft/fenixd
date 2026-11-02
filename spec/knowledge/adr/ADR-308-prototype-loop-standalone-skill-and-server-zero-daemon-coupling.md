# ADR-308：原型确认环独立 skill 与独立服务器，零 dashboard/daemon 耦合

date: 2026-11-02
status: accepted

## Context

SPEC 起草阶段引入界面原型确认环，需要伺服原型页面并接收浏览器批注。可选路径之一是复用 dashboard 路由（共享端口、鉴权与部署），但 dashboard 是 daemon 控制面：原型是起草期会话内的短生命周期工具，受众（正在确认界面的用户）与生命周期（批准即回收）都不同，并入控制面会让原型迭代绑架 dashboard 可用性，也让 daemon 承担无关风险。备选「把原型生成并入 fenix-new」同样不成立：职责膨胀且无法单独重放迭代既有原型。

## Decision

原型确认环以独立 skill `skills/fenix-prototype/` 承载，fenix-new 只做触发判定与衔接调用；伺服走独立进程的 python 标准库简易 HTTP 服务器（静态伺服 + `POST /feedback` 落盘），零第三方依赖、零 dashboard 依赖、不改 daemon。复用 dashboard 路由的备选被用户否决。服务器自带 PID 文件三态生命周期（存活复用、残留接管、结束回收）与随机高端口避让。fenix 系 skill 依赖 `/root/.claude/skills/` 符号链接被发现，新增 skill 部署需人工补链。

## Consequences

- dashboard 与 daemon 零改动、零回归面，原型侧故障不波及控制面；代价是原型服务器生命周期需自理（三态管理 + 测试钉死）。
- 原型入口与 dashboard 分离，用户需分别访问两个 URL；这是接受的体验代价。
- 后续原型侧任何能力（预览增强、批注协议演进）都应长在独立 skill 内，禁止借道 dashboard 端点或 daemon 调度承载原型会话；要打破此边界须显式 supersede 本 ADR。
