# 设计 — planner-port-alignment

## 端口来源
- verify_contract.py 在解析 serve 时输出 effective_port：cmd 含 {port}/$FENIX_VERIFY_PORT 时分配注入端口；否则取 serve.port 或启动后扫描到的邻近端口（legacy_hint 已有邻近扫描，verification.py 544-550 行）。

## planner 上下文注入
- 场景生成（planner-judge）prompt 增补「实际服务端口」段：来自 effective_port；planner 场景 URL 必须以该端口为准。
- 改写回写：pm_engine 改写场景端口后写回 scenarios 元数据 port_effective，同窗口后续阶段读取。

## 告警
- port_rewrite_count per spec ≥2 → WARNING（message 附 serve.cmd 现状与迁移建议）。

## 改动点
- .fenix/core/verify_contract.py：effective_port 输出。
- .fenix/core/pm_engine/verification.py：改写回写 port_effective + 臆测告警。
- .fenix/core/pm_engine/prompt_builder.py：planner 上下文端口注入。