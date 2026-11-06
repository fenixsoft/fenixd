"""maintenance_ledger.py — 维护型/延伸型工作轻量登记台账（maintenance-work-ledger）。

框架流水线只有 spec 全流程一种记账形态：spec done 后的延伸/维护型工作与
散件没有认领出口，从产生即无主（告警无法路由、记账不可见）。本模块提供
最小登记通道：一行登记（时间、范围、执行者、证据位置）落到项目级台账
文件 ``.fenix/maintenance_log.jsonl``，延伸/维护型工作开工或收尾时自助落账。

关键取舍（design）：独立 jsonl 而非 STATE.md 新节——STATE 写者是全量重写
语义（_admit_entry 丢弃非 spec 条目），混入登记条目会被抹掉；独立文件零
风险且可追加。台账只登记事实，不派生执行车道；条目的 ``run_id`` 字段与
``maintenance-`` 前缀 run 关联（R3），供告警归因与复盘引用。
"""

from pathlib import Path
import json
import secrets
import time

# 原子追加复用 run_files 的成文约定（单行单次写入；行超
# _ATOMIC_APPEND_LINE_BYTES=4096 时走二进制 os.write，O_APPEND 下由内核对
# 并发写者串行化——先例 code-review item 29df176ff441：TextIOWrapper 长行
# 会裂成多次 raw write、与并发写者交错产生半行 JSON 被读侧跳过）。台账落账
# 是执行者自助（执行者进程与 daemon 可并存并发写），并非单进程顺序写。
from core.agent_runner.run_files import append_run_line
from core.timelib import now_utc, to_storage

# 项目级台账文件名（相对 <project>/.fenix/）
LEDGER_FILENAME = "maintenance_log.jsonl"


def _ledger_path(project) -> Path:
    return Path(project) / ".fenix" / LEDGER_FILENAME


def append_maintenance_entry(project, scope, actor, evidence, note, run_id=None) -> dict:
    """追加一条登记到项目台账，返回写入的条目（含生成的 ts）。

    文件不存在则创建（含 .fenix 目录）；写入用追加模式并沿用 run_files.py
    的原子追加约定。字段：ts / scope / actor / evidence / note / run_id
    （run_id 未提供时写 None，字段恒在——读侧契约稳定）。
    """
    entry = {
        "ts": to_storage(now_utc()),
        "scope": str(scope),
        "actor": str(actor),
        "evidence": str(evidence),
        "note": str(note),
        "run_id": run_id,
    }
    path = _ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_run_line(path, entry)
    return entry


def list_maintenance_entries(project) -> list:
    """读取全量台账条目（旧→新），坏行容错跳过；文件不存在返回空列表。

    坏行（非法 JSON / 非 dict 顶层 / 空行）不中断读取——台账是并发追加的
    jsonl，半行交错（写侧已按原子约定防）或手工编辑损伤不应让全量读取失败。
    """
    try:
        text = _ledger_path(project).read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    entries = []
    # code-review item 34ace64df65c：按 \n 硬分割而非 splitlines()——写侧
    # json.dumps(ensure_ascii=False) 不转义 U+2028/U+2029，splitlines() 会按
    # 其边界拆行，含此类字符的登记条目裂成两个半行 JSON、双双解析失败被跳过
    # （落盘单行内唯一的真实换行即写侧追加的 \n，json 对 \r 等控制符恒转义；
    # 行尾 .strip() 兜住 \r\n）。
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


# code-review item 007fb4732748：run_id 唯一性探测只需近期条目——撞名候选
# 携带 epoch 秒段（base = maintenance-<scope>-<int(time.time())>），能与
# 候选全等相等的既有条目必然写于同一秒内、必落在台账文件尾部；唯一性对
# 全量历史去重没有语义要求（候选随机段 x<4hex> 已把并发撞名概率压到可
# 忽略），尾窗限量探测足够，登记路径的读 IO 与逐行解析成本从随台账逐年
# 累积线性上涨降为常量。
_PROBE_TAIL_LINES = 512


def _tail_maintenance_entries(project, max_lines: int = _PROBE_TAIL_LINES) -> list:
    """按行数从台账尾部限量读取有效条目（旧→新，至多 max_lines 条）。

    二进制分块自文件尾向前扩读、不整读文件——限量读的意义在同时封住读 IO
    与逐行 JSON 解析两头的线性成本（item 007fb4732748）。坏行容错（非法
    JSON / 非 dict 顶层 / 空行跳过）与 list_maintenance_entries 同口径。
    """
    path = _ledger_path(project)
    try:
        size = path.stat().st_size
    except OSError:
        return []
    chunk = 65536
    start = size
    try:
        with path.open("rb") as fh:
            while True:
                start = max(0, start - chunk)
                fh.seek(start)
                data = fh.read(size - start)
                if start > 0:
                    # 起点大概率切在半行中间：丢弃到本块首个换行为止；
                    # 整块落在同一超长行内时继续向文件头扩块
                    nl = data.find(b"\n")
                    if nl == -1:
                        continue
                    data = data[nl + 1:]
                if data.count(b"\n") >= max_lines or start == 0:
                    break
    except OSError:
        return []
    entries = []
    for line in data.decode("utf-8", errors="replace").split("\n")[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def make_maintenance_run_id(scope: str, project=None) -> str:
    """生成登记型 run id：``maintenance-<scope>-<epoch 秒>``。

    base 形态与既有 ``<prefix><spec>-<ts>`` 一致，使
    run_files.infer_run_agent_type 归属 "maintenance"。

    code-review item f22262c39d1e：秒级时间戳在「同秒同 scope 两次登记」下
    撞名——list_entries_for_run 按 run_id 全等过滤会把两次执行的条目混在
    一起，告警归因与复盘引用失真。初版 docstring 声称与 maintenance_runs.py
    两处 run id 生成点「同款」，但那两处（_unique_admin_run_id /
    _unique_evolution_run_id）实际已各自包了 ``-<n>`` 探测退避防撞，本函数
    同步跟进：提供 project 时经尾部限量读侧（_tail_maintenance_entries，
    item 007fb4732748）探测候选 run_id 是否已在台账出现，已存在即追加
    ``-<n>``（n 从 1 起递增）——撞名候选携带 epoch 秒段，冲突条目必落台账
    尾窗内，限量探测对唯一性语义足够、成本不随台账累积线性上涨。
    探测台账而非落申领占位：台账是纯登记簿（追加行 + 读侧扫描），
    run_id 只作关联键、无独立产物文件可申领。退避 run 尾段变为
    ``-<rand>-<n>``（仅 project=None 的 base 形态无随机段），
    admin_monitor._spec_from_run_id 的 ``-\\d{9,}(-(?:a|r)\\d+)*$`` 尾锚不再
    命中、scope 还原返回 None（回落泛型主体），与 code-review-<epoch>-<n>
    退避先例同口径；item 8a1e2c8bfa1e 起凡 project 非 None 的 run id 恒带
    ``-x<rand>`` 尾段（见下段），该尾锚恒不命中、还原一律回落泛型主体。

    code-review item 8a1e2c8bfa1e：探测与实际 append 之间无互斥/原子申领，
    两进程（执行者进程与 daemon 可并存并发写）同秒同 scope 并发落账时双方
    探测均未命中、各取同一 base，残余竞态仍产生同 run_id。混入短随机段把
    并发撞名概率降为可忽略（固定 ``x`` 引导 + 4 位 hex，65536 取值空间）：
    ``x`` 引导保证尾段不落入 run_files.RUN_ID_SUFFIX_RE 的 ``-a<n>``/``-r<n>``
    attempt 形态、也不满足 admin_monitor._spec_from_run_id 的 ``-\\d{9,}``
    尾锚（与既有 ``-<n>`` 退避同口径回落泛型主体）；随机段居尾，时间前缀
    保序。探测退避保留：串行的同秒同 scope 重复登记仍走确定性
    ``-<rand>-<n>`` 防撞。
    project=None 时保持纯 base 形态不变（无台账可探测的调用方形态稳定）。

    Args:
        scope: 登记范围名（进入 run id 的归因段）。
        project: 项目根（str/Path）；提供时启用台账探测退避与随机段，None
            时仅返回 base 形态（无既有台账可探测，如单测/生成即落账前的调用方）。
    """
    base = f"maintenance-{scope}-{int(time.time())}"
    if project is None:
        return base
    rand = f"x{secrets.token_hex(2)}"
    candidate = f"{base}-{rand}"
    n = 0
    # item 007fb4732748：探测走尾部限量读侧，不再全量读取台账
    existing = {e.get("run_id") for e in _tail_maintenance_entries(project)}
    while candidate in existing:
        n += 1
        candidate = f"{base}-{rand}-{n}"
    return candidate


def list_entries_for_run(project, run_id: str) -> list:
    """按 run_id 过滤台账条目（R3 关联读侧：告警归因/盘点按 run 反查登记）。

    item 007fb4732748：反查语义要求覆盖完整历史（老 run 的登记行可落在
    台账任意深处），故不做尾部限量、保持全量扫描；尾部限量只适用于
    run_id 唯一性探测（_tail_maintenance_entries）。
    """
    return [
        e for e in list_maintenance_entries(project) if e.get("run_id") == run_id
    ]
