# -*- coding: utf-8 -*-
"""端口与本地宿主服务的共享工具。

存在理由（2026-11-23 云主机实测暴露）：
场景组 B 曾把端口写死 8443/8080，在 8080 已被占用的机器上
ThreadingHTTPServer 直接抛 OSError，脚本在 rec() 之前就死掉 ——
结果是"整组静默消失"，比 BLOCKED 更危险（会被读成"跑了、没输出"）。
所以：端口默认由系统分配，占用时自动换，仍失败则抛出可被判为 BLOCKED 的异常。
"""
import socket
from http.server import ThreadingHTTPServer


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve_any(handler, port, cert=None, key=None, tries=6):
    """绑定 127.0.0.1:port；port=0 或占用时自动取空闲端口。返回 (srv, actual_port)。"""
    import ssl, threading
    last = None
    for _ in range(tries):
        p = port if port else free_port()
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), handler)
        except OSError as e:
            last = e
            if port:                      # 指定端口被占：下一轮改随机
                port = 0
                continue
            continue
        if cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, srv.server_address[1]
    raise RuntimeError("VHOST_PORT_UNAVAILABLE: 本地宿主端口无法绑定（最后一次错误：%r）" % (last,))
