# ADR-032：failover 候选链元素级模型映射

date: 2026-09-03
status: accepted

## Context

provider 候选链（ADR-004）落地时链条目仅支持字符串、角色级 model 强制必填，使「provider 自身 model 兜底」的分支不可达——同能力但模型名不同的跨供应商场景无法成链。UI 单值 select 的表单序列化回写还存在覆写链的风险。

## Decision

- 链元素形态为 `str | {provider, model?}`：模型解析三级回退（元素自带 model → 角色级 model → provider 条目的 model 字段），三者皆空则该元素校验失败（ERROR 指明元素下标）；角色级 model 由必填改为可选。
- 校验语义从「角色级 model 非空」替换为「链上每个元素可解析出模型名」；校验失败不阻塞加载，与未知 provider 同哲学——运行期跳过该元素并打 ERROR；完全无可用元素的链返回空、走默认网关。
- 切换仍以元素整体为单位（取下一元素的 provider+model 二元组注入 env），resume 照常携带；provider marker 记录实际模型，模型变化落切换日志供归因。
- UI 与保存以「表单整体状态」序列化回写：整体替换该角色条目，不允许部分字段混拼；后端 patch 应用前整体校验，失败拒绝落盘（400）——脏配置进不了配置文件。

## Consequences

- 跨供应商同能力链可表达；旧 str/list 形态逐字节兼容，纯增量。
- 跨模型 resume 的上下文兼容不做预检（无法可靠预判），由配置者担责、切换日志留痕供事后归因。
