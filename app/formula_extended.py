"""配方扩展字段：填料、母色配比、基料（占位模块）。

当前不产出数值：企业配方库与检测数据接入后，在此集中实现或由服务层
调用仓储/算法填充 ``GenerateResult.fillers``、``masterbatch_ratio_pct``、
``base_material_formula_pct``。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .models import FillerSpec

__all__ = ["extended_fields_for_generate"]


def extended_fields_for_generate() -> Tuple[List[FillerSpec], Dict[str, float], Dict[str, float]]:
    """返回与生成配方绑定的扩展字段；现阶段均为空。"""
    return [], {}, {}
