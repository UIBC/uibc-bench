# -*- coding: utf-8 -*-
"""场景组 B：did 解析与文件层的对抗性实测。

本地起一个受信（SSL_CERT_FILE 注入）的 HTTPS 服务，扮演"外部 DID 文档宿主"，
用它证明 did:web 在真实网络路径上的行为：回环/内网可达性、302 降级、超时、
超大响应、非 JSON。只影响本进程环境变量，不改产品代码。
"""
import json, os, socket, ssl, sys, threading, time, traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from _portutil import free_port, serve_any

import _subject
RESULTS = []
CA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_pki"))


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-44s %s" % (verdict, case, note))


def make_cert():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    os.makedirs(CA_DIR, exist_ok=True)
    cert_p, key_p = os.path.join(CA_DIR, "cert.pem"), os.path.join(CA_DIR, "key.pem")
    if os.path.exists(cert_p) and os.path.exists(key_p):
        return cert_p, key_p
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sub = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))])
    c = (x509.CertificateBuilder().subject_name(sub).issuer_name(sub)
         .public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
         .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
         .add_extension(san, critical=False)
         .sign(k, hashes.SHA256()))
    with open(cert_p, "wb") as f:
        f.write(c.public_bytes(serialization.Encoding.PEM))
    with open(key_p, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption()))
    return cert_p, key_p


DOC = {}
BIG = {}
HS_PORT = 0     # 解析用 HTTPS 宿主端口（由系统分配，可用 S02_HTTPS_PORT 指定）
PX_PORT = 0     # 降级用明文 HTTP 端口（同上，S02_HTTP_PORT）


def did_base(suffix=""):
    """以实际端口构造 did:web 标识，避免把 8443 写死。"""
    return "did:web:127.0.0.1%%3A%d%s" % (HS_PORT, suffix)


def make_docs():
    i = did_base()
    d = {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": i,
        "verificationMethod": [{
            "id": i + "#key-1",
            "type": "Ed25519VerificationKey2020",
            "controller": i,
            "publicKeyMultibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        }],
        "authentication": [i + "#key-1"],
    }
    return d, dict(d, blob="x" * (20 * 1024 * 1024))


class H(BaseHTTPRequestHandler):
    hits = []
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        H.hits.append(self.path)
        if self.path.endswith("/redir/did.json"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/plain/did.json" % PX_PORT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.endswith("/slow/did.json"):
            time.sleep(25)
            self._json(DOC)
            return
        if self.path.endswith("/big/did.json"):
            self._json(BIG)
            return
        if self.path.endswith("/html/did.json"):
            body = b"<html><body>500 error</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(DOC)

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PlainH(H):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        H.hits.append("plain:" + self.path)
        body = json.dumps(dict(DOC, id=did_base())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(handler, port, cert=None, key=None):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def main():
    cert, key = make_cert()
    os.environ["SSL_CERT_FILE"] = cert
    os.environ["SSL_CERT_DIR"] = CA_DIR
    global HS_PORT, PX_PORT, DOC, BIG
    HS_PORT = int(os.environ.get("S02_HTTPS_PORT") or 0) or free_port()
    PX_PORT = int(os.environ.get("S02_HTTP_PORT") or 0) or free_port()
    DOC, BIG = make_docs()
    try:
        s1, HS_PORT = serve_any(H, HS_PORT, cert, key)
        s2, PX_PORT = serve_any(PlainH, PX_PORT)
    except Exception as e:
        rec("B0 本地宿主无法监听", "BLOCKED", str(e)[:200]); return

    time.sleep(0.5)

    global SUBJECT, didmod
    try:
        didmod, SUBJECT = _subject.load("did")
    except _subject.WrongSubjectImported as e:
        rec("B0 被测仓对不上", "BLOCKED", str(e)[:300])
        write_results(); return
    except RuntimeError as e:
        rec("B0 被测仓无法定位", "BLOCKED", " ".join(str(e).split())[:300])
        write_results(); return

    # B1 回环地址是否被允许
    t0 = time.time()
    try:
        d = didmod.resolve(did_base(), timeout=5)
        rec("B1 did:web 指向回环 127.0.0.1", "INFO",  # 结论以 s02b B1' 为准（本组文档 id 不自洽）
            "解析成功（%dms），服务端收到 %s —— 无主机白名单，回环可被解析" % ((time.time() - t0) * 1000, H.hits[-1:]),
            {"kind": "SSRF", "severity": "中高"})
    except Exception as e:
        rec("B1 did:web 指向回环 127.0.0.1", "WARN",
            "%s: %s（hits=%s）" % (type(e).__name__, str(e)[:100], H.hits[-1:]),
            {"kind": "SSRF"})

    # B2 URL 构造：内网/云元数据/非标准主机
    probes = ["did:web:169.254.169.254", "did:web:10.0.0.1", "did:web:192.168.1.1:8443",
              "did:web:localhost", "did:web:metadata.google.internal",
              "did:web:example.com%3A8443", "did:web:%2F%2Fevil.com", "did:web:exa mple.com",
              "did:web:例子.中国", "did:web:example.com:user:al", "did:web:example.com::"]
    out = {}
    for p in probes:
        try:
            out[p] = didmod.did_web_url(p)
        except Exception as e:
            out[p] = "ERR %s: %s" % (type(e).__name__, str(e)[:60])
    blocked = [k for k, v in out.items() if "ERR" in v]
    rec("B2 did:web URL 构造边界", "INFO",  # 只列出构造结果，判据在 s02b B2
        "11 个边界样本，%d 个被拒绝；内网字面量未被拦：%s" % (
            len(blocked), [k for k, v in out.items() if "ERR" not in v and any(x in v for x in ("169.254", "10.0.0.1", "192.168", "localhost", "google.internal"))]),
        {"urls": out, "kind": "SSRF/输入校验"})

    # B3 302 降级到 http
    try:
        H.hits.clear()
        d = didmod.resolve(did_base(":redir"), timeout=5)
        rec("B3 https 被 302 降级到 http", "INFO",  # 本组被 id 校验挡下，真实结论见 s02b B3'
            "跟随重定向成功，最终从明文 http 取到文档；https 只校验了首个 URL（hits=%s）" % H.hits,
            {"kind": "传输降级", "severity": "中"})
    except Exception as e:
        rec("B3 https 被 302 降级到 http", "PASS" if "http" not in str(e).lower() else "WARN",
            "%s: %s" % (type(e).__name__, str(e)[:120]), {"hits": H.hits})

    # B4 超时是否真的生效
    t0 = time.time()
    try:
        didmod.resolve(did_base(":slow"), timeout=2)
        rec("B4 慢响应超时", "FAIL", "未超时（%.1fs）" % (time.time() - t0))
    except Exception as e:
        el = time.time() - t0
        rec("B4 慢响应超时", "PASS" if el < 5 else "WARN",
            "%.1fs 后抛出 %s（timeout=2）" % (el, type(e).__name__))

    # B5 20MB 响应
    t0 = time.time()
    try:
        d = didmod.resolve(did_base(":big"), timeout=20)
        rec("B5 20MB 文档", "INFO",
            "解析成功，耗时 %.1fs；无响应大小上限，内存随对端响应线性增长" % (time.time() - t0),
            {"kind": "DoS", "severity": "中"})
    except Exception as e:
        rec("B5 20MB 文档", "PASS", "%.1fs 拒绝：%s" % (time.time() - t0, str(e)[:80]))

    # B6 非 JSON / HTML 错误页
    try:
        didmod.resolve(did_base(":html"), timeout=5)
        rec("B6 返回 HTML 而非 JSON", "FAIL", "被当成 JSON 接受了")
    except Exception as e:
        rec("B6 返回 HTML 而非 JSON", "PASS", "%s: %s" % (type(e).__name__, str(e)[:90]))

    # B7 非 Ed25519 的 key 文档
    bad = dict(DOC)
    bad["verificationMethod"] = [dict(DOC["verificationMethod"][0], type="JsonWebKey2020",
                                      publicKeyMultibase="z" + "b" * 40)]
    try:
        didmod.document_ed25519_key(bad)
        rec("B7 非 Ed25519 文档", "FAIL", "未经类型校验就取出密钥")
    except Exception as e:
        rec("B7 非 Ed25519 文档", "PASS", "%s: %s" % (type(e).__name__, str(e)[:90]))

    # B8 畸形 did:key / multibase
    for v in ["did:key:", "did:key:z", "did:key:" + "z" * 300, "did:web:", "did:", "DID:web:x", " did:web:a.com"]:
        try:
            didmod.resolve(v, timeout=2)
            rec("B8 畸形 DID %r" % v, "WARN", "未拒绝")
        except Exception as e:
            rec("B8 畸形 DID %r" % v, "PASS", type(e).__name__ + ": " + str(e)[:70])

    # B9 并发一致性：同一 did:web 20 线程
    errs, oks, lock = [], [0], threading.Lock()

    def one():
        try:
            didmod.resolve(did_base(), timeout=8)
            with lock:
                oks[0] += 1
        except Exception as e:
            with lock:
                errs.append(type(e).__name__)

    H.hits.clear()
    ths = [threading.Thread(target=one) for _ in range(20)]
    t0 = time.time()
    [t.start() for t in ths]
    [t.join() for t in ths]
    rec("B9 20 线程并发解析", "PASS" if not errs else "WARN",
        "ok=%d err=%d 耗时 %.1fs，实际请求 %d 次（无缓存，扇出=并发数）" % (
            oks[0], len(errs), time.time() - t0, len([h for h in H.hits if h.startswith("/.well-known")]),
        ), {"kind": "扇出/放大", "severity": "低"})

    try:
        s1.shutdown(); s2.shutdown()
    except Exception:
        pass
    write_results()


def write_results():
    out = sys.argv[1] if len(sys.argv) > 1 else "s02_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    if globals().get('SUBJECT') and globals().get('didmod'):
        _subject.write_meta(out, SUBJECT, globals().get('didmod'), 's02')
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # 任何未预期异常都必须落成一条 BLOCKED 并写盘，绝不静默消失
        traceback.print_exc()
        rec("B0 场景组异常中止", "BLOCKED", "%s: %s" % (type(e).__name__, str(e)[:180]))
        try:
            write_results()
        except Exception:
            pass

