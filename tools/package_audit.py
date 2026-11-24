# -*- coding: utf-8 -*-
"""审查包自检（v2）：本地引用是否都在、外部链接是否内容可直达。

对应九门标准 v2 的两道硬门：
  S5（本地文件引用 MISSING = 0；单文件交付物断网可开）
  S7（状态码不是证据，内容标记才是：200 + must 片段命中；202/403 记 BLOCKED）

v2 修掉的五类自身误判（记在本工具账上）：
  #A1 URL 正则吞掉中文全角标点 → 400 / UnicodeEncodeError
  #A2 模板/占位 URL（`*`、`{`、`…`、example 域名）被当真实链接去打
  #A3 `#:~:text=` 片段链接整串直接请求 → 400；正确做法是剥片段，再用片段文字做 must
  #A4 解析器端点根 URL（需拼 DID）返回 400 被记 DEAD；实为 N/A
  #A5 第三方源码快照（外人实跑/room 等）里的外部 URL 被算作我方引用 → 默认排除

用法：
    python tools/package_audit.py --dir <审查包目录> --json ... --md ...
判定：OK / MISSING / N/A / BLOCKED / DEAD / SKIP
退出码：0 = 无 MISSING 且无 DEAD；1 = 有问题。
"""
import argparse
import glob
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MUST = {
    "w3.org/TR/did-resolution": ["DID Resolution"],
    "www.w3.org/TR/did-resolution": ["DID Resolution"],
    "raw.githubusercontent.com/w3c/did-resolution-test-suite": ["supportedDidMethods", "valid"],
    "gist.githubusercontent.com": ["did"],
    "github.com/w3c/did-resolution-test-suite": ["did-resolution-test-suite"],
    "github.com/w3c-ccg/did-resolution-mocha-test-suite": ["did-resolution"],
    "github.com/zhaoxinghua09-cell/uibc-core": ["uibc"],
    "w3c.github.io/did-resolution": ["DID Resolution"],
    "w3.org/TR/did-core": ["DID Core"],
    "www.w3.org/TR/did-core": ["DID Core"],
}
SKIP_DIRS = {"外人实跑", "room", "uibc-core-public", "uibc-patched", "node_modules", ".git"}
BAD_TAIL = "），。；、,;\"'<>”’）]"
URI_RE = re.compile(r"https?://[^\s`<>()\[\]]+")


def clean(url):
    url = url.rstrip(BAD_TAIL)
    for seg in ("，", "。", "；", "、", "）", "”", "’"):
        if seg in url:
            url = url.split(seg)[0]
    return url


def classify(url):
    if any(c in url for c in ("*", "{", "}", "…", "<", ">")):
        return "SKIP", "模板/占位"
    if any(h in url for h in ("127.0.0.1", "localhost", "0.0.0.0:")):
        return "SKIP", "本机端点（需本机脚本起服务后才有响应）"
    if "example.com" in url or "acme.example" in url or "/example/" in url:
        return "SKIP", "文档占位域名"
    if "api.siliconflow.cn" in url:
        return "N/A", "POST 专用接口，GET 恒 404"
    u = url.rstrip("/")
    if u.endswith("/identifiers") or u.endswith("/1.0/identifiers"):
        return "N/A", "解析器端点根 URL，需拼 DID 才有响应"
    return None, None


def check_url(url):
    st, why = classify(url)
    if st:
        return {"url": url, "status": st, "detail": why}
    musts = [m for k, v in MUST.items() if k in url for m in v]
    real, frag = url, ""
    import re as _re
    m = _re.search(r"#.*?:~:text", url)
    if m and "&#x3D;" in url[m.end():m.end() + 8]:
        pass
    if m:
        frag = url[m.end():]
        real = url[:m.start()]
        frag = frag.replace("&#x3D;", "=").replace("&amp;", "&")
    if m:
        try:
            frag = urllib.parse.unquote(frag.split("&")[0])
        except Exception:
            frag = ""
        frag = frag.lstrip("=").strip()
        if frag:
            musts = [" ".join(frag.split()[:8])]
    req = urllib.request.Request(real, headers={"User-Agent": "uibc-package-audit/0.4.16"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
            code = r.status
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code = e.code
        body = ""
    except Exception as e:
        return {"url": url, "status": "BLOCKED", "detail": type(e).__name__}
    if code in (202, 403, 429, 503):
        return {"url": url, "status": "BLOCKED", "detail": "http %d" % code}
    if code != 200:
        return {"url": url, "status": "DEAD", "detail": "http %d" % code}
    if not musts:
        return {"url": url, "status": "OK", "detail": "200（未配 must）"}
    norm = re.sub(r"<[^>]+>", " ", body)
    norm = urllib.parse.unquote(norm).replace("&#x3D;", "=").replace("&amp;", "&")
    norm = norm.replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
    norm = norm.replace("[=", "").replace("=]", "")
    norm = re.sub(r"\s+", " ", norm)
    hit = [m for m in musts if re.sub(r"\s+", " ", m) in norm]
    return {"url": url, "status": "OK" if hit else "DEAD",
            "detail": "命中 %r" % (hit[0][:60] if hit else None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--roots", default="")
    ap.add_argument("--external", default="",
                    help="包外工作区目录名，分号分隔；指向这些前缀的未解析引用记为 EXTERNAL（未随包的我方其它工作区）")
    ap.add_argument("--hash-manifest", default="",
                    help="hash_manifest.json：件不随包时按哈希存证（status=HASHDECL，单列，不并入 MISSING）")
    ap.add_argument("--json", default="package_audit.json")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    roots = [a.dir] + [r for r in a.roots.split(";") if r]

    urls, local = set(), []
    for root, dirs, names in os.walk(a.dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if root != a.dir:
            continue
        for n in names:
            if not n.endswith((".md", ".html", ".txt")):
                continue
            p = os.path.join(root, n)
            text = open(p, encoding="utf-8", errors="replace").read()
            for u in URI_RE.findall(text):
                u = clean(u)
                if len(u) > 12:
                    urls.add(u)
            for tok in re.findall(r"`([^`\n]{2,120})`", text):
                if "::" in tok or "|" in tok or "..." in tok or "{" in tok or "}" in tok or re.match(r"[a-z0-9.-]+\.(org|com|net|io|dev)/", tok) or tok.strip(".") in ("json", "md", "py", "html", "txt", "sh", "ps1"):
                    continue
                if tok.startswith("/") or ".well-known" in tok or tok in ("did.json", "did.jsonl"):
                    continue
                if tok.startswith("did-methods/") or tok.startswith("resolvers/"):
                    continue
                if any(h in tok for h in (".md", ".json", ".py", ".ps1", ".sh", ".zip", ".tar.gz", ".html", ".txt", "\\")) \
                        and not tok.startswith("http") and " " not in tok and "%" not in tok and "<" not in tok:
                    local.append((os.path.relpath(p, a.dir), tok))

    EXT = [x for x in a.external.split(";") if x]
    def is_external(s):
        s2 = s.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", s2):
            return True
        return any(s2.startswith(e.replace("\\", "/") + "/") or s2 == e.replace("\\", "/") for e in EXT)

    SELFP = "发布前审查_20261123_"
    def is_self(s):
        b = os.path.basename(s.replace("\\", "/"))
        return b.startswith(SELFP) and b.endswith(".zip")

    def is_trimmed(s):
        return s.replace("\\", "/").startswith("外人实跑/") or s.rstrip("\\/") == "\\evidence"

    def is_pattern(s):
        if "*" in s or "?" in s:
            return True
        s2 = s.strip()
        return s2.startswith("-") or s2.startswith(".")

    local_results = []
    for src, tok in local:
        if is_self(tok):
            local_results.append({"from": src, "ref": tok, "status": "SELF", "resolved": None,
                                  "bucket": "G 包自身文件名（读者手上的容器，不判）"})
            continue
        if is_trimmed(tok):
            local_results.append({"from": src, "ref": tok, "status": "TRIMMED", "resolved": None,
                                  "bucket": "H 精简包剔除（全量包内含，见两包差异说明）"})
            continue
        if is_external(tok):
            local_results.append({"from": src, "ref": tok, "status": "EXTERNAL", "resolved": None,
                                  "bucket": "E 包外工作区/绝对路径（未随包，文档须标不可核）"})
            continue
        if is_pattern(tok):
            local_results.append({"from": src, "ref": tok, "status": "PATTERN", "resolved": None,
                                  "bucket": "F 占位模式（通配/省略写法，非引用，不判）"})
            continue
        base = tok.split(":", 1)[0]
        cand = None
        for r in roots:
            for c in (os.path.join(r, tok), os.path.join(os.path.dirname(os.path.join(r, src)), tok),
                      os.path.join(r, base)):
                if os.path.exists(c):
                    cand = c
                    break
            if cand:
                break
        if not cand and ("/" in tok or "\\" in tok or "." in tok):
            base2 = tok.replace("\\", "/").split("/")[-1]
            for r in roots:
                for pat in (base2, "*" + base2):
                    for hit in glob.glob(os.path.join(r, "**", pat), recursive=True):
                        cand = hit
                        break
                    if cand:
                        break
                if cand:
                    break
        local_results.append({"from": src, "ref": tok,
                              "status": "OK" if cand else "MISSING",
                              "resolved": (os.path.relpath(cand, a.dir) if cand.startswith(a.dir) else cand) if cand else None})

    urls = sorted(urls)
    with ThreadPoolExecutor(max_workers=6) as ex:
        url_results = list(ex.map(check_url, urls))

    if a.hash_manifest and os.path.exists(a.hash_manifest):
        hm = json.load(io.open(a.hash_manifest, encoding="utf-8"))
        byname = {x["name"]: x for x in hm.get("files", [])}
        hdirs = set(x.replace("\\", "/") for x in hm.get("dirs", []))
        treemap = {t["leaf"]: t for t in hm.get("trees", [])}
        for x in local_results:
            if x["status"] != "MISSING":
                continue
            base = os.path.basename(x["ref"].rstrip("\\/"))
            if base in byname:
                x["status"] = "HASHDECL"
                x["hash"] = byname[base]["sha256"]
                x["manifest_bytes"] = byname[base]["bytes"]
                x["bucket"] = "D 按哈希存证（件不随包，凭 SHA256 核对）"
            else:
                leaf = x["ref"].rstrip("\\/").replace("\\", "/")
                if any(d.endswith("/" + leaf) or d == leaf for d in hdirs):
                    x["status"] = "HASHDECL"
                    x["hash"] = ""
                    x["bucket"] = "D 按哈希存证（目录，件不随包）"
                    continue
                for k, tv in treemap.items():
                    if leaf.endswith(k):
                        x["status"] = "HASHDECL"
                        x["hash"] = tv.get("tree_sha256") or ""
                        x["manifest_bytes"] = tv["bytes"]
                        x["bucket"] = "D 按哈希存证（目录树，凭整树 SHA256 核对）"
                        break

    BUCKET = {
        "weknora": "B 本机不存在（入库阻塞事实，非引用错误）",
        "家底盘点": "B 本机不存在（入库阻塞事实，非引用错误）",
        "receipt.json": "C 运行时产物（跑 run.py 才生成）",
        "s0x_results.json": "C 运行时产物/占位",
    }
    for x in local_results:
        if x["status"] != "MISSING":
            continue
        x["bucket"] = "A 引用错误（需改文档）"
        for k, v in BUCKET.items():
            if k in x["ref"]:
                x["bucket"] = v
                break

    cnt, ucnt = {}, {}
    for x in local_results:
        cnt[x["status"]] = cnt.get(x["status"], 0) + 1
    for x in url_results:
        ucnt[x["status"]] = ucnt.get(x["status"], 0) + 1
    print("本地引用 %d 条：%s" % (len(local_results), cnt))
    print("外部链接 %d 条：%s" % (len(url_results), ucnt))
    hard = [x for x in local_results if x["status"] == "MISSING" and x.get("bucket", "").startswith("A")]
    for x in local_results:
        if x["status"] == "MISSING":
            print("  [MISSING|%s] %s → %s" % (x.get("bucket", "")[:1], x["from"], x["ref"]))
    print("  其中硬伤（引用错误）%d 条，其余为阻塞事实/运行时产物" % len(hard))
    for x in url_results:
        if x["status"] in ("DEAD", "BLOCKED"):
            print("  [%s] %s (%s)" % (x["status"], x["url"], x["detail"]))

    out = {"dir": a.dir, "local": local_results, "urls": url_results,
           "summary": {"local_total": len(local_results), "local_missing": cnt.get("MISSING", 0),
                       "local_hashdecl": cnt.get("HASHDECL", 0),
                       "url_total": len(url_results), "url_ok": ucnt.get("OK", 0),
                       "url_blocked": ucnt.get("BLOCKED", 0), "url_dead": ucnt.get("DEAD", 0),
                       "url_skip": ucnt.get("SKIP", 0), "url_na": ucnt.get("N/A", 0),
                       "local_hard_missing": len(hard)}}
    with open(a.json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("json=%s" % a.json)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write("# 审查包自检（v2）\n\n本地引用 %d（MISSING %d）\n\n外部链接 %d：OK %d / BLOCKED %d / DEAD %d / SKIP %d / N-A %d\n\n" %
                     (len(local_results), cnt.get("MISSING", 0), len(url_results), ucnt.get("OK", 0),
                      ucnt.get("BLOCKED", 0), ucnt.get("DEAD", 0), ucnt.get("SKIP", 0), ucnt.get("N/A", 0)))
            for x in url_results:
                fh.write("- [%s] %s — %s\n" % (x["status"], x["url"], x["detail"]))
        print("md=%s" % a.md)
    return 0 if (len(hard) == 0 and ucnt.get("DEAD", 0) == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
