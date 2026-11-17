"""
judge_files.py — judge 归因产物按场景逐条目读写（add-judge-incremental-attribution）。

设计依据：spec/changes/evo-add-judge-incremental-attribution/design.md D1/D2。

职责：
  - judge 归因产物读写：支持新格式（scenarios 逐场景条目）与旧格式（整块归因）的双向兼容
  - 场景条目结构：{id, attribution, status, timestamp}，status ∈ {accept, requeue}
  - 证据引用可选字段（evo-env-attribution-evidence-gate）：条目可携带
    measurement_refs（量测引用列表）与 control_samples（对照样本引用列表），
    写侧键透传、读侧缺字段按空处理（向后兼容）
  - 读侧自动检测格式并回退解析，写侧统一为新格式
  - 回炉子集驱动：requeue 子集汇总回炉清单，供下轮 judge 仅重做该子集

路径约定：
  - judge 归因产物文件 = ``<vp_dir>/judge_attribution.json``
  - 回炉清单文件 = ``<vp_dir>/requeue_manifest.json``

不涉及：
  - judge prompt 构建（由 prompt_builder 负责）
  - 归因查重算法（由 verdict_check.check_batch_attribution_dedup 负责）
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fs_ops import atomic_write_json
from .path_safety import safe_component

logger = logging.getLogger("fenixd.verify_engine.judge_files")

# 归因条目状态常量
ATTRIBUTION_STATUS_ACCEPT = "accept"
ATTRIBUTION_STATUS_REQUEUE = "requeue"
ATTRIBUTION_STATUSES = (ATTRIBUTION_STATUS_ACCEPT, ATTRIBUTION_STATUS_REQUEUE)

# ── env 归因证据门（evo-env-attribution-evidence-gate）────────────────────
# 条目 schema 可选证据引用字段（task 1.3）：量测引用与验证窗口外对照样本
# 引用列表。写侧随条目键透传（save_attribution 不裁剪未知键），读侧缺字段
# 按空处理（旧格式 judge_attribution.json 照常解析，向后兼容）。字段填充
# 在 verdict_evidence 条目构造侧完成。注意与 dashboard 侧媒体管线专用门
# （admin_actions.env_attribution_evidence_gate，cls+evidence_text 签名）
# 语义无关，命名刻意区分。
ATTRIBUTION_MEASUREMENT_REFS_FIELD = "measurement_refs"
ATTRIBUTION_CONTROL_SAMPLES_FIELD = "control_samples"
ATTRIBUTION_EVIDENCE_GATE_FIELDS = (
    ATTRIBUTION_MEASUREMENT_REFS_FIELD,
    ATTRIBUTION_CONTROL_SAMPLES_FIELD,
)

# 环境量测数值模式（文本回退匹配面）：量测名称（负载/CPU/内存/温度/驱动/
# 帧率/网关错误码等）邻接数值，或数值邻接单位（%/ms/°C/GHz/fps）。
_MEASUREMENT_TEXT_RE = re.compile(
    r"("
    r"(?:load|cpu|mem|内存|温度|temp|负载|驱动|driver|帧率|fps|延迟|latency|"
    r"丢包|packet[\s_-]?loss|带宽|bandwidth|uptime|使用率|gpu|磁盘|disk|io|"
    r"网关|gateway|dns|qps|rps)[^\n\d]{0,40}?\d+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s*(?:%|ms|°C|℃|GHz|fps)"
    r")",
    re.IGNORECASE,
)

# 验证窗口外对照样本引用模式（文本回退匹配面）：历史轮次/窗口外/对照基线
# 等窗口外标记。bare「重跑/复测/自测」不构成窗口外对照——两轮同窗自测共享
# 同一负载条件，是 proposal 明文反例，MUST NOT 匹配。
_CONTROL_TEXT_RE = re.compile(
    r"(窗口外|历史轮|上一轮|前一轮|先前|历史样本|历史基线|历史轮次|"
    r"对照样本|对照组|基线对照|跨窗|另一窗口|早于验证|先于验证|"
    r"baseline|previous|prior|earlier|outside[\s_-]?of[\s_-]?the[\s_-]?window)",
    re.IGNORECASE,
)

# 文件名常量
JUDGE_ATTRIBUTION_FILENAME = "judge_attribution.json"
REQUEUE_MANIFEST_FILENAME = "requeue_manifest.json"


def _attribution_path(project_root: Path, spec_name: str) -> Path:
    """judge 归因产物文件路径（spec_name 净化口径同 engine._safe_component）。"""
    return (
        project_root
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / JUDGE_ATTRIBUTION_FILENAME
    )


def _requeue_manifest_path(project_root: Path, spec_name: str) -> Path:
    """回炉清单文件路径（spec_name 净化口径同 engine._safe_component）。"""
    return (
        project_root
        / ".fenix"
        / "verify-progress"
        / safe_component(spec_name)
        / REQUEUE_MANIFEST_FILENAME
    )


def _atomic_write_json(path: Path, payload: Any, *, tmp_prefix: str) -> None:
    """mkstemp 原子写盘统一正文（save_attribution 与 build_requeue_manifest
    共用，code-review item 794cfb6f999c）：同目录临时文件 + fdopen 失败路径
    接管（cbb57806fbfd 口径）+ flush/fsync + ``os.replace`` + 目录 fsync +
    异常清理，正文下沉共享实现 fs_ops.atomic_write_json（code-review item
    24106d6108e2），此处仅保留原函数名/签名与调用方前缀。临时文件前缀由
    调用方传入（归因 ``.judge_attr.`` / 回炉清单 ``.requeue.``）；异常降级
    策略（上抛 / 告警降级返回）属调用方语义，由调用方在捕获侧落实。
    """
    atomic_write_json(path, payload, tmp_prefix=tmp_prefix)


def load_attribution(project_root: Path, spec_name: str) -> dict[str, Any] | None:
    """读取 judge 归因产物，自动兼容新旧格式。

    新格式（逐场景条目）：
    {
      "scenarios": [
        {"id": "scenario_1", "attribution": "...", "status": "accept", "timestamp": "..."},
        {"id": "scenario_2", "attribution": "...", "status": "requeue", "timestamp": "..."},
      ],
      "format_version": "1.0"
    }

    旧格式（整块归因，回退解析）：
    {
      "attribution": "整块归因文本",
      "classification": "...",
      ...
    }

    Returns:
        归一化后的新格式 dict；文件缺失/损坏返回 None。
    """
    path = _attribution_path(project_root, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    # scenarios 键存在但类型不符 → 文件损坏，与文件缺失/JSON 解析失败同口径返回 None
    if "scenarios" in data and not isinstance(data["scenarios"], list):
        return None

    # 新格式：直接返回（已含 scenarios 字段）
    if "scenarios" in data and isinstance(data["scenarios"], list):
        # 确保格式版本字段存在
        if "format_version" not in data:
            data["format_version"] = "1.0"
        return data

    # 旧格式：回退解析，转为新格式
    return _migrate_legacy_attribution(data)


def _migrate_legacy_attribution(legacy_data: dict[str, Any]) -> dict[str, Any]:
    """将旧格式整块归因转为新格式逐场景条目。

    旧格式来自早期 judge 产物，无 scenarios 列表字段（调用方 load_attribution
    已对含 scenarios 列表的新格式提前返回，故此处只处理整块归因形态）：
    将整块归因作为单个场景条目（id = "legacy_0"）。

    attribution 为空而仅有 classification 时，文本侧保留分类内容（查重/回炉
    判定依赖该文本），同时保留独立 classification 字段并标注
    classification_fallback=True，显式标记为分类回退而非原生归因。
    """
    # 整块归因作为单个条目。attribution/classification/timestamp 须为文本字符串：
    # judge 漂移可能把它们写成 dict/list 等非字符串真值，`or ""` 只挡 falsy，非字
    # 符串真值会原样进入条目，而下游查重与回炉判定按文本 str 处理归因字段、
    # save_attribution 契约要求 timestamp 为 ISO 字符串。非字符串一律降级为空串
    # 并留痕告警（口径同 build_requeue_manifest 条目 id 畸形防御，code-review
    # item fa738bf8033b）。
    attribution = legacy_data.get("attribution") or ""
    classification = legacy_data.get("classification") or ""
    if not isinstance(attribution, str):
        logger.warning(
            "旧格式归因 attribution 非字符串（%s），降级为空串",
            type(attribution).__name__,
        )
        attribution = ""
    if not isinstance(classification, str):
        logger.warning(
            "旧格式归因 classification 非字符串（%s），降级为空串",
            type(classification).__name__,
        )
        classification = ""
    timestamp = legacy_data.get("timestamp") or ""
    if not isinstance(timestamp, str):
        logger.warning(
            "旧格式归因 timestamp 非字符串（%s），降级为空串",
            type(timestamp).__name__,
        )
        timestamp = ""
    scenario_entry = {
        "id": "legacy_0",
        "attribution": attribution,
        "status": ATTRIBUTION_STATUS_ACCEPT,
        "timestamp": timestamp,
    }
    if not attribution and classification:
        # 旧格式仅存分类文本时，文本侧保留分类内容供查重/回炉判定读取，
        # 同时保留独立 classification 字段并显式标注回退来源（非静默顶替）。
        scenario_entry["attribution"] = classification
        scenario_entry["classification"] = classification
        scenario_entry["classification_fallback"] = True

    return {
        "format_version": "1.0",
        "migrated_from_legacy": True,
        "scenarios": [scenario_entry],
    }


def save_attribution(
    project_root: Path,
    spec_name: str,
    scenarios: list[dict[str, Any]],
    format_version: str = "1.0",
) -> None:
    """原子写入 judge 归因产物（新格式）。

    每个条目结构：
    {
      "id": str,              # 场景 ID
      "attribution": str,     # 归因文本
      "status": str,          # accept 或 requeue
      "timestamp": str,       # ISO 格式时间戳（可选）
      # 可选证据引用字段（evo-env-attribution-evidence-gate，键透传不裁剪）：
      "measurement_refs": list[str],  # 可复核环境量测引用（数值+来源）
      "control_samples": list[str],   # 验证窗口外对照样本引用
    }

    写失败时清理临时文件后原样抛出（OSError 或 JSON 序列化异常，由调用方处理）。
    """
    path = _attribution_path(project_root, spec_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "format_version": format_version,
        "scenarios": scenarios,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    # 原子写盘正文与 build_requeue_manifest 共用 _atomic_write_json（含
    # fdopen 失败接管 + flush/fsync + os.replace + fs_ops.fsync_dir + 异常清理临时
    # 文件，code-review item 794cfb6f999c）；写失败清理后原样抛出（OSError
    # 或 JSON 序列化异常，由调用方处理）。
    _atomic_write_json(path, payload, tmp_prefix=".judge_attr.")


def attribution_refs(sc_or_entry: Any, field: str) -> list[str]:
    """归一化读取场景条目/落盘条目的证据引用列表字段（evo-env-attribution-evidence-gate 1.3）。

    查找顺序：顶层键 → evidence 字典内同名键（judge report 场景条目把结构化
    字段放 evidence 内，落盘归因条目提升到顶层）。返回非空字符串列表；字段
    缺失/非列表/元素为空一律按空列表处理——读侧缺字段按空处理即向后兼容
    （旧格式 judge_attribution.json 无此字段照常解析）。dict 元素序列化为
    JSON 字符串保留信息量，标量元素原样收编。
    """
    if not isinstance(sc_or_entry, dict):
        return []
    raw = sc_or_entry.get(field)
    if raw is None:
        ev = sc_or_entry.get("evidence")
        if isinstance(ev, dict):
            raw = ev.get(field)
    if not isinstance(raw, (list, tuple)):
        return []
    refs: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                text = json.dumps(item, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(item)
            if text.strip():
                refs.append(text)
        elif isinstance(item, str):
            if item.strip():
                refs.append(item.strip())
        elif isinstance(item, (int, float, bool)):
            refs.append(str(item))
    return refs


def _scenario_gate_text(sc: dict) -> str:
    """收集 env 证据门文本回退匹配面（evidence/triage/归因文本聚合）。

    judge 未填结构化字段时，量测数值与窗口外对照标记只可能出现在既有证据
    文本字段中——聚合这些字段供正则回退匹配，不影响结构化字段优先语义。
    """
    parts: list[str] = []
    ev = sc.get("evidence")
    if isinstance(ev, dict):
        for key in ("first_failed_step", "env_evidence", "reason", "note", "message"):
            val = ev.get(key)
            if isinstance(val, str):
                parts.append(val)
        failed = ev.get("failed_assertions")
        if isinstance(failed, list):
            for item in failed:
                if isinstance(item, dict):
                    for key in ("expected", "actual", "message", "evidence"):
                        val = item.get(key)
                        if isinstance(val, str):
                            parts.append(val)
    triage = sc.get("assertion_triage")
    if isinstance(triage, list):
        for item in triage:
            if isinstance(item, dict):
                for key in ("assertion", "evidence", "reason"):
                    val = item.get(key)
                    if isinstance(val, str):
                        parts.append(val)
    for key in ("reason", "note", "attribution"):
        val = sc.get(key)
        if isinstance(val, str):
            parts.append(val)
    return "\n".join(parts)


def judge_env_evidence_gate(sc: Any) -> "tuple[bool, list[str]]":
    """env 归因证据门主判据（evo-env-attribution-evidence-gate 单源）。

    校验 env 分类条目是否具备双要件（保守方向：宁降级不误 accept）：
      1. 可复核环境量测：结构化 ``measurement_refs`` 非空，或文本含量测
         数值模式（量测名称邻接数值 / 数值邻接单位）；
      2. 验证窗口外对照样本：结构化 ``control_samples`` 非空，或文本含
         窗口外对照标记（历史轮次/窗口外/基线等；bare 重跑/复测不算）。

    优先校验结构化字段（judge 按提示词模板填充），缺失时回退查文本。

    Returns:
        (passed, missing_fields)：passed=False 时 missing_fields 为缺失要件
        字段名列表（``ATTRIBUTION_EVIDENCE_GATE_FIELDS`` 的子集）。
    """
    if not isinstance(sc, dict):
        return False, list(ATTRIBUTION_EVIDENCE_GATE_FIELDS)
    measurement = attribution_refs(sc, ATTRIBUTION_MEASUREMENT_REFS_FIELD)
    control = attribution_refs(sc, ATTRIBUTION_CONTROL_SAMPLES_FIELD)
    text = _scenario_gate_text(sc)
    missing: list[str] = []
    if not measurement and not _MEASUREMENT_TEXT_RE.search(text):
        missing.append(ATTRIBUTION_MEASUREMENT_REFS_FIELD)
    if not control and not _CONTROL_TEXT_RE.search(text):
        missing.append(ATTRIBUTION_CONTROL_SAMPLES_FIELD)
    return (not missing, missing)


def get_requeue_scenarios(project_root: Path, spec_name: str) -> list[dict[str, Any]]:
    """获取所有状态为 requeue 的场景条目。

    Returns:
        requeue 场景列表；无 requeue 场景返回空列表。
    """
    attr_path = _attribution_path(project_root, spec_name)
    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        # 文件存在但 JSON 损坏/结构非法 ≠ 文件缺失：静默按空表处理会让上一轮
        # requeue 子集无留痕丢失（下轮误走全量重做或漏重验），故留痕告警
        # （带路径）；行为仍降级为空列表，不阻断主流程。
        if attr_path.exists():
            logger.warning(
                "judge 归因产物存在但损坏/结构非法，requeue 子集按空处理"
                "（回炉信息可能丢失）: %s",
                attr_path,
            )
        return []

    return [
        sc
        for sc in (attr_data.get("scenarios") or [])
        if isinstance(sc, dict) and sc.get("status") == ATTRIBUTION_STATUS_REQUEUE
    ]


def build_requeue_manifest(
    project_root: Path,
    spec_name: str,
    rejection_round: int,
) -> dict[str, Any]:
    """构建并写入回炉清单（供下轮 judge 仅重做 requeue 子集）。

    回炉清单结构：
    {
      "spec": str,
      "rejection_round": int,
      "requeue_scenario_ids": [str],
      "created_at": str,
    }

    写失败降级为仅返回清单（不影响既有流程），但留痕告警。
    """
    requeue_list = get_requeue_scenarios(project_root, spec_name)
    # 条目缺 id 或 id 非字符串（judge 输出漂移/手工编辑）时跳过，避免 KeyError
    # 中断清单构建；非字符串 id 若放行会写入清单但与字符串场景 id 永不匹配，
    # 等效静默剔除。静默缩水会让下轮按失真清单回炉（漏重验或误全量），故按
    # 产物损坏同款口径留痕告警（带路径），全部丢失时标出严重形态。
    requeue_ids = [
        sc.get("id")
        for sc in requeue_list
        if isinstance(sc, dict) and isinstance(sc.get("id"), str) and sc.get("id")
    ]
    dropped_count = len(requeue_list) - len(requeue_ids)
    path = _requeue_manifest_path(project_root, spec_name)
    if dropped_count:
        if not requeue_ids:
            logger.warning(
                "requeue 条目 %d 条全部缺 id 或 id 非字符串，回炉清单将写为空集"
                "（回炉子集全部丢失，可能误走全量重做或漏重验）: %s",
                dropped_count,
                path,
            )
        else:
            logger.warning(
                "requeue 条目 %d 条中 %d 条缺 id 或 id 非字符串，已从回炉清单剔除"
                "（回炉子集部分丢失）: %s",
                len(requeue_list),
                dropped_count,
                path,
            )

    manifest = {
        "spec": spec_name,
        "rejection_round": rejection_round,
        "requeue_scenario_ids": requeue_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # 目录创建失败与写入失败同样降级，不影响主流程；但清单整体丢失比
        # 条目剔除后果更重（下轮回炉子集全丢），环境故障须可从日志区分，
        # 沿用本文件「降级但留痕」口径告警
        logger.warning(
            "回炉清单写入前置失败（目录创建），清单未落盘"
            "（回炉子集可能丢失）: %s: %s",
            path,
            exc,
        )
        return manifest

    try:
        # mkstemp/写入/原子落盘正文与 save_attribution 共用 _atomic_write_json
        # （fdopen 失败接管 + flush/fsync + os.replace + fs_ops.fsync_dir + 异常
        # 清理临时文件，code-review item 794cfb6f999c）：replace 前刷数据
        # 落盘，防掉电后 rename 到位而内容为空/截断（清单驱动下轮回炉子集，
        # 丢失后果是回炉信息缺失）
        _atomic_write_json(path, manifest, tmp_prefix=".requeue.")
    except OSError as exc:
        # 写失败同样降级，不影响主流程；但清单整体丢失比条目剔除后果更重，
        # 沿用本文件「降级但留痕」口径告警（带路径与异常摘要）
        logger.warning(
            "回炉清单写入/原子落盘失败，清单未生效（回炉子集可能丢失）: %s: %s",
            path,
            exc,
        )

    return manifest


def clear_requeue_manifest(project_root: Path, spec_name: str) -> None:
    """清除回炉清单文件（合规采纳后调用）。"""
    path = _requeue_manifest_path(project_root, spec_name)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # 删除失败（权限/只读盘等环境故障）不影响主流程返回，但清单残留会让
        # 下轮 judge 重复消费同一 requeue 子集，沿用本文件「降级但留痕」口径告警
        logger.warning(
            "回炉清单删除失败，清单残留（下轮可能重复回炉同一子集）: %s: %s",
            path,
            exc,
        )


def migrate_legacy_attribution_file(project_root: Path, spec_name: str) -> bool:
    """迁移旧格式归因文件为新格式（原子操作）。

    Returns:
        True 表示成功迁移或已是新格式；False 表示迁移失败。
    """
    path = _attribution_path(project_root, spec_name)
    if not path.exists():
        return True  # 无需迁移

    # 直接探测磁盘文件原始形态判「已是新格式」，不绕道 load_attribution 的
    # 归一化结果：迁移走 save_attribution 落盘，payload 只含
    # format_version/scenarios/saved_at，顶层 migrated_from_legacy 标记并不
    # 写入磁盘；新格式探测仅依据 scenarios 键——上次迁移产物若被后续 judge
    # 回写（仍是「scenarios 列表」形态），绕道会对新格式再做一次等价
    # save_attribution——幂等但多一次无谓写（仅刷新 saved_at）。
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False  # 文件损坏
    if isinstance(raw, dict) and "scenarios" in raw and isinstance(raw["scenarios"], list):
        return True  # 已是新格式，无需迁移

    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        return False  # 文件损坏

    # 执行迁移（load_attribution 已自动转换格式）
    try:
        save_attribution(
            project_root,
            spec_name,
            attr_data.get("scenarios") or [],
            format_version=attr_data.get("format_version", "1.0"),
        )
        return True
    except OSError:
        return False
