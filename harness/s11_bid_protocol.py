# -*- coding: utf-8 -*-
"""场景组 J：did:bid 解析协议契约（《星火·链网BID协议》§4.2 / §4.2.5 / §5 / 附录一）。

为什么单开一组：uibc-core 的 BID 协议层不能只在自己仓里自证。这一组从**外部**
调用被测仓的公开 API，逐条检查协议条款是否真的被遵守；能验的用两个互不相干的
实现交叉验（Python 与被测仓、node/OpenSSL），不能验的标 BLOCKED 或 SKIP，不填数。

只读：不需要网络，不登录任何平台，不上链。
"""
import json, os, subprocess, sys, tempfile, time, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _subject

RESULTS = []
DID = "did:bid:ef18F9AVK4SQLZPRrPkrVWwp9kbpdXHx"
KEY_ID = DID + "#key-1"
BARE_HEX = "b9906e1b50e81501369cc777979f8bcf27bd1917d794fa6d5e320b1ccc4f48bb"   # 协议 §4.2.2.1 自己的样例


def rec(case, verdict, note="", body=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note,
                        body=None if body is None else str(body)[:600]))
    print("[%-7s] %-52s %s" % (verdict, case, note))


def doc(**over):
    d = {
        "@context": ["https://w3.org/ns/did/v1"],
        "id": DID,
        "created": "2021-06-24T09:10:09Z",
        "updated": "2021-06-24T09:10:09Z",
        "authentication": [KEY_ID],
        "publicKey": [{"controller": DID, "id": KEY_ID, "publicKeyHex": BARE_HEX, "type": "Ed25519"}],
        "extension": {"ttl": 86400, "type": 105},
    }
    d.update(over)
    return d


def fetcher_for(routes):
    def f(url, timeout=10):
        for needle, answer in routes.items():
            if needle in url:
                return answer(url) if callable(answer) else answer
        raise AssertionError("unexpected url %r" % (url,))
    return f


def ok(data):
    return {"errorCode": 0, "message": "success", "data": data}


def main():
    subject = _subject.resolve(require=False)
    if not subject:
        rec("J0 被测仓定位", "BLOCKED", "UIBC_SUBJECT 未设置，找不到被测仓")
        return finish()
    sys.path.insert(0, subject)
    try:
        from uibc_core import bid_protocol as B
    except Exception:
        rec("J0 导入 uibc_core.bid_protocol", "BLOCKED",
            traceback.format_exc().splitlines()[-1])
        return finish()
    rec("J0 被测仓", "INFO", "subject=%s" % subject, "module=%s" % B.__file__)

    j1_response_codes(B)
    j2_document_rules(B)
    j3_signing(B)
    j4_cross_language(B, subject)
    j5_sub_chain(B)
    j6_field_endpoints(B)
    j7_official_sdk_address(B, subject)
    return finish()


# ---------------------------------------------------------------- J1 §4.2.5
def j1_response_codes(B):
    table = getattr(B, "BID_RESPONSE_CODES", {})
    rec("J1.1 响应码表覆盖 0..10", "PASS" if set(table) == set(range(11)) else "FAIL",
        "codes=%s" % sorted(table))
    expect = {0: "success", 3: "server too busy", 6: "not found", 9: "verify failed"}
    bad = [c for c, n in expect.items() if table.get(c, ("",))[0] != n]
    rec("J1.2 码名与协议原文一致", "PASS" if not bad else "FAIL", "mismatch=%s" % bad)
    ok = True
    for code in range(11):
        err = B.BIDResponseError(code, did=DID)
        retryable = getattr(err, "retryable", None)
        if retryable is not bool(code in (3, 7)):
            ok = False
    rec("J1.3 只有 3/7 可重试", "PASS" if ok else "FAIL")
    err6 = B.BIDResponseError(6, did=DID)
    err9 = B.BIDResponseError(9, did=DID)
    rec("J1.4 「没找到」与「验签失败」不混为一谈",
        "PASS" if getattr(err6, "not_found", False) and not getattr(err9, "not_found", True) else "FAIL",
        "6.not_found=%s 9.kind=%s" % (getattr(err6, "not_found", None), getattr(err9, "kind", None)))
    unknown = B.BIDResponseError(77, "?", DID)
    rec("J1.5 未记载的码保留数字", "PASS" if unknown.code == 77 else "FAIL", "code=%s" % unknown.code)


# ------------------------------------------------------------- J2 文档规则
def j2_document_rules(B):
    cases = [
        ("id 必须等于请求", dict(id="did:bid:efOther")),
        ("authentication 不得引用未定义键", dict(authentication=[DID + "#key-9"])),
        ("controller 必须是 BID", dict(publicKey=[dict(doc()["publicKey"][0], controller="did:web:x")])),
        ("publicKeyHex 必须是十六进制", dict(publicKey=[dict(doc()["publicKey"][0], publicKeyHex="zz")])),
        ("alsoKnownAs.type 必须是 Int", dict(alsoKnownAs=[{"type": "101", "id": DID}])),
        ("子链解析必须有端点", dict(service=[{"id": DID + "#s", "type": "DIDSubResolver" }])),
        ("子链 protocol 必须 0..3", dict(service=[{"id": DID + "#s", "type": "DIDSubResolver",
                                                  "serviceEndpoint": "http://x/", "protocol": 9}])),
        ("ttl 必须非负整数", dict(extension={"ttl": -1})),
        ("attribute.encrypt 必须 0/1", dict(extension={"attributes": [{"key": "k", "value": "v", "encrypt": 2}]})),
        ("时间戳必须 ISO-8601", dict(created="2021-06-24")),
        ("proof.creator 必须是本文档的键", dict(proof={"creator": DID + "#key-9",
                                                      "signatureValue": "3yZe7d"})),
        ("proof 必须是 Base58", dict(proof={"creator": KEY_ID, "signatureValue": "0OIl"})),
        ("重复 publicKey.id", dict(publicKey=[doc()["publicKey"][0], dict(doc()["publicKey"][0])])),
    ]
    for name, over in cases:
        try:
            B.parse_bid_document(doc(**over), DID)
            rec("J2 %s" % name, "FAIL", "接受了非法文档")
        except Exception as exc:
            rec("J2 %s" % name, "PASS", type(exc).__name__)
    try:
        parsed = B.parse_bid_document(doc(), DID)
    except Exception:
        rec("J2 合法文档可以解析", "FAIL", traceback.format_exc().splitlines()[-1])
        return
    core = parsed.to_did_core()
    rec("J2 投影不丢 BID 自有字段", "PASS" if core.get("extension", {}).get("ttl") == 86400 else "FAIL",
        "keys=%s" % sorted(core))


# ----------------------------------------------------------------- J3 签名
def j3_signing(B):
    try:
        seed, hexed = B.generate_ed25519_pair()
        key_hex = hexed if len(hexed) > 68 else "b06566" + hexed[2:]
        signed = B.sign_bid_document(doc(publicKey=[dict(doc()["publicKey"][0], publicKeyHex=key_hex)]), seed, KEY_ID)
        rec("J3.1 自签自验", "PASS" if B.verify_bid_document(signed, DID)[0] else "FAIL")
        tampered = dict(signed, extension={"ttl": 86401, "type": 105})
        rec("J3.2 改一处即失效", "PASS" if B.verify_bid_document(tampered, DID)[0] is False else "FAIL")
        for name, hx in (("裸键 64", hexed[2:] if len(hexed) == 66 else hexed),
                         ("b0 前缀 66", "b0" + (hexed[2:] if len(hexed) == 66 else hexed)),
                         ("b06566 前缀 70", "b06566" + (hexed[2:] if len(hexed) == 66 else hexed))):
            d2 = B.sign_bid_document(doc(publicKey=[dict(doc()["publicKey"][0], publicKeyHex=hx)]), seed, KEY_ID)
            rec("J3.3 键编码 %s 可验" % name, "PASS" if B.verify_bid_document(d2, DID)[0] else "FAIL", "hex=%d" % len(hx))
    except Exception:
        rec("J3 签名闭环", "FAIL", traceback.format_exc().splitlines()[-1])


# ------------------------------------------------------- J4 跨语言（node）
def j4_cross_language(B, subject):
    js = os.path.join(subject, "tools", "verify-js", "bid.mjs")
    fixture = os.path.join(subject, "fixtures", "bid", "signed_document.json")
    if not (os.path.exists(js) and os.path.exists(fixture)):
        rec("J4 跨实现验签", "SKIP", "被测仓未提供 tools/verify-js/bid.mjs 或夹具")
        return
    try:
        proc = subprocess.run(["node", js, fixture], capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        rec("J4 跨实现验签", "SKIP", "未安装 node")
        return
    except Exception:
        rec("J4 跨实现验签", "BLOCKED", traceback.format_exc().splitlines()[-1])
        return
    out = proc.stdout + proc.stderr
    rec("J4.1 node 独立验签通过", "PASS" if proc.returncode == 0 and "signature-verified true" in out else "FAIL",
        "rc=%s" % proc.returncode)
    import hashlib
    docj = json.load(open(fixture, encoding="utf-8"))
    mine = hashlib.sha256(B.signing_bytes(docj)).hexdigest()
    line = [l for l in out.splitlines() if l.startswith("signing-bytes-sha256")]
    theirs = line[0].split()[-1] if line else ""
    rec("J4.2 两侧规范化字节一致", "PASS" if theirs == mine else "FAIL",
        "python=%s node=%s" % (mine[:16], theirs[:16]))


# ------------------------------------------------------------- J5 子链递归
def j5_sub_chain(B):
    main_ep, sub_ep = "http://main.example", "http://sub.example.com"

    def wrap(document):
        return {"errorCode": 0, "data": {"didDocument": document}}

    routes = {}
    routes[main_ep] = lambda url: wrap(dict(doc(), service=[{
        "id": DID + "#s", "type": "DIDSubResolver", "protocol": 2, "serviceEndpoint": sub_ep}]))
    routes[sub_ep] = lambda url: wrap(doc())
    try:
        parsed = B.resolve_bid_chain(main_ep, DID, fetcher=fetcher_for(routes))
        rec("J5.1 主链 → 子链 两跳", "PASS" if parsed.sub_chain_service() is None else "FAIL")
    except Exception:
        rec("J5.1 主链 → 子链 两跳", "FAIL", traceback.format_exc().splitlines()[-1])

    def looping(url):
        target = sub_ep if url.startswith(main_ep) else main_ep
        return wrap(dict(doc(), service=[{
            "id": DID + "#s", "type": "DIDSubResolver", "protocol": 2, "serviceEndpoint": target}]))

    try:
        B.resolve_bid_chain(main_ep, DID, fetcher=fetcher_for({main_ep: looping, sub_ep: looping}), max_hops=3)
        rec("J5.2 成环必须报错", "FAIL", "没有报错（可能在转圈）")
    except Exception as exc:
        hit = "cycle" in str(exc) or "环" in str(exc) or "hops" in str(exc)
        rec("J5.2 成环必须报错", "PASS" if hit else "INFO", str(exc)[-90:])


# --------------------------------------------------------- J6 §4.2.2 字段
def j6_field_endpoints(B):
    data_all = {"version": "1.0.0", "id": DID, "publicKey": [{"id": KEY_ID, "type": "Ed25519",
                                                             "controller": DID, "publicKeyHex": BARE_HEX}]}
    data_one = {"version": "1.0.0", "id": DID, "publicKey": {"id": KEY_ID, "type": "Ed25519",
                                                             "controller": DID, "publicKeyHex": BARE_HEX}}
    try:
        keys = B.resolve_public_keys("http://r.example", DID, fetcher=fetcher_for({"/public-keys": ok(data_all)}))
        rec("J6.1 全部公钥=数组", "PASS" if isinstance(keys, list) else "FAIL", "n=%d" % len(keys))
    except Exception:
        rec("J6.1 全部公钥=数组", "FAIL", traceback.format_exc().splitlines()[-1])
    calls = []
    try:
        B.resolve_public_keys("http://r.example", DID, key_id=KEY_ID,
                              fetcher=fetcher_for({"/public-keys/": ok(data_one), "/public-keys": ok(data_one)}))
        rec("J6.2 单键=对象", "PASS")
    except Exception:
        rec("J6.2 单键=对象", "FAIL", traceback.format_exc().splitlines()[-1])
    try:
        B.resolve_public_keys("http://r.example", DID, key_id=KEY_ID,
                              fetcher=fetcher_for({"/public-keys/": ok(data_all), "/public-keys": ok(data_all)}))
        rec("J6.3 单键回答却是数组必拒", "FAIL", "接受了数组")
    except Exception as exc:
        rec("J6.3 单键回答却是数组必拒", "PASS", type(exc).__name__)
    try:
        B.resolve_acsns("http://r.example", DID, fetcher=fetcher_for(
            {"/acsns": ok({"version": "1.0.0", "id": DID, "acsns": ["abcd", "1234"]})}))
        rec("J6.4 AC 号四位", "PASS")
    except Exception:
        rec("J6.4 AC 号四位", "FAIL", traceback.format_exc().splitlines()[-1])
    try:
        B.resolve_service("http://r.example", DID, DID + "#storage", fetcher=fetcher_for(
            {"/services?id=": ok({"version": "1.0.0", "id": DID,
                                  "service": {"id": DID + "#storage", "type": "DIDStorage",
                                              "serviceEndpoint": "https://did.bif.com"}})}))
        rec("J6.5 服务按 id 查询", "PASS")
    except Exception:
        rec("J6.5 服务按 id 查询", "FAIL", traceback.format_exc().splitlines()[-1])


# --------------------------------------- J7 官方 SDK 地址（三方对齐的落点）
def j7_official_sdk_address(B, subject):
    path = os.path.join(subject, "fixtures", "bid", "sdk_address.json")
    if not os.path.exists(path):
        rec("J7 官方 SDK 地址对齐", "SKIP", "被测仓未提供 fixtures/bid/sdk_address.json")
        return
    import hashlib
    fixture = json.load(open(path, encoding="utf-8"))
    key_hex = fixture.get("encPublicKey", "")
    raw, _prefix = B.strip_key_prefix(key_hex)
    derived = "did:bid:ef" + B.base58_encode(hashlib.sha256(raw).digest()[10:])
    rec("J7.1 协议规则复算 == 官方 SDK 地址", "PASS" if derived == fixture.get("address") else "FAIL",
        "%s vs %s" % (derived, fixture.get("address")))


def finish():
    out = sys.argv[1] if len(sys.argv) > 1 else "s11_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== J 组汇总 %s ===" % v)


if __name__ == "__main__":
    main()
