# 自进化标记回写提交
<!-- knowledge: capability=todo-marker-commit-on-write rev=2
     sources=spec/archive/2026-10-12-evo-add-todo-marker-commit-on-write,spec/archive/2026-10-27-evo-evolution-accept-marker-batching -->

自进化裁决标记写入项目主树 `.fenix/todo.md` 后由写路径就地完成该文件的 git 提交，提交粒度按「批处理批末合并、单点写后即时」分治：tracked 文件不滞留未提交改动，主树滞留盘点不再看到该指纹，major 级 maintree_stray_wip_stale 告警与 admin 代提交不因此路径产生。

## 规则

- 提交粒度分治：单点写路径（dashboard 手动单条接受、拒绝、手动单条删除）在标记写入后即时提交，一次写入一枚提交；批处理路径（ingest 落库、自动接受循环 auto_accept_pending、保留清理 prune_items）批内逐条写标记不触发提交，由各批在批末对本批涉及的每个项目各调一次合并提交。批去抖由调用方经显式 defer 开关声明，开关缺省为即时提交，批消费方必须显式声明 defer。
- 批末合并提交：一批接受/清理 N 条条目在 `.fenix/todo.md` 上只产生一枚提交（每项目各一枚），提交数不随条目数放大；空批不触发批末提交。不存在跨项目单提交；接受路径中的 SPEC 立项提交（spec 目录 pathspec）属立项语义，仍逐条一次，不在标记提交合并面内。
- 消息可对账：合并提交在固定主题行（`[fenix] evolution: 自进化标记回写 <date>`，遵循仓库惯例）之后以空行分隔附本批条目明细正文（「接受条目（N 条）」/「保留策略清理条目（N 条）」+ 逐条 id 列表），合并提交的 git 历史仍可对账到逐条条目；主题行本身不变。
- 无跨生产者合并窗口：提交合并只按生产者批内收集、作用面限于本批循环自己的写入，不设文件级/时间窗去抖——`.fenix/todo.md` 有 evolution 与 self_review 两个生产者以同 pathspec 不同消息提交，时间窗会把对方滞留改动卷进错误消息的提交并随 push 外泄。
- tracked 判定：以 `git ls-files` 判定 todo.md 是否被 git 跟踪；未跟踪（含目录非 git 仓库）直接跳过提交，写入行为不变、不报错。
- pathspec 限定：`git add -- .fenix/todo.md` 与 `git commit -- .fenix/todo.md` 均带 pathspec，提交仅含该文件——不带 pathspec 的 commit 会把索引中并发暂存的其他自动化产物（merge-back、交付物守卫等）卷进本提交并随 push 外泄。
- 锁外执行：提交动作在 todo.md 的 flock 释放后执行，git 子命令（各 30s 超时）不进锁内，不拉长持锁窗口阻塞 code_fix / self_review 的并发追加。
- 失败降级：commit 失败（含 index.lock 竞争）捕获后经既有日志通道留痕，不回滚写入、不向调用方抛错、不做自动重试（下一次写入自然再试）；push 失败降级 WARNING 不重试，本地提交不受影响。无变更（working tree 干净或本 pathspec 无改动）为良性 no-op，记 INFO 不告警。
- 批中途中断（daemon 被杀）时已写标记未提交属设计内窗口：todo.md 状态与 git 提交解耦、下轮扫描以文件为准，由既有恢复/盘点流程覆盖。

## 溯源

- 2026-10-12 evo-add-todo-marker-commit-on-write（spec/archive/2026-10-12-evo-add-todo-marker-commit-on-write） — 新增标记写后即时入库全部规则（tracked 判定跳过、按项目合并单提交、pathspec 双限定、ingest 批量/单点分治、锁外提交、commit/push 失败降级）
- 2026-10-27 evo-evolution-accept-marker-batching（spec/archive/2026-10-27-evo-evolution-accept-marker-batching） — 修改提交粒度分治：接受循环（自动接受）与保留清理改批末按项目合并提交（原「accept 单点写后即提交」仅 dashboard 手动路径保留），合并提交消息附条目 id 明细；显式排除文件级时间窗合并
