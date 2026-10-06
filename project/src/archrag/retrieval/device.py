"""模型设备校验与显存计量。

FlagEmbedding 在构造时把权重留在 CPU，首次前向才搬到 `devices` 指定设备；
因此调用方必须预热一次后再做校验（铁律 25）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import torch

from archrag.errors import ModelLoadError


def memory_allocated() -> int:
    """当前进程 CUDA 已分配字节数；无 CUDA 时为 0。"""
    if not torch.cuda.is_available():
        return 0
    return int(torch.cuda.memory_allocated())


def find_module(root: Any, paths: Sequence[Sequence[str]], label: str) -> torch.nn.Module:
    """按候选属性路径找到第一个 nn.Module。"""
    for path in paths:
        target = root
        for name in path:
            target = getattr(target, name, None)
            if target is None:
                break
        if isinstance(target, torch.nn.Module):
            return target
    raise ModelLoadError(f"{label} 未找到可校验的 nn.Module（候选路径 {list(paths)}）")


def verify_module(
    module: torch.nn.Module,
    *,
    device: str,
    dtype: str | None,
    label: str,
) -> dict[str, int]:
    """校验全部参数都在预期设备与精度上，返回设备分布。"""
    devices: dict[str, int] = {}
    dtypes: dict[str, int] = {}
    for parameter in module.parameters():
        devices[str(parameter.device)] = devices.get(str(parameter.device), 0) + 1
        dtypes[str(parameter.dtype)] = dtypes.get(str(parameter.dtype), 0) + 1
    if set(devices) != {device}:
        raise ModelLoadError(f"{label} 参数设备为 {devices}，期望全部在 {device}")
    if dtype is not None and set(dtypes) != {dtype}:
        raise ModelLoadError(f"{label} 参数精度为 {dtypes}，期望全部为 {dtype}")
    return devices
