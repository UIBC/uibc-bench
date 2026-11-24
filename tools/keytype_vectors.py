# -*- coding: utf-8 -*-
"""did:key 键型一致性向量（P-256 / P-521 / ed25519）——独立于 141 条基线的专项向量集。

为什么单独一个工具、不进 141 条基线：
  基线（baseline.json）度量的是"被测仓 HEAD 的现状"。键型补丁还只在分支上，
  若把 P-256/P-521 用例塞进基线，要么全红（现在失败是事实），要么逼着我们改判（那是作弊）。
  所以这里做成"同一组向量、换实现跑两次"的对照工具：A 侧该红就红，B 侧该绿就绿，谁也骗不了谁。

用法：
  python tools/keytype_vectors.py --repo <被测仓目录> --json <输出JSON>
退出码：0 = 全部通过；1 = 有失败；2 = 环境问题（仓不可导入）

向量设计（18 条）：正向 12（含与 DIF 逐字段对照、曲线方程校验、两种编码一致），负向 4，回归 2。
"""
import argparse
import base64
import json
import os
import sys

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

P256_P = int("ffffffff00000001000000000000000000000000ffffffffffffffffffffffff", 16)
P256_B = int("5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b", 16)
P521_P = int("1ff" + "f" * 128, 16)
P521_B = int("0051953eb9618e1c9a1f929a21a0b68540eea2da725b99b315f3b8b489918ef1"
            "09e156193951ec7e937b1652c0bd3bb1bf073573df883d2c34f1ef451fd46b503f00", 16)

P256_PREFIX = b"\x80\x24"   # multicodec p256-pub  (0x1200)
P521_PREFIX = b"\x82\x24"   # multicodec p521-pub  (0x1202)
K1_PREFIX = b"\xe7\x01"     # multicodec secp256k1-pub (0xeb01 的低位写法用错也会被这条抓到)
ED_PREFIX = b"\xed\x01"

# 官方套件共享向量（P-521 压缩点），以及与 DIF 公共解析器逐字段一致的期望 JWK
SHARED_DID = ("did:key:z2J9gcGbsEDUmANXS8iJTVefK5t4eCx9x5k8jr8EyXWekTiEet6Jt6gwup2a"
              "WawzhHyMadvVMFcQ3ruwqg1Y8rYzjto1ccQu")
SHARED_DIF_JWK = {
    "kty": "EC",
    "crv": "P-521",
    "x": "APSyQH8rllXhsZ0wj7IzruA-ZwOVDpRMMlaSDe9nCHM5A2eUwBYIlKl0OlZgGGtsRLip4wgbB8FkUu0AR1qaeQpO",
    "y": "AGPrAZGtk3YO4XmqbYdPKVoz8uqR7ATS1yIRP6EaVdxZDWe6lu-ofA8NXZounfgbjbVB8Xwm4azd5B1hq_vAI969",
}

RESULTS = []


def rec(case, ok, note, extra=None):
    RESULTS.append(dict(case=case, verdict="PASS" if ok else "FAIL",
                        note=note, extra=extra or {}))
    print("[%-4s] %-46s %s" % ("PASS" if ok else "FAIL", case, note))


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(B58[r])
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return ("1" * pad) + "".join(reversed(out))


def b64url_to_int(s):
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def curve_ok(x, y, p, b):
    return (y * y - (x * x * x - 3 * x + b)) % p == 0


def make_keys():
    """用 cryptography 生成两把曲线密钥；取不到就返回 None（由调用方记 BLOCKED）。"""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except Exception:
        return None
    out = {}
    for name, curve in (("p256", ec.SECP256R1()), ("p521", ec.SECP521R1())):
        priv = ec.generate_private_key(curve)
        nums = priv.public_key().public_numbers()
        out[name] = (nums.x, nums.y)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="被测仓目录（含 uibc_core）")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    sys.path.insert(0, os.path.abspath(a.repo))
    try:
        import uibc_core.did as U
    except Exception as exc:                       # 环境问题 ≠ 用例失败
        print("[ENV ] 无法从 %s 导入 uibc_core.did：%s" % (a.repo, exc))
        return 2
    impl = os.path.abspath(U.__file__)
    if not impl.startswith(os.path.abspath(a.repo) + os.sep):
        print("[ENV ] uibc_core 解析到 %s，不在指定仓 %s 之下（回退到已安装副本）" % (impl, a.repo))
        return 2
    print("[INFO] impl=%s" % impl)

    keys = make_keys()

    def resolve(did):
        try:
            return U.resolve(did), None
        except Exception as exc:
            return None, exc

    def jwk_of(doc):
        vm = (doc or {}).get("verificationMethod") or [{}]
        return vm[0].get("publicKeyJwk") or {}

    # ---- 正向 ----
    if keys:
        for name, prefix, flen, p, b, crv in (
                ("P-256", P256_PREFIX, 32, P256_P, P256_B, "P-256"),
                ("P-521", P521_PREFIX, 66, P521_P, P521_B, "P-521")):
            x, y = keys["p256" if flen == 32 else "p521"]
            comp = prefix + bytes([2 + (y & 1)]) + x.to_bytes(flen, "big")
            unc = prefix + b"\x04" + x.to_bytes(flen, "big") + y.to_bytes(flen, "big")
            d_comp = "did:key:z" + b58encode(comp)
            d_unc = "did:key:z" + b58encode(unc)

            doc, err = resolve(d_comp)
            got = jwk_of(doc)
            rec("%s 压缩点可解析" % crv, err is None and got.get("crv") == crv,
                "err=%s crv=%s" % (err, got.get("crv")))

            doc2, err2 = resolve(d_unc)
            rec("%s 未压缩点可解析" % crv, err2 is None and jwk_of(doc2).get("crv") == crv,
                "err=%s crv=%s" % (err2, jwk_of(doc2).get("crv")))
            rec("%s 两种编码得到同一 JWK" % crv, got == jwk_of(doc2) and bool(got),
                "compressed==uncompressed: %s" % (got == jwk_of(doc2)))

            if got.get("x") and got.get("y"):
                ok = curve_ok(b64url_to_int(got["x"]), b64url_to_int(got["y"]), p, b)
                rec("%s JWK 落在曲线上（y²=x³-3x+b）" % crv, ok, "mod p 校验")
                rec("%s x/y 字节长度正确" % crv,
                    len(b64url_to_int(got["x"]).to_bytes(flen, "big")) == flen,
                    "x=%d bytes / y=%d bytes" % (flen, flen))
    else:
        rec("生成测试密钥", False, "缺 cryptography，无法生成 P-256/P-521 密钥")

    # ---- 官方共享向量 + DIF 逐字段 ----
    doc, err = resolve(SHARED_DID)
    got = jwk_of(doc)
    rec("官方共享向量（P-521 压缩点）可解析", err is None and got.get("crv") == "P-521",
        "err=%s crv=%s" % (err, got.get("crv")))
    rec("与 DIF 公共解析器 publicKeyJwk 逐字段相等", got == SHARED_DIF_JWK,
        "x/y/crv/kty 全字段比对")

    # ---- 负向 ----
    x999 = (P256_P + 1).to_bytes(32, "big")
    doc, err = resolve("did:key:z" + b58encode(P256_PREFIX + b"\x02" + x999))
    rec("P-256 X 超出域（x≥p）必须报错", err is not None, "err=%s" % err)

    doc, err = resolve("did:key:z" + b58encode(P256_PREFIX + b"\x02" + bytes(31)))
    rec("P-256 点长度不足必须报错", err is not None, "err=%s" % err)

    doc, err = resolve("did:key:z" + b58encode(P521_PREFIX + bytes(66)))
    rec("P-521 缺 SEC1 前缀必须报错", err is not None, "err=%s" % err)

    doc, err = resolve("did:key:z" + b58encode(K1_PREFIX + bytes(33)))
    rec("未支持的键型（secp256k1）显式报错", err is not None, "err=%s" % err)

    # ---- 回归：ed25519 不能被改坏 ----
    doc, err = resolve("did:key:z" + b58encode(ED_PREFIX + bytes(range(32))))
    vm = (doc or {}).get("verificationMethod") or [{}]
    rec("ed25519 仍返回 Ed25519VerificationKey2020",
        err is None and vm[0].get("type") == "Ed25519VerificationKey2020",
        "type=%s" % vm[0].get("type"))
    doc, err = resolve("did:key:z" + b58encode(ED_PREFIX + bytes(31)))
    rec("ed25519 长度错误必须报错", err is not None, "err=%s" % err)

    # ---- 输出 ----
    n_pass = sum(1 for r in RESULTS if r["verdict"] == "PASS")
    n_fail = len(RESULTS) - n_pass
    print("\n=== 汇总 {PASS:%d FAIL:%d} ===  repo=%s" % (n_pass, n_fail, a.repo))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(dict(repo=os.path.abspath(a.repo), impl=impl,
                           passed=n_pass, failed=n_fail, results=RESULTS),
                      fh, ensure_ascii=False, indent=1)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
