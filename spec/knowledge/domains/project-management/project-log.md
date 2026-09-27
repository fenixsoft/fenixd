<!-- knowledge: capability=project-log rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 项目日志

`.fenix/PROJECT_LOG.md` 是项目的追加式运维日志，记录关键运行事件与人工可读的历史轨迹。

## 现行规则

- 写入方为 PMEngine：`append` 追加带时间戳的消息，每日报告（daily report）按日追加，blocker 报告每小时最多写一次（节流）。
- 日志定位是「可丢的报告」：`PROJECT_LOG` 写失败（含磁盘满）不得中断主链——push 收口、auto-recovery 等主流程对该写入做吞错保护，不向外传播异常。
- 读取方为运维视角的人与 agent：日志内容不参与状态机判定，不作为任何门禁输入。
- 文件由 `templates/PROJECT_LOG.md` 模板在项目初始化时播种。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
