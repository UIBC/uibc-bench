# -*- coding: utf-8 -*-
"""L2 红线扫描（S2 层）：禁写词 / 身份 / 授权三类。

判据：命中即列出；若命中词前后 ±14 字内有否定词（不主张/不得/不能/禁止/不算/不称/并非），记为 NEGATED（合规引用），否则记 HIT（硬伤）。

用法：
    python tools/no_claim_scan.py --dir <目录> --json out.json
退出码：0 = 无 HIT；1 = 有 HIT。
"""
import argparse
import json
import os
import re
import sys

HARD = [
    "断崖式领先", "全面超越", "遥遥领先", "模拟所有环境", "符合 W3C", "符合W3C", "通过信通院",
    "已验签", "平台已验签", "需方权限收紧", "发现对方漏洞", "没有任何第三方复现", "零缺陷",
    "100% 通过", "100%通过", "完全兼容", "国际认证", "已获认可",
]
SOFT = ["首创", "唯一实现", "唯一提供", "唯一一家", "世界领先", "行业第一", "最佳实践", "第一个实现"]
NEG = ["不主张", "不得", "不能", "禁止", "不算", "不称", "并非", "不写", "不要说", "须避免", "不得称",
       "不可以", "不可说", "不能说", "别说", "别把", "不准确", "不成立", "错", "已改", "纠正", "红线",
       "禁写", "不宜", "慎用", "改写", "降级", "了结", "不应当", "不应", "避免使用", "拒用", "禁用",
       "✗", "×", "无此", "没有这", "不存在"]
SKIP_DIRS = {"node_modules", ".git", "room", "uibc-core-public"}
EXT = (".md", ".html", ".txt")


def scan(text, word):
    out = []
    for m in re.finditer(re.escape(word), text, flags=re.I):
        s = max(0, m.start() - 16)
        ctx = text[s:m.end() + 16]
        line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end()) if text.find("\n", m.end()) > 0 else len(text)]
        if re.search(r"[“\"|]\s*[\"“]" + re.escape(word), line) and "|" in line:
            quoted = True
        else:
            quoted = ("<td>" in line and "</td>" in line and
                      any(k in line for k in ("自评", "不符", "恒为", "只能填", "我们不", "不许", "不行")))
        if any(n in ctx for n in NEG) or any(n in line for n in NEG) or quoted:
            out.append({"word": word, "verdict": "NEGATED", "context": ctx.replace("\n", " ")[:90]})
        else:
            out.append({"word": word, "verdict": "HIT", "context": line.strip()[:120]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--json", default="no_claim_scan.json")
    a = ap.parse_args()
    rows = []
    for root, dirs, names in os.walk(a.dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if not n.endswith(EXT):
                continue
            p = os.path.join(root, n)
            text = open(p, encoding="utf-8", errors="replace").read()
            for w in HARD + SOFT:
                for hit in scan(text, w):
                    hit["file"] = os.path.relpath(p, a.dir)
                    hit["severity"] = "HARD" if w in HARD else "SOFT"
                    rows.append(hit)
    hard = [r for r in rows if r["verdict"] == "HIT"]
    neg = len([r for r in rows if r["verdict"] == "NEGATED"])
    print("命中 %d 处：HIT %d / NEGATED(合规引用) %d" % (len(rows), len(hard), neg))
    files = sorted({r["file"] for r in hard})
    for r in hard:
        print("  [HIT] %s | %s | %s" % (r["file"], r["word"], r["context"][:70]))
    with open(a.json, "w", encoding="utf-8") as fh:
        json.dump({"dir": a.dir, "total": len(rows), "hit": len(hard), "negated": neg,
                   "hit_files": files, "rows": rows}, fh, ensure_ascii=False, indent=1)
    print("json=%s" % a.json)
    return 0 if not hard else 1


if __name__ == "__main__":
    sys.exit(main())
