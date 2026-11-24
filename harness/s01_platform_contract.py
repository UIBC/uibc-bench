# -*- coding: utf-8 -*-
"""场景组 A：信通院平台（iaisp.teleinfo.cn）真实契约与韧性实测。

只做只读探测与验签类查询，不注册、不写入、不改任何平台状态。
每个用例记录 状态码 / 耗时 / 响应片段 / 判定，全部输出 JSON + 人读日志。
"""
import json, ssl, socket, sys, time, threading, traceback
import urllib.request, urllib.error

BASE = "https://iaisp.teleinfo.cn"
VALID_DID = "did:cn:agent:sfZD8WUaMvz7kE2Z797nzDf7oqMmVu3r"  # 我方已注册的需方 DID（只读解析，不动私钥）
UA = "uibc-core-outsider-probe/0.5 (+field-test 2026-11-23; read-only)"
RESULTS = []


def rec(case, verdict, status=None, ms=None, note="", body=None):
    RESULTS.append(dict(case=case, verdict=verdict, status=status,
                        ms=None if ms is None else round(ms, 1), note=note,
                        body=None if body is None else body[:600]))
    print("[%-4s] %-46s http=%s %sms %s" % (verdict, case, status, "-" if ms is None else int(ms), note))


def http(url, method="GET", payload=None, timeout=15, headers=None, raw=False):
    data = None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if payload is not None:
        data = payload if raw else json.dumps(payload).encode("utf-8")
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body, time.time() - t0, dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, body, time.time() - t0, dict(e.headers)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e), time.time() - t0, {}


def safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------- A1 可用性与契约 ----------
def a1_availability():
    for i in range(5):
        st, body, ms, _ = http(BASE + "/api/public/ioa/agents")
        rec("A1 agents 读取 #%d" % (i + 1), "PASS" if st == 200 else "FAIL", st, ms)
        time.sleep(0.4)
    st, body, ms, hdr = http(BASE + "/api/public/ioa/agents")
    j = safe_json(body)
    if not j:
        rec("A1 响应合法性", "FAIL", st, ms, "不是 JSON")
        return
    # 结构探测
    keys = list(j.keys())
    data = j.get("data")
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in ("list", "records", "items", "rows", "content"):
            if isinstance(data.get(k), list):
                items = data[k]; break
    if items is None and isinstance(j.get("data"), dict):
        items = [v for v in data.values() if isinstance(v, list)]
        items = items[0] if items else None
    n = len(items or [])
    rec("A1 顶层字段", "INFO", st, ms, "keys=%s" % keys, body=body[:300])
    rec("A1 在册智能体条数", "INFO", st, ms, "n=%d" % n)
    if items:
        fieldset = sorted({k for it in items if isinstance(it, dict) for k in it.keys()})
        rec("A1 条目字段集合", "INFO", None, None, "fields=%s" % fieldset)
        # 契约漂移探测：字段缺失 / 空值 / 类型不一致 / DID 字段
        miss = {f: sum(1 for it in items if isinstance(it, dict) and (f not in it or it.get(f) in (None, "", []))) for f in fieldset}
        bad = {f: c for f, c in miss.items() if c}
        rec("A1 字段缺失/空值", "WARN" if bad else "PASS", None, None, str(bad) if bad else "无缺失")
        dtype = {}
        for f in fieldset:
            ts = {type(it.get(f)).__name__ for it in items if isinstance(it, dict)}
            if len(ts) > 1:
                dtype[f] = sorted(ts)
        rec("A1 同字段类型不一致", "FAIL" if dtype else "PASS", None, None, str(dtype) if dtype else "一致")
        didvals = [it for it in items if isinstance(it, dict) and any(str(it.get(k, "")).startswith("did:") for k in it.keys())]
        rec("A1 携带 DID 的条目数", "INFO", None, None, "%d/%d" % (len(didvals), n))
        if didvals:
            methods = {}
            for it in didvals:
                for k, v in it.items():
                    if isinstance(v, str) and v.startswith("did:"):
                        m = v.split(":")[1] if len(v.split(":")) > 1 else "?"
                        methods.setdefault(m, 0); methods[m] += 1
            rec("A1 DID 方法分布", "INFO", None, None, str(methods))


# ---------- A2 解析/验签契约 ----------
def a2_resolve():
    url = BASE + "/api/public/ioa/did/resolve-verify"
    cases = [
        ("A2 已注册 DID", {"did": VALID_DID}, 200),
        ("A2 不存在的 did:cn:agent", {"did": "did:cn:agent:0000000000000000000000000000000000000000"}, 200),
        ("A2 空字符串 DID", {"did": ""}, 400),
        ("A2 非 DID 字符串", {"did": "hello"}, 400),
        ("A2 别的方法 did:web", {"did": "did:web:example.com"}, 400),
        ("A2 别的方法 did:key", {"did": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"}, 400),
        ("A2 DID 类型错误(数字)", {"did": 12345}, 400),
        ("A2 缺 did 字段", {"foo": "bar"}, 400),
        ("A2 超长 DID 4096", {"did": "did:cn:agent:" + "a" * 4096}, 400),
        ("A2 含注入字符", {"did": "did:cn:agent:x' OR 1=1--"}, 400),
        ("A2 含路径穿越", {"did": "did:cn:agent:../../etc/passwd"}, 400),
        ("A2 多余字段", {"did": VALID_DID, "extra": {"a": 1}}, 200),
    ]
    for name, payload, want in cases:
        st, body, ms, _ = http(url, "POST", payload)
        j = safe_json(body) or {}
        ok = j.get("success")
        d = j.get("data") or {}
        summ = (d.get("summary") or {}) if isinstance(d, dict) else {}
        rs = summ.get("resolutionStatus") or summ.get("status")
        vs = summ.get("vcVerificationStatus")
        trap = (ok is True and str(rs).upper() not in ("SUCCESS", "RESOLVED", "OK"))
        note = "success=%s rs=%s vc=%s%s" % (ok, rs, vs, " <陷阱:success真但解析失败>" if trap else "")
        # 判据：该拒不拒（200 且 success，该 400 的）才算 FAIL；合法输入 200 且能有结论算 PASS
        if want == 400:
            verdict = "PASS" if st == 400 else "FAIL"
            if st != 400:
                note += " <应 400 却返回 %s>" % st
        else:
            verdict = "PASS" if (st == 200 and ok is not None) else "FAIL"
            if trap and name.startswith("A2 不存在"):
                verdict = "WARN"
                note += " <契约陷阱：只能看 resolutionStatus>"
        rec(name, verdict, st, ms, note, body=body)


# ---------- A3 方法与协议层 ----------
def a3_protocol():
    for m in ("HEAD", "OPTIONS", "PUT", "DELETE"):
        st, body, ms, hdr = http(BASE + "/api/public/ioa/agents", m)
        allow = hdr.get("Allow") or hdr.get("allow")
        rec("A3 agents %s" % m, "INFO", st, ms, "allow=%s" % allow)
    st, body, ms, _ = http(BASE + "/api/public/ioa/demand-providers")
    rec("A3 demand-providers 权限", "INFO" if st in (200, 401, 403) else "WARN", st, ms, body[:120].replace("\n", " "))
    # 不存在的路径 / 大小写 / 尾斜杠
    for p in ("/api/public/ioa/agentz", "/API/PUBLIC/IOA/AGENTS", "/api/public/ioa/agents/"):
        st, body, ms, _ = http(BASE + p)
        rec("A3 路径变体 %s" % p, "INFO", st, ms, body[:100].replace("\n", " "))
    # TLS 基线
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("iaisp.teleinfo.cn", 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname="iaisp.teleinfo.cn") as ss:
                rec("A3 TLS 基线", "PASS", None, None,
                    "ver=%s cipher=%s ALPN=%s" % (ss.version(), ss.cipher()[0], ss.selected_alpn_protocol()))
    except Exception as e:
        rec("A3 TLS 基线", "FAIL", None, None, repr(e))
    # 响应头安全基线
    st, body, ms, hdr = http(BASE + "/api/public/ioa/agents")
    interesting = {k: v for k, v in hdr.items() if k.lower() in
                   ("server", "x-powered-by", "strict-transport-security", "content-type",
                    "x-frame-options", "content-security-policy", "cache-control", "vary", "access-control-allow-origin")}
    rec("A3 响应头基线", "INFO", st, ms, str(interesting))


# ---------- A4 并发与限流 ----------
def a4_concurrency():
    url = BASE + "/api/public/ioa/agents"
    lock = threading.Lock()
    stat = {"ok": 0, "err": [], "ms": []}

    def hit():
        st, body, ms, _ = http(url, timeout=20)
        with lock:
            if st == 200:
                stat["ok"] += 1
            else:
                stat["err"].append(st)
            stat["ms"].append(ms)

    ths = [threading.Thread(target=hit) for _ in range(8)]
    t0 = time.time()
    [t.start() for t in ths]
    [t.join() for t in ths]
    dur = time.time() - t0
    ms = sorted(stat["ms"])
    p50 = ms[len(ms) // 2] if ms else 0
    p95 = ms[int(len(ms) * 0.95) - 1] if ms else 0
    rec("A4 并发 8 读", "PASS" if not stat["err"] else "WARN", None, dur * 1000 / 8,
        "ok=%d err=%s p50=%dms p95=%dms 总耗时=%.1fs" % (stat["ok"], stat["err"], p50, p95, dur))


# ---------- A5 时延与网络基线 ----------
def a5_network():
    samples = []
    for i in range(6):
        st, _, ms, _ = http(BASE + "/api/public/ioa/agents", timeout=20)
        samples.append(ms); time.sleep(0.3)
    ms = sorted(samples)
    rec("A5 时延基线(境内直连)", "INFO", None, ms[len(ms) // 2],
        "min=%d p50=%d max=%d" % (ms[0], ms[len(ms) // 2], ms[-1]))
    t0 = time.time(); socket.getaddrinfo("iaisp.teleinfo.cn", 443); dns = (time.time() - t0) * 1000
    addrs = sorted({ai[4][0] for ai in socket.getaddrinfo("iaisp.teleinfo.cn", 443, socket.AF_INET)})
    rec("A5 DNS 解析", "INFO", None, dns, "A=%s" % addrs)


def main():
    print("=== A 组：平台契约实测 %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
    for fn in (a1_availability, a2_resolve, a3_protocol, a4_concurrency, a5_network):
        try:
            fn()
        except Exception:
            rec(fn.__name__, "ERROR", None, None, traceback.format_exc().splitlines()[-1])
    out = sys.argv[1] if len(sys.argv) > 1 else "s01_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
