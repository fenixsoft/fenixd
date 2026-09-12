---
name: fenix-process
description: Use when the user wants to check detailed progress of a specific SPEC. Invoked via /fenix-process <spec-name>.
---

# Fenix Process — SPEC 详情与分诊

查看指定 SPEC 的详细进展并给出 LLM 分诊。数据与 Web Dashboard 同源（`core/dashboard/data.py` 的 `spec_detail`，即 `/api/specs/<name>` 同一份组装）；TUI 的价值不在复刻 web 详情页，而在 **LLM 主动判读**——指出当前卡点、成因与下一步。

## 用法

用户输入 `/fenix-process <spec-name>`（kebab-case 名称）。用户漏写参数时，运行 `/fenix-status` 的脚本取活跃 SPEC 列表请其选择，不要臆测。

## 输出要求

1. **一句话状态判读**：综合状态、进度、预算与验证结论（如「第 2 轮验证发现 2 个产品 Bug，尝试预算还剩 4 次，等待 fix 链」）
2. **需要关注**：本 SPEC 视角的分诊——卡点是什么、证据、建议下一步（具体到命令或 dashboard 操作）。正常推进时明确说「推进正常」，禁止硬凑
3. **数据区**：脚本输出的关键区块原文（按用户关注裁剪，异常区块不省略）

## 分诊规则

- **验证结论**：failed + 产品 Bug 列表 → 逐条摘要 Bug（场景、断言、severity）；环境问题类失败（非产品 Bug 过滤计数大）→ 提示可能是验证环境而非代码缺陷，建议核对 verify 契约或 dashboard 场景结果页
- **尝试预算**：耗尽 → 需人工介入或 `/fenix-dashboard` 调预算；剩最后 1 次 → 提醒
- **运行历史**：同 run_id 多个 attempt（`-a2`、`-a3` 后缀）→ 说明已重试多轮，结合各 attempt 状态判断是否原地打转；error/interrupted 状态的 run 要点出
- **时间轴**：`↩️` 打回节点（backward）→ 说明从哪态被打回、原因；retries 多 → 提示重试频率异常
- **验证停滞**（验证进度长时间未动但状态仍 testing）→ 结合运行历史判断 verifier 是否真在干活
- **冻结 / start_after** → 有意等待，归入「按计划」，不算问题；解冻/拾取时间转本地时区表述
- **成本**：累计成本与 token 量异常大时提示（结合重试轮次解释成因）
- **下一步动作映射**：done → `/fenix-approve`；drafted → `/fenix-ready`（manual 模式）；bug-found → 等待 fix SPEC 或人工处置；blocked → 确认冻结原因或解冻

## 步骤

### 1. 生成报告

```bash
python3 .fenix/bin/fenix_process.py "<用户提供的 spec-name>"
```

脚本输出：头部（状态/模式/依赖/分支/错误/冻结定时）→ 进度（tasks.md 分组、run 层实时、验证、出题）→ 尝试预算 → 验证结论（含产品 Bug 与非产品失败过滤计数）→ 运行历史（含归档）→ 成本 → 时间轴精华 → 工作区 → 下一步。

spec 不存在时脚本以退出码 1 报错——转告用户并建议 `/fenix-status` 查看全部名称。

### 2. 分诊并输出

按「输出要求」组织：判读 → 需要关注 → 数据区。数据区优先保留：进度、预算、验证结论、运行历史；时间轴与工作区按相关性取舍。最后可主动提议：深入某个 run 的对话、到 dashboard 看场景级截图证据（`.fenix/screenshots/<spec>/`）。
