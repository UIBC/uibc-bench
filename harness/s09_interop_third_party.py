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


# 公网 did:web 目标：由第三方主体发布、我们不控制其内容的身份文档。
# 早期版本把 I2/I4 记 BLOCKED，缺的前置正是"一个公网 did:web 目标"——不是缺代码，是缺被测对象。
# 这三条是真实存在的第三方身份（DIF、Veramo、Danube Tech 各自的域名），不伪造、不托管、不注入 fetcher：
# 真实 HTTPS 抓取，两实现各拿一份当次读数再比。
# 判定只认"两边当次读数一致 + 我方文档 id 与请求的 DID 相同"，不钉死密钥值——文档轮换是发布方的自由，
# 不该让台子红；反过来，真不一致（同一时刻两边读到的字段不同）才是互操作缺陷。
PUBLIC_DIDS = [
    "did:web:identity.foundation",
    "did:web:veramo.io",
    "did:web:danubetech.com",
]


def _keyref(vm):
    """公钥规范化。必须与 tools/interop/resolve3p.js 的 keyref() 逐字一致。"""
    if vm.get("publicKeyMultibase"):
        return "mb:" + str(vm["publicKeyMultibase"])
    if vm.get("publicKeyJwk"):
        return "jwk:" + json.dumps(vm["publicKeyJwk"], sort_keys=True, separators=(",", ":"))
    if vm.get("publicKeyHex"):
        return "hex:" + str(vm["publicKeyHex"])
    if vm.get("publicKeyBase58"):
        return "b58:" + str(vm["publicKeyBase58"])
    if vm.get("publicKeyPem"):
        return "pem:" + str(vm["publicKeyPem"])
    return "none"


def _vmlist(doc):
    return sorted(
        [dict(id=(vm.get("id") or None), type=(vm.get("type") or None),
              controller=(vm.get("controller") or None), key=_keyref(vm))
         for vm in (doc.get("verificationMethod") or [])],
        key=lambda x: str(x["id"]))


def _auth(doc):
    return sorted([a if isinstance(a, str) else (a or {}).get("id")
                   for a in (doc.get("authentication") or [])])



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

    # I2 现在有真前置了：第三方主体发布的公网 did:web（不是回环、不是自建、不注入 fetcher）。
    # 判 PASS 要同时满足两件事：① 至少一条真取到了文档；② 取到的那条，文档 id 与请求的 DID 逐字相同，
    # 且至少有一个带公钥材料的 verificationMethod。取不到（本机/CI 无出网）记 BLOCKED 并写明原因，
    # 不改成 PASS、也不改成 FAIL —— 缺的是外网连通性，不是被测仓的能力。
    pub_docs, pub_errs = {}, {}
    t_pub = time.time()
    for pd in PUBLIC_DIDS:
        try:
            pub_docs[pd] = U.resolve(pd, timeout=15)
        except Exception as e:
            pub_errs[pd] = "%s: %s" % (type(e).__name__, str(e)[:110])

    if not pub_docs:
        rec("I2 我方取公钥", "BLOCKED",
            "三条公网 did:web 一条也没取到（本机需能出网访问 443）：%s"
            % "；".join("%s→%s" % (k, v) for k, v in pub_errs.items()),
            {"needs": "outbound HTTPS", "errors": pub_errs})
    else:
        wrong_id, no_key = [], []
        for pd, doc in pub_docs.items():
            if (doc.get("id") or "") != pd:
                wrong_id.append("%s→id=%s" % (pd, doc.get("id")))
            if not any(_keyref(vm) != "none" for vm in (doc.get("verificationMethod") or [])):
                no_key.append(pd)
        ok_i2 = not wrong_id and not no_key
        detail = "；".join("%s %d 条 vm %s" % (k, len(v.get("verificationMethod") or []),
                                             _keyref((v.get("verificationMethod") or [{}])[0])[:18])
                           for k, v in pub_docs.items())
        if pub_errs:
            detail += "（未取到：%s）" % ",".join(pub_errs)
        rec("I2 我方取公钥", "PASS" if ok_i2 else "FAIL",
            "%s（%.0fms）%s" % (detail, (time.time() - t_pub) * 1000,
                              ("  文档 id 不符：" + "；".join(wrong_id)) if wrong_id else "")
            + (("  无公钥材料：" + ",".join(no_key)) if no_key else ""),
            {"docs": {k: {"id": v.get("id"), "vms": len(v.get("verificationMethod") or [])}
                      for k, v in pub_docs.items()}, "errors": pub_errs})

    t0 = time.time()
    theirs = third_party(did)
    if theirs is None:
        rec("I3 第三方解析 did:web", "BLOCKED", "未安装：先跑 npm i 于 runs/_interop（did-resolver + web-did-resolver）")
        rec("I4 两实现逐字段比对", "BLOCKED", "依赖第三方解释器（node + did-resolver），未安装")
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
        pass  # I3–I6 已在上方按依赖缺失记为 BLOCKED，不再重复记一条 FAIL
    else:
        # 逐字段比对现在比对的是"公网第三方文档"：两边各自真实抓一份，按规范化后的
        # id / verificationMethod 清单 / authentication 比。轮换频繁的文档可能在两次抓取之间变化，
        # 因此出现不一致时先让两边重抓一次再判——只有重抓后仍不一致才算互操作缺陷。
        cmp_ok, cmp_bad, cmp_skip = [], [], []

        def _fields(od, td):
            f = []
            if (od.get("id") or "") != (td.get("didDocumentId") or ""):
                f.append("id")
            if _vmlist(od) != (td.get("vmList") or []):
                f.append("verificationMethod")
            if _auth(od) != (td.get("authentication") or []):
                f.append("authentication")
            return f

        for pd in PUBLIC_DIDS:
            od = pub_docs.get(pd)
            td = third_party(pd)
            if od is None or not (td or {}).get("ok"):
                cmp_skip.append("%s（我方%s / 第三方%s）" % (
                    pd, "取到" if od is not None else "未取到",
                    "ok" if (td or {}).get("ok") else ((td or {}).get("error") or "node 无输出")))
                continue
            diffs = _fields(od, td)
            if diffs:
                try:
                    od = U.resolve(pd, timeout=15)
                    pub_docs[pd] = od
                    td = third_party(pd)
                    diffs = [] if (td or {}).get("ok") else diffs
                    diffs = _fields(od, td or {})
                except Exception as e:
                    diffs = diffs + ["重抓失败:%s" % type(e).__name__]
            if diffs:
                cmp_bad.append((pd, diffs))
            else:
                cmp_ok.append(pd)

        if cmp_bad:
            rec("I4 两实现逐字段比对", "FAIL",
                "不一致：" + "；".join("%s 字段 %s" % (d, ",".join(f)) for d, f in cmp_bad)
                + ("  （可比对一致：%s）" % ",".join(cmp_ok) if cmp_ok else ""),
                {"bad": cmp_bad, "ok": cmp_ok})
        elif cmp_ok:
            rec("I4 两实现逐字段比对", "PASS",
                "逐字段一致 %d 条：%s（id / verificationMethod / authentication；重抓后仍不一致才算缺陷）"
                % (len(cmp_ok), ",".join(cmp_ok)),
                {"ok": cmp_ok})
        else:
            rec("I4 两实现逐字段比对", "BLOCKED", "无可比对对象：" + "；".join(cmp_skip),
                {"skip": cmp_skip})

        # 回环那条仍单独判：分歧是设计，不是缺陷，但必须由机器证明它确实按设计发生了。
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
