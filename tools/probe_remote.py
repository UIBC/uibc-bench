# -*- coding: utf-8 -*-
"""对**公开注册**的 resolver 端点跑同一组绑定层断言（只读 GET，不改对方任何东西）。

用途：把"我们的 15 条断言"当尺子，去量与 w3c 套件 `resolvers/*.json` 里登记的实现。
不需要对方的密钥，也不需要对方配合——对着公开端点发十几次 GET 就行。

判定分三档：
  PASS / FAIL —— 该条适用且有明确结论
  N/A  —— 这条需要"该方法自己的一条有效 DID"，我们没有（例如 cheqd/iden3/btcr2），
           如实标 N/A，**不许把 N/A 算成通过或以失败论处**

用法：
  python tools/probe_remote.py --name DIF --base-url https://dev.uniresolver.io/1.0/identifiers \
      --did did:key:z6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp --json dif.json
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

DOC_MEDIA = "application/did+ld+json"
RES_MEDIA = "application/did-resolution"


def http(base, path, accept=None, timeout=20, scheme_check=None):
    url = (scheme_check or base) + path
    req = urllib.request.Request(url, headers={"User-Agent": "uibc-bench-probe/0.4.11"})
    if accept:
        req.add_header("Accept", accept)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except Exception as e:
        return None, {}, str(e).encode()


def J(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--did", default="")
    ap.add_argument("--json", default="remote_probe.json")
    a = ap.parse_args()

    base = a.base_url.rstrip("/")
    did = a.did
    res = []

    def add(cid, state, detail):
        res.append(dict(id=cid, state=state, detail=str(detail)[:300]))

    # ---- 负向/绑定类：不需要有效 DID ----
    st, hd, raw = http(base, "/not-a-did", RES_MEDIA)
    add("B5 INVALID_DID not-a-did → 400", "PASS" if st == 400 else "FAIL", "status=%s" % st)

    st2, _, raw2 = http(base, "/did:example", RES_MEDIA)
    add("B6 INVALID_DID did:example → 400", "PASS" if st2 == 400 else "FAIL", "status=%s" % st2)

    st3, _, raw3 = http(base, "/did:foo:abc", RES_MEDIA)
    e3 = ((J(raw3) or {}).get("didResolutionMetadata") or {}).get("error") or {}
    add("B7 未知方法 → 501", "PASS" if st3 == 501 else "FAIL", "status=%s" % st3)

    etype = str(e3.get("type", ""))
    add("B8 失败响应带 error.type",
        "PASS" if etype else "FAIL", "type=%r" % etype)
    add("B8b error.type 用 DID 命名空间 URI 形式（观察项，规范未强制）",
        "PASS" if etype.startswith("https://www.w3.org/ns/did#") else "INFO",
        "type=%r" % etype)

    d3 = J(raw3) or {}
    add("B9 失败时 didDocumentMetadata 为空",
        "PASS" if d3.get("didDocumentMetadata") in ({}, None) else "FAIL",
        "metadata=%r" % (d3.get("didDocumentMetadata"),))

    st4, hd4, raw4 = http(base, "/" + urllib.parse.quote(did, safe="") if did else "/did:foo:abc", "text/html")
    e4 = ((J(raw4) or {}).get("didResolutionMetadata") or {}).get("error") or {}
    ok4 = "REPRESENTATION_NOT_SUPPORTED" in json.dumps(e4) or (st4 or 0) >= 400
    add("B4 不支持的 Accept 被拒", "PASS" if ok4 else "FAIL",
        "status=%s error=%s" % (st4, e4.get("title")))

    st5, _, _ = http(base, "/" + urllib.parse.quote(did, safe="") + "?versionTime=not-a-date" if did else "/did:foo:abc?versionTime=not-a-date", RES_MEDIA)
    add("B13 非法 versionTime 被拒（不静默通过）",
        "PASS" if (st5 or 500) >= 400 else "FAIL", "status=%s" % st5)

    st6, hd6, _ = http(base, "/not-a-did", RES_MEDIA)
    ctype = (hd6.get("content-type") or "").split(";")[0].strip()
    add("B16 错误响应也有 Content-Type", "PASS" if ctype else "FAIL", "ctype=%r" % ctype)

    # 明文 HTTP 同一主机必须拿不到结果
    host = base.split("://", 1)[-1].split("/")[0]
    st7, _, raw7 = http("", "/1.0/identifiers/not-a-did", RES_MEDIA, timeout=10,
                        scheme_check="http://" + host)
    plain_rejected = st7 is None or (isinstance(raw7, bytes) and raw7 and b"ERR" not in raw7 and st7 != 200)
    add("B15 明文 HTTP 拿不到结果（HTTPS-only）",
        "PASS" if (st7 is None or st7 >= 400 or st7 == 0) else "FAIL",
        "status=%s" % st7)

    # 5xx 崩溃检查
    bad5xx = [x for x in (st, st2, st3) if x and 500 <= x < 600 and x != 501]
    add("B17 边界输入不引发 5xx（501 不算，那是规范要求的响应）",
        "PASS" if not bad5xx else "FAIL", "statuses=%s/%s/%s" % (st, st2, st3))

    # ---- 语义类：需要该方法的有效 DID ----
    if did:
        q = urllib.parse.quote(did, safe="")
        st8, hd8, raw8 = http(base, "/" + q, RES_MEDIA)
        doc = J(raw8) or {}
        add("B1 有效 DID 返回 200", "PASS" if st8 == 200 else "FAIL", "status=%s" % st8)

        meta_ctype = (doc.get("didResolutionMetadata") or {}).get("contentType")
        hdr = (hd8.get("content-type") or "").split(";")[0].strip()
        add("B2 HTTP Content-Type == metadata contentType",
            "PASS" if hdr == meta_ctype and hdr else "FAIL", "header=%r meta=%r" % (hdr, meta_ctype))

        add("B3 返回完整 Resolution Result（三键）",
            "PASS" if all(k in doc for k in ("didResolutionMetadata", "didDocument", "didDocumentMetadata")) else "FAIL",
            "keys=%s" % list(doc.keys()))

        st9, _, raw9 = http(base, "/" + q, DOC_MEDIA)
        d9 = J(raw9) or {}
        add("B10 Accept 表示媒体类型只回文档",
            "PASS" if st9 == 200 and "didResolutionMetadata" not in d9 else "FAIL",
            "status=%s keys=%s" % (st9, list(d9.keys())))

        add("B11 didDocument.id == 受解析 DID",
            "PASS" if (doc.get("didDocument") or {}).get("id") == did else "FAIL",
            "id=%r" % (doc.get("didDocument") or {}).get("id"))

        vms = (doc.get("didDocument") or {}).get("verificationMethod") or []
        add("B12 文档最小符合性", "PASS" if vms and all(v.get("type") and v.get("id") for v in vms) else "FAIL",
            "vm=%d" % len(vms))

        # 编码变体：把 DID 拆开重新编码
        enc = urllib.parse.quote(did, safe="")
        if enc != did:
            st10, _, _ = http(base, "/" + enc, RES_MEDIA)
            add("B14 接受 URL 编码的 DID", "PASS" if st10 == 200 else "FAIL", "status=%s" % st10)
        else:
            add("B14 接受 URL 编码的 DID", "N/A", "该 DID 无可编码字符")
    else:
        for cid in ("B1 有效 DID 返回 200", "B2 HTTP Content-Type == metadata contentType",
                    "B3 返回完整 Resolution Result（三键）", "B10 Accept 表示媒体类型只回文档",
                    "B11 didDocument.id == 受解析 DID", "B12 文档最小符合性",
                    "B14 接受 URL 编码的 DID"):
            add(cid, "N/A", "该实现不支持 did:key，我们手上没有它自己方法的一条有效 DID")

    p = sum(1 for r in res if r["state"] == "PASS")
    f = sum(1 for r in res if r["state"] == "FAIL")
    n = sum(1 for r in res if r["state"] == "N/A")
    out = dict(name=a.name, base_url=base, did=did, pass_=p, fail=f, na=n, results=res)
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%-12s PASS=%d FAIL=%d N/A=%d" % (a.name, p, f, n))
    for r in res:
        print("  [%s] %s  %s" % (r["state"], r["id"], r["detail"]))
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
