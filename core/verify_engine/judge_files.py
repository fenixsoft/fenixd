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

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 归因条目状态常量
ATTRIBUTION_STATUS_ACCEPT = "accept"
ATTRIBUTION_STATUS_REQUEUE = "requeue"
ATTRIBUTION_STATUSES = (ATTRIBUTION_STATUS_ACCEPT, ATTRIBUTION_STATUS_REQUEUE)

# 文件名常量
JUDGE_ATTRIBUTION_FILENAME = "judge_attribution.json"
REQUEUE_MANIFEST_FILENAME = "requeue_manifest.json"


def _attribution_path(project_root: Path, spec_name: str) -> Path:
    """judge 归因产物文件路径。"""
    return (
        project_root / ".fenix" / "verify-progress"
        / spec_name / JUDGE_ATTRIBUTION_FILENAME
    )


def _requeue_manifest_path(project_root: Path, spec_name: str) -> Path:
    """回炉清单文件路径。"""
    return (
        project_root / ".fenix" / "verify-progress"
        / spec_name / REQUEUE_MANIFEST_FILENAME
    )


def load_attribution(project_root: Path, spec_name: str) -> Optional[Dict[str, Any]]:
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

    # 新格式：直接返回（已含 scenarios 字段）
    if "scenarios" in data and isinstance(data["scenarios"], list):
        # 确保格式版本字段存在
        if "format_version" not in data:
            data["format_version"] = "1.0"
        return data

    # 旧格式：回退解析，转为新格式
    return _migrate_legacy_attribution(data)


def _migrate_legacy_attribution(legacy_data: Dict[str, Any]) -> Dict[str, Any]:
    """将旧格式整块归因转为新格式逐场景条目。

    旧格式可能来自早期 judge 产物，无 scenarios 字段。迁移策略：
    1. 如果存在 scenarios 列表（非标准字段），尝试解析
    2. 否则，将整块归因作为单个场景条目（id = "legacy_0"）
    """
    # 尝试从旧格式中提取场景信息
    scenarios = []

    # 方式1：旧格式可能有 scenarios 字段（非标准）
    if "scenarios" in legacy_data and isinstance(legacy_data["scenarios"], list):
        for i, sc in enumerate(legacy_data["scenarios"]):
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("id") or sc.get("scenario_id") or f"legacy_{i}")
            attribution = sc.get("attribution") or sc.get("classification") or ""
            status = sc.get("status") or ATTRIBUTION_STATUS_ACCEPT
            if status not in ATTRIBUTION_STATUSES:
                status = ATTRIBUTION_STATUS_ACCEPT
            scenarios.append({
                "id": sid,
                "attribution": attribution,
                "status": status,
                "timestamp": sc.get("timestamp") or "",
            })
    else:
        # 方式2：整块归因作为单个条目
        attribution = legacy_data.get("attribution") or ""
        classification = legacy_data.get("classification") or ""
        if not attribution and classification:
            attribution = classification
        scenarios.append({
            "id": "legacy_0",
            "attribution": attribution,
            "status": ATTRIBUTION_STATUS_ACCEPT,
            "timestamp": legacy_data.get("timestamp") or "",
        })

    return {
        "format_version": "1.0",
        "migrated_from_legacy": True,
        "scenarios": scenarios,
    }


def save_attribution(
    project_root: Path,
    spec_name: str,
    scenarios: List[Dict[str, Any]],
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

    写失败抛出 OSError（由调用方处理）。
    """
    path = _attribution_path(project_root, spec_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "format_version": format_version,
        "scenarios": scenarios,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".judge_attr.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def mark_scenario_status(
    project_root: Path,
    spec_name: str,
    scenario_id: str,
    status: str,
) -> bool:
    """更新单个场景条目的状态（accept 或 requeue）。

    Returns:
        True 表示成功更新；False 表示场景未找到。
    """
    if status not in ATTRIBUTION_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        return False

    scenarios = attr_data.get("scenarios") or []
    updated = False
    for sc in scenarios:
        if isinstance(sc, dict) and sc.get("id") == scenario_id:
            sc["status"] = status
            updated = True
            break

    if not updated:
        return False

    save_attribution(project_root, spec_name, scenarios)
    return True


def get_requeue_scenarios(project_root: Path, spec_name: str) -> List[Dict[str, Any]]:
    """获取所有状态为 requeue 的场景条目。

    Returns:
        requeue 场景列表；无 requeue 场景返回空列表。
    """
    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        return []

    return [
        sc for sc in (attr_data.get("scenarios") or [])
        if isinstance(sc, dict) and sc.get("status") == ATTRIBUTION_STATUS_REQUEUE
    ]


def build_requeue_manifest(
    project_root: Path,
    spec_name: str,
    rejection_round: int,
) -> Dict[str, Any]:
    """构建并写入回炉清单（供下轮 judge 仅重做 requeue 子集）。

    回炉清单结构：
    {
      "spec": str,
      "rejection_round": int,
      "requeue_scenario_ids": [str],
      "created_at": str,
    }

    写失败静默降级（不影响既有流程）。
    """
    requeue_list = get_requeue_scenarios(project_root, spec_name)
    requeue_ids = [sc["id"] for sc in requeue_list if isinstance(sc, dict)]

    manifest = {
        "spec": spec_name,
        "rejection_round": rejection_round,
        "requeue_scenario_ids": requeue_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    path = _requeue_manifest_path(project_root, spec_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".requeue.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        # 写失败静默，不影响主流程
        pass

    return manifest


def load_requeue_manifest(project_root: Path, spec_name: str) -> Optional[Dict[str, Any]]:
    """读取回炉清单（缺失/损坏返回 None）。"""
    path = _requeue_manifest_path(project_root, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clear_requeue_manifest(project_root: Path, spec_name: str) -> None:
    """清除回炉清单文件（合规采纳后调用）。"""
    path = _requeue_manifest_path(project_root, spec_name)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def is_full_requeue(project_root: Path, spec_name: str) -> bool:
    """判断是否全量重复（100% requeue）。

    Returns:
        True 表示所有非 PASS 场景均为 requeue 状态；无归因数据返回 False。
    """
    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        return False

    scenarios = attr_data.get("scenarios") or []
    non_pass = [
        sc for sc in scenarios
        if isinstance(sc, dict)
    ]

    if not non_pass:
        return False

    return all(
        sc.get("status") == ATTRIBUTION_STATUS_REQUEUE
        for sc in non_pass
    )


def migrate_legacy_attribution_file(project_root: Path, spec_name: str) -> bool:
    """迁移旧格式归因文件为新格式（原子操作）。

    Returns:
        True 表示成功迁移或已是新格式；False 表示迁移失败。
    """
    path = _attribution_path(project_root, spec_name)
    if not path.exists():
        return True  # 无需迁移

    attr_data = load_attribution(project_root, spec_name)
    if attr_data is None:
        return False  # 文件损坏

    # 如果已是新格式（含 scenarios 字段），无需迁移
    if "scenarios" in attr_data and not attr_data.get("migrated_from_legacy"):
        return True

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