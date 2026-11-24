# -*- coding: utf-8 -*-
"""跨实现互操作：同一份 did:web 文档，两套代码各自解析，比对结果。

参与方：
  A 我们的实现 uibc_core/did.py（本仓代码）
  B 第三方实现 uport/Veramo 生态 did-resolver + web-did-resolver（npm 包，不同方开发）

判定：文档 id、verificationMethod id/type、公钥字节、错误条件一致 → PASS。
边界：这是"代码来自不同方"，不是"实施主体不同"。W3C 的 independent 指后者，机构隔离仍未满足。
"""
import json, os, ssl, subprocess, sys, threading, time, http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
import _subject  # noqa: E402  被测仓只从一个入口定位，见 _subject.py 的历史说明
REPO = _subject.resolve()
PKI = os.path.join(KIT, "_pki")
INTEROP = os.environ.get("UIBC_INTEROP_DIR") or os.path.join(KIT, "runs", "_interop")
RESULTS = []

sys.path.insert(0, REPO)
import uibc_core.did as U  # noqa: E402


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-7s] %-28s %s" % (verdict, case, note))


DOC_T = {
    "@context": ["https://www.w3.org/ns/did/v1"],
    "id": None,
    "verificationMethod": [{
        "id": None,
        "type": "Ed25519VerificationKey2020",
        "controller": None,
        "publicKeyMultibase": None,
    }],
    "authentication": [],
}


def make_doc(did, mb):
    d = json.loads(json.dumps(DOC_T))
    d["id"] = did
    d["verificationMethod"][0].update({
        "id": did + "#key-1", "controller": did, "publicKeyMultibase": mb})
    d["authentication"] = [did + "#key-1"]
    return d


class Handler(http.server.BaseHTTPRequestHandler):
    doc = None

    def do_GET(self):
        if self.path == "/.well-known/did.json" and self.doc is not None:
            body = json.dumps(self.doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/did+ld+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


def ensure_cert():
    """优先用 _pki 里的证书；分发包不含证书时，现场自签一张（只用于回环测试）。"""
    cert, key = os.path.join(PKI, "cert.pem"), os.path.join(PKI, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    d = os.path.join(HERE, "_pki")
    os.makedirs(d, exist_ok=True)
    cert, key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime as dt
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"uibc-interop-localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    crt = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
           .public_key(k.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(now - dt.timedelta(minutes=5))
           .not_valid_after(now + dt.timedelta(days=2))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName(u"127.0.0.1"),
                                                       x509.IPAddress(__import__("ipaddress").ip_address(u"127.0.0.1"))]),
                          critical=False)
           .sign(k, hashes.SHA256()))
    with open(key, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption()))
    with open(cert, "wb") as f:
        f.write(crt.public_bytes(serialization.Encoding.PEM))
    return cert, key


def serve_https():
    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def fetch_unverified(url, timeout=10):
    """真实 HTTPS 抓取，仅对自签宿主放宽证书校验（不改变解析逻辑）。"""
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def third_party(did):
    js = os.path.join(INTEROP, "resolve3p.js")
    if not os.path.exists(js):
        return None
    env = dict(os.environ, NODE_TLS_REJECT_UNAUTHORIZED="0")
    try:
        p = subprocess.run(["node", js, did], capture_output=True, text=True,
                           env=env, timeout=90)
    except Exception as e:
        return {"ok": False, "error": "node-failed:%r" % (e,)}
    out = (p.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "node-no-output", "raw": (p.stderr or "")[:200]}
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "error": "unparsable", "raw": out[:200]}


def main():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    pk = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    mb = "z" + U._b58encode(U._ED25519_MULTICODEC + pk)

    srv, port = serve_https()
    did = "did:web:127.0.0.1%%3A%d" % port
    Handler.doc = make_doc(did, mb)
    rec("I0 本地 did:web 宿主", "INFO",
        "port=%d 文档=%d 字节 公钥 %s…" % (port, len(json.dumps(Handler.doc)), mb[:14]),
        {"port": port, "did": did, "multibase": mb})

    # 2026-11-25 改判。被测仓把 did:web 的主机策略搬进了解析契约（回环/私网一律拒），
    # 于是"我方解析本地回环 did:web"这个前提被它自己的策略作废了：原来 I1 拿注入
    # fetcher 去解析 127.0.0.1、判 PASS，等于要求实现允许指向内网的解析——那个期望本身是错的。
    # 拆成三条，每条只断言一件真的能成立的事：
    #   I1  注入 fetcher 时也必须拒 → 策略在解析层，不在传输层（这条正是把 11-25 的修复钉住）
    #   I1b 不注入 fetcher（真实传输）同样拒
    #   I2  取公钥：回环被拒就取不到 → BLOCKED，并写明缺的前置是"一个公网 did:web 目标"
    #       （不拿注入 fetcher 绕过策略去伪造这条，那样测的是被策略禁止的路径）
    ours, ours_key = None, None

    t0 = time.time()
    try:
        ours = U.resolve(did, timeout=10, fetcher=fetch_unverified)
        rec("I1 注入 fetcher 也拒回环", "FAIL",
            "解析成功（id=%s）：主机策略只在传输层，调用方自带 fetcher 就能绕过" % ours.get("id"),
            {"kind": "SSRF", "severity": "中高"})
    except Exception as e:
        hit = "public address" in str(e)
        rec("I1 注入 fetcher 也拒回环", "PASS" if hit else "FAIL",
            "%s: %s（%.0fms）" % (type(e).__name__, str(e)[:100], (time.time() - t0) * 1000))

    t0 = time.time()
    try:
        U.resolve(did, timeout=10)
        rec("I1b 真实传输同样拒", "FAIL", "不带 fetcher 也解析成功：回环没有被拒")
    except Exception as e:
        hit = "public address" in str(e)
        rec("I1b 真实传输同样拒", "PASS" if hit else "FAIL",
            "%s: %s（%.0fms）" % (type(e).__name__, str(e)[:100], (time.time() - t0) * 1000))

    rec("I2 我方取公钥", "BLOCKED",
        "回环 did:web 被策略拒绝，取不到公钥。缺的前置：一个公网 did:web 目标（需网络）；"
        "本组不用注入 fetcher 绕过策略来伪造这一条", {"needs": "public did:web target"})

    t0 = time.time()
    theirs = third_party(did)
    if theirs is None:
        rec("I3 第三方解析 did:web", "BLOCKED", "未安装：先跑 npm i 于 runs/_interop（did-resolver + web-did-resolver）")
        rec("I4 两实现逐字段比对", "BLOCKED", "依赖 I3")
        rec("I5 坏 DID 两边都拒", "BLOCKED", "依赖 I3")
        rec("I6 不可达方法两边都拒", "BLOCKED", "依赖 I3")
        # 防止整组只剩 BLOCKED 而被读成"没问题"：显式留一条 WARN 把"互操作未验证"写进计分
        rec("I组 互操作未验证", "WARN",
            "第三方依赖缺失（%s/resolve3p.js），I3–I6 全部未执行；本组结果不代表互操作通过" % INTEROP)
    else:
        rec("I3 第三方解析 did:web", "PASS" if theirs.get("ok") else "FAIL",
            "ok=%s id=%s vm=%s %.0fms %s" % (theirs.get("ok"), theirs.get("didDocumentId"),
                                            theirs.get("vmId"), (time.time() - t0) * 1000,
                                            theirs.get("error") or ""), {"result": theirs})

    if theirs is None:
        pass  # I4–I6 已在上方按依赖缺失记为 BLOCKED，不再重复记一条 FAIL
    elif ours is None:
        # 逐字段比对需要两边都拿到文档。我方现在按策略拒绝回环，客观上没有可比对对象；
        # 记 BLOCKED 而不是"通过"，同时把分歧本身单独判一条——分歧是设计，不是缺陷，
        # 但必须由机器证明它确实按设计发生了，而不是嘴上说。
        rec("I4 两实现逐字段比对", "BLOCKED",
            "我方按策略拒绝回环，没有可比对对象。要恢复这条：给一个公网 did:web 目标，"
            "两边都解析同一份文档再比", {"needs": "public did:web target"})
        ok4 = theirs.get("ok") is True
        rec("I4b 策略分歧按设计发生", "PASS" if ok4 else "FAIL",
            "我方拒回环 / 第三方成功解析=%s（第三方无主机策略，这是分歧的全部内容）" % theirs.get("ok"),
            {"th": theirs})
    def _tp_error(d):
        """第三方真的给出了自己的错误码（而不是我们脚本/node 自身故障）。"""
        e = (d or {}).get("error") or ""
        return bool(e) and not e.startswith(("node-", "unparsable"))

    if theirs is not None:
        bad = third_party("not-a-did")
        try:
            U.resolve("not-a-did", timeout=5)
            ob = None
        except Exception as e:
            ob = type(e).__name__
        ok5 = bad.get("ok") is False and ob and _tp_error(bad)
        rec("I5 坏 DID 两边都拒", "PASS" if ok5 else "FAIL",
            "我方 %s / 第三方 %s" % (ob, bad.get("error") or "(无结构化错误)"), {"th": bad})

        dead = third_party("did:web:no-such-host-abcxyz.example")
        try:
            U.resolve("did:web:no-such-host-abcxyz.example", timeout=10)
            od = "成功（不该）"
        except Exception as e:
            od = type(e).__name__
        ok6 = dead.get("ok") is False and od != "成功（不该）" and _tp_error(dead)
        rec("I6 不可达方法两边都拒", "PASS" if ok6 else "FAIL",
            "我方 %s / 第三方 %s" % (od, dead.get("error") or "(无结构化错误)"), {"th": dead})

    srv.shutdown()
    out = sys.argv[1] if len(sys.argv) > 1 else "s09_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
