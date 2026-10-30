"""core.dashboard.data.spec_archive — SPEC 归档/软删除（spec_archive 组）。

refactor-dashboard-data-module D3 分组：本模块承载 SPEC 归档职责域。
软删除、归档、归档检查、state_machine 交互。
"""

import shutil
import time
from pathlib import Path

# 跨组引用（D4：叶子→中枢，直接导入无环——spec_archive 不被中枢反向 import）
from core.timelib import now_local
from core.archive_commit import commit_archive_move

# state 组（叶子组已搬移，直接导入无环）
from .state import parse_state, parse_archived_state

# spec_docs 组（叶子组，模块级仅标准库 import，直接导入无环）：软删除/归档
# 入口的 spec 名防穿越白名单（code-review item 8d9727c5ef7a），与读侧
# resolve_spec_dir/get_spec_doc/parse_tasks 同一单源
from .spec_docs import validated_spec_name

# 共享日志兜底出口（e57bb78b236c：_archive_log 与 runs.py _retention_log 同款逻辑单源）
from ._logutil import fallback_log

# 删除先停后删的等待总上限（add-freeze-stop-inflight-agents 5.3：admin_actions
# 与 spec_archive 共用同一常量；顶层导入使测试可 patch 覆盖窗口时长）
from .admin_actions import SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS  # noqa: F401

# SPEC 终态口径单源（code-review item 6569c5ad7aa8）：archive_spec 的防御性
# 终态校验、backfill_archived_entries 的孤儿判定、auto_archive_check 的阈值
# 统计三处共用，避免内联 ("done", "pushed") 多处漂移。
_TERMINAL_STATUSES = ("done", "pushed")

# 时效归档滞留阈值（evo-spec-changes-archive-drain R2/R3）：目录 mtime 滞留
# ≥ 3 天（72 小时）才满足时效归档；时间基准统一为目录 mtime（目录 mtime 即
# 内容最后变更时刻；STATE `updated` 仅用于 R1 排序，孤儿目录无 STATE 字段）。
STALE_ARCHIVE_AGE_SECONDS = 72 * 3600

# 时效归档判据的验证报告文件名（core/verify_report.py 在验证裁决放行时写盘，
# 可作「已验证」物证；report_gate 把关）。
_VERIFICATION_REPORT_NAME = "verification-report.md"

# R4 每日滞留盘点的 24 小时去重窗口（auto_archive_check 每 300s 调用一次，
# 去重防刷屏；design 决策 5）。
_DAILY_AUDIT_INTERVAL_SECONDS = 24 * 3600

# 每日盘点去重水位（进程内 wall-clock 时间戳；模块级变量便于测试逐用例重置）。
_daily_audit_last_ts = 0.0


def _rollback_nested_archive_move(
    spec_dir: Path, target: Path, moved: Path
) -> tuple[str, Path | None]:
    """TOCTOU 嵌套落位的回滚处置（soft_delete_spec/archive_spec 共用单源）。

    exists 预检与 shutil.move 之间归档目标若被并发创建为目录，move 会把源
    目录嵌套移入其内部（target/<name>/）而非独占落位。处置对齐
    bin/fenix_archive.py::archive_change 的同源逻辑：原位空闲则移回原位完成
    回滚；原位已被并发重建、回滚自身失败或回滚时二次嵌套则放弃回滚，报错
    文案带实际落点供人工核对。不改用 os.rename 独占落位——归档可能跨设备
    （rename 会 EXDEV 失败，bin/ 侧同款裁决）。

    Returns:
        (error_msg, stranded_path)：stranded_path 非 None 表示内容未能回滚至
        原位、滞留在该嵌套路径，调用方记账/展示须以它为实际落点。
    """
    if spec_dir.is_dir():
        # 原位已被并发重建：此时移回会被 shutil.move 嵌套进重建目录内部
        # （层级二次漂移），放弃回滚，报错带实际落点供排障者直接定位。
        return (
            f"归档目标被并发创建: {target} — 原位 {spec_dir} 已被并发重建，"
            f"误移内容保留在 {moved}，请手工核对处置",
            moved,
        )
    try:
        shutil.move(str(moved), str(spec_dir))
    except OSError as e:
        # 回滚移回原位自身失败（原位被占、跨设备复制中断等）时内容仍滞留
        # 嵌套层级，报错带实际落点，与上方并发重建分支口径对齐。
        return (
            f"归档移动失败: {e} — 回滚移回原位失败，误移内容保留在 {moved}，"
            "请手工核对处置",
            moved,
        )
    # 二次 TOCTOU：回滚前 is_dir 检查与移动之间原位若被并发者重建为同名
    # 目录，shutil.move 会把内容静默嵌套移入其内部（spec_dir/<name>/）而不
    # 抛异常，报错须带实际落点（对齐 bin/ 侧同款检查）。
    nested = spec_dir / moved.name
    if nested.exists():
        return (
            f"归档目标被并发创建: {target} — 回滚时原位 {spec_dir} 已被并发"
            f"重建，误移内容嵌套保留在 {nested}，请手工核对处置",
            nested,
        )
    return (
        f"归档移动失败: 目标 {target} 在移动前一刻被并发创建（exists 预检与"
        f"移动之间的竞态窗口），内容已回滚至原位 {spec_dir}",
        None,
    )


def soft_delete_spec(project_root, spec: str, stop_callback=None) -> dict:
    """软删除 SPEC：STATE.md 移除条目 + spec/changes/<name>/ 移入 archive。

    两步任一失败则尽量回滚以保持两端数据一致（第 1 步移动目录失败时 STATE.md
    尚未改动、天然一致；第 2 步剔除 STATE 失败时尽力把已归档目录移回原位），
    由调用方依据返回码处理：
    - 活跃 STATE.md 与归档清单均不含该 spec → {found: False}（幂等，
      不发任何文件操作；add-archive-state-migration D6：found 判定含清单）
    - 运行中保护：扫描 ``.fenix/runs/*.jsonl`` 顶层（活跃目录），用末行
      非终态判定在跑（终态口径 = ``RUN_TERMINAL_EVENT_TYPES`` 并集，含
      frozen-terminated，不复用 ``classify_run``：superseded 不在终态集合内）。
      归属全等匹配（``run_spec_part(p.stem) == spec``）。
      - 有在跑 + stop_callback 为 None → {running: True}（回退既有 409
        拒绝语义，保持既有单测零改动）。
      - 有在跑 + stop_callback 非 None → 调用停止回调并有界等待终态
        （每 run 宽限 10s + 总上限 SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS）；
        超时 → {ok: False, running: True, pending: [...]}（不改 STATE/
        目录）；全部终止 → 继续正常删除。
    - 正常：remove_spec 原子剔除条目；目录若存在则 shutil.move 到
      spec/archive/<name>-<Unix秒>/；目录缺失仅清状态（幂等）。
    - 目录移动失败（OSError）：返回含 ``error``（``归档移动失败: ...``）的
      失败 dict（不裸抛异常）；STATE.md 尚未改动、目录留在原位。
    - STATE 剔除失败（OSError 或其他异常）：STATE 条目尚未删成功时尽力把
      已归档目录移回 ``spec/changes/<name>`` 并返回含 ``error`` 的失败 dict
      （不裸抛异常）；条目已删成功而仅清单小节移除失败时目录保持在 archive
      （与已删条目自洽，重试可完成清单清理），不回滚。回滚亦失败时
      ``archived``/``archive_path`` 保留滞留位置并写入 ``error``。
    - 归档同名冲突（极小概率）：在名字追加微秒后缀重试，直至成功。
    - 预检与移动之间目标被并发创建（TOCTOU，code-review item 48f255c71094）：
      内容回滚至原位并按 ``归档移动失败`` 失败形态返回（STATE.md 未改动）；
      无法回滚时 ``error`` 带实际落点留人工核对，``archived``/``archive_path``
      恒为 False/None（不作为有效归档入库）。

    Returns:
        {"found", "running", "archived": bool, "archive_path": str|null,
         "error": str|null, "pending": list|null, "stopped": int|null}
        仅 ``archived=True`` 的路径（成功 / 部分完成）附加：
        ``committed``（bool，归档自动提交是否成功）；提交失败时另有
        ``commit_warning``（str，告警文案，无告警不带该键）。
    """
    from core.agent_runner.liveness import AGENT_TERMINATE_GRACE_SECONDS
    # SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS 已在模块顶层导入（测试可 patch 覆盖）
    from .admin_actions import running_run_ids_for_spec
    proot = Path(project_root)
    # 防穿越（code-review item 8d9727c5ef7a）：spec 名拼进 spec/changes/<spec>
    # 与 spec/archive/<spec>-<Unix秒>（下方 shutil.move）前先过 kebab-case
    # 白名单——手工编辑的 STATE.md/归档清单若含 ``../`` 形态小节名，归档移动
    # 会把目录落到仓库布局之外。与读侧 resolve_spec_dir/parse_tasks（item
    # 91ba50839948）同口径；非法名按本函数既有「未找到」形态返回（幂等，
    # 不发任何文件操作，调用方 404 / spec not found 语义不变）
    if validated_spec_name(spec) is None:
        return {"found": False}
    # 初始在跑计数（stopped 字段：有在跑 agent 时记录回调前计数，无在跑为 None）
    initial_running_count = 0
    specs = parse_state(proot)
    # found 判定含清单（add-archive-state-migration D6）：条目已迁出（仅清单
    # 有）的已归档 SPEC 同样可软删除，清理动作 = 移除清单小节 + 归档目录移除。
    in_manifest = spec in parse_archived_state(proot)
    if spec not in specs and not in_manifest:
        return {"found": False}

    # ── 运行中保护：末行非终态判定（add-freeze-stop-inflight-agents 4.1/4.2）──
    # 扫描 .fenix/runs/*.jsonl 顶层（活跃目录），用 run_spec_part 全等归属
    # + 末行非终态判定在跑。末行终态 = RUN_TERMINAL_EVENT_TYPES（含本 SPEC
    # 新增的 frozen-terminated），superseded 不在该集合内（原地重试弃置，
    # 其后还有新 attempt 在跑）——classify_run 误判 superseded 为终态会把
    # 活跃 run 当已终态，让删除在 run 仍可能写盘时移走目录。
    running_ids: list = running_run_ids_for_spec(proot, spec)

    if running_ids:
        if stop_callback is None:
            # 回退既有 409 拒绝语义（保持既有单测零改动）
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": "spec 有进行中的运行",
                "pending": None,
                "stopped": None,
            }
        # 有在跑 agent → 经回调请求停止，有界等待终态
        initial_running_count = len(running_ids)
        try:
            stop_callback(running_ids)
        except Exception as e:
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": f"停止回调执行失败: {e}",
                "pending": running_ids,
                "stopped": 0,
            }
        # 有界等待：每 AGENT_TERMINATE_GRACE_SECONDS 轮询一次，总上限。
        # 在跑判定每轮复用 running_run_ids_for_spec（code-review item
        # 4b5e9fa50b3a：与初始判定单源同口径，不内联重写末行终态判定；
        # OSError 容错也由该助手内部承担）
        # 有界等待 deadline 用单调时钟（code-review item d19c607f08ef）：
        # 墙钟可能因 NTP 校时/手工设置回拨，deadline 相对变远会按回拨幅度
        # 拉长请求阻塞窗口；time.monotonic 不受跳变影响，与本仓库其他限时
        # 逻辑（quality_gates 指纹缓存 TTL）同口径
        deadline = time.monotonic() + SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS
        while time.monotonic() < deadline:
            still_running: list = running_run_ids_for_spec(proot, spec)
            if not still_running:
                running_ids = []
                break
            running_ids = still_running
            # sleep 前钳制 remaining（code-review item 02f76ca4add6）：上一轮
            # 扫描 runs 目录可能耗时越过 deadline，time.sleep(负值) 抛
            # ValueError 会破坏本函数「以返回 dict 报错、不裸抛异常」契约
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(AGENT_TERMINATE_GRACE_SECONDS, remaining))
        if running_ids:
            # 循环是「检查→sleep」结构，deadline 到期退出时 running_ids 还是
            # 上一轮快照（code-review item ad478fc32a9f）：run 可能在最后一
            # 次 sleep 期间全部终止，退出后复查一次，仍非空才判超时
            running_ids = running_run_ids_for_spec(proot, spec)
        if running_ids:
            # 超时仍有 run 未终止 → 返回失败，不改 STATE/目录
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": f"等待超时仍有 {len(running_ids)} 个 run 未终止",
                "pending": running_ids,
                # 已终止计数 = 回调前在跑数 - 复查后仍未终止数（code-review
                # item d09db0e81f6a：硬编码 0 与「已停止计数」语义不符）
                # 复查是全量重扫，等待窗口内新派发的 run 可能混入，钳 0
                # 防止负值（code-review item c1a66669c252）
                "stopped": max(0, initial_running_count - len(running_ids)),
            }
        # 全部已终止，继续正常删除流程

    from core.state_machine import StateMachine, project_state_logger

    # 跨进程写入者 MUST 注入真实 logger（fix-state-atomicity-and-selfheal-restart
    # 1.3/D2）：dashboard 与 daemon 是不同进程，无 logger 构造会让
    # remove_spec 的「Removed SPEC」留痕静默丢失。
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))

    # 1. 先移动目录（若失败，STATE.md 尚未改动，天然一致）
    changes_root = proot / "spec" / "changes"
    spec_dir = changes_root / spec
    # archive 与 changes 平级（spec/archive/），不嵌套在 changes/ 下
    archive_root = proot / "spec" / "archive"
    archived = False
    archive_path = None
    if spec_dir.is_dir():
        ts = int(time.time())
        base_name = f"{spec}-{ts}"
        dest = archive_root / base_name
        # 同名冲突：追加微秒后缀重试，避免 shutil.move 覆盖丢失数据
        if dest.exists():
            micros = now_local().strftime("%f")  # SPEC-B 批④收拢（微秒唯一性后缀）
            dest = archive_root / f"{base_name}-{micros}"
            # 极端情况仍冲突，再用递增序号兜底
            n = 1
            while dest.exists():
                dest = archive_root / f"{base_name}-{micros}-{n}"
                n += 1
        try:
            # mkdir 同样收进 try（code-review item 3dbdfe8302c9）：权限不足/
            # 磁盘满等 OSError 一并按「归档移动失败: ...」返回 dict，不裸抛
            archive_root.mkdir(parents=True, exist_ok=True)
            moved = Path(shutil.move(str(spec_dir), str(dest)))
        except OSError as e:
            # 比照 archive_spec（同文件）以返回码告知调用方，不裸抛 OSError：
            # STATE.md 尚未改动、目录留在原位，两端天然一致
            return {
                "found": True,
                "running": False,
                "archived": False,
                "archive_path": None,
                "error": f"归档移动失败: {e}",
                "pending": None,
                "stopped": initial_running_count if initial_running_count else None,
            }
        # 独占落位复核（code-review item 48f255c71094）：exists 探测与 move 之间
        # dest 若被并发创建为目录，shutil.move 会把 spec 目录嵌套移入其内部
        # （dest/<spec>/），archive_path 按外层 dest 记账即与实际内容错位。
        # 回滚处置单源 _rollback_nested_archive_move（对齐 bin/fenix_archive.py::
        # archive_change 同款 TOCTOU 处置，不换 os.rename：归档可能跨设备
        # EXDEV）。本步先于 STATE.md 改动，回滚/滞留后按既有「归档移动失败」
        # 失败形态返回，STATE 未改动、两端天然一致；内容滞留嵌套层时不置
        # archived/archive_path（不作为有效归档入库），实际落点在 error 中留痕。
        if moved != dest:
            error, _stranded = _rollback_nested_archive_move(spec_dir, dest, moved)
            return {
                "found": True,
                "running": False,
                "archived": False,
                "archive_path": None,
                "error": error,
                "pending": None,
                "stopped": initial_running_count if initial_running_count else None,
            }
        archived = True
        archive_path = str(dest)

    # 2. 再原子剔除 STATE.md 条目。remove_spec 契约（core/state_machine.py
    # remove_spec docstring）：删除与目录归档是两次独立系统操作，一致性由
    # 调用方负责——此处剔除失败时目录已移入 archive，MUST 尽力移回原位，
    # 否则 spec 永久卡在「STATE 有条目 + 活跃目录不存在」的不一致态
    # （archive_spec 报「活跃目录已不存在」、auto_archive_check 不再纳入，
    # 只能手工修复），并以返回码而非裸异常告知调用方。
    # 条目仅在清单（已迁出）时 remove_spec 无条目可剔（返回 False 幂等），
    # 改为移除清单小节；双源并存（迁出中间态）时两处都清。
    state_entry_removed = False
    try:
        if spec in specs:
            # 以 remove_spec 真实返回值驱动（code-review item f57d00940d1d）：
            # specs 是 stop_callback 有界等待前的快照，等待期间条目可能已被
            # 并发迁出（如同周期先跑的 backfill_archived_entries），remove_spec
            # 幂等空转返回 False——不得再恒置 True，否则异常路径的半态提示
            # 「STATE.md 条目已删除但归档清单小节未移除」会与事实不符。
            state_entry_removed = sm.remove_spec(spec)
        if in_manifest:
            # 清单小节移除在 .STATE.md.lock 的 flock 内执行（与迁出/回填的
            # 清单写入同锁，避免并发竞态，design D6）
            sm.remove_archived_entry(spec)
    # 非 OSError 异常（STATE.md 解析/flock 等环节，异常面同 auto_archive_check
    # 兜底注释的确认）同样不能裸抛：目录此时可能已移入 archive，STATE 条目
    # 未删成功时尽力回滚目录，再以结构化 error dict 告知调用方（code-review
    # item f9e4288dd75f）
    except Exception as e:
        rollback_err = None
        # 仅在 STATE 条目未删成功时回滚目录（code-review item f7777b34d0fc）：
        # remove_spec 已成功而清单小节移除失败时，把目录移回活跃区会卡进
        # 「STATE 无条目 + 目录在 changes/ + 清单小节残留」的不可收敛半态
        # （引擎按 STATE 派发不触及该 spec，auto_archive_check/backfill 只遍历
        # parse_state 收敛不了，is_spec_archived 因活跃目录存在判 False）；
        # 目录留在 archive 与已删条目、清单旧条目的可见性口径自洽，重试即可
        # 完成清单清理。
        if archived and not state_entry_removed:
            try:
                shutil.move(archive_path, str(spec_dir))
                # 回滚嵌套落位复核（code-review item 4f7878f4ef0f，与
                # _rollback_nested_archive_move 同口径）：回滚窗口内原位若被
                # 并发重建为目录，shutil.move 会把归档目录静默嵌套移入其内部
                # （spec_dir/<归档名>/）且不抛异常——按回滚失败记账并带实际
                # 落点（docstring「回滚亦失败时 archived/archive_path 保留
                # 滞留位置并写入 error」），不按回滚成功清账。
                nested = spec_dir / Path(archive_path).name
                if nested.exists():
                    rollback_err = (
                        "回滚移回原位时原位已被并发重建，归档目录嵌套滞留"
                        "（请手工核对处置）"
                    )
                    archive_path = str(nested)
                else:
                    archived = False
                    archive_path = None
            except Exception as re_:
                rollback_err = str(re_)
        error = f"移除 STATE.md 条目失败: {e}"
        if state_entry_removed and in_manifest:
            # 双源两步非原子的部分完成事实：STATE 条目已删而清单小节残留、
            # 第一步不可回滚，error 明示半态并给出重试自愈路径
            # （code-review item e7d9f9c7e861）
            error += "；STATE.md 条目已删除但归档清单小节未移除，可重试以完成清理"
        if rollback_err is not None:
            error += f"；归档目录回滚失败（滞留于 {archive_path}）: {rollback_err}"
        result = {
            "found": True,
            "running": False,
            "archived": archived,
            "archive_path": archive_path,
            "error": error,
            "pending": None,
            "stopped": initial_running_count if initial_running_count else None,
        }
        # 归档自动提交（code-review item db68f681c1d0）：目录滞留 archive 的部分
        # 完成路径（回滚失败 / STATE 条目已删而清单小节移除失败）同样入库——
        # 错误文案引导的重试只补 STATE/清单清理，届时 spec_dir 已不在 changes/
        # （archived=False），成功路径的 if archived 分支不再触发，首次移动产生
        # 的归档目录将永久未入库。fail-open：提交失败仅追加告警字段，不吞原
        # 错误信息（对齐成功路径与 archive_spec 的提交写法）。
        if archived:
            cr = commit_archive_move(proot, spec, archive_path)
            result["committed"] = cr["committed"]
            if cr["warning"]:
                result["commit_warning"] = cr["warning"]
        return result
    result = {
        "found": True,
        "running": False,
        "archived": archived,
        "archive_path": archive_path,
        "error": None,
        "pending": None,
        # 有在跑 agent 时登记已停止计数（initial_running_count 在回调前记录，
        # 等待循环把 running_ids 置空后仍可引用）；无在跑时为 None
        "stopped": initial_running_count if initial_running_count else None,
    }
    # 归档自动提交：目录确实移动成功才提交（fail-open，见 core/archive_commit.py）
    if archived:
        cr = commit_archive_move(proot, spec, archive_path)
        result["committed"] = cr["committed"]
        if cr["warning"]:
            result["commit_warning"] = cr["warning"]
    return result


def is_spec_archived(
    project_root, spec_name: str, state_entries: dict | None = None,
    archived_entries: dict | None = None,
) -> bool:
    """归档判定：活跃目录 `spec/changes/<name>/` 不存在，且活跃 STATE.md 或
    归档清单 `.fenix/STATE.archive.md` 有该条目（双源合取，D4）。

    state_entries / archived_entries: 调用方已解析的活跃 STATE.md / 归档清单
    快照（与 project_summary(specs=...) 同模式，SummaryIndex 重建链透传；
    code-review item c5e751f5a595——重建期逐 spec 全量重解析双 STATE 文件是
    O(N) 放大）。缺省 None 时内部自行解析，行为与原先一致；任一侧缺省仅
    该侧回退自解析，两侧快照均须各自完整（活跃侧/清单侧，不收合并快照）。

    D1：归档可见性以活跃目录存在性为准——不检测 archive/ 下具体路径
    形态（删除路径命名 `<name>-<Unix秒>` 不同、手动移动命名不可控），也不写
    STATE.md 标志。三条归档路径（界面 API / CLI skill / 手动 mv）产出相同可见性。
    条目已迁出（仅清单有，add-archive-state-migration 3.1）仍判已归档；
    双源均无该条目（从未创建/已软删除/名字拼错）返回 False 而非 True——
    合取校验防未注册名误判已归档（fix 3505adf6b20e）。
    """
    # 先查目录：未归档 spec 短路返回 False，不额外读 STATE.md（性能敏感路径，
    # /api/specs 对全部 spec 逐个调用）；目录缺席再合取双源条目校验
    if (Path(project_root) / "spec" / "changes" / spec_name).is_dir():
        return False
    if state_entries is None:
        state_entries = parse_state(project_root)
    if spec_name in state_entries:
        return True
    if archived_entries is None:
        archived_entries = parse_archived_state(project_root)
    return spec_name in archived_entries


def archive_spec(
    project_root, spec_name: str, archived_by: str = "ui",
    allow_unregistered: bool = False,
) -> dict:
    """归档 SPEC：把 `spec/changes/<name>/` 移到 `spec/archive/YYYY-MM-DD-<name>/`。

    与 `bin/fenix_archive.py::archive_change` 相同的移动逻辑与命名规则
    （D2：不 import 脚本，函数级复用核心逻辑）。归档移动成功后即迁出
    STATE.md 条目至归档清单（add-archive-state-migration D3：归档成功即迁出；
    ``archived_by`` 以本参数区分 ui/auto 两条共用路径），迁出失败降级为
    结果 dict 的 ``evict_warning`` 字段——不回滚目录移动、不改 ok 语义，
    条目留待存量回填下一轮迁出。
    终态校验在 API 层做（仅 done/pushed 可归档），本函数仍做防御性校验，
    供 daemon 自动归档（D4）与手动 API 两条路径复用同一入口。

    Args:
        project_root: 项目根目录。
        spec_name: 要归档的 SPEC 名。
        archived_by: 迁出路径溯源（缺省 ``ui``；daemon 自动归档传 ``auto``，
            孤儿接管传 ``auto-orphan``）。
        allow_unregistered: 孤儿形态入参（evo-spec-changes-archive-drain
            design 决策 6）：True 时跳过 STATE 成员查找与终态防御校验，供
            STATE.md 无条目的孤儿目录归档（R3，配 ``archived_by=auto-orphan``）。
            其余机制全部保留——防穿越白名单、TOCTOU 回滚、runs 产物清理、
            commit_archive_move 自动提交；孤儿无条目可迁出，evict 迁出环节
            跳过，不写 STATE/清单条目（不改 STATE 语义）。孤儿判据（含验证
            报告 + 滞留超期）由调用方承担（见 _archive_aged_specs）。归档
            溯源以成功结果 dict 的 ``archived_by`` 字段与调用方日志为台账
            （孤儿不落清单条目）。

    Returns:
        {"ok": bool, "found": bool, "from": str|null, "to": str|null, "error": str|null}
        - spec 不在 STATE.md → {"ok": False, "found": False, ...}（孤儿形态
          跳过该校验）
        - 非终态 → {"ok": False, "found": True, "error": "仅终态..."}（孤儿
          形态跳过该校验）
        - 活跃目录缺失（已归档）→ {"ok": False, "found": True, "archived_already": True}
        - 目标已存在 → {"ok": False, "found": True, "conflict": True}（不覆盖；
          含预检后并发创建的竞态冲突——能回滚则回滚后报 conflict，无法回滚时
          ``to`` 为内容实际落点、error 带落点留人工核对）
        - 成功 → {"ok": True, "found": True, "from": 原路径, "to": 目标路径,
          "archived_by": <溯源值>}
          附 ``state_evicted``（迁出成功）或 ``evict_warning``（迁出失败降级）；
          孤儿形态无迁出环节，两者均不出现

        结构化标志（archived_already/conflict）供 HTTP 层按标志选状态码，
        与 error 展示文案无耦合。
    """
    proot = Path(project_root)
    # 防穿越（code-review item 8d9727c5ef7a）：spec_name 拼进
    # spec/changes/<name> 与 spec/archive/<date>-<name>（下方 shutil.move）前
    # 先过 kebab-case 白名单，与读侧 resolve_spec_dir/get_spec_doc 同口径
    # （读侧 code-review item 91ba50839948 已确立，写侧对齐）；非法名按本函数
    # 既有「未找到」形态返回——HTTP 层 found=False → 404，daemon 自动归档路径
    # 按 error 跳过并记日志，不引入新返回形态。孤儿形态同样不豁免白名单
    # （design 决策 6：防穿越白名单保留）。
    if validated_spec_name(spec_name) is None:
        return {
            "ok": False,
            "found": False,
            "from": None,
            "to": None,
            "error": f"spec not found: {spec_name}",
        }
    specs = parse_state(proot)
    if not allow_unregistered:
        if spec_name not in specs:
            return {
                "ok": False,
                "found": False,
                "from": None,
                "to": None,
                "error": f"spec not found: {spec_name}",
            }
        status = specs[spec_name].get("status")
        if status not in _TERMINAL_STATUSES:
            return {
                "ok": False,
                "found": True,
                "from": None,
                "to": None,
                "error": f"仅终态 spec（done/pushed）可归档，当前状态: {status}",
            }
    # 孤儿形态（allow_unregistered=True）：跳过上方成员查找与终态防御校验
    # （design 决策 6）——孤儿目录无 STATE 条目可查、无状态可校验，归档判据
    # 由调用方（_archive_aged_specs 的 R3 分流）承担。

    change_dir = proot / "spec" / "changes" / spec_name
    if not change_dir.is_dir():
        return {
            "ok": False,
            "found": True,
            "from": None,
            "to": None,
            "archived_already": True,
            "error": f"Spec '{spec_name}' 活跃目录已不存在（可能已归档）",
        }

    from datetime import date

    target = proot / "spec" / "archive" / f"{date.today().isoformat()}-{spec_name}"
    if target.exists():
        return {
            "ok": False,
            "found": True,
            "from": str(change_dir),
            "to": str(target),
            "conflict": True,
            "error": f"归档目标已存在: {target} — 请改名或改日再归档，原目录不会被覆盖",
        }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        moved = Path(shutil.move(str(change_dir), str(target)))
    except OSError as e:
        return {
            "ok": False,
            "found": True,
            "from": str(change_dir),
            "to": str(target),
            "error": f"归档移动失败: {e}",
        }
    # 独占落位复核（code-review item 48f255c71094）：exists 预检与 move 之间
    # target 若被并发创建为目录，shutil.move 会把 change 目录嵌套移入其内部
    # （target/<name>/）。回滚处置单源 _rollback_nested_archive_move（对齐
    # bin/fenix_archive.py::archive_change 同源逻辑，不换 os.rename：归档可能
    # 跨设备 EXDEV），按既有 conflict 形态返回；内容滞留嵌套层时 to 记实际
    # 落点，防止 to 记外层路径与实际内容错位。
    if moved != target:
        error, stranded = _rollback_nested_archive_move(change_dir, target, moved)
        return {
            "ok": False,
            "found": True,
            "from": str(change_dir),
            "to": str(stranded) if stranded is not None else str(target),
            "conflict": True,
            "error": error,
        }
    result = {"ok": True, "found": True, "from": str(change_dir), "to": str(moved), "error": None}
    # 归档台账溯源：archived_by 随成功结果带回（daemon 自动归档与孤儿接管的
    # 溯源单点）。孤儿形态不写 STATE/清单条目（design 决策 6），其「台账」
    # 即本字段 + 调用方 _archive_log 的 info 留痕。
    result["archived_by"] = archived_by
    # 归档成功即迁出（add-archive-state-migration D3）：目录已移入 archive/，
    # 立即把 STATE.md 条目迁出至归档清单。迁出失败降级为 evict_warning——
    # 不回滚目录移动、不改 ok 语义；条目留在 STATE.md 等待存量回填下一轮迁出。
    # 孤儿形态（allow_unregistered=True）无条目可迁出：跳过 evict 环节，
    # 不写 STATE/清单条目（design 决策 6）。
    if not allow_unregistered:
        from core.state_machine import StateMachine, project_state_logger

        try:
            sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
            ev = sm.evict_spec(spec_name, archived_by=archived_by)
            if ev.get("ok"):
                result["state_evicted"] = True
            else:
                result["evict_warning"] = ev.get("error")
        except Exception as e:  # noqa: BLE001 fail-open：move 已成功，迁出异常只降级为告警
            result["evict_warning"] = str(e)
    # remove-auto-run-cleanup：run 产物清理的唯一入口 = SPEC 归档。change 目录
    # 移动成功后，清理 .fenix/runs/ 中属于该 spec 的产物（fix-run-cleanup-
    # attach-spec-archive D1：顶层与 archive/ 归档副本一并删除，不再移档）。
    # 与 bin/fenix_archive.py::archive_change 同源同步——本函数是
    # daemon 自动归档（auto_archive_check）与 Dashboard 界面归档
    # （POST /api/spec-archive）共用的入口，此前漏挂此步，SPEC 归档后 run 产物
    # 永久滞留 runs 顶层（实证：138 个已归档 SPEC 中 127 个的产物仍在顶层）。
    # fail-open：runs 清理失败仅在返回 dict 追加告警字段，不阻断 change 归档主流程。
    # D8：经门面延迟解析（tests 以 patch.object(dash_data, "archive_spec_runs") 替换）
    import core.dashboard.data as _facade

    # 容错口径与上方 evict 环节一致，放宽为 Exception（code-review item
    # ae9ada1e41dd）：此刻目录已移动、STATE 条目已迁出，archive_spec_runs 抛
    # 非 OSError 一路上抛会让调用方拿到异常与半完成态，违背 fail-open 承诺。
    try:
        result["runs_archived"] = _facade.archive_spec_runs(proot / ".fenix" / "runs", spec_name)
    except Exception as e:  # noqa: BLE001 fail-open：runs 清理失败只降级为告警
        result["runs_archive_warning"] = str(e)
    # 归档自动提交：移动成功立即入库（fail-open，见 core/archive_commit.py）
    cr = commit_archive_move(proot, spec_name, moved)
    result["committed"] = cr["committed"]
    if cr["warning"]:
        result["commit_warning"] = cr["warning"]
    return result


def _archive_log(logger, level: str, msg: str):
    """auto_archive_check/backfill 共用的日志出口（单源：_logutil.fallback_log）。"""
    fallback_log(logger, level, msg)


def backfill_archived_entries(project_root, logger=None) -> dict:
    """幂等存量回填（add-archive-state-migration D5）：把「已归档但条目未迁出」
    的存量条目批量迁出至归档清单。

    扫描活跃 STATE.md 中「终态 + 活跃目录 `spec/changes/<name>/` 已不存在」
    的条目，逐个 ``evict_spec(name, "backfill")``。单条失败跳过并记日志，
    不中断回填；非终态孤儿条目（活跃目录缺失的异常态）不迁出，记日志留
    人工排查。回填可安全重复执行——已迁出条目自然不在扫描集内。

    调用点挂在 ``auto_archive_check`` 的同一周期触发处（先回填后阈值归档），
    但不受 ``archive.auto_threshold`` 开关约束（阈值 0 仍回填）。

    Args:
        project_root: 项目根目录。
        logger: Logger 实例（可选；缺省 print 到 stderr）。

    Returns:
        {"scanned": int, "evicted": int, "skipped": int, "nonterminal_skipped": int}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    changes_root = proot / "spec" / "changes"
    orphans = [n for n, e in specs.items() if not (changes_root / n).is_dir()]
    if not orphans:
        return {"scanned": 0, "evicted": 0, "skipped": 0, "nonterminal_skipped": 0}

    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    evicted = skipped = nonterminal = 0
    for name in orphans:
        if specs[name].get("status") not in _TERMINAL_STATUSES:
            nonterminal += 1
            _archive_log(
                logger,
                "warning",
                f"存量回填跳过非终态孤儿条目（活跃目录缺失，留人工排查）: {name}",
            )
            continue
        try:
            r = sm.evict_spec(name, archived_by="backfill")
        except Exception as e:  # noqa: BLE001 单条失败不中断回填
            skipped += 1
            _archive_log(logger, "warning", f"存量回填迁出异常，跳过: {name}: {e}")
            continue
        if r.get("ok"):
            evicted += 1
            _archive_log(logger, "info", f"存量回填迁出: {name}（archived_by=backfill）")
        else:
            skipped += 1
            _archive_log(
                logger, "warning", f"存量回填迁出未成功，跳过: {name}: {r.get('error')}"
            )
    return {
        "scanned": len(orphans),
        "evicted": evicted,
        "skipped": skipped,
        "nonterminal_skipped": nonterminal,
    }


def _archive_aged_specs(project_root, logger=None) -> dict:
    """时效归档与孤儿接管（evo-spec-changes-archive-drain R2/R3）。

    扫描 ``spec/changes/`` 活跃目录，满足「目录含 verification-report.md +
    目录 mtime 滞留 ≥ 3 天（72 小时）」的目录自动归档，独立于
    ``archive.auto_threshold``（阈值是活跃区期望水位，时效规则是确定性收尾，
    design 决策 2）：

    - STATE 终态条目 + 判据成立 → 经既有 archive_spec 归档
      （archived_by=auto，迁出 STATE 条目至归档清单）；
    - STATE 无条目的孤儿目录 + 判据成立 → 经孤儿形态入参归档
      （allow_unregistered=True，archived_by=auto-orphan，不写 STATE/清单
      条目，design 决策 6）；
    - 非终态活跃在途目录永不归档（R5）；其余目录不动作（仅每日盘点暴露，
      见 _daily_stale_audit）。

    Args:
        project_root: 项目根目录。
        logger: Logger 实例（可选，用于记录归档动作）。

    Returns:
        {"age_archived": int, "orphan_archived": int, "skipped": int}
    """
    proot = Path(project_root)
    changes_root = proot / "spec" / "changes"
    if not changes_root.is_dir():
        return {"age_archived": 0, "orphan_archived": 0, "skipped": 0}
    specs = parse_state(proot)
    now = time.time()
    age_archived = orphan_archived = skipped = 0
    for child in sorted(changes_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        # 防穿越同口径预筛：白名单外的目录名不进入自动归档（archive_spec
        # 入口校验同样会拒，提前跳过免无谓解析与日志噪声）。
        if validated_spec_name(name) is None:
            continue
        try:
            has_report = (child / _VERIFICATION_REPORT_NAME).is_file()
            aged = (now - child.stat().st_mtime) >= STALE_ARCHIVE_AGE_SECONDS
        except OSError:
            continue  # 目录并发消失/不可读：本轮跳过，下轮再看
        if not (has_report and aged):
            continue
        registered = name in specs
        if registered and specs[name].get("status") not in _TERMINAL_STATUSES:
            continue  # R5：非终态活跃在途目录永不归档
        archived_by = "auto" if registered else "auto-orphan"
        # archive_spec 内部仅捕获 OSError；其余异常兜底转失败 dict，单条
        # 失败跳过并记日志，不中断本轮（与 R1 排水循环同口径）。
        try:
            result = archive_spec(
                proot, name, archived_by=archived_by,
                allow_unregistered=not registered,
            )
        except Exception as e:  # noqa: BLE001
            result = {
                "ok": False,
                "found": True,
                "from": None,
                "to": None,
                "error": f"归档异常: {e}",
            }
        if result.get("ok"):
            if registered:
                age_archived += 1
            else:
                orphan_archived += 1
            msg = f"时效自动归档({archived_by}): {name} → {result.get('to')}"
            if result.get("evict_warning"):
                msg += f"（迁出告警，条目留待回填: {result['evict_warning']}）"
            _archive_log(logger, "info", msg)
        else:
            skipped += 1
            _archive_log(
                logger, "warning", f"时效自动归档跳过 {name}: {result.get('error')}"
            )
    return {
        "age_archived": age_archived,
        "orphan_archived": orphan_archived,
        "skipped": skipped,
    }


def _scan_stale_dirs(proot: Path) -> list:
    """R4 盘点扫描（只读）：返回 [(目录名, [类别标记...])]，按目录名排序。

    类别口径（evo-spec-changes-archive-drain R4）：
    - ① 含 verification-report.md 且滞留 ≥ 3 天（目录 mtime，同 R2 判据）；
    - ② STATE 无条目的孤儿目录（无条件列示，满足 R3 条件者归档后自然移出）；
    - ③ STATE 终态但无 verification-report.md 的目录。
    """
    changes_root = proot / "spec" / "changes"
    if not changes_root.is_dir():
        return []
    specs = parse_state(proot)
    now = time.time()
    flagged: dict = {}
    for child in sorted(changes_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        try:
            has_report = (child / _VERIFICATION_REPORT_NAME).is_file()
            aged = (now - child.stat().st_mtime) >= STALE_ARCHIVE_AGE_SECONDS
        except OSError:
            continue
        whys: list = []
        if has_report and aged:
            whys.append("①报告+滞留≥3天")
        if name not in specs:
            whys.append("②孤儿目录")
        elif specs[name].get("status") in _TERMINAL_STATUSES and not has_report:
            whys.append("③终态无报告")
        if whys:
            flagged[name] = whys
    return sorted(flagged.items())


def _daily_stale_audit(proot: Path, logger=None) -> dict:
    """R4 每日滞留盘点（24 小时去重，design 决策 5）。

    changes/ 存在滞留目录（_scan_stale_dirs 三类口径任一命中）时，列清单发
    **一条** INFO 信号（复用 _archive_log 出口）；24 小时内不重复发送，防
    300 秒周期刷盘。纯信号零动作，不受 ``archive.auto_threshold`` 开关约束
    （threshold=0 时仍执行，作为新形态滞留的兜底可观测）。

    Returns:
        {"fired": bool, "stale_dirs": [目录名...]}——fired=False 表示本轮在
        24h 去重窗口内未触发盘点。
    """
    global _daily_audit_last_ts
    now = time.time()
    if now - _daily_audit_last_ts < _DAILY_AUDIT_INTERVAL_SECONDS:
        return {"fired": False, "stale_dirs": []}
    _daily_audit_last_ts = now
    flagged = _scan_stale_dirs(proot)
    if flagged:
        parts = [f"{name}（{'+'.join(whys)}）" for name, whys in flagged]
        _archive_log(
            logger, "info",
            "每日滞留盘点: spec/changes/ 滞留目录 " + "、".join(parts),
        )
    return {"fired": True, "stale_dirs": [name for name, _ in flagged]}


def auto_archive_check(project_root, config: dict, logger=None) -> dict:
    """daemon 周期自动归档检查（D4 + evo-spec-changes-archive-drain R1-R4）。

    主循环每 300s 调用一次，单轮内依次执行：

    1. 存量回填（先回填后归档，D5；不受 auto_threshold 开关约束）；
    2. **R1 阈值排水**：终态未归档计数 **>=** ``archive.auto_threshold`` 即
       触发（evo-spec-changes-archive-drain R1：触发由「>」改为「>=」，消除
       饱和点计数恰等于阈值时的恒不触发冻结），按 STATE.md ``updated`` 升序
       持续归档可归档条目（最久完成的先；不以 verification-report.md 为
       前置——否则无报告终态残留会让排水循环无法收敛），直至终态目录计数
       **低于**阈值。单条失败（目标已存在等）跳过并记日志、不中断循环；
       失败条目不减少计数，循环遍历全部候选、达标即止。
    3. **R2/R3 时效归档**（_archive_aged_specs）：终态+含验证报告+目录 mtime
       滞留 ≥ 3 天的目录归档（archived_by=auto）；孤儿目录同判据经孤儿形态
       入参归档（archived_by=auto-orphan）——独立于阈值，threshold=0 时一并
       禁用（design 决策 2：auto_threshold=0 禁用 R1/R2/R3 全部自动归档动作）。
    4. **R4 每日滞留盘点**（_daily_stale_audit）：24 小时去重，changes/ 存在
       滞留目录（①报告+滞留≥3天 / ②孤儿 / ③终态无报告）时发一条 INFO——
       纯信号零动作，不受 threshold 约束。

    Args:
        project_root: 项目根目录
        config: 有效配置 dict（由 ConfigLoader.resolve_config 解析）
        logger: Logger 实例（可选，用于记录归档动作；缺省 print 到 stderr）

    Returns:
        {"archived": int, "skipped": int, "target_count": int,
         "threshold": int, "total_terminal_unarchived": int, "backfill": dict,
         "age_archived": int, "orphan_archived": int, "age_skipped": int,
         "audit": dict}
        archived/skipped 为 R1 排水计数；target_count 为本轮排水拟归档数 =
        max(total_terminal_unarchived - threshold + 1, 0)（排水至低于阈值；
        threshold<=0 阈值归档关闭，target_count 恒 0）；
        total_terminal_unarchived 恒为回填后终态未归档真实总数，阈值关闭时
        仍照常统计（code-review item 1045349ad1a8）；
        backfill 为本轮存量回填计数（add-archive-state-migration 4.2）；
        age_archived/orphan_archived/age_skipped 为 R2/R3 时效归档计数；
        audit 为 R4 盘点结果 {"fired": bool, "stale_dirs": [...]}。
    """
    from core.config import ConfigLoader

    # 先回填后阈值归档（D5）：存量「终态 + 目录已归档」条目迁出不受
    # auto_threshold 开关约束，阈值 0 仍执行。
    backfill = backfill_archived_entries(project_root, logger)

    threshold = ConfigLoader.effective_auto_archive_threshold(config)

    proot = Path(project_root)
    # 回填后重读活跃 STATE：刚迁出的条目不再进入本轮阈值统计
    specs = parse_state(proot)

    # 统计终态 + 未归档（活跃目录仍存在）。阈值关闭（<=0）时同样先完成统计：
    # total_terminal_unarchived 契约为终态未归档总数，报 0 会让基于该字段的
    # 监控/日志误判无积压（code-review item 1045349ad1a8）
    candidates = []
    for name, entry in specs.items():
        if entry.get("status") not in _TERMINAL_STATUSES:
            continue
        if not (proot / "spec" / "changes" / name).is_dir():
            continue  # 已归档，不计入
        candidates.append((name, entry))

    total = len(candidates)

    # ── R1 阈值排水（evo-spec-changes-archive-drain）────────────────────
    # 触发条件由「total > threshold」改为「total >= threshold」：阈值是活跃区
    # 期望水位，计数到达水位即排水——单轮按 updated 升序持续归档可归档条目，
    # 直至终态目录计数低于阈值（需成功归档 total - threshold + 1 条；饱和点
    # 计数恰等于阈值时单轮只腾挪 1 条，积压主体的清空靠 R2 时效归档在同周期
    # 完成，design 决策 1）。threshold=0 仍为禁用（语义不变）。
    archived_count = 0
    skipped_count = 0
    target_count = 0
    if threshold > 0 and total >= threshold:
        # 按 updated 升序（最久完成的先归档）；缺 updated 归队尾——哨兵取
        # "9999-12-31"（updated 为 ISO 8601 字符串，字典序必小于该哨兵；空串最小
        # 会排到队头、抢在最久完成的 spec 之前被归档，code-review item
        # 411679cf624d）。
        def _sort_key(item):
            return item[1].get("updated") or "9999-12-31"

        candidates.sort(key=_sort_key)
        target_count = total - threshold + 1
        for name, _entry in candidates:
            # 达标即止：终态目录计数已低于阈值。目标已存在等单条失败跳过并
            # 记日志（失败不减少计数，由后续候选让位补位，排水目标仍尽力
            # 收敛）；archive_spec 内部仅捕获 OSError，其余异常兜底转既有
            # error dict 形态走统一 skip 日志路径（code-review item
            # 7b8b81ef3a8e）。
            if archived_count >= target_count:
                break
            try:
                result = archive_spec(proot, name, archived_by="auto")
            except Exception as e:
                result = {
                    "ok": False,
                    "found": True,
                    "from": None,
                    "to": None,
                    "error": f"归档异常: {e}",
                }
            if result.get("ok"):
                archived_count += 1
                msg = f"自动归档: {name} → {result['to']}"
                if result.get("evict_warning"):
                    msg += f"（迁出告警，条目留待回填: {result['evict_warning']}）"
                _archive_log(logger, "info", msg)
            else:
                skipped_count += 1
                msg = f"自动归档跳过 {name}: {result.get('error')}"
                if result.get("evict_warning"):
                    msg += f"（迁出告警: {result['evict_warning']}）"
                _archive_log(logger, "warning", msg)

    # ── R2/R3 时效归档与孤儿接管（独立于阈值；threshold=0 禁用，design 决策 2）
    if threshold > 0:
        aged = _archive_aged_specs(proot, logger)
    else:
        aged = {"age_archived": 0, "orphan_archived": 0, "skipped": 0}

    # ── R4 每日滞留盘点（24h 去重，纯信号，不受 threshold 约束）──────────
    audit = _daily_stale_audit(proot, logger)

    return {
        "archived": archived_count,
        "skipped": skipped_count,
        "target_count": target_count,
        "threshold": threshold,
        "total_terminal_unarchived": total,
        "backfill": backfill,
        "age_archived": aged["age_archived"],
        "orphan_archived": aged["orphan_archived"],
        "age_skipped": aged["skipped"],
        "audit": audit,
    }
