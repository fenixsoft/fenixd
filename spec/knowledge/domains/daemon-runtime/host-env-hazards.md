<!-- knowledge: capability=host-env-hazards rev=1
     sources=spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md -->

# 宿主环境已知脆弱面

框架宿主机的环境级故障事实与临时绕过台账：每条绕过配置都是临时手段、附带回滚义务；环境级故障的告警形态与归因判读在此登记，避免被误归因到 provider 或框架自身。

## 规则

- 网关 DNS 失效的临时绕过（待 revert）：局域网网关 192.168.20.3 的 53 端口失效（ping 通但端口无响应），现以 systemd drop-in `/etc/systemd/network/10-netplan-enp42s0.network.d/99-admin-dns-priority.conf`（223.5.5.5 静态 DNS 提权、网关 DNS 降为末位 fallback）临时绕过。网关设备须人工检修（管理面凭据不在本机）；检修完成后删除该 drop-in 文件并执行 `resolvectl revert enp42s0` 还原 DHCP 原生配置。
- dns_probe_failed 判读：批量 dns_probe_failed（派发前连通预检失败、顺延本轮派发的 agent_runner 挂点信号）先查网关 53 端口连通性，不归因 provider 或框架调度；预检自身 fail-open（探测异常、无探测目标均照常派发），故该信号成批出现即指向宿主 DNS 链路本身。
- 环境级故障面与托管链的交集：托管链整链只承载于 tmux 会话、无 systemd unit，宿主机级事件下的连坐死亡识别与整链重建配方见 [supervisor 托管链](supervisor-hosting.md)。

## 溯源

- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 新建本页：网关 DNS 失效 drop-in 临时绕过（待 revert 与还原配方）、dns_probe_failed 批量信号的归因判读、与 supervisor-hosting 宿主级暴露面互链
