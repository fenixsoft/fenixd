# 合并增量（2026-10-30 人工全量核查）

合并裁定：F3 组（fa65a881e011、7f27c2baadd6）＋F4 组（78ee6520b1ed、d36a767db499）共 5 条同根因合一 SPEC，主草稿=本条（唯一超集：双车道＋聚合告警＋WARNING 文案补仓路径）。78ee/d36a 的「无 remote 跳过语义」主旨并入本条。

- 双点位同修：evolution.py:1108 `_commit_todo_marker`（:1106-1122 push 分支）＋ self_review.py:2704 `_commit_todo`（:2700-2717），共用一个 remote 探测助手。**另须纳入 evo-add-todo-append-commit-on-write 新增的 append_todo_line 第三 push 点**（该 SPEC 在共享写函数内新增「尝试 push」且不带预检）——或抽共享 push helper 单点收口，否则修完两处又长第三处。
- 计数口径：主仓 49 条恒败 WARNING（2026-10-05T21:50Z→10-29T17:17Z，fenixd.log 4＋log.3 45，今晨 01:17 仍在）＋ dsh-plugins 侧 16 条（至 10-29T18:01Z）——替代三条各自冻结的 41/46/47。
- open question（验证纪律）：self_review 车道失败在兄弟仓场景 logger sink 静默（component=self_review 计数 0）——修复验证须对第二车道跳过语义取独立可观测证据，不能只看 fenixd.log 归零。
- 非目标（不变）：兄弟仓是否补配 remote 属项目侧治理（dsh-plugins/potplayer-base `git remote -v` 均空），留仓所有者决策；框架侧跳过语义对任意无远程仓鲁棒。
