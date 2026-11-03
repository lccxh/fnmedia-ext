#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动剔除失效源（issue #55）。

基于 sourcehealth 的健康画像（成功率/延迟/连续失败 → grade），
把长期「死亡冷却」或「高失败率」的【启用】源自动停用，避免拖慢聚合搜索与
起播竞速。停用的源登记在 state/auto_cull.json，管理页可一键恢复。

设计：与 sourcehealth 一样零外部依赖、进程内热路径不 IO；判断逻辑全部放在
纯函数里（candidate_keys / should_cull），方便单测；apply/restore 才触碰
config 与磁盘。公开/私有构建通用（只依赖通用运维能力，不含任何凭据）。
"""
from __future__ import annotations

import json
import os
import threading
import time

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "auto_cull.json")
_LOCK = threading.RLock()

# 与 sourcehealth._grade 的等级一致：0 健康 / 1 慢 / 2 高失败率 / 3 死亡冷却
GRADE_DEAD = 3
GRADE_DEGRADED = 2


def load_culled() -> dict:
    """返回已自动停用的源登记：{source_id: {name, reason, grade, at}}。"""
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_locked(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp = _STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, _STATE_PATH)
    except Exception:
        pass


def should_cull(grade: int, *, include_degraded: bool = True) -> bool:
    """单源是否应被剔除。"""
    if grade == GRADE_DEAD:
        return True
    if include_degraded and grade == GRADE_DEGRADED:
        return True
    return False


def candidate_keys(snapshot: dict, *, include_degraded: bool = True
                   ) -> list[tuple[str, int, str]]:
    """从健康画像里挑出应被停用的 (source_key, grade, reason)。

    纯函数，不碰配置与磁盘，便于单测。只依据画像，未启用/未探测过的源不会出现。
    """
    out = []
    if not snapshot:
        return out
    for key, st in snapshot.items():
        if not isinstance(st, dict):
            continue
        grade = int(st.get("grade", 0) or 0)
        if should_cull(grade, include_degraded=include_degraded):
            reason = "死亡冷却（连续失败）" if grade == GRADE_DEAD else "高失败率"
            out.append((key, grade, reason))
    return out


def apply(config_obj, snapshot: dict, *, include_degraded: bool = True
         ) -> list[dict]:
    """对启用且命中剔除候选的源执行停用，并登记到 state。

    config_obj 需提供 all_sources() 与 set_source_enabled(sid, on)（即 config.Config）。
    返回本次实际停用的源信息 [{id, name, reason}]。已是停用/已登记过的源会被跳过。
    """
    disabled: list[dict] = []
    culled = load_culled()
    cands = {k: (g, r) for k, g, r in
             candidate_keys(snapshot, include_degraded=include_degraded)}
    if not cands:
        return disabled
    for src in config_obj.all_sources():
        sid = src.get("id", "")
        if sid not in cands or sid in culled:
            continue
        if not src.get("enabled"):
            continue
        ok, _ = config_obj.set_source_enabled(sid, False)
        if ok:
            g, reason = cands[sid]
            culled[sid] = {"name": src.get("name", sid), "reason": reason,
                           "grade": g, "at": time.time()}
            disabled.append({"id": sid, "name": src.get("name", sid),
                             "reason": reason})
    with _LOCK:
        _save_locked(culled)
    return disabled


def restore(config_obj, sid: str | None = None) -> int:
    """重新启用被自动停用的源（默认全部）。返回恢复数量。"""
    culled = load_culled()
    if not culled:
        return 0
    targets = [sid] if sid else list(culled.keys())
    n = 0
    for k in targets:
        if k not in culled:
            continue
        ok, _ = config_obj.set_source_enabled(k, True)
        if ok:
            culled.pop(k, None)
            n += 1
    with _LOCK:
        _save_locked(culled)
    return n
