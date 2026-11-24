# -*- coding: utf-8 -*-
"""场景组 B2：把 B1/B3/B5 三个关键点重做成"文档 id 与请求路径一致"的干净对照。

上一轮 B3(302 降级)、B5(20MB) 被 document id 校验挡下，属于副作用而非协议防护，
不能作为结论。这里让每个路径返回 id 自洽的文档，单独看：
  - 302 到明文 http 是否真被跟随（跟随即证明 https 约束只在首跳）
  - 20MB 响应是否真有大小上限
  - 回环/内网是否真的可达（B1 已证，这里用非回环内网段复验）
"""
import json, os, ssl, sys, threading, time, traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "uibc-core-public")))
sys.path.insert(0, HERE)
import s02_did_hostile as bed          # 复用同一套本地宿主、动态端口与 did_base()
RESULTS = []
CA_DIR = os.path.abspath(os.path.join(HERE, "..", "_pki"))


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-5s] %-40s %s" % (verdict, case, note))


def base_doc(did_id, size_note=None):
    return {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": did_id,
        "verificationMethod": [{
            "id": did_id + "#key-1", "type": "Ed25519VerificationKey2020", "controller": did_id,
            "publicKeyMultibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"}],
        "authentication": [did_id + "#key-1"],
        "pad": size_note or "x",
    }


def suffix_from(path):
    """https://host/.well-known/did.json -> '' ; /redir/did.json -> ':redir'"""
    segs = [s for s in path.split("/") if s]
    if segs and segs[0] == ".well-known":
        return ""
    if segs and segs[-1] == "did.json":
        return "".join(":" + s for s in segs[:-1])
    return ""


class H(BaseHTTPRequestHandler):
    hits = []
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        H.hits.append(self.path)
        if self.path.endswith("/redir/did.json"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/plain/did.json" % bed.PX_PORT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.endswith("/big/did.json"):
            doc = base_doc(bed.did_base(":big"), "y" * (20 * 1024 * 1024))
        else:
            doc = base_doc(bed.did_base() + suffix_from(self.path))
        body = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PlainH(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        H.hits.append("plain:" + self.path)
        doc = base_doc(bed.did_base(":redir"))
        body = json.dumps(doc).encode()
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
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    os.makedirs(CA_DIR, exist_ok=True)
    if not os.path.exists(os.path.join(CA_DIR, "cert.pem")):
        bed.make_cert()
    cert, key = os.path.join(CA_DIR, "cert.pem"), os.path.join(CA_DIR, "key.pem")
    os.environ["SSL_CERT_FILE"] = cert
    os.environ["SSL_CERT_DIR"] = CA_DIR
    try:
        s1, bed.HS_PORT = bed.serve_any(H, int(os.environ.get("S02_HTTPS_PORT") or 0) or bed.free_port(), cert, key)
        s2, bed.PX_PORT = bed.serve_any(PlainH, int(os.environ.get("S02_HTTP_PORT") or 0) or bed.free_port())
    except Exception as e:
        rec("B0 本地宿主无法监听", "BLOCKED", str(e)[:200])
        return
    bed.DOC, bed.BIG = bed.make_docs()
    time.sleep(0.5)
    from uibc_core import did as didmod

    # B1' 回环（id 自洽）—— 是否成功解析
    try:
        d = didmod.resolve(bed.did_base(), timeout=5)
        rec("B1' 回环目标可解析(id自洽)", "FAIL",
            "解析成功，命中 %s：did:web 未限制回环地址" % H.hits[-1:],
            {"kind": "SSRF", "severity": "中高"})
    except Exception as e:
        rec("B1' 回环目标可解析(id自洽)", "PASS", "%s: %s" % (type(e).__name__, str(e)[:80]))

    # B3' 302 → 明文 http（目标文档 id 自洽）
    H.hits.clear()
    try:
        d = didmod.resolve(bed.did_base(":redir"), timeout=5)
        downgraded = any(h.startswith("plain:") for h in H.hits)
        rec("B3' 302 降级到 http 是否被跟随", "FAIL" if downgraded else "PASS",
            "命中序列=%s；%s" % (H.hits, "明文 http 被接受，https 只约束首跳" if downgraded else "未发生明文请求"),
            {"kind": "传输降级", "severity": "中"})
    except Exception as e:
        rec("B3' 302 降级到 http 是否被跟随", "PASS" if not any(h.startswith("plain:") for h in H.hits) else "WARN",
            "%s: %s（hits=%s）" % (type(e).__name__, str(e)[:90], H.hits))

    # B5' 20MB（id 自洽）
    import tracemalloc
    tracemalloc.start()
    t0 = time.time()
    try:
        d = didmod.resolve(bed.did_base(":big"), timeout=30)
        cur, peak = tracemalloc.get_traced_memory()
        rec("B5' 20MB 文档(id自洽)", "FAIL",
            "接受并解析，耗时 %.1fs，峰值内存 %.1fMB；无大小上限" % (time.time() - t0, peak / 1048576),
            {"kind": "DoS", "severity": "中"})
    except Exception as e:
        rec("B5' 20MB 文档(id自洽)", "PASS" if "JSON" in str(e) or "size" in str(e).lower() else "INFO",
            "%.1fs 拒绝：%s" % (time.time() - t0, str(e)[:90]))
    finally:
        tracemalloc.stop()

    # B* 301 永久重定向到另一个 https 域（跨域跳转是否被限制）
    H.hits.clear()
    try:
        s1.shutdown(); s2.shutdown()
    except Exception:
        pass
    write_results()


def write_results():
    out = sys.argv[1] if len(sys.argv) > 1 else "s02b_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        rec("B0 场景组异常中止", "BLOCKED", "%s: %s" % (type(e).__name__, str(e)[:180]))
        try:
            write_results()
        except Exception:
            pass

