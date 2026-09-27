<!-- knowledge: capability=structured-log-rotation rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 结构化日志与跨进程轮转

`core/logger.py` 提供 JSON 结构化日志与跨进程安全的轮转，落盘 `.fenix/logs/fenixd.log`。

## 现行规则

- 每行日志是一个 JSON 对象，字段：`timestamp`（UTC、`Z` 后缀）、`level`、`component`、`message`，可选 `context` 与 `exc_info`。
- 时间戳格式保持 `Z` 后缀不变：展示层与既有 grep 依赖该格式。
- `logger.exception` 约定「详情（含堆栈）留服务端日志」，traceback 必须写入 `exc_info` 字段，不允许静默丢弃。
- 轮转基于 `RotatingFileHandler`；daemon、dashboard、CLI 多进程共写同一日志文件，轮转必须跨进程安全：
  - `FlockRotatingFileHandler` 以伴随锁文件 `<日志>.lock` 的 flock 串行化各进程的轮转窗口；
  - 持锁后做 `(st_dev, st_ino)` 陈旧检测，发现基底文件已被其他进程轮转时仅重新打开新基底文件，不重复 rename。
- 组件名经 `component` 属性标注，便于按模块过滤。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
