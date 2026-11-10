# 测试编写设计规则

<!-- knowledge: capability=test-authoring-discipline rev=4
     sources=spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md,spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md,spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md,spec/knowledge/_inbox/done/dashboard-test-dist-index-pollution-1110.md -->

测试（尤其 agent 车道回归用例）编写时的隔离与替身设计纪律：进程级全局替换的复原义务、假进程替身的分发方式、常驻线程收割、用户级配置隔离、夹具路径指向与共享构建产物的读写隔离。

## 规则

- 进程级全局替换必须 try/finally 复原：测试内替换 `subprocess.Popen` 这类进程级全局对象时，复原代码必须放 try/finally——裸写在用例尾部时，SIGALRM（10s 单用例硬门，见 per-test-timeout 页）会在复原前打断，全局泄漏后同场全部子进程用例连坐超时。普通 pytest 测试类没有 `addCleanup`（unittest 专属），不存在兜底通道。
- 假 spawn 按 `cmd[0]` 分发：劫持进程启动的测试替身按命令首元素分发——真实子进程命令直通、假命令返回 fake；不按调用序号或全局一刀切分发，避免用例间互相污染。
- watchdog/常驻线程类测试必须收割线程：触及 `CLAUDE_PID` watchdog 类常驻线程的用例须在用例边界收割线程（tests/conftest autouse 收割现行）。泄漏的 watchdog 线程盯 pytest 自身 pid，负载峰值窗口集体误判死亡并对自身发 SIGTERM 自杀——非确定性的整场回归失败形态。
- 用户级配置敏感测试双隔离：全局开关常开形态下，涉及用户级配置的测试以 `patch("core.config.USER_CONFIG_DIR")` + `patch("core.dashboard.data.USER_CONFIG_PATH")` 双点隔离（仓内既定模式），不触碰真实用户配置。
- 测试夹具与场景数据 MUST 指向 `spec/archive/`：指向 `spec/changes/<SPEC>` 的夹具在 SPEC 归档迁出时批量失效，成为 judge 噪音源。
- 归档清单命中形态断言的夹具实名：凡断言「归档清单命中形态」（如指挥中心对已归档 SPEC 名下 run 的剔除聚合），夹具的 spec 段必须取真实归档清单里存在的名字——伪造名字会让 Scenario 假绿、端到端才撞墙。
- 单元测试禁读构建产物：单测 MUST NOT 依赖 gitignored 构建产物（dist）——裸 worktree 回归不含 gitignored 文件，依赖 dist 的用例每批首个回归必假失败；构建产物行为由构建级门禁（见 [build-gates 域](../build-gates/_domain.md)）承接，不进单元测试。
- 单元测试禁就地改写线上服务读盘的构建产物：dashboard 服务（systemd `fenix-dashboard.service`，端口 8787）直接读盘 serve 主树 `core/dashboard/static/dist/`——该目录是 gitignored 构建产物，但线上实例与测试共用同一份，不存在构建隔离层；`tests/conftest.py` 的 `server_fx` 夹具把仓库 `core/dashboard/static` 原样作为 static_dir 传给 `DashboardHTTPServer`。凡在 `server_fx` 上就地写 `dist/index.html` 的用例都直接改写线上服务正在读盘的产物，污染穿透到线上首页。
- 就地改写构建产物的用例必须快照回写：种入前快照 dist 文件原字节、teardown 回写原字节（`TestBundleRevHeader._seed_dist_index` 形态）；还原义务必须覆盖「index.html 已存在」形态——只处理「缺席→种入→删除」缺席分支时，真实 dist 会被用例写下的占位永久覆盖。
- 构建产物污染不会被新鲜度探针自愈：verify 开跑前的 dist 新鲜度探针（见 [serving-dist-freshness-probe 页](../verify-pipeline/serving-dist-freshness-probe.md)）按 mtime 比较 static src 树与 `dist/index.html`——测试替身写入使 dist 的 mtime 变新，探针判「新鲜」直通、绝不重建，污染可贯穿整轮验证，直到下一次真实构建才被覆盖。
- 构建产物污染复原口径：在 `core/dashboard/static/` 执行 `npm run build` 重建（max build + tailwind prebuild）；正常产物 index.html 为引用 hash 化 css/js 资源的最小 HTML 壳，`curl http://localhost:8787/` 应返回该 HTML 而非占位文本。

## 溯源

- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠测试编写设计规则五条：进程级全局替换 try/finally 复原义务（pytest 类无 addCleanup）、假 spawn 按 cmd[0] 分发、watchdog 常驻线程收割、用户级配置双隔离补丁模式、夹具路径指向 spec/archive
- 2026-11-04 memory-distill-diagnostic-signatures（spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md） — 折叠测试假失败判读签名：单元测试禁读 gitignored 构建产物（裸 worktree 回归缺 dist 即假失败），构建行为归构建级门禁
- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 折叠归档清单命中形态断言的夹具实名纪律（伪造归档名 Scenario 假绿、端到端才撞墙）
- 2026-11-10 dashboard-test-dist-index-pollution-1110（spec/knowledge/_inbox/done/dashboard-test-dist-index-pollution-1110.md） — 折叠主树 dist 污染面规则四条：单测禁就地改写线上服务读盘的构建产物（server_fx 共用同一份 dist 无隔离层）、就地改写须快照回写原字节（还原义务覆盖已存在形态）、mtime 新鲜度探针对污染零自愈、污染复原 npm run build 口径
