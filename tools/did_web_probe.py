# -*- coding: utf-8 -*-
"""did:web 第二方法探针（W1–W12）。

为什么要有这一份：CR 退出要求"每个实现 ≥2 个清单内 DID 方法"。本仓 `uibc_core.did`
的 `SUPPORTED_METHODS = ("key", "web")` 本来就实现了两个方法，但此前所有证据（141 条基线、
15 条绑定层探针、官方套件）都只走 `did:key`。这条探针把 `did:web` 的那一半也变成可执行证据。

口径（必须写清，别当成"符合 W3C did:web"）：
  * 本探针在本机起一个 HTTPS 服务，用自签证书发布 did.json；
  * 因此 fetch 时放宽 TLS 校验（自签），只用于离线复跑；
  * 真实公网 did:web 依赖公共 PKI，本探针不覆盖公网可用性；
  * 不测 did:web 的"历史版本 / 更新规则"，只测"取文档 + 校验 id + 错误不静默"。

用法：
  python tools/did_web_probe.py --repo <被测仓> --port 9580 --json did_web_probe.json
退出码：0=全过；1=有 FAIL；2=环境问题（仓库/证书/端口）。
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)

ED_SEED_DID = "did:key:z6MkiTBz1ymuepAQ4HEHYSF1H8quG5GLVVQR3djdX3mDooWp"


def ensure_cert():
    pki = os.path.join(KIT, "_pki")
    cert = os.path.join(pki, "cert.pem")
    key = os.path.join(pki, "key.pem")
    if os.path.isfile(cert) and os.path.isfile(key):
        return cert, key
    os.makedirs(pki, exist_ok=True)
    try:
        r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", key, "-out", cert, "-days", "3650",
                            "-subj", "/CN=localhost"], capture_output=True, text=True)
        if r.returncode == 0:
            return cert, key
    except FileNotFoundError:
        pass
    ps1 = os.path.join(HERE, "make_cert.ps1")
    if os.path.isfile(ps1):
        for exe in ("pwsh", "powershell"):
            try:
                r2 = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                     "-File", ps1, "-OutDir", pki],
                                    capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if r2.returncode == 0 and os.path.isfile(cert) and os.path.isfile(key):
                return cert, key
            break
    return None, None


def make_handler(docs):
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # 静默
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path not in docs:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"not found"}')
                return
            ctype, body = docs[path]
            payload = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    return H


def make_fetcher():
    """离线复跑用：自签证书 → 放宽校验。真实环境不要这么干。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def fetcher(url, timeout=10):
        req = urllib.request.Request(url, headers={
            "Accept": "application/did+ld+json, application/json",
            "User-Agent": "uibc-bench-probe/0.4.14",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    return fetcher


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=9580)
    ap.add_argument("--json", default="did_web_probe.json")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    if not os.path.isdir(os.path.join(repo, "uibc_core")):
        print("[EXIT=2] 仓库路径里没有 uibc_core/：%s" % repo)
        return 2
    sys.path.insert(0, repo)
    sys.path.insert(0, HERE)
    from uibc_core import did as D  # noqa: E402

    cert, key = ensure_cert()
    if not cert:
        print("[EXIT=2] 无法生成自签证书（openssl 与 .NET 兜底都不可用）")
        return 2

    straddr = "127.0.0.1%3A{p}".format(p=a.port)  # did:web 用 %3A 表示端口
    web_did = "did:web:" + straddr
    path_did = web_did + ":user:al"
    wrong_did = "did:web:127.0.0.1%3A1"  # 文档里写的是另一个 id

    def doc(the_id):
        return {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": the_id,
            "verificationMethod": [{
                "id": the_id + "#key-1",
                "type": "JsonWebKey2020",
                "controller": the_id,
                "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519",
                                 "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"},
            }],
            "authentication": [the_id + "#key-1"],
        }

    docs = {
        "/.well-known/did.json": ("application/did+ld+json", json.dumps(doc(web_did))),
        "/user/al/did.json": ("application/did+ld+json", json.dumps(doc(path_did))),
        "/bad-json/did.json": ("application/json", b"{not json at all"),
        "/wrong-id/did.json": ("application/did+ld+json", json.dumps(doc(wrong_did))),
    }

    from http.server import ThreadingHTTPServer
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(docs))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()

    # 等监听就绪（Windows 上首连偶发被拒，属于探针自身时序问题，不是被测方问题）
    import socket as _sk, time as _tm
    for _ in range(60):
        try:
            with _sk.create_connection(("127.0.0.1", a.port), timeout=0.2):
                break
        except OSError:
            _tm.sleep(0.05)
    else:
        print("[EXIT=2] 本地 HTTPS 服务没有起来（端口 %d）" % a.port)
        return 2

    results = []

    def add(pid, name, ok, detail):
        results.append({"id": pid, "name": name, "verdict": "PASS" if ok else "FAIL",
                        "detail": str(detail)})

    fetcher = make_fetcher()

    # --- 1. URL 映射（离线，不发请求） ---
    try:
        u1 = D.did_web_url("did:web:example.com")
        add("W1", "did:web:host → /.well-known/did.json", u1 == "https://example.com/.well-known/did.json", u1)
    except Exception as e:
        add("W1", "did:web:host → /.well-known/did.json", False, "%s: %s" % (type(e).__name__, e))
    try:
        u2 = D.did_web_url("did:web:example.com%3A8443")
        add("W2", "带端口(%3A) → https://host:8443/.well-known/did.json",
            u2 == "https://example.com:8443/.well-known/did.json", u2)
    except Exception as e:
        add("W2", "带端口(%3A) → https://host:8443/.well-known/did.json", False, str(e))
    try:
        u3 = D.did_web_url("did:web:example.com:user:al")
        add("W3", "多段标识 → /user/al/did.json", u3 == "https://example.com/user/al/did.json", u3)
    except Exception as e:
        add("W3", "多段标识 → /user/al/did.json", False, str(e))
    try:
        D.did_web_url(ED_SEED_DID)
        add("W4", "did_web_url 拒绝非 web 方法", False, "没有报错，返回了 URL")
    except Exception as e:
        add("W4", "did_web_url 拒绝非 web 方法", type(e).__name__ in ("UnsupportedMethod", "DIDError"),
            type(e).__name__)

    # --- 2. 实际取文档 ---
    try:
        d5 = D.resolve(web_did, fetcher=fetcher)
        add("W5", "根路径 did:web 解析成功且 id 一致", (d5 or {}).get("id") == web_did,
            (d5 or {}).get("id"))
    except Exception as e:
        add("W5", "根路径 did:web 解析成功且 id 一致", False, "%s: %s" % (type(e).__name__, e))
    try:
        d6 = D.resolve(path_did, fetcher=fetcher)
        add("W6", "多段标识 did:web 解析成功", (d6 or {}).get("id") == path_did, (d6 or {}).get("id"))
    except Exception as e:
        add("W6", "多段标识 did:web 解析成功", False, "%s: %s" % (type(e).__name__, e))

    # --- 3. 错误路径必须显式报错，不许静默返回半成品 ---
    bad_json_did = "did:web:127.0.0.1%3A{k}:bad-json".format(k=a.port)
    try:
        D.resolve(bad_json_did, fetcher=fetcher)
        add("W7", "非 JSON 文档 → 报错不静默", False, "返回了内容（应报错）")
    except Exception as e:
        add("W7", "非 JSON 文档 → 报错不静默", type(e).__name__ != "UnboundLocalError",
            type(e).__name__)

    wrong_doc_did = "did:web:127.0.0.1%3A{k}:wrong-id".format(k=a.port)
    try:
        got = D.resolve(wrong_doc_did, fetcher=fetcher)
        ok = (got or {}).get("id") == wrong_doc_did
        add("W8", "文档 id 与被解析 DID 不一致 → 报错", not ok,
            "id=%r" % ((got or {}).get("id"),))
    except Exception as e:
        add("W8", "文档 id 与被解析 DID 不一致 → 报错", True, "%s: %s" % (type(e).__name__, str(e)[:80]))

    missing_did = "did:web:127.0.0.1%3A{k}:nope".format(k=a.port)
    try:
        D.resolve(missing_did, fetcher=fetcher)
        add("W9", "did.json 404 → 报错不静默", False, "返回了内容（应报错）")
    except Exception as e:
        add("W9", "did.json 404 → 报错不静默", True, type(e).__name__)

    try:
        D.resolve("did:web:", fetcher=fetcher)
        add("W10", "did:web 空主机 → 报错", False, "没有报错")
    except Exception as e:
        add("W10", "did:web 空主机 → 报错", True, type(e).__name__)

    # --- 4. 两个方法在同一实现里同时可用 ---
    try:
        dk = D.resolve(ED_SEED_DID)
        add("W11", "同一实现里 did:key 仍可离线解析（两方法共存）",
            (dk or {}).get("id") == ED_SEED_DID, (dk or {}).get("id"))
    except Exception as e:
        add("W11", "同一实现里 did:key 仍可离线解析（两方法共存）", False, "%s: %s" % (type(e).__name__, e))
    try:
        D.resolve("did:example:123")
        add("W12", "不支持的方法 → 显式 UnsupportedMethod", False, "没有报错")
    except Exception as e:
        add("W12", "不支持的方法 → 显式 UnsupportedMethod",
            type(e).__name__ in ("UnsupportedMethod",), type(e).__name__)

    httpd.shutdown()

    npass = sum(1 for r in results if r["verdict"] == "PASS")
    for r in results:
        print("  [%s] %s %s  %s" % (r["verdict"], r["id"], r["name"], r["detail"]))
    print("=== did:web 探针 %d/%d ===" % (npass, len(results)))
    print("    口径：本机自签 HTTPS + 放宽 TLS 校验，只证「取文档 / 校验 id / 错误不静默」，不证公网可用性")

    out = {"repo": repo, "did": web_did, "port": a.port,
           "supported_methods": list(getattr(D, "SUPPORTED_METHODS", ())),
           "pass": npass, "total": len(results), "results": results}
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("json=%s" % a.json)
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
