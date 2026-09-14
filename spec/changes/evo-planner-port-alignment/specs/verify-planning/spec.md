# 场景端口契约对齐（planner-port-alignment）

## 需求

### R1 端口来源注入
- planner 上下文（prompt 或场景模板）注入验证契约声明的实际端口：serve.cmd 采用 {port}/$FENIX_VERIFY_PORT 时传注入端口；未采用时传 serve.port 或已探测端口。
- planner 生成场景 URL 必须基于注入端口，禁止自由臆测。

### R2 改写回写
- pm_engine 在阶段 2 可达性校验执行端口改写后，将「实际端口=xxx」写入该 spec 的验证上下文（scenarios 元数据 / planner 上下文缓存），同窗口后续场景直接复用。

### R3 臆测告警
- 同一 spec 端口臆测（改写）≥2 次时打 WARNING 并提示验证契约缺陷（serve.cmd 未端口注入），dashboard 可见。

## 验收标准
- 场景：serve.cmd 采用端口注入后，0 次端口改写日志。
- 场景：无契约时改写 ≥2 次触发契约缺陷 WARNING。
- 单元测试：改写后复用实际端口；注入端口被 planner 采用。