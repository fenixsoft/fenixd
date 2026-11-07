# dsh web 连接基线与「重新连接中」重连环判读

<!-- knowledge: capability=dsh-web-connection-baseline rev=1
     sources=spec/knowledge/_inbox/done/dsh-web-stale-asset-reconnect-loop-1107.md -->

dsh web 前端的浏览器 API 兼容基线，与实时通道（WS `/api/remote.mux`）「重新连接中」重连环的判读口径：症状签名、健康握手对照、排除面与取证方法。

## 规则

- **浏览器 API 基线**：dsh web（0.2.0-rc.2）前端依赖 `Promise.withResolvers`（Chrome/Edge ≥119、Firefox ≥121、Safari ≥17.4）与 `AbortSignal.any`（Chrome/Edge ≥116、Firefox ≥124、Safari ≥17.4）。低于基线的浏览器（如 Chrome/Edge 111）打开页面后 generation 启动即崩，业务通道一个帧都发不出——唯一修复是换/升级浏览器到基线以上，服务端侧无解。
- **症状签名**：页面能打开但侧栏底部 ConnectionIndicator 恒显「重新连接中」，同浏览器重开 token URL 无效，fenix-dsh-dashboard-bridge「工作区列表未就绪」为同一下游症状。抓包形态：WS 升级全 101、cookie 有效、ping/pong 正常，但升级后客户端零业务帧，6–10 秒后客户端主动 `close(4000,"reconnect requested")` 退避重试无限循环。
- **close 4000 是下游症状**：4000 唯一来源是 `RemoteStreamMuxClient.reconnect()`（connection loop 的 `onReconnectRequested` 回调）——WS 反复重连是受害者不是病灶，勿在传输层排查。
- **健康握手对照**：健康会话为 WS 101 → 客户端约 0.4s 内发 3 个 `open` 帧 → 服务器同秒回 item（首个含 host 即 ready）→ 长连。「101 但零业务帧」与该形态对照即可把病灶定位到客户端侧。
- **服务端/链路/凭据排除面**：admit 准入放行 101；认证 cookie 名为 `dsh-auth-`+sha256(authority)，跨重启稳定、签名 secret 持久化——dsh-web 重启只作废 URL token（每进程随机），cookie 会话不失效；frp 公网链路不改变上述判读。
- **console 优先于抓包**：`Uncaught TypeError: Promise.withResolvers is not a function` 一行 console 即可定案；pcap 只能证明「客户端没发帧」，不能证明「为什么没发」——判断证据充分性后再下结论，console 一行顶一小时抓包推理。
- **缓存解释不适用本症**：dsh 静态资产无 `Cache-Control` 头是真实存在的启发式缓存风险，但与重连环无关（同引擎无痕窗口同样崩溃）——勿以旧缓存解释「重新连接中」。
- **文案出处**：「重新连接中」来自 `dsh-client-ui-settings-general` 的 `connection.connecting` 键，渲染位置是侧栏底部 ConnectionIndicator，不是终端面板——据此区分连接层症状与终端流症状。
- **WS 排查必须 tcpdump**：playwright 的请求列表不显示 WebSocket 升级，勿以 playwright requests 做 WS 取证；在服务端 tcpdump 抓回环/链路。
- **客户端无能力探测（开放缺口）**：API 不满足时只有「重新连接中」文案、无版本过低提示；可选收口方向为 boot 前探测 `Promise.withResolvers`/`AbortSignal.any` 显示降级横幅，或外挂插件注入 polyfill。

## 关键行为

token URL 从 `/var/log/dsh-web.log` 尾部获取；浏览器侧验证用 playwright 命名会话（`-s` 隔离）。`dsh-plugin-loopback-trust` 伪造 `__DSH_TRANSPORT__.ownsHost` 同处 non-loopback 访问路径，但与本症无关。dsh 版本升级时本页基线与判读签名需复核。

## 溯源

- 2026-11-07 dsh-web-stale-asset-reconnect-loop-1107（spec/knowledge/_inbox/done/dsh-web-stale-asset-reconnect-loop-1107.md） — 新增本能力：浏览器 API 基线双门槛、低版本重连环症状签名与 close 4000 溯源、健康握手对照、服务端/cookie/frp 排除面、console 优先与 tcpdump 取证纪律、无能力探测开放缺口登记
