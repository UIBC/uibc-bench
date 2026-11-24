# -*- coding: utf-8 -*-
"""断言清单：把正文切成**编号断言**，让评审方必须逐条回 id，缺一条即视为未审。

为什么要它：实战里发现，评审方对"整篇文档"其实只审摘要表——表外的假主张（标题里的"已由信通院
复核确认"、正文里的"十门全过"）它一句都没看。所以"逐句质疑 / 全量"在提示词里写了等于没写，
必须有**强制覆盖**的编号清单 + 覆盖率读数，才能把"它审了几条"从感觉变成数字。

用法：
    python tools/claim_inventory.py --src <正文.md> --out runs/claims.json --max 70
"""
import argparse
import io
import json
import re
import sys

ASSERTIVE = ["已", "是", "无", "全部", "没有", "确认", "通过", "阻塞", "不主张", "未",
             "钉", "同值", "归零", "无法", "均为", "只", "不", "零"]

FENCE = re.compile(r"```")


def sentences(text):
    """按行处理：表格行=1 条断言；正文按句号分句。代码块整体跳过。
    每句带上"所在小节"，后面据此把断言归到 S0–S9 某一门（全文级读数要有门）。"""
    out, infence, sec = [], False, ""
    for ln in text.splitlines():
        if FENCE.match(ln.strip()):
            infence = not infence
            continue
        if infence:
            continue
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            lvl = len(s) - len(s.lstrip("#"))
            sec = s.lstrip("#").strip(" -*")
            if lvl == 1:
                # 一级标题是文档名，不是某一门的小节；否则 "S0–S9" 会把开头的断言全误归 S0
                sec = ""
            # 标题里也会写主张（"已由信通院复核确认"就是这样漏掉的），只跳过纯标题
            if len(sec) >= 12 and any(k in sec for k in ASSERTIVE + ["确认", "复核"]):
                out.append(("heading", sec, sec))
            continue
        if s.startswith("|"):
            if set(s.replace("|", "").strip()) <= set("-: "):   # 表格分隔行
                continue
            out.append(("table", s, sec))
            continue
        for part in re.split(r"[。！？]", s):
            p = part.strip(" -*>").strip()
            if len(p) >= 12:
                out.append(("prose", p + "。", sec))
    return out


def worth_claim(kind, s):
    if kind == "table":
        return len(s) >= 30
    has_num = bool(re.search(r"[0-9]", s))
    has_verb = any(k in s for k in ASSERTIVE)
    return len(s) >= 18 and (has_num or has_verb)


def gate_of(text):
    m = re.search(r"S[0-9]", text or "")
    return m.group(0) if m else ""


def build(src, out, cap, must=()):
    text = io.open(src, encoding="utf-8").read()
    claims, seen, cand = [], set(), 0
    for kind, s, sec in sentences(text):
        if not worth_claim(kind, s):
            continue
        key = re.sub(r"\s+", "", s)[:60]
        if key in seen:
            continue
        seen.add(key)
        cand += 1
        if cap and len(claims) >= cap:
            continue
        claims.append({"id": "C%03d" % (len(claims) + 1), "kind": kind,
                       "section": sec[:60], "gate": gate_of(sec) or gate_of(s),
                       "text": re.sub(r"\s+", " ", s)[:300]})
    os_dir = out.rsplit("\\", 1)[0] if "\\" in out else "."
    if os_dir and not __import__("os").path.isdir(os_dir):
        __import__("os").makedirs(os_dir, exist_ok=True)
    truncated = cand > len(claims)
    gated = sum(1 for c in claims if c["gate"])
    json.dump({"src": src, "cap": cap, "candidates": cand, "truncated": truncated,
               "gated": gated, "claims": claims},
              io.open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tb = sum(1 for c in claims if c["kind"] == "table")
    print("断言清单 %d 条（候选 %d，表格行 %d / 正文句 %d，可归门 %d%s）→ %s"
          % (len(claims), cand, tb, len(claims) - tb, gated,
             "，**已截断**" if truncated else "", out))
    bad = []
    for k in must:
        if not any(k in c["text"] for c in claims):
            bad.append(k)
    if bad:
        print("[FAIL] 这些关键串不在清单里（清单漏了它们就等于没测）：%s" % "、".join(bad))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=0, help="0=不截断")
    ap.add_argument("--must", nargs="*", default=[], help="必须出现在清单里的关键串，缺一即 FAIL")
    a = ap.parse_args()
    return build(a.src, a.out, a.max, a.must)


if __name__ == "__main__":
    sys.exit(main())
