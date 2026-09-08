# Tasks: verify-draft-bad

## Deliverables

无（fixture spec，用于验证框架的坏草稿处理机制）

## 1. 阶段一

- [x] 1.1 任务一（占位任务，无实际实现需求）

---

**验证结论**：本 spec 为框架测试用 fixture，任务书无交付物要求。
测试套件：预存 1 个时间敏感失败（`test_freeze_config_scheduled` 使用硬编码日期 `2026-09-08T01:00:00+00:00`，已过期），其余全部通过。
无代码变更需求，实现器无需修改生产代码。
