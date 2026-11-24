# -*- coding: utf-8 -*-
"""绑定层探针：不依赖官方套件，自己把 HTTP 绑定（§10.1）的 12 条要求逐条打出来。

为什么单独做：规范追踪矩阵显示，官方 23 条断言里有 10 条本台没有对应用例（只有套件在测）。
套件是别人的、要 npm + node，还依赖网络；绑定层这几条其实用标准库就能自证。
本工具**故意不并入 141 条基线**（与 keytype_vectors 同理：基线量被测仓 HEAD，新用例塞进去
只能靠改判转绿），而是作为独立证据：同一组断言，换实现跑两次。

用法：
  python tools/binding_probe.py --repo <被测实现目录> --port 9550 --json out.json
退出码：0 全过 / 1 有失败 / 2 环境问题（shim 起不来）
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOC_MEDIA = "application/did+ld+json"
RES_MEDIA = "application/did-resolution"
# W3C 规范正文里的 ed25519 did:key 示例（不依赖任何私钥）
TEST_DID = "did:key:z6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp"
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def http(port, path, accept=None):
    url = "https://127.0.0.1:%d%s" % (port, path)
    req = urllib.request.Request(url)
    if accept:
        req.add_header("Accept", accept)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            raw = r.read()
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def J(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def ensure_cert():
    """_pki 缺失就自举。优先 openssl；Windows 上没 openssl 时用 tools/make_cert.ps1
    （.NET 自签，不需要管理员、不需要 openssl）。两者都没有才明确报环境问题。"""
    pki = os.path.join(KIT, "_pki")
    cert = os.path.join(pki, "cert.pem")
    key = os.path.join(pki, "key.pem")
    if os.path.isfile(cert) and os.path.isfile(key):
        return True
    os.makedirs(pki, exist_ok=True)
    try:
        r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", key, "-out", cert, "-days", "3650",
                            "-subj", "/CN=localhost"], capture_output=True, text=True)
        if r.returncode == 0:
            return True
        print("[WARN] openssl 生成证书失败：%s" % (r.stderr or "")[:200])
    except FileNotFoundError:
        print("[WARN] 本机无 openssl，改用 Windows 原生 .NET 自签（tools/make_cert.ps1）")

    # Windows 原生兜底：不依赖 openssl，也不需要管理员权限
    ps1 = os.path.join(KIT, "tools", "make_cert.ps1")
    if os.path.isfile(ps1):
        for exe in ("pwsh", "powershell"):
            try:
                r2 = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                     "-File", ps1, "-OutDir", pki],
                                    capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if r2.returncode == 0 and os.path.isfile(cert) and os.path.isfile(key):
                return True
            print("[WARN] %s 生成证书失败：%s" % (exe, (r2.stderr or r2.stdout or "")[:200]))
            break

    print("[EXIT=2] 无法生成自签证书：openssl 与 Windows .NET 兜底都不可用")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=9550)
    ap.add_argument("--json", default="binding_probe.json")
    a = ap.parse_args()

    if not ensure_cert():
        return 2

    env = dict(os.environ)
    env["UIBC_REPO"] = os.path.abspath(a.repo)
    env["PYTHONIOENCODING"] = "utf-8"
    shim = os.path.join(KIT, "tools", "resolver_https_shim.py")
    log = open(a.json + ".shim.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, shim, "--port", str(a.port)],
                            cwd=KIT, env=env, stdout=log, stderr=subprocess.STDOUT)
    time.sleep(3)
    if proc.poll() is not None:
        print("[EXIT=2] shim 没起来，见 %s.shim.log" % a.json)
        return 2

    results = []

    def add(cid, ok, detail):
        results.append(dict(id=cid, ok=bool(ok), detail=str(detail)[:300]))

    try:
        # P1 成功解析返回 200
        st, hd, raw = http(a.port, "/1.0/identifiers/" + urllib.parse.quote(TEST_DID, safe=""),
                           RES_MEDIA)
        add("P1 成功解析返回 200", st == 200, "status=%s" % st)

        # P2 HTTP Content-Type 必须等于 metadata 里的 contentType
        doc = J(raw) or {}
        meta_ctype = (doc.get("didResolutionMetadata") or {}).get("contentType")
        hdr_ctype = (hd.get("Content-Type") or "").split(";")[0].strip()
        add("P2 HTTP Content-Type == metadata contentType",
            hdr_ctype == meta_ctype and hdr_ctype == DOC_MEDIA,
            "header=%r meta=%r" % (hdr_ctype, meta_ctype))

        # P3 Accept: did-resolution 时返回体必须含三个键
        add("P3 Accept did-resolution 返回完整 Resolution Result",
            all(k in doc for k in ("didResolutionMetadata", "didDocument", "didDocumentMetadata")),
            "keys=%s" % list(doc.keys()))

        # P4 Accept 表示媒体类型时只回文档
        st4, hd4, raw4 = http(a.port, "/1.0/identifiers/" + urllib.parse.quote(TEST_DID, safe=""),
                              DOC_MEDIA)
        d4 = J(raw4) or {}
        add("P4 Accept did+ld+json 只返回文档（无 didResolutionMetadata）",
            st4 == 200 and "didResolutionMetadata" not in d4 and "didDocument" not in d4,
            "status=%s keys=%s" % (st4, list(d4.keys())))

        # P5 不支持的 Accept 必须给 REPRESENTATION_NOT_SUPPORTED
        st5, hd5, raw5 = http(a.port, "/1.0/identifiers/" + urllib.parse.quote(TEST_DID, safe=""),
                              "text/html")
        e5 = ((J(raw5) or {}).get("didResolutionMetadata") or {}).get("error") or {}
        add("P5 不支持的 Accept → REPRESENTATION_NOT_SUPPORTED",
            "REPRESENTATION_NOT_SUPPORTED" in json.dumps(e5) and e5.get("type", "").endswith(
                "REPRESENTATION_NOT_SUPPORTED"),
            "status=%s error=%s" % (st5, e5.get("title")))

        # P6 INVALID_DID("not-a-did") → 400
        st6, _, _ = http(a.port, "/1.0/identifiers/not-a-did", RES_MEDIA)
        add("P6 INVALID_DID not-a-did → 400", st6 == 400, "status=%s" % st6)

        # P7 INVALID_DID("did:example") → 400
        st7, _, _ = http(a.port, "/1.0/identifiers/did:example", RES_MEDIA)
        add("P7 INVALID_DID did:example → 400", st7 == 400, "status=%s" % st7)

        # P8 方法不支持 → 501
        st8, _, raw8 = http(a.port, "/1.0/identifiers/did:foo:abc", RES_MEDIA)
        e8 = ((J(raw8) or {}).get("didResolutionMetadata") or {}).get("error") or {}
        add("P8 METHOD_NOT_SUPPORTED → 501", st8 == 501 and "METHOD_NOT_SUPPORTED" in
            json.dumps(e8), "status=%s error=%s" % (st8, e8.get("title")))

        # P9 失败时 didDocumentMetadata 为空结构
        d9 = J(raw8) or {}
        add("P9 失败时 didDocumentMetadata 为空结构",
            d9.get("didDocumentMetadata") == {}, "metadata=%r" % (d9.get("didDocumentMetadata"),))

        # P10 失败时 error 对象必需且带 DID 命名空间 type
        add("P10 失败时 error 对象必需且 type 在 DID 命名空间",
            bool(e8.get("type", "").startswith("https://www.w3.org/ns/did#")),
            "type=%r" % e8.get("type"))

        # P11 URL 编码的 DID 必须被接受
        encd = "did%3Akey%3Az6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp"
        st11, _, raw11 = http(a.port, "/1.0/identifiers/" + encd, RES_MEDIA)
        add("P11 接受 URL 编码的 DID",
            st11 == 200 and isinstance(J(raw11), dict), "status=%s" % st11)

        # P12 返回文档 id 必须等于受解析 DID
        add("P12 didDocument.id == 受解析 DID",
            (doc.get("didDocument") or {}).get("id") == TEST_DID,
            "id=%r" % (doc.get("didDocument") or {}).get("id"))

        # P13 didDocument 最小符合性（@context / id / verificationMethod / type）
        d13 = doc.get("didDocument") or {}
        ctx = d13.get("@context")
        vms = d13.get("verificationMethod") or []
        vm_ok = bool(vms) and all(isinstance(v, dict) and
                                  str(v.get("id", "")).startswith(TEST_DID + "#") and
                                  v.get("type") for v in vms)
        add("P13 didDocument 最小符合性（@context/id/verificationMethod/type）",
            ("https://www.w3.org/ns/did/v1" in (ctx if isinstance(ctx, list) else [ctx]))
            and d13.get("id") == TEST_DID and vm_ok,
            "ctx=%r vm=%d" % (ctx, len(vms)))

        # P14 非法 resolution option → INVALID_OPTIONS（不是 500，也不是静默忽略）
        st14, _, raw14 = http(a.port, "/1.0/identifiers/" + urllib.parse.quote(TEST_DID, safe="")
                              + "?versionTime=not-a-date", RES_MEDIA)
        e14 = ((J(raw14) or {}).get("didResolutionMetadata") or {}).get("error") or {}
        add("P14 非法 versionTime → INVALID_OPTIONS",
            e14.get("type", "").endswith("INVALID_OPTIONS") and st14 >= 400,
            "status=%s error=%s" % (st14, e14.get("title")))

        # P15 明文 HTTP 必须拿不到解析结果（端点是 HTTPS-only）
        plain_ok = True
        try:
            u = urllib.request.urlopen("http://127.0.0.1:%d/1.0/identifiers/%s"
                                       % (a.port, urllib.parse.quote(TEST_DID, safe="")), timeout=8)
            raw = u.read()
            u.close()
            plain_ok = False
            detail = "明文请求竟返回 %d 字节" % len(raw)
        except Exception as e:
            detail = "明文请求被拒：%s" % type(e).__name__
        add("P15 明文 HTTP 拿不到解析结果（HTTPS-only）", plain_ok, detail)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()

    passed = sum(1 for r in results if r["ok"])
    out = dict(repo=os.path.abspath(a.repo), total=len(results), passed=passed,
               failed=len(results) - passed, results=results)
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in results:
        print("[%s] %s  %s" % ("PASS" if r["ok"] else "FAIL", r["id"], r["detail"]))
    print("=== 绑定层探针 %d/%d ===" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
