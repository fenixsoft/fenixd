"""core.dashboard.data.runs — 运行记录（.fenix/runs/）（runs 组）。

refactor-dashboard-data-module D3 分组：本模块承载 run 记录/事件/成本职责域。
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# run 产物 agent 类型推断（原 data.py 顶层导入，随 runs 组迁移）
from core.timelib import from_epoch
from core.agent_runner.run_files import (
    infer_run_agent_type,
    run_spec_part,
)

# 共享日志兜底出口（e57bb78b236c：_retention_log 与 spec_archive.py _archive_log 同款逻辑单源）
from core.dashboard.data._logutil import fallback_log

# ── 结构化 run 指标日志索引（fix-observability-gaps 1.5 消费点）────────────
# run 收尾在 fenixd.log 写一条 metric_type=run_metrics 的结构化指标（runner.py
# _log_run_metrics），含 duration_seconds / cost_usd / terminal / provider。
# 读侧 duration 推算优先消费该指标（替代「由 run 文件 mtime 推算耗时」，
# spec「MUST NOT 仅依赖 mtime」）；无指标（旧日志/未触发）才回退 mtime。
# 索引按 log_path 分槽（{log_path: {"key": (size, 首块指纹), "index": …}}）：
# dashboard HTTP 服务单进程多项目（路由按 project 参数定位项目根），前端交替
# 轮询多个项目时各槽保留各自的增量扫描起点，互不驱逐。每槽内按 (size, 首块
# 指纹) 键增量维护：日志 append-only，size 增长只补扫新增块；size 缩小（轮转）
# 或首块指纹不符（轮转后新内容在下一次调用前快速回涨到不小于旧 size，仅凭
# size 判不出轮转）仅重建本槽。进程内缓存，读侧高频重复调用零重扫。
# 并发口径（与 _RUN_META_CACHE 的「并发双算无害」不同）：本索引的增量落账/
# 轮转重建/超限淘汰是非幂等读改写（del/原地清空/推进 key），而 dashboard 是
# ThreadingHTTPServer 多线程（server.py 上限 64），并发双算有害——竞态 del 同一
# run_id 抛 KeyError 致 runs 接口 500；在途扫描写进被替换的孤儿 dict 丢指标。
# 读改写段以 _RUN_METRIC_INDEX_LOCK 串行化（锁内纯内存操作，日志扫描 IO 在锁外）。
_RUN_METRIC_INDEX: dict = {}
_RUN_METRIC_INDEX_LOCK = threading.Lock()
# 容量上限（同 _RUN_META_CACHE 口径）：索引只增不清（除轮转本槽重建），长驻
# daemon 历史 run 数以万计时内存无界增长。超限按最旧淘汰——整体清空不可取：
# 增量扫描起点停在旧 size，清空后旧段不会重扫，近期 run 指标会整批丢失直至
# 下次轮转；各槽合计超限按槽序 + 槽内插入序（=日志出现序）裁掉最旧 run_id。
_RUN_METRIC_INDEX_MAX = 16384


def _strip_run_attempt_suffix(run_id: str) -> str:
    """run 产物 stem → 基础 run_id（剥 -a<n>/ -r<n> attempt/瞬断重试后缀）。

    指标日志的 run_id 记基础 run_id（一次 run = 逻辑整体，含多 attempt），
    产物文件按 attempt 分文件（-a<n>）且瞬断原地重试有 -r<n> 子文件——
    消费侧把产物 stem 归一到基础 id 才能在指标索引中命中。
    """
    if not run_id:
        return run_id
    # 先剥 -r<n>（原地重试子产物后缀），再剥 -a<n>（attempt 后缀）：-r<n> 可能
    # 挂在 -a<n> 之后（-a1-r1），若先剥 -a 则命中不了行尾，只能靠后续 -r 剥成
    # -a1 而漏掉 attempt 后缀——顺序不可对调
    stripped = re.sub(r"-r\d+$", "", run_id)
    stripped = re.sub(r"-a\d+$", "", stripped)
    if stripped != run_id:
        # -r<n> 可能出现在 -a<n> 之后（-a1-r1）：剥完再剥一次 -r
        stripped = re.sub(r"-r\d+$", "", stripped)
    return stripped or run_id


def _parse_run_metric_stream(f) -> dict:
    """日志文件流 → {run_id: context_dict}（run_metrics 指标行提取）。

    供主日志与轮转日志两处索引复用；解析口径与防护见 _load_run_metric_index。
    """
    index: dict = {}
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # 6fd55ebbc869: 合法 JSON 非 object 行（裸数字/字符串/数组/null）
        # 在此跳过，否则 entry.get 抛 AttributeError 穿透外层 OSError-only
        # except，致运行列表接口 500（与 classify_run 防护口径一致）
        if not isinstance(entry, dict):
            continue
        ctx = entry.get("context") or {}
        if not isinstance(ctx, dict) or ctx.get("metric_type") != "run_metrics":
            continue
        rid = ctx.get("run_id")
        # c3bef177adc7: run_id 为不可哈希类型（合法 JSON 但半损坏行）时
        # index[rid] 抛 TypeError 穿透段 2 OSError-only except 致接口 500——
        # 非 str 降级跳过，与 6fd55ebbc869 非 object 行跳过口径对齐。
        if isinstance(rid, str) and rid:
            # 同 run_id 多行按 run_id 合并而非整体覆盖（2026-10-14 事故根因）：
            # dsh run 收尾连写两条 run_metrics 形态行——先终态指标行（含
            # harness/duration，add-harness-brand-projection 2.1），紧随
            # usage_source 附加行（add-dsh-adapter-integration 4.2/4.3，仅
            # 三键）。整体覆盖会把富终态行替换成裸附加行：harness 双丢回退
            # claude（全部 dsh run 显示 Claude 品牌）、duration 静默回退
            # mtime 推算。合并语义下附加行只补键；同名字段后行刷新（重试
            # 链多条终态行时新终态值仍胜出）。
            prev = index.get(rid)
            index[rid] = {**prev, **ctx} if prev else ctx
    return index


def _log_head_fingerprint(log_path: Path, chunk: int = 512) -> str:
    """日志首块内容指纹（md5 前 8 位）——轮转探测键成分。

    仅凭 size 缩小判轮转有个盲区：轮转后新内容在下一次调用前回涨到不小于
    旧 size（繁忙 daemon 有可能），增量 seek(旧 offset) 会落在新内容任意
    字节处，起点附近指标行被静默漏采、索引混入旧文件残留。首块指纹不符
    即视为轮转，整体重建。
    """
    try:
        with log_path.open("rb") as f:
            head = f.read(chunk)
    except OSError:
        return ""
    return hashlib.md5(head).hexdigest()[:8]


def _load_run_metric_index(project_root: Path) -> dict:
    """增量维护 run 指标索引 {base_run_id: metric_dict}（进程内缓存，按 log_path 分槽）。

    metric_dict 取日志行的 context（含 duration_seconds/cost_usd/terminal/
    provider 等），run_id 为 context.run_id（基础 run id）。日志轮转
    （size 缩小，或首块指纹不符的轮转后快速回涨形态）时仅本槽整体重建，追加
    （size 增长且指纹不变）只补扫新增部分。各槽合计超
    _RUN_METRIC_INDEX_MAX 按最旧淘汰（防长驻进程无界增长）。扫描中途读
    失败不推进 key（下轮从旧 offset 重扫同一区间，重扫幂等）。

    并发：读改写段（定槽/重建清空/合并推进/超限淘汰）经 _RUN_METRIC_INDEX_LOCK
    串行化，日志扫描 IO 在锁外（锁内只做内存操作）。

    返回值是槽内活索引 dict（非副本）：后续调用的超限淘汰会原地删改其中
    条目，调用方仅限同步读取（如 load_run_metric 的即时 .get），
    MUST NOT 跨语句长期持有。
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    log_path = logs_dir / "fenixd.log"
    try:
        size = log_path.stat().st_size
    except OSError:
        return {}
    head_hash = _log_head_fingerprint(log_path)
    key = (size, head_hash)
    # 段 1（锁内，纯内存）：定槽 + 判定增量/重建起点；fast path（key 未变）在此
    # 直接返回，日志扫描 IO 全部留在段 2 锁外，不阻塞其他线程的读路径。
    with _RUN_METRIC_INDEX_LOCK:
        slot = _RUN_METRIC_INDEX.setdefault(str(log_path), {"key": None, "index": {}})
        if key == slot["key"]:
            return slot["index"]
        # size 缩小（轮转）、首块指纹不符（轮转后快速回涨超旧 size）或首扫 → 本槽清空重建
        prev_key = slot["key"]
        if prev_key is None or size < prev_key[0] or head_hash != prev_key[1]:
            # 原地清空而非换引用：段 3 合并按 slot["index"] 现取落账，换引用会把
            # 并发在途扫描写进孤儿 dict（丢指标且新空索引被误标记为已扫到本 offset）
            slot["index"].clear()
            start = 0
        else:
            start = prev_key[0]
    # 段 2（锁外，IO）：补扫新增块 / 重建全量扫描，解析结果先落局部 dict。
    scanned = None
    try:
        # 二进制模式 + 手动 decode（对齐 log_index 的偏移读取口径）：start 来自
        # 上轮 stat 的字节 size，对文本流 seek 任意整数依赖 TextIOWrapper 接受
        # 非 tell() cookie 的实现细节；"rb" 下偏移语义完全自控（start 落多字节
        # UTF-8 序列中间时首行 U+FFFD 解析失败被跳过，与文本模式行为一致）。
        # \n 不可能是多字节序列的组成字节，逐行 decode 等价整块 decode，且保持
        # 流式内存轮廓（重建分支不整读大日志）。
        with log_path.open("rb") as f:
            if start:
                f.seek(start)
            scanned = _parse_run_metric_stream(
                raw.decode("utf-8", errors="replace") for raw in f
            )
    except OSError:
        # 3c9c40ef135f：扫描中途读失败不推进 key——下一轮从旧 offset 重扫同一
        # 区间（_parse_run_metric_stream 按 run_id 键级合并写产物，重扫幂等）；
        # 轮转/首扫重建分支已清空的本槽索引由下轮（指纹不符/size 判定）重判
        # 重建自愈。对齐 log_index._update_log_block_index「读取失败不推进」口径。
        pass
    # 段 3（锁内，纯内存）：合并落账 + 推进 key + 超限淘汰。段 1/3 锁间隙内其他
    # 线程可能已清空/推进本槽，合并始终写 slot["index"] 现取的本槽 dict，不持
    # 段 1 的旧引用。落账按 run_id 键级合并（与 _parse_run_metric_stream 同
    # 口径）：增量块的行可能与前块同 run_id（如收尾连写的 usage_source 附加行
    # 落在终态行入账后的下一扫描块），整体 update 会用后块条目替换前块富终态
    # 行——harness/duration 双丢；键级合并下重扫/并发双扫同样幂等收敛。
    with _RUN_METRIC_INDEX_LOCK:
        index = slot["index"]
        if scanned is not None:
            for rid, ctx in scanned.items():
                prev = index.get(rid)
                index[rid] = {**prev, **ctx} if prev else ctx
            slot["key"] = key
        # 容量上限：各槽合计超限按最旧淘汰（槽按出现序、槽内 dict 保插入序＝日志
        # 出现序），保近期 run 指标
        total = sum(len(s["index"]) for s in _RUN_METRIC_INDEX.values())
        if total > _RUN_METRIC_INDEX_MAX:
            excess = total - _RUN_METRIC_INDEX_MAX
            for s in _RUN_METRIC_INDEX.values():
                if excess <= 0:
                    break
                s_index = s["index"]
                for rid in list(s_index)[:excess]:
                    del s_index[rid]
                    excess -= 1
        return index


# 同主日志索引按 log_path 分槽（dashboard 单进程多项目交替查询各自零重建）。
# 槽容量上限（code-review 63a3bfee947f，与主索引 _RUN_METRIC_INDEX_MAX 同动机）：
# 槽只增不回收——每个被查询过的项目永久占一槽（槽内是整份轮转日志的索引），
# 项目移除后槽仍保留，多项目长驻 daemon 内存随「历史项目数 × 单轮转日志 run
# 数」单调增长。超限按槽插入序（=项目首查序）淘汰最旧槽：整槽 del 而非清条目，
# 下次访问走首扫全量重建即自愈（轮转日志冻结、size 键语义，重建即正确），无
# 主索引那种「清索引不推进 key 丢增量段」的顾虑；仍在轮询的被淘汰项目仅多一次
# 全量重扫。
_ROTATED_METRIC_INDEX: dict = {}  # {str(log_path): {"key": (size,), "index": {run_id: ctx}}}
_ROTATED_METRIC_INDEX_MAX_SLOTS = 256


def _load_rotated_run_metric_index(project_root: Path) -> dict:
    """轮转日志 .fenixd.log.1 的 run_metrics 索引（跨轮转旧 run 回退源，按 log_path 分槽）。

    主日志索引只覆盖最近一次轮转之后的行，轮转前收尾的旧 run 终态只在
    .fenixd.log.1（evo-fix-self-review-phantom-failed-samples 2.1）。轮转
    日志写入后冻结、下次轮转被整体替换，每槽按 size 键增量维护：
    size 变化（含被新轮转替换）仅重建本槽。槽总数上限
    _ROTATED_METRIC_INDEX_MAX_SLOTS，超限按插入序淘汰最旧槽。

    并发：与主索引同款，读改写段（定槽 fast path/落账推进 key）经
    _RUN_METRIC_INDEX_LOCK 串行化，扫描 IO 在锁外；落账前 re-stat 复核
    size 未变再落账（防 stat→open 撞上轮转的键内容错位）。
    """
    log_path = Path(project_root) / ".fenix" / "logs" / "fenixd.log.1"
    try:
        size = log_path.stat().st_size
    except OSError:
        return {}
    key = (size,)
    # 段 1（锁内，纯内存）：定槽 + fast path（key 未变直接返回）。与主索引
    # _load_run_metric_index 同款并发口径：落账（换引用推进 key）是非幂等
    # 读改写，经 _RUN_METRIC_INDEX_LOCK 串行化，扫描 IO 留在段 2 锁外。
    with _RUN_METRIC_INDEX_LOCK:
        slot = _ROTATED_METRIC_INDEX.setdefault(str(log_path), {"key": None, "index": {}})
        if key == slot["key"]:
            return slot["index"]
    # 段 2（锁外，IO）：整体重建扫描，解析结果先落局部 dict。
    index: dict = {}
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            index = _parse_run_metric_stream(f)
    except OSError:
        pass
    # 段 3（锁内）：落账前 re-stat 复核 size 未变——本文件会被下一次轮转整体
    # 替换，stat→open 竞态可把一轮的扫描结果以另一轮的 size 键落账，此后
    # key 恒命中、陈旧索引要等再下一次轮转才自愈（code-review 95a3f6dcf9d2）。
    # size 已变/文件暂不可见（轮转窗口）则本轮只返回现扫结果不落账，下轮按
    # 新 key 重建自愈。re-stat 是单次元数据 IO，刻意留在锁内以闭合
    # stat→open→落账窗口。
    with _RUN_METRIC_INDEX_LOCK:
        try:
            unchanged = log_path.stat().st_size == size
        except OSError:
            unchanged = False
        if unchanged:
            slot["index"] = index
            slot["key"] = key
        # 容量上限（锁内纯内存，段 1 新建槽必经本段）：超限按槽插入序淘汰
        # 最旧槽，新建槽落账后立即闭合超限窗口。
        while len(_ROTATED_METRIC_INDEX) > _ROTATED_METRIC_INDEX_MAX_SLOTS:
            del _ROTATED_METRIC_INDEX[next(iter(_ROTATED_METRIC_INDEX))]
        return index


def load_run_metric(project_root, run_file_stem: str) -> "dict | None":
    """公共访问器：按 run 产物 stem 查 run_metrics 指标 context（双源交叉守卫）。

    供聚合侧（core/self_review.py 幻影失败守卫）复用：stem 先经
    _strip_run_attempt_suffix 归一为基础 run_id（指标日志记基础 id，产物
    按 attempt 分文件）；主日志索引未命中时回退轮转日志 .fenixd.log.1
    （跨轮转旧 run）。两处均未命中返回 None——调用侧按「索引缺失维持现状」
    处理，宁可不拦不可误伤真实失败样本。
    """
    if not project_root or not run_file_stem:
        return None
    base = _strip_run_attempt_suffix(str(run_file_stem))
    if not base:
        return None
    root = Path(project_root)
    metric = _load_run_metric_index(root).get(base)
    if metric:
        return metric
    return _load_rotated_run_metric_index(root).get(base)


def _logged_run_duration(project_root: Path, run_file_stem: str,
                         engine: str = "") -> float | None:
    """从结构化指标读 run 耗时（替代 mtime 推算）。

    run_file_stem 为产物文件名（含 -a<n>/ -r<n>），归一化为基础 run_id 后
    在指标索引中查找；命中返回 duration_seconds（float），未命中 None。
    双源查找（主日志索引 → 轮转日志 .fenixd.log.1 回退）复用 load_run_metric
    单源（含 _strip_run_attempt_suffix 归一），回退口径演进只改一处。
    engine 预留字段：后续如需区分「哪个消费点」可传值；当前恒空。
    """
    metric = load_run_metric(project_root, run_file_stem)
    if not metric:
        return None
    d = metric.get("duration_seconds")
    if d is None:
        return None
    try:
        return float(d)
    except (TypeError, ValueError):
        return None

# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

# run 终态事件类型 → classify_run 状态映射。写侧唯一权威是
# core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（result=自然完成,
# error=进程异常终止, interrupted=daemon 停机/启动终态补写, cancelled=人工取消,
# frozen-terminated=spec 冻结终止（add-freeze-stop-inflight-agents D2，
# 行来源：runner.py _run_agent finally 段在 join 后、与 cancelled 行同级
# 追加——读侧缺该映射会把已冻结终止的 run 永远判成 running）），
# 读侧缺类型会把已终结 run 永远判成 running（overview 活跃 Agent 数虚高事故：
# 11 个被杀 run 全部计入活跃，真实活跃仅 1）。测试锁两侧同步。
# fix-retry-orphan-active-runs 追加变体：运行期间原地重试换新 sub_run_id 弃置
# 旧产物文件（写侧补写 superseded 终态），interrupted 补写够不到（daemon 存活
# 期无停机），缺 superseded 映射会把弃置文件永远判成 running——2026-09-10
# 实测 23 活跃仅 2 真实，21 具尸体全数源于该形态。
_RUN_TERMINAL_STATUS_MAP = {
    "result": "done",
    "error": "error",
    "interrupted": "interrupted",
    "cancelled": "cancelled",
    "frozen-terminated": "frozen-terminated",
    "superseded": "superseded",  # fix-retry-orphan-active-runs：原地重试弃置产物终态
    # add-timeline-gate-failure-display D3：门禁因产物硬门失败终止本次 attempt 的
    # 终态（写侧 runner.py _append_gate_blocked，两侧同步义务见 liveness.py
    # RUN_TERMINAL_EVENT_TYPES）。superseded 是同一失败链的**中间弃置件**（紧随其后的
    # gate-blocked 才是收口终态），两者并存但语义不同——MUST NOT 把 superseded 当
    # gate-blocked 的替代，也不必把 superseded 从本映射移除（弃置文件仍需判终态，
    # 否则旧产物永远判 running）。
    "gate-blocked": "gate-blocked",
}

# 读侧 mtime 陈旧兜底阈值（fix-retry-orphan-active-runs D2）：末行非终态
# （running/empty）且产物 mtime 停更超过该秒数 → get_runs 判 stale（弃置/断尾，
# 读侧专属状态枚举，非事件类型，不写入任何产物文件）。退避档上限 120s + agent
# 单 turn（长构建/长测试）余量；live run 每 turn 写事件，30 分钟无写入必非在飞。
# 不做配置项（design D2：避免触发「新增配置必须带 Dashboard 界面」约束）。
_RUN_STALE_SECONDS = 1800

# 公开访问面（code-review item b569f5bb4a32）：core.code_review 跨包消费
# 终态映射与 stale 阈值，此前只能引用下划线私有名——私有名不在公开契约内，
# 本模块重命名/搬移即令消费方运行时 ImportError。公开名与私有定义同一对象
# 单源绑定（非复制定义），私有名与门面 re-export 面原样保留。
RUN_TERMINAL_STATUS_MAP = _RUN_TERMINAL_STATUS_MAP
RUN_STALE_SECONDS = _RUN_STALE_SECONDS


def classify_run(lines: list) -> str:
    """根据产物文件行判定运行终态：done / error / interrupted / cancelled /
    superseded / frozen-terminated / gate-blocked / running / empty。

    终态全集以 _RUN_TERMINAL_STATUS_MAP 为单源（frozen-terminated=spec 冻结
    终止、gate-blocked=门禁硬失败终止，两映射的来历见映射行内注释），映射
    新增条目后此处枚举须同步补齐。
    runner「终态后置」不变量保证任一终态事件即文件最后一行（result/error 在
    收尾 join 后落盘，interrupted 由 daemon 停机/启动清扫追加，cancelled 由
    取消路径最后落盘，superseded 由原地重试弃置前补写），故只看末行即可判定。
    """
    if not lines:
        return "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running"
    # c3bef177adc7: type 值为不可哈希类型（合法 JSON 但数组/对象，手工编辑/
    # 半损坏产物）时 dict.get 抛 TypeError，runs 读接口整体 500——非 str 降级
    # 按 running，与本函数非 dict 行降级及 6fd55ebbc869 防护口径同族对齐。
    t = last.get("type")
    if not isinstance(t, str):
        return "running"
    return _RUN_TERMINAL_STATUS_MAP.get(t, "running")


# run_id 白名单（code-review item 325d0b089a9d）：run 产物 stem 由
# `<spec/admin 前缀>-<epoch>(-a<n>/-r<n>)` 形态构成，字符集仅字母数字与
# `. _ -`。显式排除路径分隔符——HTTP 查询参数 run_id 原样透传进本函数，
# `run_id=../../foo` 形态可拼出 runs 目录之外的 .jsonl 读取路径。
# 尾锚用 \Z 而非 $（code-review item 898d72a30cc5）：Python re 的 $ 在字符串
# 末尾换行之前也匹配，"x\n" 形态的 run_id 会漏过白名单，\Z 绝对锚定堵住该缝。
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+\Z")


def _resolve_run_file(project_root, run_id: str) -> Path:
    """定位 run 产物：优先活跃目录，缺失时回读 archive/（add-run-archive）。

    run_id 先经白名单校验（code-review item 325d0b089a9d）：含路径分隔符或
    其它越界字符一律视为不存在——返回 runs 目录内的固定哨兵路径（不会命中
    任何产物文件），调用方既有的 ``exists()`` 缺失分支按「run 不存在」处理，
    与 archive 回退双缺失时返回不存在路径的既有行为一致。
    """
    proot = Path(project_root)
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return proot / ".fenix" / "runs" / ".invalid-run-id"
    live = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if live.exists():
        return live
    return proot / ".fenix" / "runs" / "archive" / f"{run_id}.jsonl"


def _first_run_event_ts(path: Path) -> "str | None":
    """run 产物首个带 timestamp 事件的时间（真实启动时刻）。

    run_id 内嵌时间戳是**首次派发**时刻：多 attempt run（-a2+）复用同一
    run_id 基座只加后缀，按 run_id 解析会让所有 attempt 显示同一开始时刻、
    duration 虚增（含前序 attempt 寿命）。真实起点取产物首个带 timestamp 的
    事件：文件头部是无时间戳的 provider_marker/hook/system 事件（实测 10+ 行），
    故扫描前 200 行、命中即停；全部无样本返回 None（调用方回退 run_id 内嵌
    时间戳）。
    """
    # 跨组引用（timeline 组公开别名 parse_iso_ts）经门面延迟解析（D4）
    import core.dashboard.data as _facade

    try:
        with path.open("rb") as f:
            for _ in range(200):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = ev.get("timestamp") if isinstance(ev, dict) else None
                if ts and _facade.parse_iso_ts(str(ts)) is not None:
                    return str(ts)
    except OSError:
        return None
    return None


# ── run 元数据 memo（fix-dashboard-read-path-performance D3） ──────────────
# run 元数据（status_raw/started/duration_seconds/file_size）按
# (path, mtime_ns, size, project_root) 缓存：append-only 产物未变即零读，跳过 _first_run_event_ts
# （扫描头 200 行 + json.loads）与尾读。读路径把 O(总量) 降为 O(变更量)。
# 与 _RUN_TASK_CACHE/_GLOBAL_BUDGET_CACHE 同模式（GIL 保护下的最优竞态：并发
# 双算无害）。缓存存 status_raw——stale 判定依赖当前时刻，每次按 now 重算。
_RUN_META_CACHE: dict = {}
_RUN_META_CACHE_MAX = 16384
# code-review item 95590b3c2534：终态产物缓存固化宽限窗（秒）。run 收尾先向产物
# 追加终态事件（_run_agent finally），后写 fenixd.log run_metrics 真实耗时指标
# （成功/失败路径都在其后经 worktree 清理等数秒级间隙才落盘）；两步之间读路径
# 一旦把 mtime 推算耗时以「终态产物 mtime_ns/size」为键固化，键永不变化，指标
# 落盘也不再被消费。窗口内对「终态且结构化指标未命中」的 run 以「临时条目」
# 入缓存（见 _run_meta_cached）：窗内照常命中 memo（burst 读零重扫），窗口过后
# 重算一次——指标已落盘则固化真实值；仍缺失（旧日志/中断 run）才按 mtime 兜底
# 永久固化。
_RUN_METRIC_GRACE_SECONDS = 15


def _run_meta_cached(p: Path, stat, now: float,
                     project_root: Path | None = None) -> dict:
    """计算/复用单条 run 元数据（status/started/duration_seconds/file_size）。

    命中（path, mtime_ns, size, project_root 全同）即返回缓存；未命中完整计算并写入缓存。
    耗时/开始时刻/状态推导逻辑与既有 get_runs 逐字等价（见各步注释），
    仅挪入本函数以便整体 memo。

    fix-observability-gaps 1.5（消费点）：project_root 非空时 duration_seconds
    **优先读结构化 run 指标**（runner 收尾写进 fenixd.log 的
    metric_type=run_metrics 行，含真实 duration_seconds），替代「由 run 文件
    mtime 推算耗时」（spec「MUST NOT 仅依赖 mtime」）；指标缺失（旧日志/
    未触发）回退 mtime 推算。project_root 省略（仅取 status 的调用方如
    _is_run_archivable）跳过指标查找，行为与现状一致。
    """
    # 缓存键须含 project_root 维度（None 归一化为 ""）：duration_seconds 是否
    # 优先读结构化指标取决于调用是否传 project_root，若不纳入键，同一产物
    # 先被 _is_run_archivable（不传）缓存 mtime 推算耗时后，get_runs（传入）
    # 会命中同键复用错误值（终态产物 mtime/size 不再变化，先到者长期固定）。
    key = (str(p), stat.st_mtime_ns, stat.st_size,
           str(project_root) if project_root is not None else "")
    cached = _RUN_META_CACHE.get(key)
    if cached is not None:
        meta_c, provisional_until = cached
        # code-review item 95590b3c2534：临时条目（宽限窗内固化的终态 run）到期
        # 重算一次——此时 mtime 宽限窗亦必已过（上次计算时刻 ≥ mtime），指标已
        # 落盘则固化真实值，仍缺失则按 mtime 兜底永久固化（不再反复重扫）。
        if provisional_until is not None and now >= provisional_until:
            cached = None
        else:
            status = meta_c["status_raw"]
            # fix-retry-orphan-active-runs D3：stale 判定按当前时刻每次重算
            if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
                status = "stale"
            # code-review 929e46a31513：与下方现算分支返回形状统一（都含
            # status_raw），避免消费方在「首调命中、二调现算」间键忽有忽无
            return {
                "status_raw": meta_c["status_raw"],
                "status": status,
                "started": meta_c["started"],
                "duration_seconds": meta_c["duration_seconds"],
                "file_size": meta_c["file_size"],
            }
    run_id = p.stem
    # 耗时：run_id 起始时间戳为 attempt 段前的 10 位 unix 秒（int(time.time())），
    # 文件 mtime 为终止。优先匹配 `-<ts>-a<n>`（含 attempt 后缀的真实格式），
    # 回退 `-<ts>`（旧格式无 attempt 后缀），再无则退化 mtime（现状兜底）。
    tm = re.search(r"-(\d{9,10})-a\d+$", run_id) or re.search(r"-(\d{9,10})$", run_id)
    start_ts = int(tm.group(1)) if tm else stat.st_mtime
    # started 优先取产物首行事件时间戳（真实启动时刻）：run_id 内嵌时间戳
    # 是首次派发时刻，多 attempt run（-a2+）复用同一 run_id 基座只加后缀，
    # 按 run_id 解析会让所有 attempt 显示同一开始时刻、duration 虚增
    # （含前序 attempt 寿命）。真实起点取产物首个带 timestamp 的事件：
    # 文件头部是无时间戳的 provider_marker/hook/system 事件（实测 10+ 行），
    # 故扫描前 200 行、命中即停；全部无样本返回 None（调用方回退 run_id 内嵌
    # 时间戳）。
    real_start = _first_run_event_ts(p)
    # 跨组引用（timeline 组公开别名 parse_iso_ts）经门面延迟解析（D4）
    import core.dashboard.data as _facade

    real_dt = _facade.parse_iso_ts(real_start) if real_start else None
    if real_dt is not None:
        started = real_dt.astimezone(timezone.utc).isoformat()
        duration_seconds = max(0, int(stat.st_mtime - real_dt.timestamp()))
    else:
        # started 用 run_id 解析出的开始时间戳，而非文件 mtime
        # （mtime 是运行 *结束* 时间）。duration_seconds = mtime - start_ts 已真实计算，
        # 若 started 仍取 mtime，则运行列表/时间轴会把每次运行显示为「在结束时刻才开始」，
        # 与真实耗时自相矛盾（耗时列为真实秒数而开始时间却是结束时刻）。
        started = from_epoch(start_ts).isoformat()  # SPEC-B 批④收拢
        duration_seconds = max(0, int(stat.st_mtime - start_ts))
    # fix-observability-gaps 1.5（消费点）：结构化指标优先——run 收尾落盘的
    # duration_seconds 为真实耗时（time.time()-start_time），替代 mtime 推算；
    # 命中即用、未命中维持 mtime 兜底（旧日志不丢）。
    logged = None
    if project_root is not None:
        logged = _logged_run_duration(Path(project_root), run_id)
        if logged is not None:
            duration_seconds = int(round(logged))
    status_raw = classify_run(_read_run_lines(p, max_lines=3))
    status = status_raw
    # fix-retry-orphan-active-runs D3：末行非终态且文件 mtime 停更超过
    # _RUN_STALE_SECONDS → 判 stale（原地重试弃置尸体 / 进程被杀无终态断尾），
    # stale 不进 _RUN_TERMINAL_STATUS_MAP（非事件类型）。
    if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
        status = "stale"
    meta = {
        "status_raw": status_raw,
        "status": status,
        "started": started,
        "duration_seconds": duration_seconds,
        "file_size": stat.st_size,
    }
    # code-review item 95590b3c2534：终态 + 结构化指标未命中 + 产物刚收尾（宽限
    # 窗内）→ 缓存条目标记临时（provisional）。此时 duration 是 mtime 兜底值，
    # 而真实耗时指标行可能尚在写盘路上；一旦按普通条目固化，永不变化的缓存键
    # 会把它永久钉住。临时条目在窗内照常命中 memo（D3 契约：文件未变零重扫），
    # 窗口过后重算一次：指标已落盘则固化结构化值，仍缺失（旧日志/中断 run）则
    # 按 mtime 兜底永久固化。
    provisional_until = None
    if (project_root is not None and logged is None
            and status_raw in _RUN_TERMINAL_STATUS_MAP.values()
            and (now - stat.st_mtime) < _RUN_METRIC_GRACE_SECONDS):
        provisional_until = now + _RUN_METRIC_GRACE_SECONDS
    if len(_RUN_META_CACHE) > _RUN_META_CACHE_MAX:
        _RUN_META_CACHE.clear()
    _RUN_META_CACHE[key] = (meta, provisional_until)
    return meta


def get_runs(project_root, spec_name: str | None = None, include_archive: bool = False, files: list | None = None) -> list:
    """列出项目的运行记录（.fenix/runs/*.jsonl）。

    spec_name 省略时返回全部；否则仅返回归属该 spec 的记录
    （run_spec_part 全等精确归属，code-review item 78dc8a67623f：子串包含在
    spec 名互为前缀时会把前缀兄弟 spec 的 run 串入对方统计）。
    include_archive=True 时并入 runs/archive/ 的归档产物（同 run_id 以活跃
    副本优先），供时间轴/运行历史/耗时统计回看已归档的旧 run。
    files: 调用方预扫描的产物路径集（如 SummaryIndex._runs_by_spec_sigs 的
        分组结果）；提供时跳过目录 glob（D2：目录 glob 次数降为常数）。
        与 glob 路径同样按 spec 精确归属过滤、同样以活跃副本优先去重。
    每条: {run_id, agent_type, spec, status, duration_seconds, started,
        file_size}（事件明细不在条目内，见 get_run_events）
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    if files is None:
        try:
            files = list(runs_dir.glob("*.jsonl"))
            if include_archive:
                archive_dir = runs_dir / "archive"
                if archive_dir.is_dir():
                    files.extend(archive_dir.glob("*.jsonl"))
        except OSError:
            return []
    else:
        files = list(files)
        if not include_archive:
            files = [p for p in files if p.parent.name != "archive"]
    # 同 run_id 以活跃副本优先去重（预选集可能同时含 live+archive 同名产物，
    # 与 glob 路径语义一致），再按 mtime 降序（latest_run 取 files[0]）。
    try:
        live, archived = [], []
        for p in files:
            (archived if p.parent.name == "archive" else live).append(p)
        seen = {p.stem for p in live}
        files = live + [p for p in archived if p.stem not in seen]

        def _mtime_desc_key(p):
            # 单文件 stat 失败（并发归档/删除等 OSError 子类）只回退 mtime 0
            # （排到末尾，随后由逐条 stat 的 except OSError 跳过），不放大为整表清空。
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        files.sort(key=_mtime_desc_key, reverse=True)
    except OSError:
        return []
    now = time.time()
    for p in files:
        run_id = p.stem
        # dsh 原始事件 dump 旁路（<run_id>.dsh-events.jsonl，add-dsh-adapter-
        # integration 可观测性三件套）不是 run 产物：不带 spec 过滤的裸 glob 会
        # 把它当「spec 名带 .dsh-events 尾巴的幻影 run」混入运行时间轴（
        # code-review item c8be48d57864），读侧按 stem 后缀排除（glob 路径与
        # 调用方预选集共用本过滤点）；其回收交 runs 保留清理——终态/stale 移入
        # archive/ 后按无主天龄兜底删除。
        if run_id.endswith(".dsh-events"):
            continue
        # 精确归属守卫（code-review item 78dc8a67623f）：子串包含在 spec 名互为
        # 前缀时（如 add-foo 与 add-foo-bar）互相串入对方 run；与读侧既有口径
        # 一致（recovery.py 活性探针、budget.py 预算计数均用 run_files.
        # run_spec_part 全等归属），本函数的消费点含 engine.py total_duration
        # 快照求和，前缀兄弟 spec 的耗时不得计入。
        if spec_name and run_spec_part(run_id) != spec_name:
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        # 从 run_id 推断 agent 类型与 spec（前缀表 = run_files 唯一真源；
        # 此前是本地漂移副本，漏了 spec-review-/dispute-judge- → 评审 Agent
        # 在时间线上退化为泛型 "agent"，且 spec 残留整个 run_id）。
        agent_type, _ = infer_run_agent_type(run_id)
        # spec_part 后缀剥离（attempt/瞬态重试段 + 时间戳）复用
        # run_files.run_spec_part 唯一真源（infer → strip_run_id_suffixes →
        # 时间戳剥除同口径），避免内联副本随剥离规则演进再次漂移。
        spec_part = run_spec_part(run_id)
        # 元数据（status/started/duration/file_size）按 (path, mtime_ns, size) memo
        # （fix-observability-gaps 1.5：project_root 传入使 duration 优先读结构化指标）
        meta = _run_meta_cached(p, stat, now, project_root=Path(project_root))
        # add-harness-brand-projection 2.2：harness 透出（品牌投影真相源）——
        # 从 run_metrics 旁路行取该 run 派发时登记的 adapter.name；存量 run
        # 指标行无该键（或指标行整体缺失）缺省 claude，前端按回退链消费
        # （harnessBrandLogic.resolveHarness）。复用上方 duration 指标查找
        # 已预热的增量索引——非纯内存 dict 直查：fast path 仍含 stat+打开
        # 日志读首块指纹校验与 _RUN_METRIC_INDEX_LOCK，只是无全量重扫；本处
        # 与上方 duration 查找对每条 run 各触发一次 load_run_metric（轮询
        # 每条 run 两次该成本），勿在此路径叠加高频调用。
        harness = "claude"
        metric = load_run_metric(Path(project_root), run_id)
        if metric and metric.get("harness"):
            harness = str(metric["harness"])
        out.append(
            {
                "run_id": run_id,
                "agent_type": agent_type,
                "spec": spec_part,
                "status": meta["status"],
                "duration_seconds": meta["duration_seconds"],
                "started": meta["started"],
                "file_size": meta["file_size"],
                "harness": harness,
            }
        )
    return out


# 尾读字节窗口（fix-dashboard-read-path-performance D3）：取末 N 行先 seek 尾部
# 窗口读；窗口内完整行不足 max_lines（单行超窗 / 前导行残段被丢弃）时回退全量
# 逐行读。64KB 覆盖 result 终结事件行（4KB+）与常规产物尾部；单行超过窗口即回退。
_READ_RUN_TAIL_WINDOW = 64 * 1024


def _parse_line_event(line: str) -> dict:
    """单行 JSONL 容错解析为事件 dict（三处解析器共用的统一口径）。

    损坏行与「json.loads 成功但非 dict」的行（int/str/list 等）均降级为
    stderr 条目，保证下游 events 恒为 dict 列表（code-review 28b98abd04a6：
    尾窗路径原先只捕 JSONDecodeError，非 dict 行会原样吐给前端 events 窗口）。
    """
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        entry = {"type": "stderr", "line": line}
    if not isinstance(entry, dict):
        entry = {"type": "stderr", "line": str(entry)}
    return entry


def _parse_tail_lines(lines: list, max_lines: int) -> list:
    """把文本行序列容错解析为事件，保留末 max_lines 条（空行跳过）。"""
    tail = deque(maxlen=max_lines)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        tail.append(_parse_line_event(line))
    return list(tail)


def _read_run_lines_full(path: Path, max_lines: int) -> list:
    """全量逐行读取产物尾部（尾读回退分支，与旧实现语义一致）。"""
    tail = deque(maxlen=max_lines)
    try:
        with path.open("rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                tail.append(_parse_line_event(line))
    except OSError:
        pass
    return list(tail)


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。

    优先从文件尾部按字节窗口 seek 读取（append-only 场景末 N 行远小于窗口，
    避免全量逐行读）；窗口内完整行不足 max_lines（单行超窗 / 前导行残段被
    丢弃）时回退全量逐行读。正确性约束不变：MUST NOT 从行的中间截断导致末行
    被误解析——result/error 终结事件行可能超长（result 携带完整结果数据，
    4KB+），若字节窗口把末行从中间截断、parse 失败后被包装成伪 stderr 事件
    排在真实末尾，classify_run 会把已完成 run 误判为 running（overview 活跃
    Agent 数虚高事故）。窗口首行是上一行的残段，必须丢弃而非解析。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= _READ_RUN_TAIL_WINDOW:
        return _read_run_lines_full(path, max_lines)
    try:
        with path.open("rb") as f:
            f.seek(-_READ_RUN_TAIL_WINDOW, 2)
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    # 首行是从字节窗口切入的残段（从上一行中间开始），丢弃
    parsed = _parse_tail_lines(text.split("\n")[1:], max_lines)
    if len(parsed) >= max_lines:
        return parsed
    # [fenix-ignore:d6b237f46378] info 性能项不修：流式尾读重构风险大于收益（本函数有截断末行误判 running 的事故约束），超长末行罕见且全量回退语义正确
    # 窗口内完整行不足 max_lines（单行超窗等）→ 回退全量逐行读
    return _read_run_lines_full(path, max_lines)


# 公开访问面（code-review item b569f5bb4a32）：跨包消费方 core.code_review
# 引用公开名，与 _read_run_lines 同一函数对象单源绑定。
read_run_lines = _read_run_lines
# 公开访问面（code-review item 2546f200e430）：timeline.py 跨组引用改用公开名
# （不跨组消费下划线私有名），与私有实现同一函数对象单源绑定。
resolve_run_file = _resolve_run_file


def _parse_run_lines(lines) -> list:
    """逐行解析 JSONL 行序列为事件（容错：损坏行/非 dict 行降级为 stderr 条目）。"""
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        events.append(_parse_line_event(line))
    return events


def get_run_events(project_root, run_id: str, tail: int = 300, offset_from_end: int = 0) -> dict:
    """读取单次运行产物流的尾部窗口（前端默认展示最近 N 条，全量拉取是浪费）。

    返回: {run_id, exists, status, events, total_events, error}
    events 为窗口 [len-tail-offset_from_end, len-offset_from_end) 的逐行解析结果
    （add-run-record-readability 4.1 向前分页；offset_from_end 为负时按 0 钳制，
    窗口越出流首时按流首截断）；offset_from_end=0 时与既有尾部截取 events[-tail:]
    逐字段一致。total_events 为实际总事件数（不受窗口影响）；status/error 由
    _read_run_lines 尾读末行终态判定（终态后置不变量，与 get_runs 的
    classify_run 读取范式同口径）。

    tail 下限归一为 ≥1（code-review item 590aa3c551db）：路由层只做上限钳制，
    tail=0/负值会到达本函数——events[-0:] 即 events[0:] 使 offset=0 分支返回
    全量流、offset>0 分支返回空窗，同一参数两侧语义相悖；统一钳到 1 消除分歧。

    流式扫描（code-review item cba668786b37）：本函数是前端轮询热路径，长 run
    产物（数万行）不再全文件逐行 json.loads + 全量列表驻留——单遍逐行只做非空
    行计数（total_events 无需解析 JSON），仅驻留尾部窗口的原始行文本；窗口
    边界在计数完成后才确定，窗口内行再逐行解析。
    """
    run_file = _resolve_run_file(project_root, run_id)
    if not run_file.exists():
        return {
            "run_id": run_id,
            "exists": False,
            "status": "missing",
            "events": [],
            "total_events": 0,
            "error": None,
        }
    offset = max(int(offset_from_end or 0), 0)
    tail = max(int(tail), 1)  # 下限归一：防 tail=0 走 events[-0:]=全量（见 docstring）
    total = 0
    suffix = deque(maxlen=tail + offset)  # 仅驻留窗口原始行文本，不解析
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                total += 1
                suffix.append(line)
    except OSError:
        return {
            "run_id": run_id,
            "exists": True,
            "status": "error",
            "events": [],
            "total_events": 0,
            "error": {"error": "unreadable"},
        }
    # 窗口 [total-offset-tail, total-offset) 折算进驻留后缀坐标（base = 后缀首行
    # 的全局行号；请求窗越出后缀覆盖范围时按流首截断，与全量列表切片语义一致）
    kept = list(suffix)
    base = total - len(kept)
    end = max(total - offset, 0)
    start = max(end - tail, 0)
    window = [
        _parse_line_event(line)
        for line in kept[max(start - base, 0):max(end - base, 0)]
    ]
    # status/error 沿用 64KB 尾读（终态后置不变量：任一终态事件即文件末行，
    # error 即末行终态事件；与 _run_meta_cached/run_activity 同一读取范式）
    tail_events = _read_run_lines(run_file, max_lines=3)
    error = None
    for entry in reversed(tail_events):
        if entry.get("type") == "error":
            error = entry
            break
    return {
        "run_id": run_id,
        "exists": True,
        "status": classify_run(tail_events),
        "events": window,
        "total_events": total,
        "error": error,
    }


def read_run_events_between(
    project_root, run_id: str, start_offset: int
) -> "tuple[list, int] | None":
    """读取运行产物从 start_offset 字节到读取时 EOF 的事件（增量推送用）。

    O_APPEND 只增写：按上次记录的字节偏移读取新增部分，避免整文件重读。
    返回 (事件列表, 实际读取终止偏移)：偏移取读取完成后的 f.tell()，调用侧
    （watcher 增量推送的基线推进）用它而非扫描入口 stat 的 size，消除
    stat→read 窗口内新追加字节「本轮已解析推送、基线却停在 stat 值、下轮
    重读同一区间重复推送」的重叠（code-review item 098ae174254b）。
    跨扫描边界被截断的半个 JSON 行会降级为 stderr 条目（_parse_run_lines 容错）。
    读失败（文件被并发归档/移除等 OSError）返回 None 以区别于「无新增」的 []，
    调用侧（watcher 增量推送）据此保留旧基线，下一轮重读同一区间。
    run_id 先经 _RUN_ID_RE 白名单校验（code-review item f970801a5c7d，与
    _resolve_run_file 同口径）：含路径分隔符等越界字符一律按读失败返回 None，
    不拼 runs 目录之外的读取路径。
    """
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return None
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        with run_file.open("rb") as f:
            f.seek(start_offset)
            raw = f.read()
            end_offset = f.tell()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    return _parse_run_lines(text.splitlines()), end_offset


# ── 聚合视图（供 Web API / 概览 / 详情） ──────────────────────────


def active_run_count(project_root) -> int:
    """统计处于 running / empty（可能正在增长）状态的运行数。"""
    return sum(1 for r in get_runs(project_root) if r["status"] in ("running", "empty"))


def _run_tail_insights(
    run_file: Path, tail_bytes: int = 65536, marker_scan_cap: int = 4 << 20
) -> dict:
    """读取 run 产物尾部：ClaudeCode 最后一条总结 + 实际驱动的 LLM + usage 四分项 + 终态原因。

    summary 优先取 result 事件的 result 字段（run 最终总结，markdown 文本，
    与 runner.py 提取产物口径一致）；无 result（运行中/中断）时回退最后一条
    assistant 文本。llm 取最后一个 provider_marker 事件（attempt 启动时写入，
    failover 切换产生多个，取最后 = 实际完成 run 的网关）。usage 取 result 事件
    的 usage 字段（add-model-billing-cost-display D2，成本本地计算数据源；
    result 是流终态必在尾窗内，无 result → None）。reason 取终态事件的人类
    可读原因（error 事件的 error 字段 / interrupted、cancelled 事件的 reason
    字段；终态后置不变量保证末行即终态，遍历顺序天然取末行生效），时间轴
    run 节点据此展示失败/中止原因，无终态或成功 run 为空串。只读文件尾部
    tail_bytes 字节避免时间轴加载全量扫描；seek 产生的截断首行直接丢弃。
    marker 可能落在 attempt 大量输出之外（尾窗扫不到），此时按 256KB 块
    向前回扫（上限 marker_scan_cap），仍无则留空；回扫把尾窗截断首行残段
    与各块首行的行尾残段逐轮拼接复原跨界行，避免边界行两侧同时解析失败。
    """
    try:
        size = run_file.stat().st_size
        with run_file.open("rb") as f:
            if size > tail_bytes:
                f.seek(-tail_bytes, 2)
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"summary": "", "llm": "", "usage": None, "reason": ""}

    def parse_chunk(raw: str, skip_first: bool) -> tuple:
        lines = raw.split("\n")
        if skip_first:
            lines = lines[1:]
        result_text = last_asst = llm = ""
        usage = None
        reason = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            # code-review ae465a29d3c6: 合法 JSON 非 object 行（裸数字/字符串/
            # 数组/null）在此跳过，否则 e.get 抛 AttributeError 致时间轴接口
            # 500（与 _parse_run_metric_stream / classify_run 防护口径一致）
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t == "provider_marker":
                m, p = e.get("model"), e.get("provider")
                if m and p:
                    llm = f"{m}@{p}"
            elif t == "result":
                rt = e.get("result")
                if isinstance(rt, str) and rt.strip():
                    result_text = rt.strip()
                u = e.get("usage")
                if isinstance(u, dict) and u:
                    usage = u
            elif t == "assistant":
                c = e.get("content")
                if isinstance(c, str) and c.strip():
                    last_asst = c.strip()
                elif isinstance(c, list):
                    texts = [
                        b.get("text", "")
                        for b in c
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = "\n".join(t for t in texts if t.strip())
                    if joined.strip():
                        last_asst = joined.strip()
            elif t in _RUN_TERMINAL_STATUS_MAP:
                # 终态原因：error 事件原因在 error 字段，interrupted/cancelled
                # 在 reason 字段；末行终态后处理，天然取末行生效
                reason = str(e.get("error") or e.get("reason") or "").strip()
        return result_text or last_asst, llm, usage, reason

    summary, llm, usage, reason = parse_chunk(data, skip_first=size > tail_bytes)
    if not llm and size > tail_bytes:
        chunk = 262144
        floor = max(0, size - tail_bytes - marker_scan_cap)
        pos = size - tail_bytes
        # 尾窗被 skip_first 丢弃的首行残段是跨越 size - tail_bytes 边界那行
        # 的后半截，缓存给回扫首块拼接；否则边界行尾窗侧解析不了、回扫侧
        # 又只是块末残段，两侧同时失败致 marker 丢失
        carry = data.split("\n", 1)[0]
        try:
            with run_file.open("rb") as f:
                while pos > floor and not llm:
                    start = max(floor, pos - chunk)
                    f.seek(start)
                    raw = f.read(pos - start).decode("utf-8", errors="replace")
                    # carry 是上界 pos 处被截断行的行尾残段：该行的行头在本
                    # 块末尾，raw + carry 复原整行，避免边界行两侧同时解析
                    # 失败被静默跳过
                    merged = raw + carry
                    _, llm, _, _ = parse_chunk(merged, skip_first=start > 0)
                    # code-review 206a0485a7e8：skip_first 丢弃的 merged 首行
                    # 在 start 恰落行边界时是完整行——中间块尚可靠 carry 于
                    # 下一轮复原重析，末块（start == floor）后无下一轮，
                    # provider_marker 行恰落此处会被静默漏采。对被丢首行单独
                    # 补采一次：llm 已非空时不覆盖（保持「取文件序更晚
                    # marker」语义）；行中间残段 json.loads 失败自然跳过，
                    # 嵌套对象残段因外层闭合符尾随也必失配，无误采面
                    if not llm and start > 0:
                        try:
                            fe = json.loads(merged.split("\n", 1)[0].strip())
                        except (json.JSONDecodeError, ValueError):
                            fe = None
                        if (isinstance(fe, dict)
                                and fe.get("type") == "provider_marker"):
                            fm, fp = fe.get("model"), fe.get("provider")
                            if fm and fp:
                                llm = f"{fm}@{fp}"
                    # 下一轮的 carry 取本轮 raw 首行（跨下界 start 边界那行
                    # 的行尾残段）：行头在更早块末尾，须靠它拼接复原；
                    # start > 0 恒下传 skip_first（不依赖块尾是否以换行收尾），
                    # 被丢首行完整/残段两种形态已由上方补采兜住
                    carry = raw.split("\n", 1)[0]
                    pos = start
        except OSError:
            # 回扫期间文件可能被保留清理/归档动作并发移除：降级返回已得的
            # summary/usage/reason（llm 留空），与首段尾窗读取防护口径一致
            pass
    return {"summary": summary, "llm": llm, "usage": usage, "reason": reason}


# 公开访问面（code-review item 2546f200e430）：与 _run_tail_insights 同一函数
# 对象单源绑定；置于定义之后（模块级别名引用后向符号会 NameError）。
run_tail_insights = _run_tail_insights


def compute_run_cost(
    usage: "dict | None", model_used: str, provider_used: str, billing_table: "dict | None"
) -> "float | None":
    """按「provider 卡片开关 + 行 model 匹配」计算单 run 成本（design D2）。

    成本 = input/1M×输入价 + output/1M×输出价 + cache_read/1M×缓存读价
         + cache_creation/1M×缓存写价。
    usage 缺失、provider 卡片计费未开启、该卡片无匹配 model 价格行（或价格行
    字段残缺）→ 返回 None（unpriced，展示「成本不可用」，绝不回退网关回传金额）。
    匹配键以 run 产物 provider_marker 的实际网关与模型为准（failover 切换后
    成本归属仍精确）。

    Args:
        usage: run 产物 result 事件 usage 字段（dict 或 None）
        model_used: 实际驱动模型名（provider_marker 的 model）
        provider_used: 实际驱动网关名（provider_marker 的 provider）
        billing_table: per-provider 计价表 {provider_name: {enabled, prices}}
            （_load_billing_config 产物）或 None
    """
    if not isinstance(usage, dict):
        return None
    if not isinstance(billing_table, dict) or not model_used or not provider_used:
        return None
    card = billing_table.get(provider_used)
    if not isinstance(card, dict) or not card.get("enabled"):
        return None
    price_keys = {
        "input": ("input_tokens", "input_per_million"),
        "output": ("output_tokens", "output_per_million"),
        "cache_read": ("cache_read_input_tokens", "cache_read_per_million"),
        "cache_creation": ("cache_creation_input_tokens", "cache_creation_per_million"),
    }
    for row in card.get("prices") or []:
        if not isinstance(row, dict):
            continue
        if row.get("model") != model_used:
            continue
        try:
            total = 0.0
            for _part, (usage_key, price_key) in price_keys.items():
                price = row.get(price_key)
                if price is None:
                    return None
                tokens = int(usage.get(usage_key) or 0)
                total += tokens / 1_000_000.0 * float(price)
            return total
        except (TypeError, ValueError):
            return None
    return None


def _split_llm_marker(llm: str) -> tuple:
    """把 provider_marker 的 `model@provider` 串拆回 (model, provider)。

    无 @ 的残留串视为只有模型名（provider 置空 → 无法匹配价格，判不可计价）。
    """
    if not llm:
        return "", ""
    if "@" in llm:
        model, provider = llm.rsplit("@", 1)
        return model, provider
    return llm, ""


# 公开访问面（code-review item 329a77d10a7e）：timeline.py 跨组引用改用公开名
# （不跨组消费下划线私有名），与 _split_llm_marker 同一函数对象单源绑定。
split_llm_marker = _split_llm_marker


def run_activity(project_root, spec_name, *, now: float | None = None, files=None) -> dict:
    """最新 impl run 的存活心跳（不依赖 TaskCreate/TaskUpdate 的实时兜底）。

    run_task_progress（fix-implementer-task-progress D3）依赖 run 产物中的
    TaskCreate/TaskUpdate 事件（parse_run_task_done）。该信号虽在 2026-09-15
    经 ``CLAUDE_CODE_ENABLE_TODO_TOOLS=1`` 显式启用后恢复，但实现期间 agent
    未必立刻建 Task、且历史 run 仍可能无事件，信号可能滞后或缺失——任务进度
    列静止在 0/N 时用户无法分辨「卡死」与「正在实现但细粒度进度不可用」。
    本函数改用与任务工具无关的线索：**产物文件是否仍在写**。

    - ``active``：最新 impl run 末行非终态（running/empty）且产物 mtime 未超
      ``_RUN_STALE_SECONDS``（复用 get_runs 的停更判据，两处同一阈值——已死
      断尾/弃置尸体不会外显为活跃）；
    - ``last_event_seconds_ago``：产物 mtime 距现在的秒数（无 run → None）。

    无 run / 解析失败 → ``{"active": False, "last_event_seconds_ago": None}``。
    纯读侧观测，不写入任何状态；``now`` 仅测试注入。
    """
    # D8/D4：find_impl_run_file 已迁至 tasks.py，经门面解析
    import core.dashboard.data as _facade

    run_file = _facade.find_impl_run_file(project_root, spec_name, files=files)
    if run_file is None:
        return {"active": False, "last_event_seconds_ago": None}
    try:
        mtime = run_file.stat().st_mtime
    except OSError:
        return {"active": False, "last_event_seconds_ago": None}
    now = time.time() if now is None else now
    age = max(0, int(now - mtime))
    status = classify_run(_read_run_lines(run_file, max_lines=3))
    active = status in ("running", "empty") and age <= _RUN_STALE_SECONDS
    return {"active": active, "last_event_seconds_ago": age}


# ── runs 保留周期清理（fix-dashboard-read-path-performance D4，语义随
# fix-run-cleanup-attach-spec-archive 更新） ────────────────────────────────
# daemon 周期任务挂载点（fenixd.py 主循环，300s 节拍对齐 auto_archive_check）：
# ① 终态 run 移入归档（活跃目录有界性）；② 无主车道归档产物天龄兜底
# （归档目录有界性）。SPEC 归档产物的清理不在这里——archive_spec_runs
# 在 SPEC 归档时把该 SPEC 的顶层与归档副本一并删除（run_files.py），产物
# 生命周期绑定 SPEC 生命周期：归档前可回看、归档即清理。
# ② 兜底语义（fix-run-cleanup-attach-spec-archive D2/D3）：code-fix /
# admin-global / code-review 等无显性 SPEC 的车道产物永不触发 SPEC 归档
# 清理，按「run_spec_part 不属于活跃 SPEC 集（spec/changes/ 目录名集合）
# 且 mtime 超保留天数」删除，保证归档目录有界。活跃集每周期现算（不缓存），
# SPEC 归档后其残留产物自动落入无主集，14 天内由本兜底或归档清理删除，
# 双保险。删除 MUST 记录日志（文件名可追溯）、每周期删除量有批次上限，
# MUST NOT 静默大批量删除；活跃集扫描失败 fail-closed 跳过本轮兜底
# （防把活跃 SPEC 误判无主大规模误删）。
_RETENTION_MOVE_PER_CYCLE_MAX = 100  # 每周期最多移入归档数（单轮 I/O 尖峰抑制）
_RETENTION_DELETE_PER_CYCLE_MAX = 100  # 每周期最多删除数（5.1a：分批清理）
# 无主归档产物保留天数（模块常量；非配置项——按「配置项必须带 Dashboard 界面」
# 约定，将来如需可调再另行立项）。
_LANE_RUN_RETENTION_DAYS = 14
# 可归档状态：终态（result/error/interrupted/cancelled/superseded/gate-blocked）
# + stale 断尾尸体（末行非终态且 mtime 停更超 _RUN_STALE_SECONDS——进程被杀
# 无终态补写，不可复活，留活跃目录只会让有界性落空）。
# add-timeline-gate-failure-display D4：集合由 _RUN_TERMINAL_STATUS_MAP.values()
# 派生，新增 gate-blocked 映射后自动纳入，**零改代码**——但 MUST 有用例锁定
# （否则后人把本行改成硬编码清单时会静默漏掉新终态）。
_RETENTION_ARCHIVABLE_STATUSES = frozenset(_RUN_TERMINAL_STATUS_MAP.values()) | {"stale"}


def _active_spec_names(proot: Path) -> set:
    """活跃 SPEC 集合 = ``spec/changes/`` 下的一级目录名集合（每周期现算，不缓存）。

    ``spec/archive/`` 已归档 SPEC 不计入——归档 SPEC 的残留产物按无主天龄
    清理正是期望行为（fix-run-cleanup-attach-spec-archive D3）。目录读取
    失败抛 OSError 由调用方 fail-closed 处理（跳过本轮兜底，防误删）。
    """
    changes_dir = proot / "spec" / "changes"
    return {p.name for p in changes_dir.iterdir() if p.is_dir()}


def _is_run_archivable(p: Path) -> bool:
    """判定 run 产物是否可归档（终态或 stale 断尾；running/empty 且停更未超时 → False）。

    状态判定复用 get_runs 的 memo（(path, mtime_ns, size, project_root)，含 stale 动态判定），
    周期清理不重复读文件。
    """
    try:
        stat = p.stat()
    except OSError:
        return False
    status = _run_meta_cached(p, stat, time.time())["status"]
    return status in _RETENTION_ARCHIVABLE_STATUSES


def _retention_log(logger, level: str, msg: str) -> None:
    """统一清理日志出口（单源：_logutil.fallback_log）。"""
    fallback_log(logger, level, msg)


def _retention_files_differ(a: Path, b: Path) -> bool:
    """轻量判等：size 或 mtime 不同即视为分歧；探测失败保守返回 True。

    用于第 1 步「归档副本已存在时删除顶层副本」的分歧检测（code-review
    item 750bb741c8fd），不做逐字节比对（产物可能较大，此处只需发现明显分歧）。
    """
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return True
    return sa.st_size != sb.st_size or int(sa.st_mtime) != int(sb.st_mtime)


def _retention_top_copy_newer(p: Path, dest: Path) -> bool:
    """顶层副本 mtime 是否晚于归档副本（探测失败保守按「更晚」= 保留顶层）。

    同名去重的删除守卫（code-review item f7332957913b）：本函数把停更超
    _RUN_STALE_SECONDS 的在飞 run 判 stale 移入归档后，runner 按原路径追加会在
    活跃目录重建产物，续写与终态事件只落在顶层副本——此时顶层（较新、含终态）
    晚于归档副本（截断前缀、无终态），按「归档为准」删除会销毁较新记录且归档
    副本永无终态。仅顶层不晚于归档副本时才允许走删除路径；stat 失败不可验证
    时同样保留顶层（宁可下轮重判，不可销毁未核实的新数据）。
    """
    try:
        return p.stat().st_mtime > dest.stat().st_mtime
    except OSError:
        return True


# 顶层副本比归档副本新的已告警去重（code-review item b4a5ba2f8cd1）：守卫
# 命中态在 SPEC 归档前无法收敛（归属活跃 SPEC 的归档副本不被天龄兜底删除、
# 顶层副本保持终态可归档判定恒命中），每清理周期逐条重报会产生无界重复
# 日志——进程内按文件名去重，同名只告警一次。
_RETENTION_TOP_NEWER_WARNED: set = set()


def _retention_top_newer_warned() -> set:
    """已告警文件名集（超界整体清空：文件名集与归档滞留量同阶，正常极小）。"""
    if len(_RETENTION_TOP_NEWER_WARNED) > 1024:
        _RETENTION_TOP_NEWER_WARNED.clear()
    return _RETENTION_TOP_NEWER_WARNED


def runs_retention_check(project_root, config: dict | None = None, logger=None) -> dict:
    """daemon 周期 runs 保留清理（fix-dashboard-read-path-performance D4）。

    两步（各自独立失败互不阻断，异常记日志不抛）：
    1. 终态（done/error/interrupted/cancelled/superseded/gate-blocked，及 stale
       断尾）run 从活跃 runs/ 移入 archive/——活跃目录有界性由「终态即移出」保证。
       同 run_id 归档副本已存在时删除顶层副本（轻量判等后仍以归档为准，分歧记
       WARNING），删除不计入 moved、单独记日志；顶层副本 mtime 晚于归档副本者
       除外——那是归档后按原路径重建的较新记录（含续写与终态事件），保留顶层
       并记 WARNING（code-review item f7332957913b）。
    2. 无主车道归档产物天龄兜底（fix-run-cleanup-attach-spec-archive D2）：
       ``archive/*.jsonl`` 中 run_spec_part 不属于活跃 SPEC 集（``spec/changes/``
       目录名集合，每周期现算）且 mtime 超过 ``_LANE_RUN_RETENTION_DAYS`` 天者
       删除；逐条记日志（文件名可追溯）、每周期删除量有批次上限
       （_RETENTION_DELETE_PER_CYCLE_MAX），不静默大批量删除。活跃 SPEC 集扫描
       失败 fail-closed：跳过本轮兜底仅记 WARNING（防误删活跃 SPEC 产物）。
       归属活跃 SPEC 的归档产物不被本步删除——SPEC 归档时由 archive_spec_runs
       统一清理，产物生命周期绑定 SPEC 生命周期。

    Args:
        project_root: 项目根目录
        config: 兼容保留参数（runs.keep 消费点已随 fix-run-cleanup-attach-spec-archive
            移除，本参数不再被消费；daemon 调用方签名稳定优先）。
        logger: Logger 实例（可选；缺省经 logging 模块 stderr 记录）

    Returns:
        {"moved": int, "deleted": int, "archive_total": int,
         "deleted_names": [str, ...], "error": str | None}

    ``error`` 为本轮清理的降级摘要（活跃目录/spec/changes/归档目录扫描失败
    等扫描级失败，多项以 ``"; "`` 连接；全成功为 None）——调用方可据此感知
    本轮清理是否降级，无须翻日志。
    """
    proot = Path(project_root)
    runs_dir = proot / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return {
            "moved": 0,
            "deleted": 0,
            "archive_total": 0,
            "deleted_names": [],
            "error": None,
        }

    # 1. 终态 run 移入归档（同 run_id 归档副本已存在时改为删除顶层副本——
    #    判等后仍以归档为准，不计入 moved；顶层副本比归档副本新则保留顶层，
    #    见去重删除守卫）
    moved = 0
    # 扫描级失败摘要（code-review item b15df4b11c6c）：失败态此前只落 WARNING
    # 日志、error 恒 None，调用方无法感知本轮清理已降级——各扫描失败分支在此
    # 追加摘要，返回时 "; " 连接（全成功为 None）。
    errors: list = []
    try:
        actions = 0  # 每周期动作量上限计数（移入 + 去重删除），与返回值 moved 解耦
        for p in runs_dir.glob("*.jsonl"):
            if actions >= _RETENTION_MOVE_PER_CYCLE_MAX:
                break
            if not _is_run_archivable(p):
                continue
            archive_dir = runs_dir / "archive"
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / p.name
                if dest.exists():
                    # 去重删除守卫（code-review item f7332957913b）：顶层副本比归档
                    # 副本新时不得按「归档为准」删除。该形态源于本函数把停更超
                    # _RUN_STALE_SECONDS 的在飞 run 判 stale 移档后，runner 按原路径
                    # 追加在活跃目录重建产物——续写与终态事件只落在顶层副本，删顶层
                    # 会丢失较新记录且归档副本永无终态。保留顶层并告警，待 SPEC 归档
                    # /人工对账收口；在飞误判 stale 的上游概率由阈值注释声明接受，
                    # 此处只堵「销毁较新数据」这一真实损害。
                    if _retention_top_copy_newer(p, dest):
                        # 同名重复告警去重（code-review item b4a5ba2f8cd1）：
                        # 收敛路径——无主车道等第 2 步天龄兜底（14 天）删掉归档
                        # 副本后重新走移档分支；活跃 SPEC 至 archive_spec_runs
                        # 归档清理。收敛前每周期只首报一次。
                        if p.name not in _retention_top_newer_warned():
                            _retention_top_newer_warned().add(p.name)
                            _retention_log(
                                logger,
                                "warning",
                                f"runs 保留: 顶层副本比归档副本新，跳过同名去重删除以保留较新记录 {p.name}",
                            )
                        actions += 1
                        continue
                    # 去重删除前做轻量判等（code-review item 750bb741c8fd）：旧实现
                    # 无条件 unlink 且不留日志、仍计入 moved（误报「移入归档」），
                    # 仅在「归档副本与顶层副本同源」假设下安全。顶层副本因本函数
                    # retention 移档后又按原路径追加终态行（如 daemon 重启
                    # interrupted 补写）与归档副本分歧时，较新产物会被静默销毁、
                    # 排障无迹。对齐 archive_spec_runs（item ca47fc88588f）：分歧记
                    # WARNING 再删；删除路径单独记日志使清理动作可审计。
                    if _retention_files_differ(p, dest):
                        _retention_log(
                            logger,
                            "warning",
                            f"runs 保留: 顶层副本与归档副本内容分歧，仍按归档为准删除顶层 {p.name}",
                        )
                    _retention_log(
                        logger, "info", f"runs 保留: 删除活跃同名副本（归档已存在） {p.name}"
                    )
                    p.unlink()
                else:
                    p.replace(dest)
                    moved += 1
                    _retention_log(logger, "info", f"runs 保留: 终态 run 移入归档 {p.name}")
                actions += 1
            except OSError as e:
                _retention_log(logger, "warning", f"runs 保留: 移入归档失败 {p.name}: {e}")
    except OSError as e:
        _retention_log(logger, "warning", f"runs 保留: 活跃目录扫描失败: {e}")
        errors.append(f"活跃目录扫描失败: {e}")

    # 2. 无主车道归档产物天龄兜底（fix-run-cleanup-attach-spec-archive D2/D3）
    deleted = 0
    deleted_names: list = []
    archive_total = 0
    archive_dir = runs_dir / "archive"
    try:
        active_specs = _active_spec_names(proot)
    except OSError as e:
        # fail-closed：活跃 SPEC 集扫描失败（含 spec/changes 不存在）时无法区分
        # 无主/有主，跳过本轮兜底防把活跃 SPEC 产物大规模误删，仅记 WARNING。
        _retention_log(
            logger, "warning", f"runs 保留: spec/changes 扫描失败，本轮跳过无主产物兜底: {e}"
        )
        errors.append(f"spec/changes 扫描失败，本轮跳过无主产物兜底: {e}")
        active_specs = None
    if active_specs is not None:
        try:
            if archive_dir.is_dir():
                cutoff = time.time() - _LANE_RUN_RETENTION_DAYS * 86400
                archive_files = list(archive_dir.glob("*.jsonl"))
                archive_total = len(archive_files)
                victims = []
                for p in archive_files:
                    if len(victims) >= _RETENTION_DELETE_PER_CYCLE_MAX:
                        break
                    if run_spec_part(p.stem) in active_specs:
                        continue
                    # 单文件 stat 失败（并发删除/移动等 OSError 子类）保守跳过
                    # （视为有主不删），不放大为放弃本周期整轮兜底。
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    if mtime < cutoff:
                        victims.append(p)
                for victim in victims:
                    try:
                        victim.unlink()
                        deleted += 1
                        deleted_names.append(victim.name)
                        _retention_log(
                            logger,
                            "info",
                            f"runs 保留: 删除无主归档产物 {victim.name}"
                            f"（归属无活跃 SPEC 且超 {_LANE_RUN_RETENTION_DAYS} 天）",
                        )
                    except OSError as e:
                        _retention_log(
                            logger, "warning", f"runs 保留: 删除失败 {victim.name}: {e}"
                        )
        except OSError as e:
            _retention_log(logger, "warning", f"runs 保留: 归档目录扫描失败: {e}")
            errors.append(f"归档目录扫描失败: {e}")

    return {
        "moved": moved,
        "deleted": deleted,
        "archive_total": archive_total,
        "deleted_names": deleted_names,
        "error": "; ".join(errors) or None,
    }
