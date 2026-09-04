# Dashboard 使用指南

Fenix Web Dashboard（`http://localhost:8787`）是跨项目的可视化监控与运维入口。本章逐面板讲解五页与关键操作。

## 启动

```bash
/fenix-dashboard
```

输出可直接粘贴到浏览器的访问 URL。Dashboard 进程为独立长驻服务，由 `/fenix-dashboard` 启动或复用；被占用端口由旧 dashboard 实例自动接管。

## 侧边栏菜单

| 菜单 | 路径 | 用途 |
|------|------|------|
| 概览 | `/overview` | 跨项目状态统计、任务进度、问题、活跃运行 |
| 项目 | `/projects` | 项目列表与各项目聚合摘要 |
| 设置 | `/settings` | 配置管理、验证契约、token 预算面板 |
| 运维 | `/activities` | Administrator 活动时间线 + 人工告警处置 |
| 帮助 | `/help` | 帮助文档中心（本文档集） |

## 五页逐面板

### 概览页（/overview）

- **跨项目状态统计**：SPEC 总数、按状态分类计数、活跃运行数
- **任务进度**：任务完成率（task_done/task_total）
- **问题区**：各项目 problems 计数（阻塞/告警）
- **活跃运行**：进行中的 Agent run 列表（按类型分组）

### 项目列表页（/projects）

- 每个项目卡片：daemon 健康状态、SPEC 数、状态分布、任务进度、验证场景数、简介
- 项目级操作：启停 daemon（start/stop）、软删除（delete）、重新生成简介

### SPEC 详情页（/projects/:name/:spec）

- SPEC 元数据：状态、优先级、创建/更新时间、分支、error
- 五个文档页签：需求背景（proposal）/ 详细设计（design）/ 任务清单（tasks）/ 验证报告 / 测试场景清单
- **行操作**（详情行工具条）：
  - **设置优先级**：1-9（P1 最高）
  - **冻结/解冻**：人工冻结（blocked + 标记）/ 解冻恢复
  - **清除错误**：在线清除 error 字段（置空写回 STATE.md）
  - **归档**：终态（done/pushed）SPEC 目录移入 archive
  - **删除**：软删除（剔除 STATE.md + 目录移入 archive；运行中返回 409）
  - **呼叫 Admin**：手动唤起 Administrator（写 admin_invoke_request.json）

### 设置页（/settings）

- **配置管理**：分项目读写受管配置键（llm / agents.models / gates.approve_mode）
- **验证契约**：verify.yaml 的查看与编辑入口
- **Token 预算面板**：查看/调整 token 预算与消耗
- **提示词管理**：查看通用层 agents/ 提示词、编辑项目级附加提示词

### 运维记录页（/activities）

- **自动运维视图**：Administrator 活动时间线（处置记录、结果标签）
- **人工告警视图**：未处理升级告警列表 + 「标记已处理」操作
- **告警处置**：顶部横幅展示跨项目未处理告警总数；每条告警含信号类型、严重度、证据、建议

## 帮助页自身用法

「帮助」菜单（运维之下）进入本文档中心：

- **桌面端**：左侧文档目录（选中高亮）+ 右侧 Markdown 正文
- **移动端**（<768px）：正文 + 顶部「文档目录」按钮打开抽屉切换
- **URL 同步**：`#/help?doc=<name>` 可直链到具体文档，刷新/分享不丢失
- **文档切换**：目录点击或正文内相对链接均可页内切换

## 安全边界

- Dashboard 仅绑定 `127.0.0.1`，不对公网开放
- 无鉴权机制——不要暴露到公网或内网不可信网络
- 所有 API 均有防穿越校验与错误容错，不会因异常数据 500

## 相关文档

- [帮助中心首页](README.md) — 返回本帮助中心
- [核心概念与架构](02-concepts.md) — 多项目机制
- [配置参考](08-config.md) — Dashboard 设置页与配置键映射