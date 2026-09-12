---
name: fenix-status
description: Use when the user wants to check Fenix framework status, view all SPEC progress, check daemon health, or see recent project activity. Invoked via /fenix-status.
---

# Fenix: 状态面板

展示 Fenix Loop Engineering Framework 运行状态。数据与 Web Dashboard 同源（`core/dashboard/data.py`）；TUI 的价值不在复刻 web 表格，而在 **LLM 主动分诊**——告诉用户该看什么、该做什么。

## 输出要求

1. **一句话总判**：综合全局状态用一句中文概括（如「1 个 SPEC 验证停滞，其余按计划等待拾取」）——自己判断，不要机械拼接
2. **需要关注**：分诊清单，按优先级排序；每条 = 问题 + 证据 + **建议动作（具体到命令）**。无异常时明确写「✅ 无需关注」，禁止硬凑条目
3. **数据速览**：脚本输出的「守护进程/告警/活跃运行/状态统计」头部 + 活跃 SPEC 明细 + 终态折叠行
4. 结尾附快捷命令

**信号汇总段是分诊素材，不原样罗列**——它的内容已融入「需要关注」。

## 分诊规则

按严重度排序（🔴 → ⚠️ → ℹ️）：

- 🔴 守护进程停止 → 建议运行 `/fenix-setup`
- 🔴 critical 未处理告警 / ⚠️ major → 给出告警摘要，建议到 dashboard 运维记录页查看处置上下文，或呼叫 Admin 介入
- ⚠️ 非 done 状态带 error → 摘录错误要点，判断是瞬时故障还是需要人工干预
- ⚠️ 尝试预算耗尽 → 说明已到重试上限，建议人工排障或 `/fenix-dashboard` 调高该 spec 预算
- ⚠️ 验证停滞（进度文件 >30 分钟未更新）→ 建议先 `/fenix-process <name>` 看验证结论与运行历史，确认是否真卡死
- ⚠️ auto 模式下 SPEC 滞留 done → 提示推送可能失败，`/fenix-approve` 人工兜底
- ℹ️ done 待推送（manual 模式）→ `/fenix-approve`
- ℹ️ drafted 待晋升（manual 晋升模式）→ `/fenix-ready`
- ℹ️ bug-found 无活跃 fix 子 SPEC → 提示修复链可能未建立
- ℹ️ 尝试预算剩最后 1 次 → 提醒即将到达上限
- **已知等待（冻结 / start_after 定时）不算问题**——归入一句「按计划等待」，不要写进关注清单

跨条目关联判断：多个 spec 同时异常时找共性（同一 provider、同一时间点），一次性指出根因候选，而不是逐条复读。

## 步骤

### 1. 生成报告

```bash
python3 .fenix/bin/fenix_status.py
```

脚本输出：守护进程/告警/活跃运行/状态统计 → 活跃 SPEC 明细（状态、任务/run/验证/出题进度、预算、耗时、error、冻结与定时标记）→ 终态折叠行 → 信号汇总。数据与 dashboard `/api/specs` 同源，无需自行解析 STATE.md。

### 2. 分诊并输出

按「输出要求」组织：总判 → 需要关注（含建议动作）→ 数据速览 → 快捷命令。

时间戳一律转本地时区表述。活跃 SPEC 可按优先级与异常程度决定详略，但**不要省略任何活跃 SPEC 行**。

### 3. 快捷命令

```
/fenix-new "需求"          — 创建新需求
/fenix-process <spec-name> — 查看某 SPEC 详情
/fenix-approve             — 审查并推送完成的 SPEC
/fenix-ready               — 晋升草稿（manual 晋升模式）
/fenix-dashboard           — 打开 Web Dashboard（实时监控/运维操作）
/fenix-setup               — 重启 fenixd
```
