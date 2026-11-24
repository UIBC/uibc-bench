# -*- coding: utf-8 -*-
"""证据分档器 v2：可核实 / 可追溯 / 通配命中 / 多义 / 引文跳过 / 真缺件。

v1（v0.4.23）只有三档，跑出"39 条待补路径"，我据此在 46 号写了「多为只写文件名、补路径即可升级」。
本轮自己复核发现这句是**我方的夸大**：39 条里真正"补一条路径就能升级"的只有 4 条，
其余是日志/命令引文、省略号占位、跨环境产物、多义同名。所以 v2 把类别拆细。
（缺陷 #38，记在 47 号。）

类别：
  verified    包内可读、非空
  traceable   包外精确路径本轮实测存在，或同名唯一命中
  glob        通配/花括号写法，且本轮至少命中 1 个文件（说明"指得到"）
  ambiguous   同名文件在多个位置命中（需在文档里消歧，不能算已定位）
  quote       日志/命令引文（如 `-returned.json`、`SUITE_COMMIT_PIN=…`、含省略号）→ 跳过
  otherhost   另一台机器路径（/home/...）
  missing     以上皆非：包内没有、路径不存在、也无通配命中 → 真缺件

用法：python tools/evidence_grades.py --dir <review_dir> --roots "a;b;c" --json out.json --md out.md
"""
import argparse
import fnmatch
import io
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--roots", default="")
ap.add_argument("--json", required=True)
ap.add_argument("--md", default="")
ap.add_argument("--exclude", default="", help="排除的文件名通配，分号分隔（如 草案副本）")
ap.add_argument("--hash-manifest", default="", help="哈希存证清单：件不随包但可按 SHA256 核对的引用记 hashdecl（不算不可核）")
a = ap.parse_args()

ROOTS = [a.dir] + [r for r in a.roots.split(";") if r]
EXCL = [p for p in getattr(a, "exclude", "").split(";") if p]
EXT = r"\.(?:md|json|py|html|log|txt|zip|gz|bundle|ps1|sh|diff)"
REF = re.compile(r"`([^`<>]{3,140}?" + EXT + r")`")
ABS = re.compile(r"`?([A-Za-z]:\\[^`\n|，。、]{3,140}?" + EXT + r")`?")
INDEX = None
ORDER = [("verified", "可核实"), ("selfref", "包自身文件名"), ("hashdecl", "按哈希存证"), ("traceable", "可追溯"), ("glob", "通配命中"),
         ("ambiguous", "多义待消歧"), ("otherhost", "他机路径"), ("urlpath", "URL 路径"), ("extpath", "外部仓路径"), ("quote", "引文跳过"), ("missing", "真缺件")]


def index_roots():
    global INDEX
    if INDEX is not None:
        return INDEX
    INDEX = []
    for r in ROOTS:
        if not os.path.isdir(r):
            continue
        for dp, _d, fs in os.walk(r):
            if dp.count(os.sep) - r.count(os.sep) > 6:
                _d[:] = []
                continue
            for f in fs:
                INDEX.append(os.path.join(dp, f))
            if len(INDEX) > 250000:
                return INDEX
    return INDEX


def in_pack(ref):
    if os.path.isabs(ref):
        return ref if os.path.isfile(ref) and os.path.getsize(ref) > 0 else ""
    c = os.path.join(a.dir, ref.replace("/", os.sep))
    return c if os.path.isfile(c) and os.path.getsize(c) > 0 else ""


def exact_elsewhere(ref):
    p = ref.replace("/", os.sep)
    if os.path.isabs(p):
        return p if os.path.isfile(p) else ""
    for r in ROOTS:
        c = os.path.join(r, p)
        if os.path.isfile(c):
            return c
    return ""


def basename_hits(ref):
    base = os.path.basename(ref.replace("/", os.sep))
    if not base or "*" in base or "{" in base:
        return []
    return [f for f in index_roots() if os.path.basename(f) == base]


def glob_hits(ref):
    """通配引用要同时满足：文件名模式命中 + 引用里写死的目录段都在路径里。
    不加目录约束时 `tools/*.json` 会把全盘 19659 个 json 都算命中，那是假命中（v2 首跑踩过）。"""
    p = ref.replace("/", os.sep)
    base = os.path.basename(p)
    alts = [base]
    m = re.match(r"^(.*)\{([^}]*)\}(.*)$", base)
    if m:
        alts = [m.group(1) + x + m.group(3) for x in m.group(2).split(",")]
    if "{" not in base and not any("*" in x for x in alts):
        return []
    lits = [s for s in p.split(os.sep)[:-1] if s and "*" not in s and "{" not in s and not s.endswith(":")]
    hits = []
    for f in index_roots():
        bn = os.path.basename(f)
        ok = any(fnmatch.fnmatch(bn, alt) for alt in alts)
        if not ok:
            continue
        parts = f.replace("/", os.sep).split(os.sep)
        if all(any(l.lower() == q.lower() for q in parts) for l in lits):
            hits.append(f)
    return hits


def suffix_hits(ref):
    r"""引用写的是从某层往下的相对路径（如 `defect_logs\index.json`），就在全索引里按路径后缀找。"""
    segs = [s for s in ref.replace("/", os.sep).split(os.sep) if s]
    if len(segs) < 2 or any("*" in s or "{" in s for s in segs):
        return []
    tail = os.sep + os.sep.join(segs).lower()
    return [f for f in index_roots() if f.lower().endswith(tail)]


def classify(ref):
    if ref.startswith("/") and not re.match(r"[A-Za-z]:", ref):
        if re.match(r"^/(home|root|tmp|var|etc|usr|opt|mnt|srv)/", ref):
            return "otherhost", "另一台机器路径"
        return "urlpath", "本机 URL/接口路径，不是文件"
    if any(t in ref for t in ("=", "…", "...", "取不到")) or ref.startswith("-"):
        return "quote", "日志/命令/占位引文，不是一条可定位引用"
    if re.search(r"\.(json|md|txt|log|py)/(\.|\w)", ref):
        return "quote", "一个反引号里塞了两个文件名（a.json/b.md 写法），不是单条引用"
    if "Error:" in ref or "Traceback" in ref:
        return "quote", "日志行/异常片段，不是文件引用"
    if " --" in ref or "xxx" in ref or " / " in ref or ref in (".tar.gz", "tar.gz", ".zip") or re.match(r"^[\w.-]+\.(org|com|net|cn)/", ref):
        return "quote", "命令行片段/占位名/无协议 URL 片段，不是一条可定位引用"
    if os.path.basename(ref.replace("\\", "/")).startswith("发布前审查_20261123_") and ref.replace("\\", "/").endswith(".zip"):
        return "selfref", "审查包自身文件名（读者手上的容器），不是包内文件引用"
    if in_pack(ref):
        return "verified", "包内可读"
    if exact_elsewhere(ref):
        return "traceable", "包外精确路径实测存在"
    s = suffix_hits(ref)
    if s:
        return "traceable", "按路径后缀命中：" + s[0]
    g = glob_hits(ref)
    if g:
        return "glob", "通配命中 %d 个（示例 %s）" % (len(g), os.path.basename(g[0]))
    segs = [s for s in ref.replace("/", os.sep).split(os.sep) if s]
    if len(segs) >= 2:
        first = segs[0].rstrip(":")
        if not any(os.path.isdir(os.path.join(r, first)) or os.path.isdir(os.path.join(a.dir, first)) for r in ROOTS if os.path.isdir(r)):
            return "extpath", "仓内/远端相对路径，本机无此目录树"
    h = basename_hits(ref)
    if len(h) == 1:
        return "traceable", "同名唯一命中：" + h[0]
    if len(h) > 1:
        return "ambiguous", "同名 %d 处，需消歧" % len(h)
    return "missing", "包内没有、路径不存在、无通配可命中"


HMAP = {}
HMDIRS = set()
if a.hash_manifest and os.path.exists(a.hash_manifest):
    _hm = json.load(io.open(a.hash_manifest, encoding="utf-8"))
    HMAP = {x["name"]: x for x in _hm.get("files", [])}
    HMDIRS = set(x.replace("\\", "/") for x in _hm.get("dirs", []))

rows = []
for md in sorted(f for f in os.listdir(a.dir) if f.endswith(".md") and not any(fnmatch.fnmatch(f, e) for e in EXCL)):
    txt = io.open(os.path.join(a.dir, md), encoding="utf-8", errors="replace").read()
    refs = [m.group(1).strip() for m in REF.finditer(txt)] + [m.group(1).strip() for m in ABS.finditer(txt)]
    seen = set()
    for r in refs:
        if r in seen or "|" in r or "://" in r:
            continue
        seen.add(r)
        for pre in ("python3 ", "python ", "$ ", "./"):
            if r.startswith(pre):
                r = r[len(pre):]
        grade, why = classify(r)
        if grade in ("missing", "extpath", "otherhost", "ambiguous"):
            _b = os.path.basename(r.rstrip("\\/"))
            if _b in HMAP:
                grade, why = "hashdecl", "件不随包，按 SHA256 存证（%d 字节，清单见 51_收尾证据）" % HMAP[_b]["bytes"]
            else:
                _l = r.rstrip("\\/").replace("\\", "/")
                if any(d.endswith("/" + _l) or d == _l for d in HMDIRS):
                    grade, why = "hashdecl", "目录不随包，按目录存证（清单见 51_收尾证据）"
        rows.append({"doc": md, "ref": r, "grade": grade, "why": why})

cnt, by_doc = {}, {}
for r in rows:
    cnt[r["grade"]] = cnt.get(r["grade"], 0) + 1
    by_doc.setdefault(r["doc"], {}).setdefault(r["grade"], 0)
    by_doc[r["doc"]][r["grade"]] += 1

io.open(a.json, "w", encoding="utf-8").write(json.dumps(
    {"dir": a.dir, "roots": ROOTS, "total_refs": len(rows), "counts": cnt, "by_doc": by_doc, "refs": rows},
    ensure_ascii=False, indent=2))

if a.md:
    out = ["# 证据分档 v2（%d 条引用）\n" % len(rows),
           "> 由 `tools/evidence_grades.py` 生成。v2 比 v1 多拆出「通配命中 / 多义 / 引文跳过」，"
           "因为 v1 把这三类都记成「待补路径」——那是**分类粗，不是文档差**（缺陷 #38）。\n",
           "## 汇总\n", "| 档 | 条数 |", "|---|---|"]
    for k, label in ORDER:
        out.append("| %s | %d |" % (label, cnt.get(k, 0)))
    out.append("| **合计** | %d |\n" % len(rows))
    out.append("## 按文档\n")
    out.append("| 文档 | 可核实 | 可追溯 | 通配 | 多义 | 他机 | 外仓 | 引文 | 真缺件 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for d in sorted(by_doc):
        v = by_doc[d]
        out.append("| %s | " % d + " | ".join(str(v.get(k, 0)) for k, _ in ORDER) + " |")
    miss = [r for r in rows if r["grade"] == "missing"]
    out.append("\n## 真缺件（%d 条）：这些才是要补的东西\n" % len(miss))
    if miss:
        out.append("| 文档 | 引用 |")
        out.append("|---|---|")
        for r in miss:
            out.append("| %s | `%s` |" % (r["doc"], r["ref"]))
    amb = [r for r in rows if r["grade"] == "ambiguous"]
    out.append("\n## 多义待消歧（%d 条）：同名多处，文档里要点名是哪一份\n" % len(amb))
    if amb:
        out.append("| 文档 | 引用 | 说明 |")
        out.append("|---|---|---|")
        for r in amb[:40]:
            out.append("| %s | `%s` | %s |" % (r["doc"], r["ref"], r["why"]))
    io.open(a.md, "w", encoding="utf-8").write("\n".join(out) + "\n")

print("refs=%d " % len(rows) + " ".join("%s=%d" % (k, cnt.get(k, 0)) for k, _ in ORDER) + " -> " + a.json)
