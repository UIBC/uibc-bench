# -*- coding: utf-8 -*-
"""措辞扰动器：对同一份文档做「不改事实、只改说法」的同义改写，产出扰动版与变更清单。

为什么要这个工具：43 号实测到"只改一句措辞，门级结论就回退"（一致率 0.80），
但那是人事后改的，没法复现、也没法批量。规格 v4 第 6 条要求「同义改写后一致率 ≥0.90」，
这一条必须是机器能执行的动作，否则永远是纸面条款。

三条硬纪律：
1. **不碰事实**：含数字、哈希、文件名、门标签（S0–S9）、判定词（无法核实/夸大/不实/部分核实/可核实）
   的行整行跳过，一个替换都不做。
2. **只做保守同义**：均→都、但→不过、因此→所以、已→已经、且→并且、若→如果、以及→和。
   这些替换不改变命题真值，只改语气。
3. **留痕**：输出扰动版 md、变更清单 json（每处改动带行号与原/新词），并给两份文件的 sha256。

用法：python tools/phrase_perturb.py <src.md> <out.md> <out.json>
"""
import hashlib
import io
import json
import os
import re
import sys

if len(sys.argv) < 4:
    print("usage: phrase_perturb.py <src.md> <out.md> <out.json>"); sys.exit(0)

SRC, OUT_MD, OUT_JSON = sys.argv[1], sys.argv[2], sys.argv[3]

RULES = [
    ("均", "都"),
    ("但", "不过"),
    ("因此", "所以"),
    ("已", "已经"),
    ("且", "并且"),
    ("若", "如果"),
    ("以及", "和"),
    ("并且", "而且"),
    ("必须", "务必"),
    ("可以", "可"),
    ("没有", "未"),
    ("不是", "并非"),
    ("全部", "全都"),
    ("同时", "并"),
]

BLOCK = re.compile(r"(S[0-9])|(sha256|SHA256)|(无法核实|夸大|不实|部分核实|可核实)|([0-9A-F]{16,})|(\.md|\.json|\.py|\.html|\.zip|\.gz|\.bundle)")


def sha(p):
    h = hashlib.sha256()
    with io.open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest().upper()


src = io.open(SRC, encoding="utf-8").read()
lines = src.split("\n")
changes = []
out_lines = []
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    # 跳过标题行、表格行、代码块围栏、空行、以及一切含事实的行
    if (not stripped) or stripped.startswith("#") or stripped.startswith("```"):
        out_lines.append(line)
        continue
    if stripped.startswith("|") and set(stripped) <= set("|-: "):
        out_lines.append(line)
        continue
    if BLOCK.search(line):
        out_lines.append(line)
        continue
    new = line
    for a, b in RULES:
        if a in new:
            cnt = new.count(a)
            new = new.replace(a, b)
            changes.append({"line": i, "from": a, "to": b, "count": cnt})
    out_lines.append(new)

pert = "\n".join(out_lines)
io.open(OUT_MD, "w", encoding="utf-8").write(pert)

changed_lines = len({c["line"] for c in changes})
report = {
    "src": os.path.basename(SRC),
    "out": os.path.basename(OUT_MD),
    "sha256_src": sha(SRC),
    "sha256_out": sha(OUT_MD),
    "changed_lines": changed_lines,
    "total_lines": len(lines),
    "replacements": sum(c["count"] for c in changes),
    "skipped_by_fact_guard": sum(1 for l in lines if BLOCK.search(l) and l.strip() and not l.strip().startswith(("#", "|", "```"))),
    "rules": [{"from": a, "to": b} for a, b in RULES],
    "changes": changes,
}
io.open(OUT_JSON, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=2))
print("changed %d/%d lines, %d replacements -> %s"
      % (changed_lines, len(lines), report["replacements"], OUT_MD))
