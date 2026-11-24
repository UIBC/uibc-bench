# -*- coding: utf-8 -*-
"""从看板 HTML 抽出「自身缺陷台账」，落成独立 markdown 证据件。

为什么要这个工具：全文级复核连着四轮都对 38 号 S4 行判「夸大」，理由是
「未提供具体的缺陷修复日志或复跑结果文件」。台账原先长在 09 号看板 HTML 里的一张表，
机器读不动、外人也翻不到。把台账抽成独立 md（每条带根因、危害、修法、验证读数、来源行），
证据就从「藏在一个 76 KB HTML 的第 541 行」变成「一个可以直接打开的文件」。

纪律：只搬运与排版，不改台账内容；每条标来源行号；凑不齐的编号如实列出，不编条目。
"""
import io
import os
import re
import sys

if len(sys.argv) < 3:
    print("usage: defects_ledger.py <board.html> <out.md>"); sys.exit(0)

HTML = sys.argv[1]
OUT = sys.argv[2]

raw = io.open(HTML, encoding="utf-8").read()


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def line_of(pos):
    return raw.count("\n", 0, pos) + 1


def first_sentence(seg, limit=200):
    t = strip_tags(seg)
    for sep in ("。", "；"):
        t = t.split(sep)[0]
    return t[:limit].strip()


anchor = raw.find("自身缺陷台账")
if anchor < 0:
    sys.exit("找不到「自身缺陷台账」")
tstart = raw.find("<table", anchor)
tend = raw.find("</table>", tstart)
rows = []
for m in re.finditer(r"<tr>(.*?)</tr>", raw[tstart:tend], re.S):
    cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
    if len(cells) >= 4:
        rows.append((cells, line_of(tstart + m.start())))

patterns = [
    r"第\s*(\d+)\s*个缺陷",
    r"（第\s*(\d+)\s*个）",
    r"第\s*(\d+)\s*/\s*(\d+)\s*个",
]
mentions = {}
for pat in patterns:
    for m in re.finditer(pat, raw):
        tail = first_sentence(raw[m.start(): m.start() + 420])
        for g in m.groups():
            if g and int(g) not in mentions:
                mentions[int(g)] = (tail, line_of(m.start()))
found = sorted(mentions)
missing = [n for n in range(1, 19) if n not in mentions]

out = []
out.append("# 自身缺陷台账（独立证据件，v0.4.21）\n")
out.append("> 由 `tools/defects_ledger.py` 从 `09_S5_可视化看板.html` 自动抽出，内容不改一字，每条标来源行号。")
out.append("> 用途：把原先长在 HTML 里的台账变成机器可读、外人可翻的证据件。\n")
out.append("## 一 主台账（含根因 / 危害 / 修法与验证 / 状态）\n")
out.append("| # | 缺陷 | 根因 | 危害 | 修法与验证 | 状态 | 来源行 |")
out.append("|---|---|---|---|---|---|---|")
for cells, ln in rows:
    c = [x.replace("|", "／") for x in (cells + [""] * 6)[:6]]
    out.append("| " + " | ".join(c) + " | %d |" % ln)
out.append("")
out.append("## 二 散落在各小节的编号缺陷（只认三种写法，共 %d 条：%s）\n"
           % (len(found), "、".join(str(x) for x in found)))
if found:
    out.append("| 编号 | 原文首句（截至第一个句号或分号） | 来源行 |")
    out.append("|---|---|---|")
    for n in found:
        txt, ln = mentions[n]
        out.append("| %d | %s | %d |" % (n, txt.replace("|", "／"), ln))
else:
    out.append("（无）")
out.append("")
if missing:
    out.append("**本件未逐字核到编号 %s**：它们在看板与 38/42/43 号里以叙述形式出现，"
               "本件不为凑齐 1–18 而编条目，需要时按看板对应小节回看。\n"
               % "、".join(str(x) for x in missing))
out.append("## 三 怎么核\n")
out.append("1. 每条按「来源行」回 `09_S5_可视化看板.html` 对应行逐字比对，本件不改写。")
out.append("2. 「验证」列里的读数（如 `s02 13P/2I`、`4-did 14/1`）来自该轮实跑，可对照 `runs/` 与基线 `baseline.json`。")
out.append("3. 本件是「台账」，**不是**逐条独立的复跑日志文件；这一点在看板与 43 号里都写明，不靠措辞混过去。")

io.open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("rows=%d numbered=%d missing=%d -> %s (%d bytes)"
      % (len(rows), len(found), len(missing), OUT, os.path.getsize(OUT)))
