"""
judge_files.py — judge 归因产物按场景逐条目读写（add-judge-incremental-attribution）。

设计依据：spec/changes/evo-add-judge-incremental-attribution/design.md D1/D2。

职责：
  - judge 归因产物读写：支持新格式（scenarios 逐场景条目）与旧格式（整块归因）的双向兼容
  - 场景条目结构：{id, attribution, status, timestamp}，status ∈ {accept, requeue}
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
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .path_safety import safe_component

logger = logging.getLogger("fenixd.verify_engine.judge_files")

# 归因条目状态常量
ATTRIBUTION_STATUS_ACCEPT = "accept"
ATTRIBUTION_STATUS_REQUEUE = "requeue"
ATTRIBUTION_STATUSES = (ATTRIBUTION_STATUS_ACCEPT, ATTRIBUTION_STATUS_REQUEUE)

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


def _fsync_dir(path: Path) -> None:
    """fsync 父目录，持久化 rename 的目录项元数据。

    POSIX 语义下 os.replace 落盘数据不等于目录项已持久化，主机掉电后
    可能 tmp 与目标文件一起消失。judge 归因/回炉清单属可重算产物，故
    尽力而为：fsync 目录失败不阻断主流程。
    """
    try:
        dir_fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _atomic_write_json(path: Path, payload: Any, *, tmp_prefix: str) -> None:
    """mkstemp 原子写盘统一正文（save_attribution 与 build_requeue_manifest
    共用，code-review item 794cfb6f999c）：同目录临时文件 + fdopen 失败路径
    接管（cbb57806fbfd 口径）+ flush/fsync + ``os.replace`` + _fsync_dir，
    异常时清理临时文件后原样上抛。临时文件前缀由调用方传入（归因
    ``.judge_attr.`` / 回炉清单 ``.requeue.``）；异常降级策略（上抛 / 告警
    降级返回）属调用方语义，由调用方在捕获侧落实。
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=tmp_prefix, suffix=".json.tmp"
    )
    try:
        # fdopen 失败路径显式接管（同 maintenance_runs._append_token_run 的
        # cbb57806fbfd 口径）：with 的 close 只在 fdopen 成功后才生效，fdopen
        # 自身抛错时裸 fd 无人关闭——f 为 None 时兜底 os.close。
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        finally:
            if f is not None:
                f.close()
            else:
                try:
                    os.close(fd)
                except OSError:
                    pass
        os.replace(tmp_path, path)
        _fsync_dir(path.parent)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    # 整块归因作为单个条目
    attribution = legacy_data.get("attribution") or ""
    classification = legacy_data.get("classification") or ""
    scenario_entry = {
        "id": "legacy_0",
        "attribution": attribution,
        "status": ATTRIBUTION_STATUS_ACCEPT,
        "timestamp": legacy_data.get("timestamp") or "",
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
    # fdopen 失败接管 + flush/fsync + os.replace + _fsync_dir + 异常清理临时
    # 文件，code-review item 794cfb6f999c）；写失败清理后原样抛出（OSError
    # 或 JSON 序列化异常，由调用方处理）。
    _atomic_write_json(path, payload, tmp_prefix=".judge_attr.")


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
        # （fdopen 失败接管 + flush/fsync + os.replace + _fsync_dir + 异常
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
    except OSError:
        pass


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
