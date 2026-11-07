# dsh web「重新连接中」无限重连 = 浏览器内核过旧（1107 排查定案）

## 现象
dsh web（3080）页面能打开，但侧栏底部 Settings 行 ConnectionIndicator 恒显「重新连接中」；关标签页重开 token URL 无效。

## 真根因（用户 console 定案）
用户浏览器 **Edge/Chrome 111**（UA 抓包取证：`Chrome/111.0.0.0 ... Edg/111.0.1661.44`）不满足 dsh 0.2.0-rc.2 前端 API 基线：
- `Promise.withResolvers` 要求 Chrome/Edge ≥119、Firefox ≥121、Safari ≥17.4
- `AbortSignal.any` 要求 Chrome/Edge ≥116、Firefox ≥124、Safari ≥17.4

console 三连：`(索引):45 Uncaught TypeError: Promise.withResolvers is not a function` → `AbortSignal.any is not a function at RemoteStream.read`（generation 启动即崩，故一个业务帧都发不出）→ `[connection] connection lost, retry #N` 无限循环。fenix-dsh-dashboard-bridge「工作区列表未就绪」为下游症状。
**修复 = 换/升级浏览器**：Edge/Chrome ≥119（建议直接最新版）、Firefox ≥124、Safari ≥17.4。

## 帧级取证链（方法论价值，结论曾一度误判为缓存）
- 文案出处：`dsh-client-ui-settings-general` L891 `"connection.connecting": "重新连接中"`（侧栏底部 ConnectionIndicator，非终端面板）。
- 健康握手（本地+公网域名全新浏览器）：WS `/api/remote.mux` 101 → 客户端 ~0.4s 发 3 个 `open` 帧 → 服务器同秒回 item（首个含 host 即 ready）→ 长连。
- 用户侧（服务端回环抓包 92s）：12 次升级全 101、cookie 有效、ping/pong 正常，但升级后客户端零业务帧，6-10s 后客户端 `close(4000,"reconnect requested")` → 退避重试循环。
- 4000 唯一来源 `RemoteStreamMuxClient.reconnect()` ← connection loop `onReconnectRequested`；WS 抖动是受害者不是病灶。
- 服务端/frp/cookie 全排除：admit 准入 101；cookie 名=`dsh-auth-`+sha256(authority) 跨重启稳定、签名 secret 持久化，重启仅作废 URL token（每进程随机）。
- **教训：我曾依据「dsh 资产无 Cache-Control 头」误判为旧缓存**——头确实缺失（启发式缓存风险真实存在），但与本症无关（同引擎无痕窗口也会崩）。判断证据充分性后再下结论：pcap 只证明「客户端没发帧」，不能证明「为什么没发」；console 一行顶一小时抓包推理。
- **playwright 请求列表不显示 WebSocket 升级**——WS 排查必须 tcpdump，勿信 playwright requests。

## 可立项（未立项）
dsh 客户端缺能力探测：API 不满足时只显「重新连接中」无任何提示。可考虑外挂插件注入 polyfill 或 boot 前检测 `Promise.withResolvers/AbortSignal.any` 并显示「浏览器版本过低」横幅。

## 关联
11-06 dsh web 重启族；`dsh-plugin-loopback-trust`（伪造 `__DSH_TRANSPORT__.ownsHost`，与本症无关但同处 non-loopback 路径）。
