"""归档自动提交（archive-auto-commit 即时化）。

归档移动（``spec/changes/<name>/`` → ``spec/archive/<dir>/``）成功后立即在
项目仓库产生一次 pathspec 限定的提交，不再等 push 流程尾部收口：

- 仅提交归档路径与随批改写的知识页（``extra_paths``，move-distill-trigger-
  to-push 3.2 溯源改写产物）：``git add --`` +
  ``git commit -m ... --`` 同一 pathspec（--only 语义），不吞索引中无关
  staged 内容、不扫进 spec/ 下其它正在修改的文件；
- fail-open：非 git 仓库 / git 失败一律以 ``warning`` 返回，不抛异常、
  不回滚已成功的目录移动，归档本体不受影响；
- 只 commit 不 push：push 仍由人工门禁（fenix-approve）与 push 流程负责；
  pm_engine push 尾部的归档收口保留为兜底（有残留才动作）。

知识蒸馏派发已迁出本模块（move-distill-trigger-to-push 1.2）：归档不再触发
蒸馏，蒸馏由 ``PmEngine.approve_push``（done→pushed 成功转移）单点派发；
返回结构保留 ``distill: None`` 键兼容既有消费方。

本模块的 warning 走裸 ``logging.getLogger("fenixd.archive_commit")`` 通道（经
传播汇入全局 "fenixd" 日志器）。多项目同进程下该通道无自有 handler，记录会
串写进最后构造 Logger 实例项目的 fenixd.log（core/logger.py item
9ed664019b2d 的已知接受项），输出项目归属不确定，排障时按时间与上下文归属。
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("fenixd.archive_commit")

_PROBE_TIMEOUT = 30
_ADD_TIMEOUT = 60
_COMMIT_TIMEOUT = 120
# pathspec 安全白名单：spec_name / 归档目录名允许的合法字符集；
# 同时排除纯点段（"." / ".."）——git 会把 spec/changes/.. 归一化上跳，
# 使提交范围从单条归档扩大到计划外目录
_SAFE_PATH_RE = re.compile(r"^(?!\.?\.$)[A-Za-z0-9._-]+$")


def commit_archive_move(project_root, spec_name: str, archive_dir, extra_paths=None) -> dict:
    """提交一次归档移动（只 commit，不 push）。

    蒸馏派发已迁出（move-distill-trigger-to-push 1.2）：归档移动不再触发
    ``dispatch_distill``，触发点在 ``PmEngine.approve_push`` 成功转移后。

    Args:
        project_root: 项目根目录
        spec_name: SPEC 名（用于提交信息）
        archive_dir: 移动后的归档目录路径（Path/str）
        extra_paths: 随本次归档一并入库的附加文件相对路径清单（可 None）。
            move-distill-trigger-to-push 3.2：调用方在目录移动成功后、提交前
            完成知识页溯源改写（``core.knowledge.rewrite_source_links_to_
            archive``），把改写过的 ``spec/knowledge/`` 文件传入，与归档两侧
            并入同一 ``[fenix] archive:`` 提交（改写与移动原子落库，知识页
            链接任何时刻指向真实存在的路径）。逐段过 pathspec 白名单，非法
            或磁盘上已不存在的条目剔除留痕（fail-open，不阻塞归档主路径）。

    Returns:
        {"committed": bool, "commit": str|null, "warning": str|null,
         "distill": None}
        - committed=True：提交成功，commit 为本次提交的全量 hash
          （哈希读取失败时为 null，提交本身已落库）；
        - committed=False：warning 说明原因（非 git 仓库 / git 失败 / 无可提交内容）；
        - distill 恒为 None（键保留兼容既有消费方；蒸馏不再由归档触发）。
    """
    proot = Path(project_root)
    # distill 恒 None：归档不再触发蒸馏（触发点已迁至 approve_push），
    # 键保留兼容既有消费方（含 git 探测失败的提前返回路径）
    result = {"committed": False, "commit": None, "warning": None, "distill": None}

    def _fail(msg: str) -> dict:
        result["warning"] = msg
        return result

    # 非 git 仓库 / git 不可用 → fail-open
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return _fail(
                "非 git 仓库，跳过归档提交: "
                + (probe.stderr.strip() or probe.stdout.strip() or f"exit {probe.returncode}")
            )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _fail(f"git 探测失败，跳过归档提交: {e}")

    # pathspec 安全：spec_name / 归档目录名直接拼入 git pathspec，glob（* ? []）
    # 会被按模式匹配解释而可能误匹配计划外路径；白名单不通过时 fail-open 跳过提交。
    # fullmatch 锚定整串（$ 会放过尾部带 \n 的名字），口径同 code_review.py 的 legit_re
    if not (
        _SAFE_PATH_RE.fullmatch(spec_name)
        and _SAFE_PATH_RE.fullmatch(Path(archive_dir).name)
    ):
        return _fail(
            "spec_name 或归档目录名含 pathspec 危险字符，跳过归档提交: "
            f"{spec_name!r} / {Path(archive_dir).name!r}"
        )

    # pathspec 组装：changes 侧仅在存在目录或存在跟踪文件时参与——从未入库的
    # spec 归档后该路径 matches nothing，会让整条 git add fatal 退出。
    changes_side = f"spec/changes/{spec_name}"
    archive_side = f"spec/archive/{Path(archive_dir).name}"
    paths = []
    if (proot / archive_side).exists():
        paths.append(archive_side)
    if (proot / changes_side).exists():
        paths.append(changes_side)
    else:
        tracked = _has_tracked_files(proot, changes_side)
        if tracked:
            paths.append(changes_side)
        elif tracked is None:
            # 删除侧探测失败与「无跟踪文件」不可区分会导致该侧被静默丢弃，
            # 残留删除只能等 push 尾部兜底；此处留 warning 让失败可察觉。
            logger.warning(
                "changes 删除侧跟踪文件探测失败（%s），删除可能未纳入本次归档提交，"
                "残留待 push 尾部兜底收口",
                changes_side,
            )
    if not paths:
        return _fail("归档路径均无可提交内容，跳过归档提交")

    # 附加路径（知识页溯源改写产物，move-distill-trigger-to-push 3.2）：逐段
    # 过 pathspec 白名单（含目录段，同一危险字符口径），非法条目剔除留痕；
    # 磁盘上已不存在的条目同样剔除——git add 对 matches nothing 的 pathspec
    # 会 fatal 退出。附加路径并入同一 ``[fenix] archive:`` 提交（--only
    # pathspec 语义不变，不吞索引中无关 staged 内容）。
    for extra in extra_paths or []:
        segs = Path(extra).parts
        if not segs or not all(_SAFE_PATH_RE.fullmatch(s) for s in segs):
            logger.warning("归档提交忽略 pathspec 危险的附加路径: %r", extra)
            continue
        extra_rel = Path(extra).as_posix()
        if not (proot / extra_rel).exists():
            logger.warning("归档提交忽略已不存在的附加路径: %s", extra_rel)
            continue
        paths.append(extra_rel)

    commit_msg = f"[fenix] archive: {spec_name} 归档入库"
    try:
        add = subprocess.run(
            ["git", "add", "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_ADD_TIMEOUT,
        )
        if add.returncode != 0:
            # add 部分命中失败（如个别路径被忽略/消失）时其余路径可能已写入
            # 索引，回滚口径同下方 commit 失败/异常两分支，避免残留半状态。
            _unstage(proot, paths)
            return _fail(f"git add 失败: {add.stderr.strip() or f'exit {add.returncode}'}")
        commit = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_COMMIT_TIMEOUT,
        )
        if commit.returncode != 0:
            _unstage(proot, paths)
            return _fail(f"git commit 失败: {commit.stderr.strip() or f'exit {commit.returncode}'}")
        # 提交已落库，先行置位：后续读哈希若因超时/OSError 失败，不能回退成
        # committed=False（否则上层误判未提交而重试，只会得到 nothing to
        # commit 的二次告警）；此时仅将 commit 置 None，不当异常收场。
        result["committed"] = True
        # 取哈希不用 rev-parse HEAD：commit 成功到读取 HEAD 之间有窗口，
        # daemon/dashboard 并发操作同一仓库时会记到别人的提交；本次提交恒触碰
        # paths，用 pathspec 限定的 log -1 锚定本次提交本身。
        # 残余窗口（接受现状）：本次 commit 落库之后、下方 log -1 读取之前，
        # 若并发方对同一 pathspec 又落库一笔提交，log -1 会返回他方哈希——
        # 仅 commit 元数据字段失真，提交本体已正确落库。
        try:
            rev = subprocess.run(
                ["git", "log", "-1", "--format=%H", "--"] + paths,
                cwd=str(proot),
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return result
        result["commit"] = rev.stdout.strip() if rev.returncode == 0 else None
        return result
    except (OSError, subprocess.TimeoutExpired) as e:
        _unstage(proot, paths)
        return _fail(f"归档提交异常: {e}")


def _unstage(proot: Path, paths) -> None:
    """提交失败/异常后，把本次已写入索引的归档路径 reset 回滚（fail-open）。

    只 reset 本次 pathspec 范围，不动索引中其它无关 staged 内容；reset 自身
    失败时静默忽略（仅 best-effort），保证失败路径不在索引残留半状态。
    """
    try:
        subprocess.run(
            ["git", "reset", "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _has_tracked_files(proot: Path, pathspec: str) -> bool | None:
    """pathspec 下是否有 git 跟踪文件（判定删除侧是否需要参与提交）。

    True/False = 探测成功（有/无跟踪文件）；None = 探测失败（ls-files
    超时/OSError/非零退出），不与「无跟踪文件」混同，调用方据以留痕。
    """
    try:
        r = subprocess.run(
            ["git", "ls-files", "--", pathspec],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


# ── 归档移动残留扫描（共享辅助，evo-mergeback-archive-residue-selfheal 1.1）──
#
# engine._archive_move_residue（push 尾部归档收口的特征扫描）与 merge-back
# 顺延链的自愈评估（queue._assess_archive_residue_selfheal）共用同一扫描落点，
# 避免两处特征漂移。engine 方法保留原三元组签名改为委托复用。


class ArchiveResidueScan(NamedTuple):
    """scan_archive_residue 的结构化结果。

    - found / spec_names / residue_paths：engine._archive_move_residue 既有
      三元组契约（委托复用零语义变化）；
    - entries：逐条残留明细（自愈授权「同 spec 两侧成对」校验的数据源）；
    - non_spec_dirty：spec/changes 与 spec/archive 两类路径之外的脏文件——
      任一存在即判非归档残留（自愈否决证据，绝不自动触碰源码路径）；
    - error：git status 探测失败信息（调用方按「无残留」fail-open 的依据）。
    """

    found: bool
    spec_names: list
    residue_paths: list
    entries: list
    non_spec_dirty: list
    error: str | None = None


def archive_residue_spec(rel_path: str) -> str:
    """从 spec/changes/ 相对路径提取涉及 spec 名。

    - 删除侧：`spec/changes/<spec>/...` → `<spec>`
    - 归档新增侧：`spec/archive/.../...` → `<spec>`。归档目录命名两种：
      软删除 `<spec>-<Unix秒>[-(ms|-n)]`（剥离尾部纯数字段）、
      归档 `YYYY-MM-DD-<spec>`（剥离日期前缀）
    """
    if rel_path.startswith("spec/archive/"):
        seg = rel_path[len("spec/archive/") :].split("/", 1)[0]
        # 归档命名：YYYY-MM-DD-<spec>；剥离日期前缀。日期前缀段须优先走本分支
        # （code-review item 3fb781c010f1）：规格名本身可含数字尾段（如
        # code-review-fix-1792101520），若先套下方软删除正则会把规格名自身的
        # 尾段当 Unix 秒剥掉，与 changes 侧解析出的 spec 名失配，成对残留被
        # 误判「仅单侧（半提交形态）」拒绝 merge-back 自愈
        m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", seg)
        if m:
            return m.group(1)
        # 软删除命名：<spec>-<Unix秒>[-(ms|-n)]；剥离尾部纯数字段
        m = re.match(r"^(.*?)(?:-\d{10,13}(?:-\d{1,6})*)$", seg)
        return m.group(1) if m else seg
    if rel_path.startswith("spec/changes/"):
        return rel_path[len("spec/changes/") :].split("/", 1)[0]
    return ""


def scan_archive_residue(project_root) -> ArchiveResidueScan:
    """只读扫描主树归档移动残留（宽判据：任一侧即算残留）。

    归档移动（soft_delete_spec 用 shutil.move 把 spec 目录移入 archive）在 git
    视角表现为两类残留：``spec/changes/<spec>/...`` 删除侧、
    ``spec/archive/<dir>/...`` 新增/修改侧（rename 检测 R 的行任一侧命中同样
    计入）。判定失败时 error 带回原因、按「无残留」处理（fail-open：不因
    检测异常阻塞调用方主流程）。
    """
    try:
        result = subprocess.run(
            # -uall：未跟踪目录不折叠，逐文件列出，归档新增 spec 名才能解析；
            # core.quotePath=false（code-review item e8342559acd3）：默认对含
            # 非 ASCII/特殊字符路径按 C 风格加引号转义，下方 startswith
            # spec/changes/、spec/archive/ 判定会失配致归档残留漏判
            ["git", "-c", "core.quotePath=false", "status", "--porcelain", "-uall"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except Exception as e:
        return ArchiveResidueScan(False, [], [], [], [], f"git status 异常: {e}")
    if result.returncode != 0:
        return ArchiveResidueScan(
            False, [], [], [], [],
            (result.stderr or result.stdout).strip()[:200]
            or f"git status exit {result.returncode}",
        )

    names: list = []
    paths_out: list = []
    entries: list = []
    non_spec_dirty: list = []
    found = False
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        rest = line[3:].strip()
        # rename 行形态：`R  old -> new`，两侧都要参与归档判定。取最后一个
        # 「 -> 」分隔符：路径名可字面含该子串（quotePath=false 下 git 不加
        # 引号转义），从左拆会碎成 >2 段使 renamed 判定失效、两侧候选错位
        candidates = [rest]
        if " -> " in rest:
            candidates = [p.strip() for p in rest.rsplit(" -> ", 1)]
        # R/C rename 行（code-review item e0d1dc8780aa）：已 staged 的归档移动
        # 呈现为 `R  spec/changes/... -> spec/archive/...`，此前只认 D/??/A/M，
        # 两侧候选均不满足导致残留漏判——old 侧视同删除、new 侧视同新增
        renamed = xy.startswith(("R", "C")) and len(candidates) == 2
        line_hits: list = []
        for idx, path in enumerate(candidates):
            # 归档产物横跨两处：删除侧 spec/changes/<spec>/、新增侧 spec/archive/...
            # （archive 已平级化到 spec/ 下，不再嵌套于 changes/）
            in_changes = path.startswith("spec/changes/")
            in_archive = path.startswith("spec/archive/")
            if not (in_changes or in_archive):
                # 框架运行时目录（.fenix/STATE.md 等持续写动的元数据）豁免否决：
                # 它永不进入补提交（add 限定精确残留路径）、也与 merge 无关
                # （生产布局被 .gitignore 覆盖根本不出现；非 gitignore 项目下
                # 若计入会把自愈永久否决成死车道）。
                if path.startswith(".fenix/"):
                    continue
                # 两类路径之外的脏文件：宽判据不认（原语义跳过），结构化带回
                # 供自愈授权否决（混合脏文件判非归档残留）
                non_spec_dirty.append(path)
                continue
            deleted = "D" in xy or (renamed and idx == 0)
            # 显式按 xy 字段位判定新增/修改（code-review item 2fc03362a40b）：
            # 首位 A/M（staged）或次位 A/M（unstaged），不依赖「porcelain
            # 状态字符集不含其它字母」的子串包含巧合，与 deleted 判定同口径。
            added = (
                xy.startswith("??")
                or xy[0] in "AM"
                or xy[1] in "AM"
                or (renamed and idx == 1)
            )
            if deleted or (in_archive and added):
                found = True
                hit = {
                    "path": path,
                    "side": "changes" if in_changes else "archive",
                    "deleted": deleted,
                    "added": added,
                    "renamed": renamed,
                    "spec": archive_residue_spec(path),
                    # rename 行两侧均在残留集合内时行末回填 True（天然成对）
                    "pair_complete": False,
                }
                entries.append(hit)
                line_hits.append(hit)
                names.append(hit["spec"])
                paths_out.append(path)
        if renamed and len(line_hits) == 2:
            # git R 重命名行天然成对（evo-mergeback-archive-residue-selfheal
            # 判据：两侧同现即完整归档移动，免逐侧单侧配对校验）
            for hit in line_hits:
                hit["pair_complete"] = True
    return ArchiveResidueScan(
        found,
        list(dict.fromkeys(n for n in names if n)),
        list(dict.fromkeys(paths_out)),
        entries,
        non_spec_dirty,
        None,
    )


def assess_archive_residue_selfheal(scan: ArchiveResidueScan) -> tuple:
    """在宽判据之上做 merge-back 自愈授权校验（只读，本 SPEC 判据落点）。

    helper 自身（scan_archive_residue）是「任一侧即算残留」的宽判据，自愈
    授权必须在其上加两道收窄：

    - 全部脏文件都落在 spec/changes 与 spec/archive 两类路径——任一例外即
      「混合脏文件」，判非归档残留（绝不自动触碰/提交源码路径，非目标红线）；
    - 残留按**同 spec 名两侧成对**：changes 删除侧与 archive 新增侧同 spec 名
      同时在场（git R 重命名行两侧均命中时视为天然成对）；仅单侧的半提交
      形态（如 archive 侧已提交、只剩 changes 删除态）不授权自动收尾，
      防把来历不明的 spec/changes 删除误当残留提交。

    Returns: (authorized: bool, reason: str)——reason 供日志与告警 evidence
    留痕（判据命中与否）。
    """
    if scan.error:
        return False, f"git status 探测失败: {scan.error}"
    if scan.non_spec_dirty:
        preview = "、".join(scan.non_spec_dirty[:5])
        more = f" 等 {len(scan.non_spec_dirty)} 个" if len(scan.non_spec_dirty) > 5 else ""
        return False, (
            f"存在 spec/changes、spec/archive 两类路径之外的脏文件: {preview}{more}"
        )
    if not scan.found:
        # 主树干净（无残留，或残留已被归档自身收口完成提交）：无可补提交，
        # 直接授权重放 merge——design「收口已完成则跳过补提交直接重放」，
        # 否则该场景会被熔断告警空烧一轮人工。否决集只含 error / 类外脏文件
        # / 单侧不成对残留。
        return True, "无归档移动残留（主树干净，跳过补提交直接重放合并）"
    del_specs: set = set()
    add_specs: set = set()
    rename_paired: set = set()
    strays: list = []
    for hit in scan.entries:
        if hit["renamed"] and hit["pair_complete"]:
            # 天然成对的 rename 行按 changes 侧 spec 名记成对
            if hit["side"] == "changes":
                rename_paired.add(hit["spec"])
            continue
        if hit["side"] == "changes" and hit["deleted"]:
            del_specs.add(hit["spec"])
        elif hit["side"] == "archive" and hit["added"]:
            add_specs.add(hit["spec"])
        else:
            strays.append(hit["path"])
    if strays:
        return False, f"存在不成对的归档残留形态: {'、'.join(strays[:5])}"
    unpaired = del_specs ^ add_specs
    if unpaired:
        return False, (
            "归档残留仅单侧（半提交形态，不授权自动收尾）: "
            + "、".join(sorted(unpaired)[:5])
        )
    # [fenix-ignore:60f9a07520c8] 非死分支：成对 rename 行两侧可均落 spec/archive/
    # （archive 内部改名被 stage），两条命中都走上方 continue、不计入任何集合，
    # rename_paired 与 del_specs 可同时为空——此处须显式拒绝授权（否则穿透到
    # return True 会放行提交与 changes↔archive 配对无关的脏状态），删除即引入 bug
    if not (rename_paired or del_specs):
        return False, "无成对归档残留"
    return True, "归档残留两侧成对且全部脏文件落 spec/ 两类路径"
