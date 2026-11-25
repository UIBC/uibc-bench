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
    j8_trusted_resolution(B, subject)
    j9_vector_pack(B, subject)
    j10_address_derivation(subject)
    j11_binary_codec(subject)
    j12_demo_and_layout(subject)
    j13_bit_flip_and_placement(subject)
    return finish()


def j13_bit_flip_and_placement(subject):
    """A decoder can be "implemented" and still not notice that it was re-arranged.

    J11 shows the layer runs backwards. J13 asks the sharper question: for every
    single bit of a valid message, does something happen? The subject must show
    which bits are dead (the header's reserved ones) and that a *structural* edit
    - moving a field to another container - is refused rather than decoded into
    the same document.
    """
    import json
    import subprocess

    tool = os.path.join(subject, "tools", "mutate_bid_binary.py")
    if not os.path.exists(tool):
        rec("J13 逐位翻转与容器归属", "SKIP", "被测仓未提供 tools/mutate_bid_binary.py")
        return
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    res = subprocess.run([sys.executable, tool, "--json"], cwd=subject, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env, timeout=240)
    if res.returncode != 0:
        rec("J13.1 探针能跑并输出机读结果", "FAIL",
            "rc=%d %r" % (res.returncode, (res.stderr or "")[-120:]))
        return
    try:
        data = json.loads(res.stdout)
    except Exception as exc:                                  # noqa: BLE001
        rec("J13.1 探针能跑并输出机读结果", "FAIL", "not JSON: %s" % exc)
        return
    rec("J13.1 探针能跑并输出机读结果", "PASS",
        "%d bytes, %d bits" % (data.get("message_bytes", 0), data["total"]))

    total = data["total"]
    covered = data["rejected"] + data["changed"] + len(data["blind"])
    rec("J13.2 每一位都被归类且只归一类",
        "PASS" if covered == total and total == data["message_bytes"] * 8 else "FAIL",
        "rejected=%d changed=%d blind=%d total=%d"
        % (data["rejected"], data["changed"], len(data["blind"]), total))

    # the blind set must be exactly the header's reserved bits, derived from the
    # subject's own constants rather than taken from the subject's own report
    try:
        from uibc_core.bid_binary import _FLAG_BITS, _OPCODE_SHIFT
        used = {bit for _n, bit in _FLAG_BITS} | set(range(_OPCODE_SHIFT, _OPCODE_SHIFT + 4))
        unnamed = {8 + (15 - bit) for bit in range(16) if bit not in used}
        expected = unnamed | set(range(24, 32))
    except Exception:                                          # noqa: BLE001
        expected = None
    if expected is None:
        rec("J13.3 盲位恰好是头部保留位", "SKIP", "被测仓未暴露 _FLAG_BITS/_OPCODE_SHIFT")
    else:
        rec("J13.3 盲位恰好是头部保留位",
            "PASS" if set(data["blind"]) == expected else "FAIL",
            "blind=%d expected=%d" % (len(data["blind"]), len(expected)))

    body_blind = [b for b in data["blind"] if b // 8 >= 16]
    rec("J13.4 报文正文一位都不盲", "PASS" if body_blind == [] else "FAIL",
        "body_blind=%r" % (body_blind[:5],))

    # structural edit: the same leaves under a different container
    try:
        from uibc_core import bid_binary as BB
    except Exception:                                          # noqa: BLE001
        rec("J13.5 改容器必须被拒", "SKIP", "被测仓未提供 uibc_core.bid_binary")
        return
    moved = [BB.Unit(0x2100, BB.build_unit(0x2111, b"did:bid:efX#key-1"))]
    try:
        BB.decode_document(moved)
        refused, why = False, "decoded without complaint"
    except ValueError as exc:
        refused, why = True, str(exc)[:90]
    rec("J13.5 把 publicKey 改成文档包装层必须被拒", "PASS" if refused else "FAIL", why)

    try:
        lenient = BB.decode_document(moved, strict_placement=False)
        booked = "publicKey.id" in getattr(lenient, "misplaced", {})
    except TypeError:
        booked = False
    rec("J13.6 宽容读法把错位记账而不是丢字段", "PASS" if booked else "FAIL",
        "strict 默认拒收，strict_placement=False 时进 misplaced")

    # the documented message size must match the bytes actually produced
    rec("J13.7 示范报文 196 字节与文档一致",
        "PASS" if data["message_bytes"] == 196 else "FAIL",
        "actual=%d documented=196" % data["message_bytes"])


# ------------------------------------ J10 地址推导：50 条官方样本必须逐字节复现
RFC_RAW_PUBLIC = "d308378e6b5ff0c2b4be3da741538004525d6388e5df32deb79e2b0c02f133c7"
RFC_SUFFIX = "38VPR182Y4uTkq32fykXjbKBPdQZutH"


def j10_address_derivation(subject):
    """Is the address rule a rule, or a claim? 50 SDK-produced addresses must re-derive.

    This group exists because the subject once published "addresses can be checked
    but not re-derived" - which was true only under the wrong Base58 alphabet. Here
    the subject has to reproduce all 50 official samples byte for byte, and has to
    keep the two variants apart (RFC-003's version byte vs the shipped SDK's omission).
    """
    try:
        from uibc_core import bid_address as AD
    except Exception:
        rec("J10 地址推导", "SKIP", "被测仓未提供 uibc_core.bid_address")
        return
    path = os.path.join(subject, "fixtures", "bid", "sdk_address_batch.json")
    if not os.path.exists(path):
        rec("J10 地址推导", "SKIP", "被测仓未提供 fixtures/bid/sdk_address_batch.json")
        return
    samples = json.load(open(path, encoding="utf-8"))
    bad = []
    for s in samples:
        got = AD.derive_did(s["encPublicKey"], "Ed25519", version_byte=False)["did"]
        if got != s["address"]:
            bad.append((s["address"], got))
    note = "%d/%d" % (len(samples) - len(bad), len(samples))
    if bad:
        note += " first=%r" % (bad[0],)
    rec("J10.1 50 条官方地址逐字节复现", "PASS" if not bad else "FAIL", note)

    hits = sum(1 for s in samples
               if AD.derive_did(s["encPublicKey"], "Ed25519", version_byte=True)["did"] == s["address"])
    rec("J10.2 带版本字节是另一个变体（0 命中）", "PASS" if hits == 0 else "FAIL", "hits=%d" % hits)

    rfc = AD.derive_did("b0" + RFC_RAW_PUBLIC, "Ed25519", version_byte=True)
    rec("J10.3 RFC-003 例题后缀复现", "PASS" if rfc["suffix"] == RFC_SUFFIX else "FAIL", rfc["suffix"])

    wrong = AD.address_matches("b0" + "11" * 32,
                               AD.derive_did("b0" + RFC_RAW_PUBLIC, version_byte=True)["did"])
    rec("J10.4 换一把公钥就必须不匹配", "PASS" if wrong is False else "FAIL", "matches=%r" % wrong)

    # The four-letter claim is a claim about the alphabet itself; check it directly.
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(AD.SDK_BASE58_ALPHABET, AD.BITCOIN_BASE58_ALPHABET)) if a != b]
    rec("J10.5 两张字母表只差 4 个大小写", "PASS" if diffs == [(10, "b", "B"), (27, "u", "U"),
                                                            (34, "B", "b"), (52, "U", "u")] else "FAIL",
        "diffs=%r" % (diffs,))


# ----------------------------------------- J9 被测仓自带的向量集，由外部脚本复跑
def j9_vector_pack(B, subject):
    """The subject's own vector pack must be runnable by a stranger, and must be green.

    This is the weakest-looking case and the most useful one: it checks that the
    pack is data (a stranger can run it), that the subject's checker exits 0, and
    that the run prints the full pass count - not "0 failures" with nothing run.
    """
    checker = os.path.join(subject, "tools", "check_bid_vectors.py")
    pack = os.path.join(subject, "vectors", "bid-resolution-v1.json")
    if not (os.path.exists(checker) and os.path.exists(pack)):
        rec("J9 向量集可被外人复跑", "SKIP", "被测仓未提供 tools/check_bid_vectors.py + vectors/")
        return
    total = len(json.load(open(pack, encoding="utf-8"))["cases"])
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, checker, "--subject", subject], cwd=subject,
                          capture_output=True, text=True, timeout=180, env=env)
    last = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    ok = proc.returncode == 0 and ("%d/%d passed" % (total, total)) in last[0]
    rec("J9 向量集可被外人复跑（%d 条，全过）" % total, "PASS" if ok else "FAIL",
        "rc=%d %s" % (proc.returncode, last[0][:70]))


# ---------------------------------------- J8 §4.2.4 可信解析（不能相信解析服务的自述）
def j8_trusted_resolution(B, subject):
    """The resolver is untrusted by construction; `data.verify` is a claim, not proof."""
    import hashlib  # noqa: F401  (kept for symmetry with J7's imports)

    try:
        resolve = B.resolve_bid_trusted
    except AttributeError:
        rec("J8 §4.2.4 可信解析", "SKIP", "被测仓未提供 resolve_bid_trusted")
        return

    signed_path = os.path.join(subject, "fixtures", "bid", "signed_document.json")
    if not os.path.exists(signed_path):
        rec("J8 §4.2.4 可信解析", "SKIP", "被测仓未提供 fixtures/bid/signed_document.json")
        return
    doc = json.load(open(signed_path, encoding="utf-8"))
    did = doc["id"]

    def envelope(d, verify):
        return {"errorCode": 0, "data": {"version": "1.0.0", "verify": verify, "didDocument": d}}

    def fetch(answer):
        calls = []

        def f(url, timeout=10):
            calls.append(url)
            return answer
        f.calls = calls
        return f

    # J8.1 the request shape is the protocol's, not ours
    f = fetch(envelope(doc, True))
    r = resolve("http://r.example", did, fetcher=f)
    rec("J8.1 请求形如 {url}/{bid}?verify=true", "PASS" if f.calls == ["http://r.example/%s?verify=true" % did] else "FAIL",
        str(f.calls))
    rec("J8.2 服务自述 verify=true + 好签名 → trusted", "PASS" if r.trusted and r.fully_trusted else "FAIL",
        "trusted=%s fully=%s state=%s" % (r.trusted, r.fully_trusted, r.delegate_state))

    # J8.3 the lie: server says verified, document was altered after signing
    tampered = dict(doc, created="2021-06-24T09:10:10Z")
    r = resolve("http://r.example", did, fetcher=fetch(envelope(tampered, True)))
    rec("J8.3 服务说验过、文档却被动过 → 不信", "PASS" if (r.server_verify and not r.trusted) else "FAIL",
        "server_verify=%s trusted=%s reason=%s" % (r.server_verify, r.trusted, r.reason[:60]))

    # J8.4 a string "true" is not the Bool true
    try:
        resolve("http://r.example", did, fetcher=fetch({"errorCode": 0, "data": {"verify": "true", "didDocument": doc}}))
        rec("J8.4 verify='true' 字符串必须被拒", "FAIL", "accepted a string")
    except Exception as e:  # noqa: BLE001
        rec("J8.4 verify='true' 字符串必须被拒", "PASS", type(e).__name__)

    # J8.5 verify=false is an answer, not an exception
    r = resolve("http://r.example", did, fetcher=fetch(envelope(doc, False)))
    rec("J8.5 服务说 verify=false → 不信任但不抛异常", "PASS" if (not r.server_verify and not r.trusted) else "FAIL",
        r.reason[:60])

    # J8.6 delegateSign present without a resolver → visibly unchecked
    signer_seed = bytes([0x11] * 32)
    signer_id = "did:bid:efJgt44mNDewKK1VEN454R17cjso3mSG#key-1"
    signer_hex = "b06566" + B.ed_public_key(signer_seed).hex()
    d2 = json.loads(json.dumps(doc))
    d2["extension"] = dict(d2["extension"])
    d2["extension"]["delegateSign"] = {
        "signer": signer_id,
        "signatureValue": B.base58_encode(B.ed_sign(signer_seed, B.delegate_signing_bytes(d2)))}
    d2 = B.sign_bid_document(d2, bytes(range(32)), doc["authentication"][0])

    r = resolve("http://r.example", did, fetcher=fetch(envelope(d2, True)))
    rec("J8.6 delegateSign 无解析器可取签名者公钥 → unchecked 且不冒充全信",
        "PASS" if (r.delegate_state == "unchecked" and r.trusted and not r.fully_trusted) else "FAIL",
        "state=%s trusted=%s fully=%s" % (r.delegate_state, r.trusted, r.fully_trusted))

    r = resolve("http://r.example", did, fetcher=fetch(envelope(d2, True)),
                delegate_key_resolver=lambda kid: signer_hex)
    rec("J8.7 delegateSign 给出签名者公钥 → verified", "PASS" if r.delegate_state == "verified" else "FAIL",
        "state=%s reason=%s" % (r.delegate_state, r.reason[:40]))

    wrong = "b0" + B.ed_public_key(bytes([0x22] * 32)).hex()
    r = resolve("http://r.example", did, fetcher=fetch(envelope(d2, True)),
                delegate_key_resolver=lambda kid: wrong)
    rec("J8.8 delegateSign 用错公钥 → invalid 且整体不信任", "PASS" if r.delegate_state == "invalid" and not r.trusted else "FAIL",
        "state=%s trusted=%s" % (r.delegate_state, r.trusted))

    # J8.9 the subject ships a runnable demo; run it, don't just read it
    demo = os.path.join(subject, "tools", "demo_bid_trusted.py")
    if not os.path.exists(demo):
        rec("J8.9 跑被测仓的可信解析 demo", "SKIP", "未提供 tools/demo_bid_trusted.py")
        return
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, demo], cwd=subject, capture_output=True, text=True, timeout=120, env=env)
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    rec("J8.9 跑被测仓的可信解析 demo", "PASS" if proc.returncode == 0 else "FAIL",
        "rc=%d tail=%s" % (proc.returncode, " | ".join(tail)))


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
        _j34_sm2(B)
    except Exception:
        rec("J3 签名闭环", "FAIL", traceback.format_exc().splitlines()[-1])

# ------------------------------------ J11 二进制编解码：只有解码器没法被反驳
def j11_binary_codec(subject):
    """Can the subject's §4.3 layer be run backwards, and are its guesses switches?

    "We implemented the binary protocol" is unverifiable when the only evidence is
    that a decoder returned a dict. These conditions make the subject produce the
    bytes itself, refuse its own invented IDs, and prove that flipping an
    assumption changes what it reads.
    """
    try:
        from uibc_core import bid_binary as BB
    except Exception:
        rec("J11 二进制编解码", "SKIP", "被测仓未提供 uibc_core.bid_binary")
        return
    for name in ("encode_units", "encode_message", "encode_document", "ASSUMPTIONS"):
        if not hasattr(BB, name):
            rec("J11 二进制编解码", "SKIP", "仪器不全：缺 %s" % name)
            return

    # J11.1 order is information at the unit layer - a sorter would pass a weaker test
    units = [BB.Unit(0x2102, b"did:bid:ef00"), BB.Unit(0x2101, b"1.0.0")]
    raw = BB.encode_units(units)
    back = BB.parse_units(raw)
    rec("J11.1 单元层逐字节往返（含非升序）",
        "PASS" if back == units and BB.encode_units(back) == raw else "FAIL",
        "raw=%s" % raw.hex())

    # J11.2 header + option + body must reproduce the same bytes
    msg = BB.encode_message([BB.Unit(0x2102, b"did:bid:ef00")], 0x01020304,
                            option_bytes=b"\x01\x00\x00\x00")
    hdr = BB.parse_header(msg)
    again = BB.encode_message([BB.Unit(0x2102, b"did:bid:ef00")], hdr.transaction_id,
                              option_bytes=hdr.option_bytes)
    rec("J11.2 报文层逐字节往返（含 option）",
        "PASS" if again == msg and hdr.header_length == 20 else "FAIL",
        "len=%d hdr=%d" % (len(msg), hdr.header_length))

    # J11.3 the flag order assumption must actually be a parameter
    flag_msg = BB.encode_message([], 7, flags={"qr": 1})
    try:
        msb = BB.parse_header(flag_msg, flag_bit_order="msb").flags
        lsb = BB.parse_header(flag_msg, flag_bit_order="lsb").flags
    except TypeError:
        rec("J11.3 flag 位序是参数而非注释", "FAIL", "parse_header 不接受 flag_bit_order")
        msb = lsb = None
    if msb is not None:
        rec("J11.3 flag 位序是参数而非注释",
            "PASS" if msb != lsb and msb.get("qr") == 1 and lsb.get("qr") == 0 else "FAIL",
            "msb=%r lsb=%r" % (msb, lsb))

    # J11.4 a width that disagrees with the bytes must raise, not misread
    wrong = None
    try:
        BB.decode_document([BB.Unit(0x3000, BB.build_unit(0x3200, b"\x00\x00\x00\x05"))],
                           integer_widths={"long": 8})
    except ValueError as exc:
        wrong = str(exc)
    # the reason matters: raising because the field sits in the wrong container
    # would pass this condition without testing the width at all
    ok = bool(wrong) and "declared" in wrong and "carries" in wrong
    rec("J11.4 宽度与字节不符必须 raise", "PASS" if ok else "FAIL",
        (wrong or "没有 raise")[:80])

    # J11.5 an unknown path cannot be invented into a unit ID
    refused = False
    try:
        BB.encode_document({"publicKey": {"madeUp": "x"}})
    except ValueError:
        refused = True
    rec("J11.5 不存在的字段路径不许自造 unit ID", "PASS" if refused else "FAIL")

    # J11.6 hostile bytes: 500 random strings, ValueError only
    import random as _r
    rng = _r.Random(2026)
    bad = []
    for _ in range(500):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 48)))
        try:
            BB.decode_message(data)
        except ValueError:
            pass
        except Exception as exc:
            bad.append(type(exc).__name__)
    rec("J11.6 随机字节只允许 ValueError", "PASS" if not bad else "FAIL",
        "other=%s" % (sorted(set(bad))[:4],))

    # J11.7 the registry itself: six entries, each naming a gap and a choice
    reg = BB.ASSUMPTIONS
    wanted = {"flag_bit_order", "integer_widths", "acsns_spelling",
              "bid_document_collision", "fragment_reassembly", "signature_unit_ids"}
    ok = (set(reg) == wanted and
          all(item.get("gap") and item.get("choice") and item.get("status") for item in reg.values()))
    rec("J11.7 六条推断都登记了缺口与处置", "PASS" if ok else "FAIL",
        "keys=%s" % (sorted(reg),))



# ------------------------------------ J12 可运行 demo 与生成式图
def j12_demo_and_layout(subject):
    """Tests can agree with code and still tell a stranger nothing.

    J12 asks for the two artefacts that let an outsider check the layer without
    reading the source: a demo that runs and says so, and a diagram that is
    regenerated from the module rather than drawn once by hand.
    """
    import subprocess

    demo = os.path.join(subject, "tools", "demo_bid_binary.py")
    if not os.path.exists(demo):
        rec("J12 demo 与布局图", "SKIP", "被测仓未提供 tools/demo_bid_binary.py")
        return
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"

    def run(args):
        return subprocess.run([sys.executable] + args, cwd=subject, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=180)

    res = run([demo, "--flip"])
    ok = (res.returncode == 0 and "ALL OK" in (res.stdout or "")
          and "HARD-FAIL" not in (res.stdout or ""))
    rec("J12.1 demo 跑得起来且自报 ALL OK", "PASS" if ok else "FAIL",
        "rc=%d tail=%r" % (res.returncode, (res.stdout or res.stderr or "")[-60:]))
    if not ok:
        return
    two = ("msb=" in res.stdout and "lsb=" in res.stdout)
    rec("J12.2 demo 同时展示两种读法", "PASS" if two else "FAIL")

    render = os.path.join(subject, "tools", "render_bid_binary_layout.py")
    doc = os.path.join(subject, "docs", "BID-BINARY-LAYOUT.svg")
    if not (os.path.exists(render) and os.path.exists(doc)):
        rec("J12.3 图由模块常量生成且与仓库那份一致", "SKIP", "缺 render 脚本或 SVG")
        return
    r2 = run([render, "--stdout"])
    fresh = r2.stdout or ""
    committed = open(doc, encoding="utf-8").read()
    rec("J12.3 图由模块常量生成且与仓库那份一致",
        "PASS" if r2.returncode == 0 and fresh == committed else "FAIL",
        "fresh=%dB committed=%dB" % (len(fresh), len(committed)))




def _j34_sm2(B):
    """§5 also allows SM2. Checked here against the subject, not against our own copy:
    the standard's example (GM/T 0003.5 Annex A) is used to build a document and the
    subject must verify it and reject a tampered copy."""
    try:
        from uibc_core import sm2 as S
    except Exception:
        rec("J3.4 SM2 验签（GM/T 0003.5 附录A）", "SKIP", "被测仓未提供 uibc_core.sm2")
        return
    d = 0x3945208F7B2144B13F36E38AC6D39F95889393692860B51A42FB81EF4DF7C5B8
    px = 0x09F9DF311E5421A150DD7D161E4BC5C672179FAD1833FC076BB08FF356F35020
    py = 0xCCEA490CE26775A52DC6EA718CC1AA600AED05FBF35E084A6632F6072DA9AD13
    try:
        body = px.to_bytes(32, "big") + py.to_bytes(32, "big")
        base = doc()
        unsigned = {k: v for k, v in base.items() if k != "proof"}
        unsigned["publicKey"] = [dict(base["publicKey"][0], publicKeyHex="b06566" + body.hex(), type="SM2")]
        r, s = S.sign(d, B.signing_bytes(unsigned), px=px, py=py)
        signed = dict(unsigned)
        signed["proof"] = {"creator": KEY_ID,
                           "signatureValue": B.base58_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
                           "type": "SM2Signature"}
        ok, reason = B.verify_bid_document(signed, DID)
        rec("J3.4a SM2 文档可验（并写明所用区分标识）", "PASS" if ok and "SM2" in reason else "FAIL", reason[:70])
        bad = dict(signed, created="2021-06-24T09:10:10Z")
        ok2, reason2 = B.verify_bid_document(bad, DID)
        rec("J3.4b SM2 签名后改动必须被拒", "PASS" if ok2 is False else "FAIL", reason2[:60])
    except Exception:
        rec("J3.4 SM2 验签（GM/T 0003.5 附录A）", "FAIL", traceback.format_exc().splitlines()[-1])



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


# --------------------------------------- J7 官方 SDK 地址（能校验什么、不能反推什么）
def j7_official_sdk_address(B, subject):
    """The SDK's addresses are evidence for one property, not for a derivation.

    History: this group first asserted "protocol rule reproduces the SDK address",
    on a single fixture. Over 50 seeds only 7 agree - the SDK's base58 codec is not
    the Bitcoin one - so the derivation claim was withdrawn upstream. What is
    checked here is the property that survived: the subject ACCEPTS every address
    the official implementation emits. The divergence is reported as INFO, because
    it is a fact about the SDK, not a defect in the subject.
    """
    import hashlib
    from uibc_core import did_cn as DIDCN
    batch_path = os.path.join(subject, "fixtures", "bid", "sdk_address_batch.json")
    single_path = os.path.join(subject, "fixtures", "bid", "sdk_address.json")

    if os.path.exists(batch_path):
        rows = json.load(open(batch_path, encoding="utf-8"))
        bad = []
        for row in rows:
            suffix = row["address"].split(":", 2)[-1]
            try:
                d = DIDCN._check_bid(suffix)
            except Exception as e:  # noqa: BLE001 - any rejection is the finding
                bad.append((row["address"], repr(e)))
                continue
            if not (d["shape"] == "main" and d["crypto"] == "Ed25519" and d["encoding"] == "base58"):
                bad.append((row["address"], d))
        rec("J7.1 官方 SDK 产出的 %d 条地址全部被接受（主链/Ed25519/base58）" % len(rows),
            "PASS" if not bad else "FAIL", "rejected: %s" % (bad[:2] if bad else "none"))

        lengths = {len(r["address"].split(":", 2)[-1]) for r in rows}
        in_range = all(22 <= n <= 42 for n in lengths)
        distinct = len({r["address"] for r in rows}) == len({r["encPublicKey"] for r in rows}) == len(rows)
        rec("J7.2 suffix 长度落在协议 (22,42) 且键/地址互不重复", "PASS" if in_range and distinct else "FAIL",
            "lengths=%s distinct=%s" % (sorted(lengths), distinct))

        matches = 0
        for row in rows:
            raw, _p = B.strip_key_prefix(row["encPublicKey"])
            derived = "did:bid:ef" + B.base58_encode(hashlib.sha256(raw).digest()[10:])
            matches += derived == row["address"]
        rec("J7.3 协议规则复算（Bitcoin base58）能复现的样本数", "INFO",
            "%d/%d 一致 —— SDK 的 base58 编解码非 Bitcoin 字母表，地址可校验但不可反推"
            % (matches, len(rows)))
        return

    if os.path.exists(single_path):
        fixture = json.load(open(single_path, encoding="utf-8"))
        suffix = fixture["address"].split(":", 2)[-1]
        d = DIDCN._check_bid(suffix)
        rec("J7.1 单条官方 SDK 地址被接受", "PASS" if d["shape"] == "main" else "FAIL", str(d))
        rec("J7.2 可复算性", "INFO", "只有单样本；复算主张需 ≥50 样本，被测仓未提供 sdk_address_batch.json")
        return

    rec("J7 官方 SDK 地址", "SKIP", "被测仓未提供 fixtures/bid/sdk_address.json")


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
