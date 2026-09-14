# planner-port-alignment — 验证场景端口契约对齐

## 背景
planner 在场景 URL 中臆测端口，与实际服务端口不符，触发「验证目标应用不可达→自动启动服务→改写场景端口」链路：add-web-ui 窗口内 8 次端口改写 + 7 次自动启动，每次多耗一轮验证环境初始化；verify_contract 组件反复输出「serve.cmd 未引用端口注入」WARNING。验证契约的端口注入机制（serve.cmd 的 {port}/$FENIX_VERIFY_PORT）已存在但未被 planner 与 serve 采用。

## 目标
- planner 生成场景 URL 时从验证契约的实际端口来源读取端口（serve 端口注入 / 已探测到的实例端口），不再臆测。
- pm_engine 改写场景端口后，向 planner 上下文回写「实际端口=xxx」，后续场景直接复用。
- 同一 spec 端口臆测 ≥2 次时打 WARNING 并提示契约缺陷。

## 非目标
- 不改自动启动服务的既有兜底行为。
- 不改验证裁决/费控逻辑。

## 验收
- 新验证轮不再出现「场景 URL 端口与应用实际端口不符」改写日志（serve.cmd 采用端口注入时）。
- 改写发生后同窗口后续场景复用实际端口。