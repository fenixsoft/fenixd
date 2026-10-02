# planner 路由地图（planner-route-map）

<!-- knowledge: capability=planner-route-map rev=1
     sources=spec/archive/2026-09-11-add-planner-efficiency -->

planner 出题前的入口索引注入机制：把逐轮 grep 源码取证压缩为读一份带出处的路由索引。

## 规则

- 验证管线进入阶段1（planner 出题）之前、impl worktree 就绪之后，对 **impl worktree**（非主树）执行项目声明的生成器 `bin/gen-route-map.py`（项目内文件），产物写入 `<worktree>/.fenix/route-map.md`。
- 地图必须覆盖 impl 分支上新增的路由/入口——spec 待验证的新能力入口不得缺席；条目自带 `文件:行号` 出处。
- HEAD 键控复用：worktree HEAD 未变的重入（replan 循环、重验）复用已生成地图，不重复执行生成器；HEAD 变更（re-dispatch 带来新提交）须重新生成。
- prompt 注入：地图存在时注入 planner prompt（经 `_project_extra_section` 机制），措辞必须声明其为「**已知入口索引、非穷尽清单**」——spec 涉及但地图未覆盖的入口，planner 仍须自行源码取证；场景 navigate 出处标注要求照常生效。
- fail-open——地图是加速器非依赖：生成器缺失、执行失败或超时不阻塞验证管线，记 warning（含 stderr 摘要）后按无地图继续；生成器单次执行有超时上限（缺省 60s）。项目未声明生成器时不生成、不注入，planner 按现行 prompt 工作。
- 静态地图兼容：项目无生成器但人工提交了主树 `.fenix/route-map.md` 时，注入该静态地图（新鲜度责任在项目），措辞同样为索引非穷尽。优先级：worktree 生成地图 > 主树静态地图 > 无。
- 生成器自检：用宽 grep 启发式统计路由候选总数，与解析产出条目数差异超阈值（如 ≥30%）时在输出中报告覆盖差异 warning（不阻塞，地图照常产出）；dashboard 参考实现必须含此自检。

## 溯源

- 2026-09-11 2026-09-11-add-planner-efficiency（spec/archive/2026-09-11-add-planner-efficiency） — 新增路由地图生成协议（impl worktree 为源、HEAD 键控复用、fail-open、静态地图兼容、生成器自检）与 prompt 注入「索引非穷尽」措辞契约。
