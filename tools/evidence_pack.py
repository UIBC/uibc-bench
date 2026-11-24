# -*- coding: utf-8 -*-
"""证据包生成与校验（S5「引用必可解析」+ S6「给评审方的一手证据」两用）。

它做两件事：
  1. 校验：按"门 → 文件"映射，逐个检查文件在包内是否存在；缺失即 FAIL（退出码 1）。
  2. 摘录：把每门的**原始行**（不是结论）按固定上限摘出来，写成 evidence_pack.json / .md，
     供外部评审方在不装环境、不进仓库的情况下看到一手数据——这正是第九轮"无法核实 25 条"的根因。

用法：
    python tools/evidence_pack.py --dir <审查包> --out runs/evidence_pack.json [--md runs/evidence_pack.md]
    python tools/evidence_pack.py --dir <审查包> --verify-only
"""
import argparse
import io
import json
import os
import re
import sys

# 门 → 证据文件（相对审查包目录）。写死在这里，是为了让"索引"可被机器校验，而不是手写一张可能过期的表。
MAP = {
    "S0": ["39_规范钉住证据\\spec_pin.json",
           "01_S0_前提与定位.md"],
    "S1": ["05_S6\\20261123_四镜回执_siliconflow.md",
           "05_S6\\_rerun4_expert.txt",
           "40_外部复核证据\\s1_expert.json"],
    "S2": ["38_九门自查证据\\no_claim_scan.json"],
    "S3": ["34_竞品证据\\resolvers\\DIF.json", "34_竞品证据\\resolvers\\cheqd.json",
           "34_竞品证据\\resolvers\\dcd.json", "34_竞品证据\\resolvers\\iden3.json"],
    "S4": ["34_竞品证据\\20261123_remote_negative_paths.json",
           "32_载体变异证据\\win\\mutation_win.json",
           "32_载体变异证据\\vm\\runs\\20261123_mutation_vm.json",
           "32_载体变异测试.md::M1",
           "09_S5_可视化看板.html::自身缺陷台账",
           "38_九门自查证据\\defects_ledger.md",
           "38_九门自查证据\\defect_logs\\index.json",
           "38_九门自查证据\\defect_logs\\R1_defect_A_port.log",
           "38_九门自查证据\\defect_logs\\R5_full_baseline_run.log"],
    "S5": ["38_九门自查证据\\package_audit.json", "38_九门自查证据\\s5_offline_scan.json"],
    "S6": ["40_外部复核证据\\round8.json", "40_外部复核证据\\round9.json"],
    "S7": ["38_九门自查证据\\package_audit.json"],
    "S8": ["09_S5_可视化看板.html"],
    "S9": ["38_九门自查证据\\s9_anon_visibility.json", "40_外部复核证据\\s9_visibility.json"],
}
CAP = {"rows": 8}          # 每个 JSON 最多摘 8 条原始记录
MAXCHARS = {"md": 1800, "html": 400, "json": 2600}


def verify(base):
    out, miss = [], []
    for gate, paths in MAP.items():
        for p in paths:
            base_path = p.split("::")[0]
            full = os.path.join(base, base_path)
            ok = os.path.exists(full)
            out.append({"gate": gate, "path": p, "exists": ok,
                        "bytes": os.path.getsize(full) if ok else None})
            if not ok:
                miss.append("%s -> %s" % (gate, p))
    return out, miss


def pick(obj):
    """从 JSON 里挑"最像原始记录"的那一段，并截断。"""
    if isinstance(obj, dict):
        if "rows" in obj and isinstance(obj["rows"], list):
            return {"summary": {k: v for k, v in obj.items() if k != "rows" and not isinstance(v, (dict, list))},
                    "rows_sample": obj["rows"][:CAP["rows"]], "rows_total": len(obj["rows"])}
        if "items" in obj and isinstance(obj["items"], list):
            return {"summary": {k: v for k, v in obj.items() if k != "items" and not isinstance(v, (dict, list))},
                    "items_sample": obj["items"][:CAP["rows"]], "items_total": len(obj["items"])}
        keep = {}
        for k, v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                keep[k] = v[:CAP["rows"]]
                keep[k + "_total"] = len(v)
            elif not isinstance(v, (dict, list)):
                keep[k] = v
        return keep or {k: v for k, v in list(obj.items())[:6]}
    return obj


def excerpt(base, path):
    # 支持 "path::关键词" 切片：从关键词处取一段，避免长文档开头没写到重点就截断了
    kw = ""
    if "::" in path:
        path, kw = path.split("::", 1)
    full = os.path.join(base, path)
    raw = io.open(full, encoding="utf-8", errors="replace").read()
    if kw:
        i = raw.find(kw)
        if i >= 0:
            raw = raw[max(0, i - 200):]
    low = path.lower()
    if kw:
        if low.endswith((".html",".htm")):
            t = re.sub(r"<[^>]+>", " ", raw)
            t = re.sub(r"\s+", " ", t)
            return t[:MAXCHARS["md"]]
        return raw[:MAXCHARS["md"]]
    if low.endswith(".json"):
        try:
            return json.dumps(pick(json.loads(raw)), ensure_ascii=False)[:MAXCHARS["json"]]
        except Exception:
            return raw[:MAXCHARS["json"]]
    if low.endswith(".md"):
        return raw[:MAXCHARS["md"]]
    return raw[:MAXCHARS["html"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="runs/evidence_pack.json")
    ap.add_argument("--md", default="")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    files, miss = verify(a.dir)
    print("证据文件 %d 个：存在 %d / 缺失 %d" % (len(files), len(files) - len(miss), len(miss)))
    for m in miss:
        print("  [MISSING] " + m)
    if a.verify_only:
        return 0 if not miss else 1

    pack = {"dir": a.dir, "files": files, "gates": {}}
    for gate, paths in MAP.items():
        items = []
        for p in paths:
            if os.path.exists(os.path.join(a.dir, p.split("::")[0])):
                items.append({"path": p, "excerpt": excerpt(a.dir, p)})
        pack["gates"][gate] = items

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, ensure_ascii=False, indent=1)
    total = sum(len(x["excerpt"]) for g in pack["gates"].values() for x in g)
    print("摘录 %d 字（%d 门）→ %s" % (total, len(pack["gates"]), a.out))

    if a.md:
        lines = ["# 证据包（原文节选，未加工）", ""]
        for gate, items in pack["gates"].items():
            lines.append("## %s" % gate)
            for it in items:
                lines.append("### `%s`" % it["path"])
                lines.append("```")
                lines.append(it["excerpt"])
                lines.append("```")
        io.open(a.md, "w", encoding="utf-8").write("\n".join(lines))
        print("md=%s" % a.md)
    return 0 if not miss else 1


if __name__ == "__main__":
    sys.exit(main())
