# -*- coding: utf-8 -*-
"""最小 HTTPS binding（DIF Universal Resolver 1.0 协议），只做协议适配，不加任何行为。

用途：官方 W3C DID Resolution Test Suite 只认 HTTPS endpoint；
      本仓解析逻辑是库函数，没有 HTTP 面。本 shim 只把库函数按规范媒体类型暴露出来，
      使"官方套件 -> 我们的解析器"这条链路可被任何外人复跑。

协议：
  GET /1.0/identifiers/<did>
    Accept: application/did-resolution  -> {didResolutionMetadata, didDocument, didDocumentMetadata}
    Accept: application/did+ld+json     -> DID 文档本身
  错误结构遵循 DID Resolution 规范（error 是对象，带 type = https://www.w3.org/ns/did#<CODE>），
  HTTP 状态码：INVALID_DID/INVALID_OPTIONS 400 / NOT_FOUND 404 /
  REPRESENTATION_NOT_SUPPORTED 406 / METHOD_NOT_SUPPORTED 501 / INTERNAL_ERROR 500

启动：
  python tools/resolver_https_shim.py --port 9443 --cert _pki/cert.pem --key _pki/key.pem
"""
import argparse, json, os, ssl, sys, urllib.parse, http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
# 默认解析本仓克隆的被测实现；UIBC_REPO 可指向另一个候选实现（对照实验用，不改默认行为）
REPO = os.environ.get("UIBC_REPO") or os.path.join(KIT, "uibc-core-public")
sys.path.insert(0, REPO)

import uibc_core.did as U  # noqa: E402

# 实现来源必须可证：曾出现 UIBC_REPO 指向坏目录时，import 静默回退到机器上已安装的另一份 uibc_core
# （云主机上有 editable install 指向 work_20261122/main_verify），于是"只换实现"的对照可能测的是第三份代码。
# 这里强制校验：解析到的模块必须位于 UIBC_REPO 之下，否则拒绝启动（exit 3），绝不静默降级。
_IMPL = os.path.abspath(U.__file__)
_REPO_ABS = os.path.abspath(REPO)
if not _IMPL.startswith(_REPO_ABS + os.sep):
    sys.stderr.write("[shim] FATAL: uibc_core 解析到 %s，不在指定实现 %s 之下"
                     "（很可能回退到已安装副本）。拒绝启动。\n" % (_IMPL, _REPO_ABS))
    sys.exit(3)
print("[shim] impl=%s repo=%s" % (_IMPL, _REPO_ABS), flush=True)

RES_MEDIA = "application/did-resolution"
DOC_MEDIA = "application/did+ld+json"

ERR_STATUS = {
    "INVALID_DID": 400,
    "INVALID_OPTIONS": 400,
    "NOT_FOUND": 404,
    "REPRESENTATION_NOT_SUPPORTED": 406,
    "INVALID_DID_DOCUMENT": 500,
    "METHOD_NOT_SUPPORTED": 501,
    "FEATURE_NOT_SUPPORTED": 501,
    "INTERNAL_ERROR": 500,
}


def _is_datetime(s):
    try:
        import datetime as dt
        dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, body, ctype):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _err(self, err, msg):
        st = ERR_STATUS.get(err, 500)
        body = json.dumps({
            "didResolutionMetadata": {
                "contentType": RES_MEDIA,
                "error": {"type": "https://www.w3.org/ns/did#" + err,
                          "title": err, "detail": msg},
            },
            "didDocument": None,
            "didDocumentMetadata": {},
        })
        self._send(st, body, RES_MEDIA)

    def do_GET(self):
        accept = (self.headers.get("Accept") or "*/*").lower()
        path, _, qs = self.path.partition("?")
        if not path.startswith("/1.0/identifiers/"):
            return self._err("NOT_FOUND", "only /1.0/identifiers/<did>")
        did = urllib.parse.unquote(path[len("/1.0/identifiers/"):])
        if not did.startswith("did:"):
            return self._err("INVALID_DID", "not a DID: %s" % did)
        q = urllib.parse.parse_qs(qs)
        for vt in q.get("versionTime", []):
            if not _is_datetime(vt):
                return self._err("INVALID_OPTIONS", "versionTime 不是 datetime: %s" % vt)

        want_res = (RES_MEDIA in accept) or ("*/*" in accept)
        want_doc = DOC_MEDIA in accept
        if not want_res and not want_doc:
            return self._err("REPRESENTATION_NOT_SUPPORTED", "unsupported Accept: %s" % accept)

        try:
            doc = U.resolve(did)
        except U.UnsupportedMethod as e:
            return self._err("METHOD_NOT_SUPPORTED", str(e))
        except U.DIDError as e:
            msg = str(e)
            kind = "INVALID_DID" if ("invalid" in msg or "not a DID" in msg) else "NOT_FOUND"
            return self._err(kind, msg)
        except Exception as e:
            return self._err("NOT_FOUND" if "URLError" in type(e).__name__ else "INTERNAL_ERROR",
                             repr(e)[:200])

        if want_doc and not want_res:
            return self._send(200, json.dumps(doc, ensure_ascii=False), DOC_MEDIA)
        body = json.dumps({"didResolutionMetadata": {"contentType": DOC_MEDIA},
                           "didDocument": doc,
                           "didDocumentMetadata": {}}, ensure_ascii=False)
        # 规范要求 HTTP Content-Type 与 didResolutionMetadata.contentType 相等；
        # contentType 描述的是返回文档的表示，因此两者都用 DOC_MEDIA（此前错用 RES_MEDIA，把一条断言打红）
        self._send(200, body, DOC_MEDIA)

    def log_message(self, fmt, *a):
        sys.stderr.write("[shim] " + (fmt % a) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9443)
    ap.add_argument("--cert", default=os.path.join(KIT, "_pki", "cert.pem"))
    ap.add_argument("--key", default=os.path.join(KIT, "_pki", "key.pem"))
    a = ap.parse_args()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(a.cert, a.key)
    srv = socketserver.ThreadingTCPServer(("0.0.0.0", a.port), H)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("listening https://0.0.0.0:%d/1.0/identifiers/  (self-signed)" % a.port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
