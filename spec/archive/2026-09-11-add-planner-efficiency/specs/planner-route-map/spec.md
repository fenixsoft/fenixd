# planner-route-map — 路由地图生成协议与 prompt 注入

## ADDED Requirements

### Requirement: 地图生成时机与来源

框架 SHALL 在验证管线进入阶段1（planner 出题）之前、impl worktree 就绪之后，对 **impl worktree**（非主树）执行项目声明的生成器（`bin/gen-route-map.py`，项目内文件），产物写入 `<worktree>/.fenix/route-map.md`。地图 MUST 覆盖 impl 分支上新增的路由/入口（spec 待验证的新能力入口不得缺席）。

#### Scenario: 生成器存在时 planner 前生成地图

- **WHEN** 项目根存在 `bin/gen-route-map.py` 且验证管线进入阶段1（impl worktree 已就绪）
- **THEN** 生成器以 impl worktree 为根执行，`<worktree>/.fenix/route-map.md` 在 planner prompt 组装前存在；地图包含 impl 分支新增的路由条目（含 `文件:行号` 出处）

#### Scenario: 新增入口必须可见

- **WHEN** impl 分支相对 main 新增了页面/端点（spec 交付物）
- **THEN** 生成的地图包含该新增入口条目——地图来源是 impl worktree 而非主树

### Requirement: HEAD 键控复用

地图 SHALL 以 worktree HEAD 为复用键：HEAD 未变的重入（replan 循环、重验）复用已生成地图不重复执行生成器；HEAD 变更（re-dispatch 带来新提交）SHALL 重新生成。

#### Scenario: replan 循环不重复生成

- **WHEN** 同一 verify 轮内场景验收失败触发 replan（worktree HEAD 未变）
- **THEN** 第二次进入阶段1 时复用已有地图，生成器未再次执行

#### Scenario: HEAD 变更后重生成

- **WHEN** planner 失败 → implementer 重派新增提交 → 重新进入阶段1（worktree HEAD 已变）
- **THEN** 生成器重新执行，地图反映新 HEAD

### Requirement: prompt 注入措辞为「索引非穷尽」

地图存在时，planner prompt SHALL 注入其内容（经既有 `_project_extra_section` 机制），且措辞 MUST 声明其为「**已知入口索引、非穷尽清单**」：spec 涉及但地图未覆盖的入口，planner 仍 MUST 自行源码取证。地图条目自带 `文件:行号` 出处（沿用现行审计要求）。

#### Scenario: 注入后保留独立取证许可证

- **WHEN** 地图注入 prompt 且 spec 交付物涉及某入口
- **THEN** prompt 文本明确 planner 对地图外/存疑路径仍有 grep 取证义务；场景 navigate 出处标注要求不变

### Requirement: fail-open——地图是加速器非依赖

生成器缺失、执行失败或超时 SHALL NOT 阻塞验证管线：记 warning 后按无地图继续（planner 逐轮 grep 现状）。生成器单次执行 SHALL 有超时上限（缺省 60s）。

#### Scenario: 无生成器回退现状

- **WHEN** 项目未声明 `bin/gen-route-map.py`
- **THEN** 不生成地图、不注入段落，planner 按现行 prompt 工作（存量项目零迁移）

#### Scenario: 生成器失败不阻塞

- **WHEN** 生成器执行非零退出或超时
- **THEN** 记 warning（含 stderr 摘要），验证管线继续，无地图注入

### Requirement: 静态地图兼容

项目无生成器但人工提交了 `.fenix/route-map.md`（主树）时，框架 SHALL 注入该静态地图（新鲜度责任在项目）。优先级：worktree 生成地图 > 主树静态地图 > 无。

#### Scenario: 静态地图被注入

- **WHEN** 主树存在 `.fenix/route-map.md` 且无生成器（或生成器失败）
- **THEN** 静态地图内容注入 planner prompt，措辞同样为索引非穷尽

### Requirement: 生成器自检

生成器 SHOULD 内置自检：用宽 grep 启发式统计路由候选总数，与解析产出条目数差异超阈值时在输出中报告 warning（防解析模式漏配——地图缺条目时 planner 依赖措辞兜底）。dashboard 参考实现 MUST 含此自检。

#### Scenario: 覆盖差异告警

- **WHEN** 生成器启发式计数显著高于解析条目数（如差 ≥30%）
- **THEN** 生成器输出含覆盖差异 warning（不阻塞，地图照常产出）
