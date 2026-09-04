# Proposal: improve-failover-model-mapping-ui

## Why

add-provider-failover 落地后暴露两个缺口：1) 角色级 `model` 对整条链强制生效且校验要求非空，导致"provider 条目自带 model"的回退是死代码——跨供应商链（inferaiapi 的 deepseek-v4-flash / aliyun 的 -0731 / bigmodel 的 glm-*）做兜底时会以错误模型名请求必然 unrecognized_model，链形同虚设；2) Dashboard 设置界面的 agent 分配仍是单选下拉，无法表达链，且表单保存会用单值覆写 YAML 里已配置的链。

## What Changes

- **链元素模型映射**：`agents.models.<role>.provider` 列表元素支持 `str | {provider, model}` 对象形态；角色级 `model` 语义降为"全链缺省"；校验规则改为"角色级缺省与元素自带 model 合计必须覆盖链上每一项"。
- **failover 使用元素自身模型**：切换时向目标 provider 发送该元素映射的模型名；provider_marker 与 switch 日志记录 model 变化。
- **Dashboard 链编辑器**：设置界面 agent 分配支持可排序多 provider 列表（每行 provider 下拉 + model 文本框），加载识别 str/list/对象形态，保存序列化为链；杜绝单值覆写。

## Capabilities

### New Capabilities
- `chain-model-mapping`: 候选链元素级模型解析、校验放宽与 failover 集成
- `dashboard-chain-editor`: 设置界面多 provider 链的可视化编辑与安全保存

### Modified Capabilities

<!-- modify add-provider-failover 已交付的 provider-chain-config 模型解析行为，
     因 spec/specs/ 为空，以 ADDED 声明新能力并在 spec 中注明取代关系 -->

## Impact

- **代码**：`core/config.py`（_validate_agent_models、get_agent_model_assignment）、`core/agent_runner.py`（provider_marker / switch 日志带模型变化）、`core/dashboard/data.py`（config patch 序列化链）、`core/dashboard/static/app.js`（分配表单）
- **配置**：无需新增键；文档注释补对象形态示例
- **测试**：config 解析矩阵（str/list/对象/混合/缺省覆盖）、failover 切换模型选择用例、UI patch 序列化往返用例
