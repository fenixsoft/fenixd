#!/usr/bin/env python3
"""bin/probe_prompt_cache.py — 网关前缀缓存能力探针（fix-agent-lane-efficiency D3）。

对指定 provider 发送带 cache_control 的稳定前缀两轮请求，解析第二轮的
usage.cache_read_input_tokens，输出确定性 JSON 判据（provider / cache_supported /
evidence），用于判定该网关是否产生可复用的前缀缓存命中。

定案（2026-09-20 探针实测）：网关接受 cache_control 并写入缓存（第1次
cache_read≈6144），但写入的缓存不可复用（第2次 cache_read≈113 或恒 0）；
全 provider 一致。框架侧不做缓存优化（Non-Goals）。本探针保留以供网关升级
后复验。

用法：
    python3 bin/probe_prompt_cache.py --provider <provider-name>
    python3 bin/probe_prompt_cache.py --provider inferaiapi.com --config .fenix/config.yaml

选项：
    --provider  provider 名称（对应 llm.providers[].name）
    --config    配置文件路径（默认 .fenix/config.yaml）

退出码：0 = 成功（含 cache_supported=false），1 = 参数/连接错误。
"""

import argparse
import json
import sys
import time
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

# ── 稳定前缀（~6K tokens 量级，用于两次请求的比较）──
STABLE_PREFIX = (
    "You are a helpful assistant. " * 200
    + "Answer with a single word."
)


def _build_request(provider: dict) -> dict:
    """构造带 cache_control 的请求体（system 段作缓存前缀）。

    模型名取 provider 的 model（缺失时回退 common/default 字段检查）。
    """
    model = provider.get("model") or provider.get("default_model")
    if not model:
        raise ValueError(
            f"provider '{provider.get('name')}' 缺 model 字段，无法构造探针请求"
        )
    return {
        "model": model,
        "max_tokens": 10,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": STABLE_PREFIX,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }


def _post_once(provider: dict, body: dict) -> tuple:
    """向 provider 的 messages 端点发一次请求，返回 (parsed_response_body, raw)。

    第一元素是**完整响应体**的 JSON 解析结果（dict；usage 是其中的子字典，
    由调用方 ``parsed.get("usage")`` 自取），非 usage 载荷本身（code-review
    item b74eff2a140a：旧 docstring 称返回 usage_dict 与实现不符）。响应体
    非法 JSON 时回退 ({"raw": 前500字符}, raw)。

    使用 stdlib urllib，避免依赖 requests；超时 120s。
    """
    import urllib.error
    import urllib.request

    baseurl = provider.get("baseurl", "").rstrip("/")
    if not baseurl:
        raise ValueError("provider 缺 baseurl")
    url = baseurl + "/v1/messages"
    api_key = provider.get("apikey") or provider.get("api_key")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": (api_key or ""),
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return {"raw": raw[:500]}, raw


def probe(provider_name: str, config_path: Path) -> dict:
    """对指定 provider 执行前缀缓存探针。

    返回 JSON 判据 dict：
        provider: str
        cache_supported: bool
        evidence: dict（round1 / round2 usage 摘要）
    """
    # 配置文件缺失与 provider 名缺失区分（code-review item 9c3cc76cd230）：
    # 两者此前同返 None，probe() 恒报「provider 不在配置文件」——--config
    # 路径给错时诊断指向错误原因。文件缺失先行短路并如实报错。
    if not config_path.exists():
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"配置文件不存在: {config_path}",
        }
    provider = _load_provider(config_path, provider_name)
    if provider is None:
        return {
            "provider": provider_name,
            "cache_supported": None,
            "error": f"provider '{provider_name}' 不在配置文件 {config_path} 中",
        }
    body = _build_request(provider)

    rounds = []
    errors = []
    for i in (1, 2):
        try:
            parsed, _raw = _post_once(provider, body)
        except Exception as e:  # 网络/解析/HTTP 错误：round 留空并记录
            errors.append(f"round{i}: {e!r}")
            rounds.append({"round": i, "error": f"{e!r}"})
        else:
            # usage 归一化在守卫外（code-review item 14a31e7379a3）：int() 遇
            # 非数值 usage 属编程/数据错误，应向上抛真实异常——收窄守卫区域
            # 到网络调用后不再被静默记成网络型轮错误、掩盖缺陷仍产出裁决。
            usage = parsed.get("usage") or {}
            rounds.append(
                {
                    "round": i,
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "cache_read_input_tokens": int(
                        usage.get("cache_read_input_tokens") or 0
                    ),
                    "cache_creation_input_tokens": int(
                        usage.get("cache_creation_input_tokens") or 0
                    ),
                }
            )
        time.sleep(1)

    # cache_supported 判据：第二轮有读取且第二轮 cache_read 显著（>0）。
    # 第1轮 cache_read 高而第2轮低（或恒 0）= 写入不可复用，不支持。
    r2 = rounds[1] if len(rounds) > 1 else {}
    r2_cr = int(r2.get("cache_read_input_tokens") or 0)
    cache_supported = r2_cr > 0

    evidence = {"rounds": rounds}
    if errors:
        evidence["errors"] = errors
    # D3 定案记录：网关不接受可复用前缀缓存时输出 false 与实测差异。
    # 任一轮失败时差异不可判定（成功轮子集可能缩成单元素，把真实差异
    # 掩盖为「相同」），显式标注跳过而非给出误导性 distinct=False。
    if any("error" in r for r in rounds):
        evidence["rounds_distinct"] = None
        evidence["rounds_distinct_note"] = "存在失败轮次，差异判定不可信，已跳过"
    else:
        distinct = len(set(
            int(r.get("cache_read_input_tokens") or 0) for r in rounds
        )) > 1
        evidence["rounds_distinct"] = distinct
    return {
        "provider": provider_name,
        "cache_supported": cache_supported,
        "evidence": evidence,
    }


def _load_provider(config_path: Path, provider_name: str):
    """从配置文件中提取指定 provider 的连接信息。"""
    import yaml

    if not config_path.exists():
        return None
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    llm = raw.get("llm") or {}
    providers = llm.get("providers") or []
    for p in providers:
        if isinstance(p, dict) and p.get("name") == provider_name:
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="网关前缀缓存能力探针")
    parser.add_argument("--provider", required=True, help="provider 名称")
    parser.add_argument(
        "--config",
        default=str(FRAMEWORK_ROOT / ".fenix" / "config.yaml"),
        help="配置文件路径（默认 .fenix/config.yaml）",
    )
    args = parser.parse_args()

    result = probe(args.provider, Path(args.config))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 网络/参数类硬错误（provider 缺失）退出码 1；判据结果（无论支持与否）为 0
    if result.get("cache_supported") is None:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())