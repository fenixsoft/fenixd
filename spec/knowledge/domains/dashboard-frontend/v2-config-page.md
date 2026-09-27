<!-- knowledge: capability=v2-config-page rev=1 sources=spec/archive/2026-09-06-v2-config-page -->

# v2 配置页

v2 的配置编辑页：5 页签回显与保存、Agent 链编辑器与完整性校验、编辑期 SSE 豁免。

## 现行规则

- 配置页提供 5 个页签；页面加载后回显当前配置（llm 缺失时兜底）；配置沿用户级→项目级三级回退。
- 修改任意字段保存经 `POST /api/config`（buildConfigPayload 合并）；保存不覆盖未受管子键；成功 toast（5 秒窗口），重载后新值回显。
- Agent 模型页签为可排序多行编辑器（角色 select + 模型名，角色枚举见 behavior.md §6）；链不满足完整性（必填角色缺失 / 模型名不存在）时保存被 validateChain 拦截并显示错误文案，不发 POST。
- 配置页不监听任何 `sse:*` 广播（编辑豁免）：输入聚焦过程中后端产生 state/refresh 帧，表单值与焦点不被清空，无 reload 发生。

## 溯源

- 史前复原 — v2 配置页 5 页签 + provider 链编辑器 + 三级回退 + 编辑豁免；保存不覆盖未受管子键
- 2026-09-06 v2-config-page — 落地配置回显与保存闭环（toast + 重载回显）、Agent 链完整性校验拦截与编辑期 SSE 豁免
