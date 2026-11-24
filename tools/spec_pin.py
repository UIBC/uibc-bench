# -*- coding: utf-8 -*-
"""S0 补强：把"钉修订号"做成可检验的物件。

DID Resolution 只有 ED（Living/Editor's Draft，无修订号），所以钉法改为**三钉**：
  1. 规范 URL（正文首段）
  2. 抓取当日的正文 SHA-256（本工具记录）
  3. 章节锚点（引用处写 `#types` 这类）
任何一钉变了，下一次复跑就会对不上——这才是"可核"而不是"我记得是这么写的"。

用法：
    python tools/spec_pin.py --out runs/spec_pin.json [--dir <审查包>]

它做两件事：
  A. 抓取规范页与套件关键文件，记录 HTTP 状态、Last-Modified、ETag、正文 SHA-256（归一化前后各一份）。
  B. 扫审查包正文里所有 `w3c.github.io/did-resolution/#…` 锚点，检查该锚点在本轮抓到的正文里是否真实存在。
     锚点不存在 = 引用写错（不是"页面改版"就一定是，"页面改版"也要如实记录）。
"""
import argparse
import hashlib
import io
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone

TARGETS = [
    ("DID Resolution (ED)", "https://w3c.github.io/did-resolution/", True),
    ("DID Core (TR/REC)", "https://www.w3.org/TR/did-core/", True),
    ("suite tests/helpers.js", "https://raw.githubusercontent.com/w3c/did-resolution-test-suite/main/tests/helpers.js", False),
    ("suite resolvers/DIF.json", "https://raw.githubusercontent.com/w3c/did-resolution-test-suite/main/resolvers/DIF.json", False),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "uibc-spec-pin/0.4.17"})
    try:
        with urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()) as r:
            raw = r.read()
            return {"status": r.status, "last_modified": r.headers.get("Last-Modified"),
                    "etag": r.headers.get("ETag"), "bytes": len(raw), "body": raw}
    except Exception as e:
        return {"status": "ERR", "error": "%s: %s" % (type(e).__name__, e), "body": b""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/spec_pin.json")
    ap.add_argument("--dir", default="")
    a = ap.parse_args()

    rec = {"generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
           "method": "GET + SHA-256（正文归一化前后各一份）", "targets": [], "anchors": []}
    bodies = {}
    for name, url, required in TARGETS:
        r = fetch(url)
        body = r.pop("body", b"")
        text = body.decode("utf-8", "replace")
        norm = re.sub(r"<[^>]+>", " ", text)
        norm = re.sub(r"\s+", " ", norm).strip()
        r.update({"name": name, "url": url, "required": required,
                  "sha256_raw": hashlib.sha256(body).hexdigest().upper() if body else None,
                  "sha256_text": hashlib.sha256(norm.encode("utf-8")).hexdigest().upper() if norm else None})
        rec["targets"].append(r)
        if r["status"] == 200:
            bodies[url] = (text, norm)

    if a.dir and "https://w3c.github.io/did-resolution/" in bodies:
        text, norm = bodies["https://w3c.github.io/did-resolution/"]
        ids = set(re.findall(r'id="([^"]+)"', text))
        used = set()
        for root, _d, names in os.walk(a.dir):
            for n in names:
                if not n.endswith((".md", ".html")):
                    continue
                t = io.open(os.path.join(root, n), encoding="utf-8", errors="replace").read()
                for m in re.finditer(r"did-resolution(?:/)?(?:#|&#35;)([A-Za-z0-9_\-\.]+)", t):
                    used.add(m.group(1))
        for anc in sorted(used):
            rec["anchors"].append({"anchor": anc,
                                   "exists_in_ed": anc in ids,
                                   "file": "见正文"})

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)

    for t in rec["targets"]:
        print("[%s] %s  http=%s  bytes=%s  sha256_text=%s  lm=%s" %
              (t["status"], t["name"], t["status"], t.get("bytes"),
               (t.get("sha256_text") or "")[:16], (t.get("last_modified") or "-")))
    if rec["anchors"]:
        bad = [x["anchor"] for x in rec["anchors"] if not x["exists_in_ed"]]
        print("锚点 %d 个，其中有 %d 个在 ED 正文里找不到：%s" % (len(rec["anchors"]), len(bad), bad or "无"))
    print("json=%s" % a.out)
    req = [t for t in rec["targets"] if t.get("required")]
    opt_bad = [t["name"] for t in rec["targets"] if not t.get("required") and t["status"] != 200]
    if opt_bad:
        print("可选目标不可达（不计失败，但需在报告里写明）：%s" % opt_bad)
    return 0 if all(t["status"] == 200 for t in req) else 1


if __name__ == "__main__":
    sys.exit(main())
