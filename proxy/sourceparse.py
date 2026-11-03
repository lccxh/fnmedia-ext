#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量资源站文本解析（纯标准库，无外部依赖，便于单测）。

解析形态：
  - 逐行：`名称,地址` / `名称|地址` / `名称 地址` / 仅地址（名称取域名）；
    行内可带成对引号/括号包裹，会自动剥离。
  - 整段 JSON 数组：[{name, api|url}, ...]
  - 整段 JSON 对象（TVBox 风格）：取其 `sites`/`data`/`list` 数组里的项。
非 http(s) 地址、空行、注释(# 开头)会被跳过。
"""
from __future__ import annotations

import json


def parse_sources_text(raw: str) -> list[dict]:
    """解析批量导入文本，返回 [{name, api}] 列表（未做去重/存在性校验）。"""
    if not raw or not raw.strip():
        return []
    raw = raw.strip()

    # ---- 先尝试整段 JSON ----
    try:
        j = json.loads(raw)
    except Exception:
        j = None
    if isinstance(j, list) or isinstance(j, dict):
        out: list[dict] = []
        items = j if isinstance(j, list) else (
            j.get("sites") or j.get("data") or j.get("list") or [])
        for it in items:
            if not isinstance(it, dict):
                continue
            api = (it.get("api") or it.get("url") or "").strip()
            if not api.startswith(("http://", "https://")):
                continue
            name = (it.get("name") or it.get("title") or "").strip()
            if not name:
                name = api.split("/")[2] if "://" in api else api
            out.append({"name": name, "api": api})
        if out:
            return out

    # ---- 回退：逐行解析 ----
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去掉整行成对引号/括号包裹
        if len(line) >= 2 and line[0] in "\"'([" and line[-1] in "\"')]":
            line = line[1:-1].strip()
        api = ""
        name = ""
        for sep in (",", "|", "\t"):
            if sep in line:
                a, b = line.split(sep, 1)
                a, b = a.strip(), b.strip()
                if a.startswith(("http://", "https://")):
                    api, name = a, b
                elif b.startswith(("http://", "https://")):
                    api, name = b, a
                else:
                    api, name = b, a
                break
        if not api:
            if line.startswith(("http://", "https://")):
                api = line
            else:
                toks = line.rsplit(None, 1)
                if len(toks) == 2 and toks[1].startswith(("http://", "https://")):
                    name, api = toks[0], toks[1]
        if not api.startswith(("http://", "https://")):
            continue
        api = api.rstrip("/")
        if not name:
            name = api.split("/")[2] if "://" in api else api
        out.append({"name": name.strip(), "api": api})
    return out
