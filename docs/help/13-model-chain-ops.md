# 13 模型链运维

本文描述模型链（`agents.models.<role>.provider` 候选链）中出现「拒模型」条目时的人工运维步骤：如何识别、何时摘除、摘除哪些条目、如何恢复，以及恢复后的核对项。

> 背景：框架对 `unrecognized_model`（provider 明确拒绝某模型名）有快速 failover——run 内沿链切换下一候选、不重派、不递增 transient/同因重派计数（`add-impl-selfcheck-model-probe`）。链上每个被拒条目都会拖慢当次 run 并污染日志，但框架**不会**自动修改你的配置，摘除条目是人工步骤。

## 1. 摘除理由：12 次拒模型实测

2026-09 生产环境实测：`maomaoai` provider 对模型名 `deepseek-v4.1-flash` 连续返回 `unrecognized_model`（12 次，跨多个 impl run，每次派发必现、无一例外）。结论：

- 该 (provider, model) 组合是**确定性失败**，与网关负载无关——重试、等待、重派都不会自愈；
- 每次派发都会在 run 内先撞该条目再切链，白烧一次进程启动 + 一次失败告警；
- 若链上所有条目都被拒，run 以 `[model-chain-unavailable]` 归因收场且**不会自动重派**（阻断循环，等人工处理）。

因此被拒条目应当摘除，而不是留在链上「等它恢复」。

## 2. 识别信号

出现以下任一信号即说明链上存在拒模型条目：

1. **WARNING 日志**（`logs/agent_runner.log` 或 daemon 日志）：
   `Unrecognized model rejected by provider (add-impl-selfcheck-model-probe) — provider='<名>' model='<模型名>' run_id='...' spec='...'`
   同一 (provider, model) 反复出现即应摘除。
2. **spec error 字段 / Dashboard 告警**：错误文本含
   `[model-chain-unavailable] 全链模型不可用：provider '<名>' 拒绝模型 '<模型名>'（unrecognized_model，链尾无更多候选；本 run 已有 N 个链上候选被拒）`
   ——文本直接点名了要摘的 provider 与模型名。

## 3. 摘除步骤（运行时 `.fenix/config.yaml` 人工同步修改）

模型链定义在**运行时** `.fenix/config.yaml`（模板 `config.template.yaml` 只有注释示例，不含活动链）。摘除是纯配置编辑，daemon 无需重启（runner 每次派发都从 config 重新解析链）：

1. 停掉正在跑的受影响 spec（或等当前 run 自然收场——它在等人工摘除，不会重派）。
2. 编辑 `.fenix/config.yaml`，定位 `agents.models` 下出现该组合的角色链（形态 2 字符串数组 / 形态 3 对象数组都可能），删除被拒条目：
   - 形态 3 示例：删除 `- provider: "maomaoai"\n  model: "deepseek-v4.1-flash"` 两行；
   - 形态 2 示例：把 `"maomaoai"` 从 `provider: [...]` 数组中移除。
3. **各链剩余条目 ≥3 核对**：摘除后检查受影响角色的链上剩余可用条目数不少于 3（保证 failover 仍有纵深；不足时先补入其它可用 provider/model 再摘）。
4. 若多角色共享同一 provider 条目（如 `implementer` 与 `fast-track` 链），**每个引用处都要同步摘除**——链按角色独立展开，无全局去重。
5. 手工触发一次重派：清除 spec 的 `error` 字段（Dashboard「清除错误」或 CLI），既有轮询/事件机制会自然重排该 spec。

## 4. 恢复条件

摘除的条目在以下条件**全部**满足后才考虑加回链上：

1. provider 侧确认支持该模型名（以 provider 官方模型列表或一次成功调用为准，不能凭文档推断）；
2. 手工对该 provider+model 发起一次探针调用（任一 CLI 请求）返回成功、无 `unrecognized_model`；
3. 加回后观察首个 run：`agent_runner` 日志不再出现该组合的 `Unrecognized model rejected by provider` WARNING。

> 模型名变更（如 `deepseek-v4.1-flash` → 新版本名）不算「同一模型恢复」，需按新条目重新探针。

## 5. 在 `.fenix/todo.md` 登记提醒

摘除动作完成后，在项目根 `.fenix/todo.md` 登记一条提醒（人工步骤，框架不代写）：

```markdown
- [ ] 模型链摘除跟进：<provider> / <model> 于 <日期> 摘除（12 次拒模型实测）；
      待 provider 确认支持后按 docs/help/13-model-chain-ops.md §4 条件恢复。
```

用途：把「链上少了哪些条目、为什么少、何时能加回」留在项目视野内，避免数周后链纵深悄然缩水无人知晓。

## 6. 相关机制速查

| 机制 | 行为 |
|------|------|
| run 内拒模型识别 | WARNING 留痕 + 沿链切下一候选（`classify_unrecognized_model_error`，不入瞬断/同因计数） |
| 链尾仍被拒 | 失败归因注入 `[model-chain-unavailable]`，attempt 预算立即收场 |
| 派发器读侧 | 看到该归因**不重派、不增 retry、不翻转状态机**，spec 原状等人工 |
| 自动恢复 | 无——摘除/加回均为人工步骤（本文） |
