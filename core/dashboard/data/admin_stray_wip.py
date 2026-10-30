"""core.dashboard.data.admin_stray_wip — 主树散件 WIP 根治执行器。

code-review item 2b295d77482e（D3 分组惯例）：admin_actions.py 中 evo-stray
系列的主树 git 散件根治族（commit/untrack_stray_wip 与 untracked 认领的
archive/ignore/delete）整体拆出本模块——三类职责（请求信号与 STATE 写操作 /
裁决映射执行器 / 主树 git 散件根治）的失败语义、测试面与改动频率不同，
独立成模块降低单文件定位与并行改动摩擦。函数体逐行原样搬移，零逻辑改动。

兼容约定：admin_actions.py 顶部显式 re-export 本模块全部迁出符号，旧导入
路径（tests 与 core.worktree_manager.stray_wip 经 admin_actions 导入
parse_stray_wip_manifest / _exec_*）保持有效；.gitignore 字节写助手
_atomic_write_bytes 为两模块共用（admin_actions 的场景修订回滚亦消费），
同经 re-export 解析。

signal_type 绑定守卫单源（design D4）：本族执行器是 admin 处置动作中对主树
执行 git 写/文件触碰的唯一暴露面，各执行器入口 fail-closed 校验
signal_type 白名单（详见各常量注释）。
"""

import fcntl
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.admin_stray_wip")


# ── 主树散件 WIP 提交（evo-add-commit-stray-wip-choice 2.1）──────────────

# signal_type 绑定守卫单源（design D4）：commit_stray_wip 是 admin_actions
# 首个对主树执行 git 写的执行器（现存执行器只动 spec 状态机/配置），而
# resolve_choice 对未注册信号存在「非 spec_scoped 动作全表反查放行」通道
# （adjudication_choices.resolve_choice 解析序 2）——注册为非作用域动作后，
# 任意未注册 signal_type（含姊妹 info 信号 maintree_untracked_stray_stale）
# 都能解析到它。执行器 MUST 校验 signal_type 与本常量全等，其余一律拒绝
# （零 git 写），把 git 写暴露面收口到 maintree_stray_wip_stale。
COMMIT_STRAY_WIP_SIGNAL_TYPE = "maintree_stray_wip_stale"


def parse_stray_wip_manifest(evidence) -> list:
    """从信号记录 evidence 解析「文件清单(N):」段（stray_wip 内嵌 prose）。

    stray_wip._write_alert 把清单以 ``文件清单(N): a, b;`` 形态内嵌进 evidence
    文本（无结构化字段），本函数按段解析：返回清单内相对路径列表（保序
    去重）；无清单段 / 清单为「无」→ 空列表。只做段级文本解析，不做路径
    合法性裁决（合法性由调用方以「清单 ∩ 当刻 git status」求交保证）。

    分号截断缓解（code-review item 2dc676288186）：清单段以 ``;`` 收尾且
    文件名无转义，``[^;]+`` 在文件名自带的分号处截断、其后条目静默丢失
    （逗号拆散是碎片仍可探测，分号截断是丢尾）。声明计数 N 与实际解析
    条目数不符时 logger.warning 留痕，供人工按 evidence 原文核对——根治
    须写读两侧成对改结构化清单字段（stray_wip.py 在修复清单外）。
    """
    m = re.search(r"文件清单\((\d+)\):\s*([^;]+)", str(evidence or ""))
    if not m:
        return []
    declared = int(m.group(1))
    raw = m.group(2).strip()
    if not raw or raw == "无":
        return []
    # 写侧截断注记剥离（code-review item 25c02e6d1261，与
    # stray_wip._evidence_file_manifest 成对单源）：清单超 50 条时尾部附
    # 「等 N 项」（N＝声明总数），不剥离会被当作末位路径拼进清单、令执行器
    # 对着不存在的路径求交落空。截断态下「声明 N 条、实解析 50 条」属预期
    # 差异，豁免下方分号截断告警。
    truncated = False
    tail = re.search(r"\s等\d+项$", raw)
    if tail:
        truncated = True
        raw = raw[: tail.start()].rstrip()
    out: list = []
    for item in raw.split(","):
        p = item.strip()
        if p and p not in out:
            out.append(p)
    if declared and not truncated and len(out) != declared:
        logger.warning(
            "stray_wip 清单疑似分号截断：声明 %d 条、实解析 %d 条"
            "（文件名含分号会在该处截断丢尾），请按记录 evidence 原文人工核对",
            declared, len(out),
        )
    return out


def _stray_manifest_comma_fragments(candidates, probe) -> list:
    """检测清单疑似因文件名含逗号被按逗号切散的碎片路径（item 86cda9326ae7）。

    写侧 stray_wip._evidence_file_manifest 以 ``', '.join(files)`` 生成清单段
    且无转义，本模块 parse_stray_wip_manifest 按逗号切分——文件名本身含逗号
    时被拆成不存在的碎片路径，各执行器与当刻 status/磁盘求交全部落空，该
    散件永远无法经裁决动作处置。根治须写读两侧成对改（NUL 分隔或结构化
    清单字段），stray_wip.py 在修复清单外；本模块单侧缓解：把相邻候选按
    ``,`` 与 ``, ``（写侧 join 的两种分隔形态）重新拼合，probe（当刻 status
    路径集成员判定或磁盘存在判定）命中即视为疑似拆散碎片返回，供调用方在
    求交失败的 error/steps 附提示。只提示不改执行集合——重新拼合是对含糊
    文本的猜测性再分割（无法区分 'a,b.py'+'c' 与 'a'+'b,c.py'），不据此
    放行 git 写/文件触碰。连续拼合窗口限 6 段（覆盖单文件名至多 5 个逗号），
    防全量两两拼合的平方级膨胀。
    """
    frags: list = []
    n = len(candidates)
    for i in range(n):
        acc_cs = str(candidates[i])
        acc_cs_sp = acc_cs
        for j in range(i + 1, min(i + 6, n)):
            acc_cs = f"{acc_cs},{candidates[j]}"
            acc_cs_sp = f"{acc_cs_sp}, {candidates[j]}"
            for cand in (acc_cs, acc_cs_sp):
                if cand not in frags and probe(cand):
                    frags.append(cand)
    return frags


def _git_out(project_root, *args: str) -> str:
    """在 project_root 跑 git 命令，返回 stdout；非零退出抛 RuntimeError。

    固化解码口径 + 超时（code-review item f4c753f87e84）：text=True 缺省按
    随 locale 的默认编码解码，消费面含 ``status --porcelain -z`` /
    ``ls-files -z``（-z 对非 ASCII 路径原样输出字节），非 UTF-8 locale 下
    抛 UnicodeDecodeError——pipeline._fix_diff_files 同形态实测事故，修法
    对齐其 code-review item de067b5e1d70（encoding="utf-8"+errors="replace"）；
    无 timeout 时索引锁被占/hook 挂起会无限阻塞调用线程（alert-resolve/
    admin 处置端点所在线程），取 30s（与 _path_already_ignored 同口径），
    超时抛 RuntimeError 由各调用方既有 except 分支兜底。
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"git 命令超时（30s）: {' '.join(args[:2])}") from e
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout


def _git_status_paths(project_root) -> set:
    """当刻 ``git status --porcelain -z`` 涉及路径集（-z 免引号；含 rename 双侧）。"""
    tokens = _git_out(project_root, "status", "--porcelain", "-z").split("\0")
    paths: set = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        # porcelain v1 行形态 ``XY <path>``（XY 两状态字符 + 空格）；rename/
        # copy 的 orig path 跟随在独立 NUL 字段（无 XY 前缀），显式消费。
        if len(tok) >= 4 and tok[2] == " ":
            paths.add(tok[3:])
            if tok[0] in ("R", "C") and i < len(tokens):
                paths.add(tokens[i])
                i += 1
    return paths


def _latest_stray_wip_manifest(project_root, signal_type: str) -> list:
    """store 内最新一条含可解析清单的 signal_type SIGNAL 记录 → 文件清单。

    strays 执行器（commit/untrack）共用的清单单源：read_all 倒序返回，取
    最新可解析记录；无匹配记录 / store 不可读 → 空列表（调用方按「无清单
    不执行 git 写」处置）。
    """
    from core.admin_store import SIGNAL, AdminStore

    try:
        records = AdminStore(Path(project_root), logger=None).read_all()
    except Exception:
        return []
    for rec in records:
        if (rec.get("kind") != SIGNAL
                or rec.get("signal_type") != signal_type):
            continue
        manifest = parse_stray_wip_manifest(rec.get("evidence"))
        if manifest:
            return manifest
    return []


def _exec_commit_stray_wip(project_root, note: str = "", signal_type: str = "",
                           paths=None) -> dict:
    """commit_stray_wip：提交主树信号清单内的散件 WIP（全局信号专用）。

    约束（design D2/D4）：
    - signal_type 绑定守卫：仅 maintree_stray_wip_stale 可触达（其余信号类型
      ——含未注册信号与姊妹信号 maintree_untracked_stray_stale——一律拒绝，
      零 git 写）；
    - 文件来源 MUST 限信号记录 evidence 的「文件清单(N):」段与当刻
      ``git status --porcelain`` 的交集，拒任意路径；清单中已不在当刻 status
      的文件跳过不报错（同指纹一次性告警，清单会陈旧）；交集内未跟踪条目
      不随本动作提交（pathspec 提交对未跟踪文件必 fatal），提示走
      untrack_stray_wip；交集为空返回明确 error、不产生空提交；
    - 非 destructive（提交可回溯），无需确认门；成功结果附提交 hash。
      提交已落库而哈希回读失败（如超时）不回滚也不报失败，commit_hash 为
      空串并在 steps 说明（同 _exec_untrack_stray_wip 口径）。

    paths 仅供程序化调用方显式收窄提交范围（MUST 为清单子集，清单外路径
    拒绝，零 git 写）；缺省从 store 内最新一条含可解析清单的
    maintree_stray_wip_stale SIGNAL 记录解析（同指纹一次性告警语义下在途
    记录至多一条；execute_adjudication_choice 契约不携带告警 id，故按记录
    自取）。提交经 pathspec 形态（``git commit -- <paths>``）：只落清单内
    路径的工作区内容，不裹挟索引中其它暂存改动。
    """
    from core.admin_store import SIGNAL, AdminStore

    # D4 绑定守卫：在任何 git 读/写之前 fail-closed。
    sig = str(signal_type or "").strip()
    if sig != COMMIT_STRAY_WIP_SIGNAL_TYPE:
        return {
            "ok": False, "steps": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 commit_stray_wip"
                      f"（仅限 {COMMIT_STRAY_WIP_SIGNAL_TYPE}；git 写暴露面"
                      f"收口到本信号，design D4）"),
        }

    proot = Path(project_root)
    # 清单单源：信号记录 evidence 清单段（拒任意路径）。
    manifest = _latest_stray_wip_manifest(proot, COMMIT_STRAY_WIP_SIGNAL_TYPE)
    if not manifest:
        return {
            "ok": False, "steps": [],
            "error": ("未找到含可解析文件清单的 maintree_stray_wip_stale 信号"
                      "记录（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行 git 写"),
        }

    # 显式 paths 白名单校验：清单外路径拒绝（零 git 写）。
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "ok": False, "steps": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)

    # 与当刻 git status 求交：清单中已不在当刻 status 的文件跳过不报错。
    try:
        dirty = _git_status_paths(proot)
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：_git_out 的
        # RuntimeError 消息含最多 300 字符 git stderr 原文，可能携带仓库内部
        # 路径，细节经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "commit_stray_wip 读取 git status 失败: %s: %s",
            type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "读取 git status 失败（详见服务端日志）"}
    to_commit = [p for p in candidates if p in dirty]
    skipped = [p for p in candidates if p not in dirty]
    # 含逗号文件名拆散检测（item 86cda9326ae7，见 helper docstring）：碎片
    # 落空时在拒绝 error/steps 附提示，不据此改写执行集合。
    comma_frags = (
        _stray_manifest_comma_fragments(candidates, dirty.__contains__)
        if skipped else []
    )
    if not to_commit:
        err = ("信号清单内文件已全部不在当刻工作区改动中（同指纹一次性"
               "告警，清单陈旧），不产生空提交；"
               f"清单({len(manifest)}): {', '.join(manifest)}")
        if comma_frags:
            err += (f"；另检测到清单段疑因文件名含逗号被切散出 "
                    f"{len(comma_frags)} 个碎片路径"
                    f"（{', '.join(comma_frags)}），本动作无法处置"
                    "（清单段按逗号切分、写侧无转义的格式限制）")
        return {"ok": False, "steps": [], "error": err}

    # 未跟踪分流（code-review item 48fc7cf0837c）：porcelain 交集自然混入
    # 未跟踪（??）条目，而 ``git commit -- <path>`` 对未跟踪文件报 fatal
    # 「pathspec did not match any file(s) known to git」，任一未跟踪项即
    # 整批提交放弃。tracked/未跟踪两态分流：只提交 tracked 子集；未跟踪
    # 散件按分工走 untrack_stray_wip（出库+ignore 根治，对已脱离索引条目
    # 幂等跳过），此处提示不报错。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：同上，git stderr
        # 原文经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "commit_stray_wip 读取 git 索引失败: %s: %s",
            type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "读取 git 索引失败（详见服务端日志）"}
    untracked = [p for p in to_commit if p not in indexed]
    to_commit = [p for p in to_commit if p in indexed]
    if not to_commit:
        return {
            "ok": False, "steps": [],
            "error": ("信号清单∩当刻改动内文件均未被 git 跟踪（未跟踪散件按"
                      "分工应走 untrack_stray_wip），不产生提交；"
                      f"清单({len(manifest)}): {', '.join(manifest)}"),
        }

    try:
        msg = (f"[fenix] admin: 提交主树散件 WIP"
               f"（{COMMIT_STRAY_WIP_SIGNAL_TYPE} 信号清单内 "
               f"{len(to_commit)} 文件）")
        if note:
            msg += f"\n\n裁决依据：{note}"
        _git_out(proot, "commit", "-m", msg, "--", *to_commit)
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：同上，git stderr
        # 原文经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "commit_stray_wip git 提交失败: %s: %s", type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "git 提交失败（详见服务端日志）"}

    # pathspec 锚定读哈希（code-review item 7fe327348b37，同
    # archive_commit.commit_archive_move / queue.py 既有口径：不用
    # rev-parse HEAD，防 commit→读取窗口内并发提交记到别人头上，审计
    # 追溯失真）。
    # 回读 MUST 与上方 commit 分离（code-review item a107cdc890b0，同
    # dd2262c17587 在 _exec_untrack_stray_wip / _append_gitignore_and_commit
    # 已修的同形轻症）：此处失败时提交已落库，若仍并入 commit 的 try 走
    # 失败分支，调用方会据「git 提交失败」重试而产出重复提交，审计结果与
    # 盘面不一致。回读失败仅 WARNING 留痕，commit_hash 置空并在 steps 说明。
    commit_hash = ""
    try:
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", *to_commit,
        ).strip()
    except (OSError, RuntimeError) as e:
        # 不外泄裸异常文本（code-review item e584a2ede367 同口径）。
        logger.warning(
            "commit_stray_wip 提交已落库但哈希回读失败: %s: %s",
            type(e).__name__, e,
        )
    steps = [
        f"提交主树散件 WIP {len(to_commit)} 个文件（信号清单∩当刻改动）："
        f"{', '.join(to_commit)}",
    ]
    if commit_hash:
        steps.append(f"提交 hash: {commit_hash}")
    else:
        steps.append("提交已落库但哈希回读失败（commit hash 缺失，详见服务端日志）")
    if skipped:
        steps.append(
            f"清单内已不在当刻改动、跳过 {len(skipped)} 个：{', '.join(skipped)}"
        )
    if comma_frags:
        steps.append(
            f"检测到清单段疑因文件名含逗号被切散出 {len(comma_frags)} 个碎片"
            f"路径（{', '.join(comma_frags)}），未纳入本动作（清单段按逗号"
            "切分、写侧无转义的格式限制）"
        )
    if untracked:
        steps.append(
            f"清单内未跟踪散件 {len(untracked)} 个不随本动作提交"
            f"（pathspec 提交仅限 tracked；走 untrack_stray_wip 根治）："
            f"{', '.join(untracked)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "commit_hash": commit_hash,
        "committed_files": to_commit,
    }


# ── 主树复发型散件根治 untrack（evo-recurring-stray-remediation 1.2）──────

# signal_type 绑定守卫单源：与 commit_stray_wip 同一信号（design D4 同款
# 收口逻辑——resolve_choice 非作用域全表反查通道对本动作同样可达，执行器
# MUST 校验 signal_type 后才落 git 写）。
UNTRACK_STRAY_WIP_SIGNAL_TYPE = COMMIT_STRAY_WIP_SIGNAL_TYPE


def _path_already_ignored(proot, path: str) -> bool:
    """path 是否已被既有 ignore 规则覆盖（check-ignore --no-index 口径）。

    tracked 文件的普通 check-ignore 恒为非忽略（误报，stash_guard 同款教训），
    ``--no-index`` 只按 ignore 规则判定。git 不可用/超时按「未忽略」处理
    （保守追加，去重由字面行比对兜底）。

    解码口径与 _git_out 同款固化（code-review item d1081ee9fee8）：
    ``encoding="utf-8" + errors="replace"``（裸 text=True 缺省按 locale 解码，
    非 UTF-8 locale 下非 ASCII 字节流会抛 UnicodeDecodeError）；解码异常
    仍按「未忽略」保守处理。

    ``path`` 是**字面路径名**（check-ignore 对待测路径不按模式解析），
    故不做 gitignore 语法转义——转义只作用于写入 .gitignore 的规则行与
    字面行去重（_gitignore_escape_entry，code-review item f0d504af6cac）。
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(proot), "check-ignore", "--no-index", "-q", "--", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        # ValueError 兜 UnicodeDecodeError（code-review item d1081ee9fee8，
        # 解码口径对齐 _git_out 既有固化 f4c753f87e84；显式 encoding 后理论
        # 不可达，留作纵深防御），按「未忽略」保守追加语义处理。
        return False
    return r.returncode == 0


def _atomic_write_bytes(path, data: bytes) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子**字节**写。

    fs_utils.atomic_write_text 的字节形态（item 41c87143c57e）：.gitignore
    追加/还原路径须保留既有非 UTF-8 字节，不能经文本解码往返，而
    atomic_write_text 只收 str——本助手沿用同一原子纪律（唯一临时名防并发
    截断 + fsync + replace），供 .gitignore 字节级写回专用。

    权限位保留与父目录 fsync（code-review item af658e96d7aa，对齐
    fs_utils.atomic_write_text 同款附属纪律）：mkstemp 恒以 0600 建临时
    文件，直接 replace 会把目标文件权限重置为 0600——.gitignore 等经追加/
    还原回写后其他用户/工具不可读（多用户检出下忽略规则对协作面失效）。
    替换既有文件时继承其 mode；新文件放宽到 0644。rename 后尽力而为
    fsync 父目录（目录项持久化，掉电不回退）。chmod 与目录 fsync 失败均
    不阻断写回主流程（权限/持久性是尽力而为的附属属性）。
    """
    path = Path(path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            # 单次 os.stat，以 FileNotFoundError 区分「不存在→0644」与
            # 「其他 OSError→跳过 chmod」（fs_utils.atomic_write_text 的
            # item 7b94b65d0f0c 同款：exists+stat 双探测在两步间目标被
            # 并发删除时会连带跳过 chmod）。
            try:
                mode = os.stat(path).st_mode & 0o777
            except FileNotFoundError:
                mode = 0o644
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
        # 尽力而为 fsync 父目录（rename 的目录项变更须刷父目录才有掉电
        # 持久化保证，item f19b8ef57ce6 同口径）；目录 fsync 个别文件系统
        # 不支持，失败不阻断主流程。
        try:
            dir_fd = os.open(str(parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _gitignore_escape_entry(entry: str) -> str:
    """把清单路径转义成 gitignore 字面匹配语义的规则行（item f0d504af6cac）。

    追加规则的目标是对清单路径**字面**忽略，但 gitignore 语法里首字符
    ``#`` 是注释、首字符 ``!`` 是反向排除、``* ? [ ]`` 是通配元字符、
    ``\\`` 是转义前缀、行尾空格被裁剪——含这些形态的文件名原样写入会
    语义失真，散件实际未被忽略（untrack_stray_wip 根治后文件重新浮现、
    同指纹告警复发）。转义口径：反斜杠与 glob 元字符前置 ``\\``、首字符
    ``#``/``!`` 前置 ``\\``、行尾空格逐个前置 ``\\``；普通文件名转义
    前后不变（零行为漂移）。
    """
    escaped = entry.replace("\\", "\\\\")
    escaped = re.sub(r"([*?\[\]])", r"\\\1", escaped)
    if escaped[:1] in ("#", "!"):
        escaped = "\\" + escaped
    escaped = re.sub(r" +$", lambda m: "\\ " * len(m.group()), escaped)
    return escaped


# 项目级 .gitignore 读-改-写互斥锁（code-review item b30e2e7dbcb7）：
# _atomic_write_bytes 只保证单次写的原子性，不串行化「读快照-追加/还原-
# 整文件 replace」序列——两个并发处置动作（人工裁决与 AdminMonitor 自动
# 执行同时触发 ignore/归档认领）各自基于旧快照落盘，后写者覆盖先写者，
# 先追加的 ignore 行静默丢失（散件未被忽略、同指纹告警复发）。比照
# AdminStore._lock 的 flock 口径为全模块 .gitignore 触碰点收口同一把锁；
# 锁文件落 ``.git/fenix-gitignore.lock``——.git 内容对 git status 恒不可见、
# 任何仓库（含测试临时检出）零新增散件面，落项目根或 .fenix 会在无既有
# 忽略规则的检出里自身成为 untracked 散件。flock 同进程跨 fd 亦互斥
# （AdminStore 同款），daemon 与 Dashboard 独立进程、ThreadingHTTPServer
# 每请求一线程均被串行化。
@contextmanager
def _gitignore_lock(proot):
    """.gitignore 读-改-写/快照还原序列的项目级排他锁（with 作用域持锁）。

    锁文件创建/acquire 失败（.git 缺失或不可写等异常环境）按 OSError 上抛，
    由调用方既有 OSError 兜底收敛为动作失败——锁不可得时放行写回会复活
    本锁要挡的并发丢写面，不静默降级。
    """
    lock_path = Path(proot) / ".git" / "fenix-gitignore.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lf = open(lock_path, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    finally:
        lf.close()


def _append_gitignore_entries(proot, paths) -> list:
    """把 paths 逐条追加进 .gitignore（去重），返回实际新增条目列表。

    条目先经 _gitignore_escape_entry 转义成字面匹配规则行再比对/写入
    （code-review item f0d504af6cac），返回与写入的都是转义后的行。
    去重双重口径：转义后条目字面行已在 .gitignore → 不重复写（幂等重入
    不增行）；``check-ignore --no-index`` 判定已被既有规则覆盖（如通配
    ``*.log``）→ 追加亦冗余，不写（复核仍传原始路径，见
    _path_already_ignored）。.gitignore 不存在则新建。

    读快照-去重判定-原子写回整体收进项目级排他锁（code-review item
    b30e2e7dbcb7，_gitignore_lock）：锁外并发追加各自基于旧快照整文件
    replace，后写者覆盖先写者、先追加的规则行静默丢失。
    """
    gi = Path(proot) / ".gitignore"
    with _gitignore_lock(proot):
        # 字节级读入（code-review item 41c87143c57e）：.gitignore 可能含历史手工
        # 编辑留下的非 UTF-8 字节，read_text(errors="replace") 再整文件回写会把
        # 坏字节静默改写成 U+FFFD——追加只增行，既有字节须原样保留。去重判定仍
        # 走文本口径（仅读侧比较，不回写）：合法行不受有损解码影响，比对不失真。
        raw = gi.read_bytes() if gi.exists() else b""
        have_lines = {
            ln.strip() for ln in raw.decode("utf-8", errors="replace").splitlines()
        }
        appended: list = []
        for p in paths:
            # 去重按转义后的字面行（item f0d504af6cac）：.gitignore 实际存的
            # 是转义行，按原始路径比对会漏判（如 # 开头文件名的历史行只是
            # 注释，永远等不到字面匹配）。
            entry = _gitignore_escape_entry(p)
            if entry in have_lines or _path_already_ignored(proot, p):
                continue
            appended.append(entry)
            have_lines.add(entry)
        if appended:
            sep = b"" if (not raw or raw.endswith(b"\n")) else b"\n"
            # 原子写回（code-review item c971a8de0638）：裸 write_bytes 非原子，
            # 进程中断/磁盘满可留下截断的 .gitignore（仓库忽略规则整体丢失面）
            # ——gi_backup 只覆盖 _abort 显式回滚路径，不覆盖写半程中断。改走
            # mkstemp+replace 原子字节写（atomic_write_text 同纪律的字节形态，
            # item 41c87143c57e：既有字节不经解码往返）。
            _atomic_write_bytes(
                gi, raw + sep + ("\n".join(appended) + "\n").encode("utf-8"))
    return appended


def _exec_untrack_stray_wip(project_root, note: str = "", signal_type: str = "",
                            paths=None) -> dict:
    """untrack_stray_wip：主树复发型散件当场根治（git rm --cached + .gitignore）。

    对告警指认文件清单执行出库 + ignore 规则追加 + 独立提交（design D4：
    untrack 与 .gitignore 追加原子成一批独立提交，不与处置中其他改动混合，
    可整体 revert 回滚）。约束：

    - signal_type 绑定守卫（design D4，同 _exec_commit_stray_wip）：仅
      maintree_stray_wip_stale 可触达，其余一律拒绝、零 git 写；
    - 文件来源 MUST 限信号记录 evidence「文件清单(N):」段（拒任意路径）；
      与当刻 git status 与索引求交——已不在 status 的跳过（清单陈旧）；仍在
      status 但已脱离索引的视为已根治过，跳过不报错（幂等重入）；可执行
      集合为空返回明确 error、不产生空提交；
    - 复用 stash_guard staged 子集守卫/回滚骨架：rm 循环 → staged 子集守卫
      （口径与 ``_untrack_index_paths`` 一致，额外放行 .gitignore——根治
      提交的另一半；staged 名单同源反转义）→ 裸 commit；回滚段复用
      ``G6StashGuardMixin._reset_index_paths``（经 _UntrackGuardProbe 最小
      宿主），追加的 .gitignore 一并还原（暂存态 reset + 文件内容恢复），
      任何中止分支不残留半程改动。不打开 stash_guard「check-ignore 全须
      忽略」前置门（design D1）。不能用 ``commit -- <paths>`` 限定：路径已
      被 rm --cached 移出 index，pathspec 解析必 fatal（stash_guard 同款
      教训），故裸 commit + staged 子集守卫；守卫快照与裸 commit 之间的
      并发裹挟窗口（人工 git 操作/自动处置并发暂存）由提交后
      ``show --name-only`` 集合复核兜底（code-review item cf800d2e5f17）：
      越界即 ``reset --soft HEAD^`` 撤销提交并整体还原、如实报错。

    paths 仅供程序化调用方显式收窄作用面（MUST 为清单子集，清单外拒绝，
    零 git 写）；缺省取 store 内最新一条含可解析清单的 maintree_stray_wip_stale
    SIGNAL 记录（execute_adjudication_choice 契约不携带告警 id，同
    commit 执行器按记录自取）。结果记录 untrack 文件清单（untracked_files）、
    .gitignore 实际新增条目（gitignore_appended）与提交号（commit_hash）。
    提交已落库而哈希回读失败（如超时）不回滚，commit_hash 为空串并在
    steps 说明。
    """
    # D4 绑定守卫：在任何 git 读/写之前 fail-closed。
    sig = str(signal_type or "").strip()
    if sig != UNTRACK_STRAY_WIP_SIGNAL_TYPE:
        return {
            "ok": False, "steps": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 untrack_stray_wip"
                      f"（仅限 {UNTRACK_STRAY_WIP_SIGNAL_TYPE}；git 写暴露面"
                      f"收口到本信号，design D4）"),
        }

    proot = Path(project_root)
    # 清单单源：信号记录 evidence 清单段（拒任意路径）。
    manifest = _latest_stray_wip_manifest(proot, UNTRACK_STRAY_WIP_SIGNAL_TYPE)
    if not manifest:
        return {
            "ok": False, "steps": [],
            "error": ("未找到含可解析文件清单的 maintree_stray_wip_stale 信号"
                      "记录（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行 git 写"),
        }

    # 显式 paths 白名单校验：清单外路径拒绝（零 git 写）。
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "ok": False, "steps": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)

    # 与当刻 git status / 索引求交：三态分流。
    try:
        dirty = _git_status_paths(proot)
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：_git_out 的
        # RuntimeError 消息含最多 300 字符 git stderr 原文，可能携带仓库内部
        # 路径，细节经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "untrack_stray_wip 读取 git 状态失败: %s: %s",
            type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "读取 git 状态失败（详见服务端日志）"}
    to_untrack = [p for p in candidates if p in dirty and p in indexed]
    skipped_stale = [p for p in candidates if p not in dirty]
    already_untracked = [p for p in candidates if p in dirty and p not in indexed]
    # 含逗号文件名拆散检测（item 86cda9326ae7，同 commit 执行器口径）。
    comma_frags = (
        _stray_manifest_comma_fragments(candidates, dirty.__contains__)
        if skipped_stale else []
    )
    if not to_untrack:
        err = ("信号清单内文件均已不在 git 索引（已根治过或已删除），"
               f"无需重复执行 untrack；清单({len(manifest)}): "
               f"{', '.join(manifest)}")
        if comma_frags:
            err += (f"；另检测到清单段疑因文件名含逗号被切散出 "
                    f"{len(comma_frags)} 个碎片路径"
                    f"（{', '.join(comma_frags)}），本动作无法处置"
                    "（清单段按逗号切分、写侧无转义的格式限制）")
        return {"ok": False, "steps": [], "error": err}

    gi_path = proot / ".gitignore"
    gi_backup = gi_path.read_bytes() if gi_path.exists() else None

    # 复用 stash_guard 回滚子函数的最小宿主（code_fix._main_tree_dirty_files
    # 的 ``_Probe(G6StashGuardMixin)`` 先例：完整 WorktreeManager 装配是死重；
    # 函数级 import 规避装载环）。不打开 stash_guard「check-ignore 全须忽略」
    # 前置门（design D1：目标生成物文件本就不被 ignore，独立执行器作用面
    # 限告警指认清单，误伤面最小）。
    from core.worktree_manager.stash_guard import G6StashGuardMixin
    from core.worktree_manager.mergeback import _unquote_git_path

    class _StashGuardTagLogger:
        """标准 logging → stash_guard ``(tag, msg)`` 双参口径适配。

        stash_guard 自愈骨架以 ``self.logger.warning("worktree_manager", msg)``
        双参口径写日志（Fenix 项目 logger 形态）；本模块 logger 是标准
        logging，直传会把 msg 当 % 参数——适配器折回单参格式化。
        """

        def __init__(self, base):
            self._base = base

        def warning(self, tag, msg):
            self._base.warning("%s: %s", tag, msg)

    class _UntrackGuardProbe(G6StashGuardMixin):
        """仅承载 project_root/logger 的守卫探针壳（回滚子函数宿主）。"""

        def __init__(self, pr, base_logger):
            self.project_root = Path(pr)
            self.logger = _StashGuardTagLogger(base_logger)

    probe = _UntrackGuardProbe(proot, logger)
    processed: list = []   # 已成功 rm --cached 的路径（中止按此回滚索引态）
    appended: list = []    # 已写入 .gitignore 的条目（中止一并还原）

    def _abort(reason: str) -> dict:
        rollback = list(processed)
        if appended:
            rollback.append(".gitignore")
        # 回滚段复用 stash_guard 骨架（_reset_index_paths：只重置索引不动
        # 工作区；尽力而为，失败仅记 warning 不掩盖原始原因）。
        probe._reset_index_paths(rollback)
        restore_note = ""
        if appended:
            try:
                # 还原写回同收项目级排他锁（code-review item b30e2e7dbcb7，
                # _gitignore_lock）：基于整文件快照的回写/删除若与并发处置
                # 的追加交错，后写者覆盖先写者、并发新增的 ignore 行静默
                # 丢失。此处调用时刻无他锁在持（_append_gitignore_entries
                # 已在其锁内完成写并释放），无嵌套死锁面。
                with _gitignore_lock(proot):
                    if gi_backup is None:
                        gi_path.unlink(missing_ok=True)
                    else:
                        # 原子字节写回备份原始字节（code-review item 41c87143c57e）：
                        # 还原不经 decode/re-encode 往返——.gitignore 含非 UTF-8 字节
                        # 时 errors="replace" 会把坏字节改写成 U+FFFD，还原结果不再
                        # 字节级等值于备份。原子纪律沿用 item 55aaffc3e33b（与
                        # _append_gitignore_entries 同口径）：裸 write_bytes 非原子，
                        # 还原时刻恰逢进程被杀/磁盘满会留下截断的 .gitignore（仓库
                        # 忽略规则整体丢失面）。
                        _atomic_write_bytes(gi_path, gi_backup)
            except OSError as e:
                # 还原失败不吞中止原因（code-review item c88d597d898e，比照
                # _append_gitignore_and_commit 还原分支同口径）：磁盘满/权限
                # 问题抛 OSError 会被 execute_adjudication_choice 的宽 except
                # 吃成泛化「动作执行异常」，且索引已重置而 .gitignore 未还原
                # ——细节日志留痕，steps 保留还原失败线索，error 仍携带原始
                # 中止 reason。
                logger.warning(
                    "untrack_stray_wip 中止还原 .gitignore 失败: %s: %s",
                    type(e).__name__, e,
                )
                restore_note = "；.gitignore 还原失败（保留现状）"
        abort_steps: list = []
        if restore_note:
            abort_steps.append(f"untrack 根治中止回滚{restore_note}")
        return {"ok": False, "steps": abort_steps,
                "error": f"untrack 根治中止已回滚（主树状态已还原）: {reason}"}

    try:
        for path in to_untrack:
            _git_out(proot, "rm", "-f", "--cached", "--", path)
            processed.append(path)
        appended = _append_gitignore_entries(proot, to_untrack)
        if appended:
            _git_out(proot, "add", "--", ".gitignore")
        # staged 子集守卫（stash_guard._untrack_index_paths 同口径）：裸
        # commit 会把索引里其它 staged 条目连带入库，校验暂存集 ⊆ 本次
        # untrack 路径 ∪ {.gitignore}，越界先回滚再放弃。名单反转义：diff
        # --cached 对非 ASCII 路径默认输出 C-quoted 转义形。
        staged_out = _git_out(proot, "diff", "--cached", "--name-only", "HEAD")
        staged_set = {_unquote_git_path(ln) for ln in staged_out.splitlines()}
        allowed = set(to_untrack) | ({".gitignore"} if appended else set())
        if not staged_set <= allowed:
            return _abort(
                "索引存在本次作用面之外的暂存条目: "
                f"{sorted(staged_set - allowed)}"
            )
        msg = (f"[fenix] admin: 根治主树复发型散件"
               f"（untrack_stray_wip 出库 {len(to_untrack)} 文件）")
        if note:
            msg += f"\n\n裁决依据：{note}"
        _git_out(proot, "commit", "-m", msg)
        # 提交集合复核（code-review item cf800d2e5f17）：上方 staged 子集
        # 守卫取的是 diff --cached 时刻快照，其后到裸 commit 之间的窗口内
        # 被并发暂存的条目（人工 git 操作或 AdminMonitor 自动处置并发执行）
        # 不参与校验，会被裸 commit 一并裹挟入库——恰是守卫要防的「索引被
        # 裹挟」事故面。提交落地后读回实际提交集合复核，发现越界条目即
        # ``git reset --soft HEAD^`` 撤销提交（索引回到提交前暂存态，外来
        # 暂存保留），再走 _abort 整体还原并如实报错。
        try:
            committed_out = _git_out(
                proot, "show", "--name-only", "--format=", "HEAD")
            committed = {
                _unquote_git_path(ln)
                for ln in committed_out.splitlines() if ln.strip()
            }
            hijacked = sorted(committed - allowed)
        except (OSError, RuntimeError) as e:
            # 复核读取失败时提交已落库，MUST NOT 走 _abort（dd2262c17587
            # 同款边界：回滚范围以「提交是否已落库」为界）——比照哈希回读
            # 失败先例仅 WARNING 留痕、跳过复核按成功收尾，steps 说明。
            # 不外泄裸异常文本（item e584a2ede367 同口径）。
            logger.warning(
                "untrack_stray_wip 提交集合复核读取失败（跳过复核）: %s: %s",
                type(e).__name__, e,
            )
            hijacked = None
        if hijacked:
            try:
                _git_out(proot, "reset", "-q", "--soft", "HEAD^")
            except (OSError, RuntimeError) as e:
                # 撤销失败不谎报「已回滚」：提交（含裹挟条目）已落库，如实
                # 上报人工核查；细节日志留痕、不外泄 git stderr 原文。
                logger.warning(
                    "untrack_stray_wip 撤销裹挟提交失败: %s: %s",
                    type(e).__name__, e,
                )
                return {"ok": False, "steps": [],
                        "error": ("提交集合复核发现作用面之外的裹挟条目且撤销"
                                  f"失败（提交已落库，需人工核查）: {hijacked}")}
            return _abort(
                "提交集合复核发现作用面之外的裹挟条目（已撤销提交并回滚）: "
                f"{hijacked}"
            )
    except OSError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：OSError 可携带
        # 内部路径/errno，细节经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "untrack_stray_wip git/文件操作失败: %s: %s",
            type(e).__name__, e,
        )
        return _abort("git 操作失败（详见服务端日志）")
    except RuntimeError as e:
        # subprocess.TimeoutExpired 不可达（code-review item 87fd1a921031）：
        # try 内全部 git 调用经 _git_out（内部已把超时归一为 RuntimeError
        # 抛出），.gitignore 判定的 _path_already_ignored 自吞
        # TimeoutExpired/OSError/ValueError（含解码异常，
        # code-review item d1081ee9fee8）——超时由本 RuntimeError 分支兜底。
        # 不外泄裸异常文本（code-review item e584a2ede367）：同上，_git_out
        # 的 RuntimeError 含 git stderr 原文，日志留痕、客户端收固定文案。
        logger.warning(
            "untrack_stray_wip git 命令失败: %s: %s", type(e).__name__, e,
        )
        return _abort("git 操作失败（详见服务端日志）")

    # pathspec 锚定读哈希（code-review item 7fe327348b37，同
    # _exec_commit_stray_wip / archive_commit.commit_archive_move 口径）：
    # 提交本体因 rm --cached 后 pathspec 解析必 fatal 而只能裸 commit
    # （stash_guard 同款教训），读哈希按被出库路径锚定，同样防
    # commit→读取窗口内并发提交记到别人头上。
    # 回读 MUST 与上方 commit 分离（code-review item dd2262c17587）：此处
    # 失败时提交已落库，若仍走 _abort 会把 .gitignore 还原为写前备份并对
    # 已不在索引的出库路径复位索引（ignore 规则在 HEAD 有、工作区无，被
    # 出库文件在后续盘点重新浮现），且「主树状态已还原」文案失实、调用方
    # 收失败结论而提交已发生——_abort 的回滚范围以「提交是否已落库」为界。
    # 回读失败仅 WARNING 留痕，按成功收尾并在 steps 说明哈希缺失。
    commit_hash = ""
    try:
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", *to_untrack,
        ).strip()
    except (OSError, RuntimeError) as e:
        # 不外泄裸异常文本（code-review item e584a2ede367 同口径）。
        logger.warning(
            "untrack_stray_wip 提交已落库但哈希回读失败: %s: %s",
            type(e).__name__, e,
        )

    steps = [
        f"untrack 出库 {len(to_untrack)} 个文件（信号清单∩当刻改动∩索引）："
        f"{', '.join(to_untrack)}",
    ]
    if appended:
        steps.append(f".gitignore 追加 {len(appended)} 条（去重后实际新增）: "
                     f"{', '.join(appended)}")
    else:
        steps.append(".gitignore 无需追加（既有规则已覆盖或条目已存在）")
    if commit_hash:
        steps.append(f"提交 hash: {commit_hash}")
    else:
        steps.append("提交已落库但哈希回读失败（commit hash 缺失，详见服务端日志）")
    if hijacked is None:
        steps.append("提交集合复核读取失败已跳过（并发裹挟防线本次未生效，"
                     "详见服务端日志）")
    if skipped_stale:
        steps.append(
            f"清单内已不在当刻改动、跳过 {len(skipped_stale)} 个: "
            f"{', '.join(skipped_stale)}"
        )
    if comma_frags:
        steps.append(
            f"检测到清单段疑因文件名含逗号被切散出 {len(comma_frags)} 个碎片"
            f"路径（{', '.join(comma_frags)}），未纳入本动作（清单段按逗号"
            "切分、写侧无转义的格式限制）"
        )
    if already_untracked:
        steps.append(
            f"清单内已脱离索引（已根治过）、跳过 {len(already_untracked)} 个: "
            f"{', '.join(already_untracked)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "commit_hash": commit_hash,
        "untracked_files": to_untrack,
        "gitignore_appended": appended,
    }


# ── 主树 untracked 散件认领（evo-stray-untracked-escalation 3.1）──────────

# signal_type 绑定白名单单源（design D4 同款收口逻辑）：认领执行器是主树
# git 写/文件删除的暴露面，白名单仅收录升级信号——姊妹 info 信号
# （maintree_untracked_stray_stale）与 tracked 桶信号（maintree_stray_wip_stale
# 等）一律拒绝、零 git 写零文件触碰。evidence 清单段解析复用
# parse_stray_wip_manifest（升级信号 evidence 与 info 前身同段级格式，仅指
# 解析器复用，不将 info 信号放行为执行目标）。
UNTRACKED_CLAIM_SIGNAL_TYPES = ("maintree_untracked_stray_escalated",)

# 显式归档登记目录（相对 project_root）：归档裁决把清单内散件移入该目录的
# UTC 时间戳子目录（保留清单内相对路径结构），并把登记目录本身追加进
# .gitignore——归档是「已认领存放」语义，登记目录 MUST NOT 计入后续
# untracked 盘点（无忽略规则的项目否则会把归档产物再当散件告警，裁决自我
# 循环）；.gitignore 追加以 pathspec 独立提交落地（可整体 revert）。
UNTRACKED_STRAY_ARCHIVE_DIR = ".fenix/stray-archive"


def _claim_untracked_manifest(project_root, signal_type: str, paths=None) -> dict:
    """认领执行器共用前置：绑定守卫 → 清单单源 → 显式 paths 白名单校验。

    binding 守卫在任何 git 读/写之前 fail-closed（spec「tracked 信号拒绝零
    git 写」验收口径）；manifest 解析只读 AdminStore（零 git 零文件触碰）。
    paths 仅供程序化调用方显式收窄作用面（MUST 为清单子集，清单外拒绝），
    语义对齐 commit/untrack 执行器同款 D2 约束。

    Returns: {"manifest": [...], "candidates": [...], "error": str}
    error 非空时调用方原样返回失败结果（零 git 写、零文件触碰）。
    """
    sig = str(signal_type or "").strip()
    if sig not in UNTRACKED_CLAIM_SIGNAL_TYPES:
        return {
            "manifest": [], "candidates": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 untracked 散件"
                      f"认领（白名单仅限 {', '.join(UNTRACKED_CLAIM_SIGNAL_TYPES)}；"
                      "tracked 桶与 info 信号零 git 写零文件触碰，design D4）"),
        }
    proot = Path(project_root)
    # 清单解析与传入 sig 严格绑定（code-review item 16ab21f59713）：先精确
    # 解析本信号自己的最新记录——白名单扩容为多信号后，纯遍历会把兄弟信号
    # 的清单记录当成 B 信号的执行目标（archive/ignore/delete 作用面错配）。
    # 仅当本 sig 无可解析记录时才回退遍历白名单（item a830be215f12 的
    # 「固定取 [0] 恒解析不到自己记录」问题由回退分支兜住）。
    manifest: list = _latest_stray_wip_manifest(proot, sig)
    if not manifest:
        for claim_sig in UNTRACKED_CLAIM_SIGNAL_TYPES:
            if claim_sig == sig:
                continue
            manifest = _latest_stray_wip_manifest(proot, claim_sig)
            if manifest:
                break
    if not manifest:
        return {
            "manifest": [], "candidates": [],
            "error": (f"未找到含可解析文件清单的 "
                      f"{', '.join(UNTRACKED_CLAIM_SIGNAL_TYPES)} 信号记录"
                      "（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行认领写"),
        }
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "manifest": [], "candidates": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)
    return {"manifest": manifest, "candidates": candidates, "error": ""}


def _append_gitignore_and_commit(proot, entries, header: str) -> dict:
    """追加 .gitignore 并以 pathspec 独立提交落地（认领裁决共用）。

    pathspec 形态（``git commit -- .gitignore``，commit_stray_wip 同款）：
    只落 .gitignore 的工作区内容，不裹挟索引中其它暂存改动——认领裁决
    MUST NOT 制造「索引被裹挟」的新散件。.gitignore 尚未入库时先 add 再
    pathspec 提交（新文件须在索引内 pathspec 才可解析）。提交失败时尽力
    还原追加行（不残留半程改动；还原失败保留现状不掩盖原始原因）。

    Returns: {"appended": [...], "commit_hash": str, "error": str}
    """
    appended = _append_gitignore_entries(proot, entries)
    if not appended:
        return {"appended": [], "commit_hash": "", "error": ""}
    # .gitignore 入库态快照（code-review item 8db336608775）：新文件场景 add
    # 已把 .gitignore 暂存，失败还原分支除回滚工作区内容外还须撤销暂存，
    # 否则残留 staged 半程改动。ls-files 失败时入库态未知，按「已跟踪」保守
    # 处理（不补 reset——git 已异常，再补写只会放大）。
    gitignore_untracked = False
    commit_hash = ""
    try:
        tracked = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
        gitignore_untracked = ".gitignore" not in tracked
        if gitignore_untracked:
            _git_out(proot, "add", "--", ".gitignore")
        msg = f"[fenix] admin: {header}（{len(appended)} 条）"
        _git_out(proot, "commit", "-m", msg, "--", ".gitignore")
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：_git_out 的
        # RuntimeError 消息含最多 300 字符 git stderr 原文，可能携带仓库内部
        # 路径，细节经服务端日志留痕，客户端（认领裁决 alert-resolve 端点）
        # 收固定文案。
        logger.warning(
            "_append_gitignore_and_commit 提交失败（header=%s）: %s: %s",
            header, type(e).__name__, e,
        )
        restore_note = ""
        try:
            gi = proot / ".gitignore"
            # 读-过滤-写整体收进项目级排他锁（code-review item b30e2e7dbcb7，
            # _gitignore_lock）：字节级行过滤还原同样是基于整文件快照的回写，
            # 锁外并发追加/他处还原会互相覆盖、先写的行静默丢失。此处调用
            # 时刻无他锁在持（_append_gitignore_entries 已释放），无嵌套死锁面。
            with _gitignore_lock(proot):
                # 字节级行过滤还原（code-review item 41c87143c57e）：还原不经
                # 文本解码往返——.gitignore 含非 UTF-8 字节时
                # read_text(errors="replace") 再回写会把坏字节改写成 U+FFFD。
                # 追加行是本函数新写的完整行，按字节行精确匹配剔除即可。
                appended_lines = {p.encode("utf-8") for p in appended}
                kept = [
                    ln for ln in gi.read_bytes().splitlines(keepends=True)
                    if ln.strip() not in appended_lines
                ]
                # 原子写回（code-review item 8db336608775，与
                # _append_gitignore_entries 同口径）：裸写回非原子，还原时刻
                # 恰逢进程被杀/磁盘满会留下截断的 .gitignore（仓库忽略规则
                # 整体丢失面）。
                _atomic_write_bytes(gi, b"".join(kept))
        except OSError:
            restore_note = "；.gitignore 还原写回失败（保留现状）"
        if gitignore_untracked:
            try:
                _git_out(proot, "reset", "-q", "--", ".gitignore")
            except RuntimeError as reset_err:
                logger.warning(
                    "_append_gitignore_and_commit 撤销 .gitignore 暂存失败: "
                    "%s: %s", type(reset_err).__name__, reset_err,
                )
                restore_note += "；撤销 .gitignore 暂存失败（详见服务端日志）"
        return {"appended": [], "commit_hash": "",
                "error": (f".gitignore 追加提交失败（已尽力还原追加行"
                          f"{restore_note}；详见服务端日志）")}
    # pathspec 锚定读哈希（code-review item 7fe327348b37，同
    # _exec_commit_stray_wip / archive_commit.commit_archive_move 口径：
    # 不用 rev-parse HEAD，防 commit→读取窗口内并发提交记到别人头上）。
    # 回读移出上方 try（code-review item dd2262c17587 同形轻症）：此处失败
    # 时提交已落库，走还原分支会把已入库的追加行从工作区剔除（工作区与
    # HEAD 脱钩）。失败仅 WARNING 留痕，commit_hash 置空由调用方 steps
    # 如实展示。
    try:
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", ".gitignore",
        ).strip()
    except RuntimeError as e:
        logger.warning(
            "_append_gitignore_and_commit 提交已落库但哈希回读失败"
            "（header=%s）: %s: %s",
            header, type(e).__name__, e,
        )
    return {"appended": appended, "commit_hash": commit_hash, "error": ""}


def _stray_manifest_path_escapes(proot, paths) -> list:
    """清单路径「相对且不越出项目根」纵深校验，返回不合规条目（空=全部合法）。

    清单解析自告警 evidence 文本段（parse_stray_wip_manifest 只做段级文本
    解析，不做路径合法性裁决），绝对路径条目会使 ``proot / p`` 整体替换基准
    路径、含 ``..`` 条目可指向项目根之外（code-review item a2e84e9e166c）。
    同模块先例防线：夹具写入走 validate_scenario_revision_paths 白名单、
    spec 名拼路径走 kebab-case 正则；散件路径散布全仓、不在任何目录白名单
    内，故只取其绝对路径/穿越规则做同型校验，白名单目录约束不适用。
    首段冒号（Windows 盘符形态）检查仅 ``os.name == "nt"`` 生效——POSIX
    文件名可合法含冒号，非 nt 下一律判不合规会把此类条目从 archive/ignore/
    delete 三个执行器永久剔除（code-review item 8502d6ba2438）；非 nt 的
    越界风险由绝对路径判定与下方 realpath 前缀锚定兜底。
    """
    base = os.path.realpath(os.path.abspath(str(proot)))
    check_win_drive = os.name == "nt"
    bad: list = []
    for raw in paths or []:
        p = str(raw or "").strip()
        if (not p or p.startswith("~") or os.path.isabs(p)
                or (check_win_drive and ":" in p.split("/")[0])):
            bad.append(p)
            continue
        norm = os.path.normpath(p)
        if norm == "." or norm.startswith(".."):
            bad.append(p)
            continue
        # realpath 前缀断言：解析后必须仍落在项目根之内（顺带挡住中间目录为
        # 指向项目外符号链接的形态）。
        anchored = os.path.realpath(os.path.join(base, norm))
        if anchored != base and not anchored.startswith(base + os.sep):
            bad.append(p)
    return bad


def _exec_archive_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                  paths=None) -> dict:
    """archive_untracked_stray：显式归档——清单内散件移入登记目录（全局信号专用）。

    约束（design D4 同款收口）：
    - signal_type 绑定白名单（UNTRACKED_CLAIM_SIGNAL_TYPES）：仅
      maintree_untracked_stray_escalated 可触达，tracked 桶与 info 信号一律
      拒绝，零 git 写零文件触碰；
    - 文件来源 MUST 限信号记录 evidence「文件清单(N):」段（拒任意路径）；
    - 归档落点 .fenix/stray-archive/<UTC时间戳>/（保留相对路径结构）；登记
      目录先追加 .gitignore 并独立提交（幂等，重入去重），再逐文件移动——
      已移动文件不回拉（移动是逐文件原子操作，留在登记目录属已认领态），
      失败如实上报、重试续移剩余文件；
    - 清单内已不在磁盘的文件跳过不报错（同指纹一次性告警，清单会陈旧）；
      可归档集合为空返回明确 error。移动前 ls-files 复核 untracked 身份
      （code-review item 6715a1facae4，同 commit/untrack 执行器）并对清单
      条目做相对路径/越界校验（code-review item a2e84e9e166c）：已变
      tracked 与绝对路径/穿越条目一并跳过（tracked 文件移动＝git 可见删改）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    # 路径纵深校验（code-review item a2e84e9e166c，_stray_manifest_path_escapes
    # 同型防线）：不合规条目剔除、不阻断其余合规条目。
    escapes = _stray_manifest_path_escapes(proot, pre["candidates"])
    compliant = [p for p in pre["candidates"] if p not in escapes]
    # 三态分流（code-review item f7c915465d1d，与 delete 执行器的显式非普通
    # 文件分支对齐）：在盘但非普通文件（目录等）单列跳过原因，不落入「已不
    # 在磁盘」口径——条目实际在盘，只是不满足普通文件归档条件。
    existing, skipped, not_plain = [], [], []
    for p in compliant:
        f = proot / p
        if not f.exists():
            skipped.append(p)
        elif not f.is_file():
            not_plain.append(p)
        else:
            existing.append(p)
    # 含逗号文件名拆散检测（item 86cda9326ae7，求交探针改磁盘存在判定）。
    comma_frags = (
        _stray_manifest_comma_fragments(compliant, lambda p: (proot / p).exists())
        if skipped else []
    )
    # tracked 复核防线（code-review item 6715a1facae4，同 commit/untrack 执行器
    # 的 ls-files 求交）：清单+磁盘存在不代表仍 untracked——同指纹一次性告警的
    # 清单会陈旧，文件可能在告警后已被 commit_stray_wip 等途径提交跟踪（同一
    # 信号下并排裁决动作的先后组合）；对 tracked 路径执行移动会制造 git 可见
    # 的删改，违背「零 git 写、只动 untracked」契约。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：git stderr 原文
        # 经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "archive_untracked_stray 读取 git 索引失败: %s: %s",
            type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "读取 git 索引失败（详见服务端日志）"}
    newly_tracked = [p for p in existing if p in indexed]
    existing = [p for p in existing if p not in indexed]
    if not existing:
        err = ("信号清单内文件均已不在磁盘（同指纹一次性告警，清单陈旧），"
               f"无可归档文件；清单({len(pre['manifest'])}): "
               f"{', '.join(pre['manifest'])}")
        if newly_tracked:
            err += f"；其中 {len(newly_tracked)} 个已变 tracked（不执行归档移动）"
        if not_plain:
            err += f"；其中 {len(not_plain)} 个在盘但非普通文件（跳过不触碰）"
        if escapes:
            err += f"；其中 {len(escapes)} 条路径不合规已剔除"
        if comma_frags:
            err += (f"；另检测到清单段疑因文件名含逗号被切散出 "
                    f"{len(comma_frags)} 个碎片路径"
                    f"（{', '.join(comma_frags)}），本动作无法处置"
                    "（清单段按逗号切分、写侧无转义的格式限制）")
        return {"ok": False, "steps": [], "error": err}
    gi = _append_gitignore_and_commit(
        proot, [f"{UNTRACKED_STRAY_ARCHIVE_DIR}/"], "登记 untracked 散件归档目录",
    )
    if gi["error"]:
        return {"ok": False, "steps": [], "error": gi["error"]}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest_root = proot / UNTRACKED_STRAY_ARCHIVE_DIR / stamp
    moved, failed = [], ""
    try:
        for p in existing:
            dest = dest_root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(proot / p), str(dest))
            moved.append(p)
    except OSError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：OSError 可携带
        # 内部路径/errno，细节经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "archive_untracked_stray 归档移动失败（已移动 %d 个）: %s: %s",
            len(moved), type(e).__name__, e,
        )
        failed = (f"归档移动失败（已移动 {len(moved)} 个留在登记目录，"
                  f"重试续移；详见服务端日志）")
    steps = []
    if gi["appended"]:
        if gi["commit_hash"]:
            steps.append(
                f"登记目录 {UNTRACKED_STRAY_ARCHIVE_DIR}/ 追加 ignore 并独立提交"
                f"（{gi['commit_hash'][:12]}）"
            )
        else:
            steps.append(
                f"登记目录 {UNTRACKED_STRAY_ARCHIVE_DIR}/ 追加 ignore 并独立提交；"
                "提交已落库但哈希回读失败（commit hash 缺失，详见服务端日志）"
            )
    else:
        steps.append(f"登记目录 {UNTRACKED_STRAY_ARCHIVE_DIR}/ 已在 ignore 规则内，无需追加")
    steps.append(
        f"归档 {len(moved)} 个 untracked 散件至 {UNTRACKED_STRAY_ARCHIVE_DIR}/{stamp}/"
        f"（保留相对路径）: {', '.join(moved)}"
    )
    if skipped:
        steps.append(f"清单内已不在磁盘、跳过 {len(skipped)} 个: {', '.join(skipped)}")
    if comma_frags:
        steps.append(
            f"检测到清单段疑因文件名含逗号被切散出 {len(comma_frags)} 个碎片"
            f"路径（{', '.join(comma_frags)}），未纳入本动作（清单段按逗号"
            "切分、写侧无转义的格式限制）"
        )
    if not_plain:
        steps.append(
            f"清单内在盘但非普通文件（目录等）、跳过不触碰 {len(not_plain)} 个"
            f"（不执行归档移动）: {', '.join(not_plain)}"
        )
    if newly_tracked:
        steps.append(
            f"清单内已变 tracked、跳过 {len(newly_tracked)} 个（告警后已被提交"
            f"跟踪，不执行归档移动）: {', '.join(newly_tracked)}"
        )
    if escapes:
        steps.append(
            f"清单内 {len(escapes)} 条路径不合规（绝对路径/越出项目根），"
            f"跳过不触碰: {', '.join(escapes)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    if failed:
        steps.append(failed)
        return {"ok": False, "steps": steps, "error": failed}
    return {
        "ok": True, "steps": steps, "error": None,
        "archived_files": moved,
        "archive_dir": f"{UNTRACKED_STRAY_ARCHIVE_DIR}/{stamp}",
        "gitignore_appended": gi["appended"],
        "commit_hash": gi["commit_hash"],
    }


def _exec_ignore_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                 paths=None) -> dict:
    """ignore_untracked_stray：清单内 untracked 路径追加 .gitignore（去重）。

    约束同认领族（白名单守卫/清单单源/pathspec 独立提交）。清单条目先经
    _stray_manifest_path_escapes 纵深校验（archive/delete 执行器同款防线，
    code-review item 97f425982d6e 对齐同族一致性）：不合规条目剔除并进
    steps 说明，全部不合规返回明确 error（对齐 archive/delete 空集拒绝口径）。
    去重双重口径复用 _append_gitignore_entries：条目字面行已存在或既有规则
    （含通配）已覆盖的不重复写。清单内路径无须仍在磁盘（ignore 规则对路径
    生效）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    # 路径纵深校验（code-review item a2e84e9e166c 同型防线，同 archive/delete
    # 执行器）：不合规条目剔除、不阻断其余合规条目。
    escapes = _stray_manifest_path_escapes(proot, pre["candidates"])
    candidates = [p for p in pre["candidates"] if p not in escapes]
    if not candidates:
        return {
            "ok": False, "steps": [],
            "error": (f"信号清单内全部 {len(escapes)} 条路径不合规"
                      f"（绝对路径/越出项目根），无可忽略条目；"
                      f"清单({len(pre['manifest'])}): "
                      f"{', '.join(pre['manifest'])}"),
        }
    gi = _append_gitignore_and_commit(
        proot, candidates, "追加 untracked 散件 ignore 规则",
    )
    if gi["error"]:
        return {"ok": False, "steps": [], "error": gi["error"]}
    steps = []
    if gi["appended"]:
        steps.append(
            f".gitignore 追加 {len(gi['appended'])} 条（去重后实际新增）: "
            f"{', '.join(gi['appended'])}"
        )
        if gi["commit_hash"]:
            steps.append(f"独立提交 hash: {gi['commit_hash']}")
        else:
            steps.append("提交已落库但哈希回读失败（commit hash 缺失，详见服务端日志）")
    else:
        steps.append(".gitignore 无需追加（既有规则已覆盖或条目已存在）")
    if escapes:
        steps.append(
            f"清单内 {len(escapes)} 条路径不合规（绝对路径/越出项目根），"
            f"跳过不触碰: {', '.join(escapes)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "gitignore_appended": gi["appended"],
        "commit_hash": gi["commit_hash"],
    }


def _exec_delete_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                 paths=None) -> dict:
    """delete_untracked_stray：删除清单内 untracked 散件文件（destructive）。

    约束同认领族。只删普通文件（is_file 门，防御性收口——目录与特殊文件
    拒绝，不 rmtree）；已不在磁盘的跳过不报错，全不存在时明确 error。
    删除前 ls-files 复核 untracked 身份（code-review item 6715a1facae4，同
    archive 执行器）并对清单条目做相对路径/越界校验（code-review item
    a2e84e9e166c）：已变 tracked 与绝对路径/穿越条目跳过不删。零 git 写
    （untracked 文件删除不经 git，ls-files 为只读复核；ignore/登记需求走
    其它两裁决），空目录残留不进 git status、无再告警面，不顺手清理
    （零额外触碰）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    # 路径纵深校验（code-review item a2e84e9e166c，同 archive 执行器）：
    # 不合规条目剔除、不阻断其余合规条目。
    escapes = _stray_manifest_path_escapes(proot, pre["candidates"])
    compliant = [p for p in pre["candidates"] if p not in escapes]
    # 三态分流（与 archive 执行器同构），但 delete 保持整体拒绝语义（docstring
    # 防御性收口声明：目录与特殊文件拒绝，不 rmtree、不部分删除）——扫完全
    # 清单收集全部非普通文件，error 携带完整语境（全部受阻条目 + 未处置的
    # 普通文件数）供人工判断（code-review item ece5d22ae9ef）。
    targets, skipped, not_plain = [], [], []
    for p in compliant:
        f = proot / p
        if not f.exists():
            skipped.append(p)
        elif not f.is_file():
            not_plain.append(p)
        else:
            targets.append(p)
    if not_plain:
        err = ("拒绝删除非普通文件（防御性收口，仅文件删除）: "
               + ", ".join(not_plain))
        err += f"；其余 {len(targets)} 个普通文件未删除"
        return {"ok": False, "steps": [], "error": err}
    # 含逗号文件名拆散检测（item 86cda9326ae7，同 archive 执行器口径）。
    comma_frags = (
        _stray_manifest_comma_fragments(compliant, lambda p: (proot / p).exists())
        if skipped else []
    )
    # tracked 复核防线（code-review item 6715a1facae4，同 commit/untrack/
    # archive 执行器的 ls-files 求交）：告警后已被提交跟踪的路径不再删除，
    # 否则会把 tracked 文件的工作区副本直接 unlink 制造 git 可见删改。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：git stderr 原文
        # 经服务端日志留痕，客户端收固定文案。
        logger.warning(
            "delete_untracked_stray 读取 git 索引失败: %s: %s",
            type(e).__name__, e,
        )
        return {"ok": False, "steps": [],
                "error": "读取 git 索引失败（详见服务端日志）"}
    newly_tracked = [p for p in targets if p in indexed]
    targets = [p for p in targets if p not in indexed]
    if not targets:
        err = ("信号清单内文件均已不在磁盘（同指纹一次性告警，清单陈旧），"
               f"无可删除文件；清单({len(pre['manifest'])}): "
               f"{', '.join(pre['manifest'])}")
        if newly_tracked:
            err += f"；其中 {len(newly_tracked)} 个已变 tracked（不执行删除）"
        if escapes:
            err += f"；其中 {len(escapes)} 条路径不合规已剔除"
        if comma_frags:
            err += (f"；另检测到清单段疑因文件名含逗号被切散出 "
                    f"{len(comma_frags)} 个碎片路径"
                    f"（{', '.join(comma_frags)}），本动作无法处置"
                    "（清单段按逗号切分、写侧无转义的格式限制）")
        return {"ok": False, "steps": [], "error": err}
    deleted, failed = [], ""
    try:
        for p in targets:
            (proot / p).unlink()
            deleted.append(p)
    except OSError as e:
        # 部分删除如实回传（code-review item a527df01d2de，与 archive 执行器
        # 「已移动 N 个、重试续移」的部分进度口径对齐）：本轮已删清单并入
        # steps，不留对操作者不可见的半程删除状态。不外泄裸异常文本
        # （code-review item e584a2ede367）：OSError 细节日志留痕，客户端收
        # 固定文案。
        logger.warning(
            "delete_untracked_stray 删除失败（已删除 %d 个）: %s: %s",
            len(deleted), type(e).__name__, e,
        )
        failed = f"删除失败（已删除 {len(deleted)} 个，重试续删剩余；详见服务端日志）"
    steps = [f"删除 {len(deleted)} 个 untracked 散件文件: {', '.join(deleted)}"]
    if skipped:
        steps.append(f"清单内已不在磁盘、跳过 {len(skipped)} 个: {', '.join(skipped)}")
    if comma_frags:
        steps.append(
            f"检测到清单段疑因文件名含逗号被切散出 {len(comma_frags)} 个碎片"
            f"路径（{', '.join(comma_frags)}），未纳入本动作（清单段按逗号"
            "切分、写侧无转义的格式限制）"
        )
    if newly_tracked:
        steps.append(
            f"清单内已变 tracked、跳过 {len(newly_tracked)} 个（告警后已被提交"
            f"跟踪，不执行删除）: {', '.join(newly_tracked)}"
        )
    if escapes:
        steps.append(
            f"清单内 {len(escapes)} 条路径不合规（绝对路径/越出项目根），"
            f"跳过不触碰: {', '.join(escapes)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    if failed:
        steps.append(failed)
        return {"ok": False, "steps": steps, "error": failed}
    return {
        "ok": True, "steps": steps, "error": None,
        "deleted_files": deleted,
    }

