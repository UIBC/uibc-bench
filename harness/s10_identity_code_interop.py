# -*- coding: utf-8 -*-
"""身份码两套体系互操作：同一串码，两个读取器各自表态，且互不冒充。

参与方：
  文档 1  GB/Z 185.2-2026（八段，无校验码）        → uibc_core.agent_identity_code
  文档 2  ACPs-spec-AIC-v02.02（十段，四字符 CRC） → uibc_core.acps_identity_code
  第三方  aipmc-basic 0.0.2（Rust，只认十段）       → 其结果取 2026-11-24 实跑记录，本组不重编

判定：每个读取器只认自己那份文档；对方形状必须被拒且给出理由。
      I7–I14：不带盐时校验码一律不判，两条路径都到不了 VERIFIED（形状判与值判分开）。
      I15–I18：给定私盐后必须给出值判（VERIFIED / INVALID），并证明结果与段序无关。

边界：`aipmc-basic` 那半边的结论来自 2026-11-24 的实跑日志
      （uibc-core `docs/THIRD-PARTY-DIVERGENCE.md`），本组不重跑 Rust，
      因此第三方列记 REFERENCE 而不是 PASS——不把引用当复算。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
REPO = os.environ.get("UIBC_SUBJECT") or os.path.join(KIT, "uibc-core-public")
RESULTS = []

# 来源守卫：必须证明读的是 REPO 里的代码，否则宁可不测。
# 2026-11-24 在云主机上踩过一次：REPO 指向不存在的目录时，sys.path 会退到
# 机器上已安装的同名包，测试照跑、结论照出，但测的根本不是指定的那份代码。
if not os.path.isdir(REPO):
    sys.exit("[ABORT] 被测路径不存在：%s（不会被当成通过，也不会静默退回已安装包）" % REPO)
sys.path.insert(0, REPO)
import uibc_core  # noqa: E402
_SRC = os.path.abspath(uibc_core.__file__)
if not _SRC.startswith(os.path.abspath(REPO) + os.sep):
    sys.exit("[ABORT] uibc_core 实际来自 %s，不在被测路径 %s 之下；拒绝用别人的代码出结论" % (_SRC, REPO))
from uibc_core.agent_identity_code import parse_agent_code, detect_profile  # noqa: E402
from uibc_core.acps_identity_code import read_acps_code, verify_acps_code  # noqa: E402


def rec(case, verdict, note="", extra=None):
    RESULTS.append(dict(case=case, verdict=verdict, note=note, extra=extra or {}))
    print("[%-9s] %-30s %s" % (verdict, case, note))


EIGHT = "1.2.156.3088.1.360.360.000000001"                    # 国标八段形态
TEN = "1.2.156.3088.1.0001.00001.ABC123.000001.176F"          # ACPs 十段，crate 示例
TEN_ALT = "1.2.156.3088.1.1.34C2.478BDF.3GF546.0JU4"          # AIC §3 段序 + 文档自带算例
TEN_CRATE = "1.2.156.1234.1.1.34C2.478BDF.3GF546.0H9T"        # aipmc-basic crate 里的示例（前缀不同）
TEN_BADCRC = "1.2.156.3088.1.0001.00001.ABC123.000001.9999"   # 故意错校验码
SPEC_SALT = bytes.fromhex("1234")                              # ACPs 文档公开的那个示例盐
TEN_OVW = "1.2.156.3088.1.34C2.478BDF.3GF546.1.0SEN"          # overview §5.2 段序（版本在实例后）


def main():
    # I7 八段读者见到十段 → 必须拒，且说清是另一份文件
    r = parse_agent_code(TEN)
    ok = r["state"] == "INVALID" and ("ten arcs" in r["detail"] or "aip-acps" in r["detail"])
    rec("I7 八段读者拒十段", "PASS" if ok else "FAIL", r["state"], {"detail": r["detail"][:120]})

    # I8 十段读者见到八段 → 必须拒，并点名"该去另一个读取器"
    r = read_acps_code(EIGHT)
    ok = r["state"] == "INVALID" and "different reader" in r["detail"]
    rec("I8 十段读者拒八段", "PASS" if ok else "FAIL", r["state"], {"detail": r["detail"][:120]})

    # I9 十段读者读十段 → INCONCLUSIVE，且校验码标未验证
    r = read_acps_code(TEN)
    ok = r["state"] == "INCONCLUSIVE" and "checksum: not checked" in r["detail"]
    rec("I9 十段自读且不判校验码", "PASS" if ok else "FAIL", r["state"], {"scope": r["scope"][:100]})

    # I10 错校验码仍不判 → 任何"有效/无效"的断言都算失败
    r = read_acps_code(TEN_BADCRC)
    ok = r["state"] == "INCONCLUSIVE"
    rec("I10 错校验码不判", "PASS" if ok else "FAIL",
        "state=%s（盐未公开，拒判）" % r["state"])

    # I11 crate 示例的前缀不被写死
    r = read_acps_code(TEN_CRATE)
    ok = r["state"] == "INCONCLUSIVE" and "1.2.156.1234" in r["detail"]
    rec("I11 示例前缀不被写死", "PASS" if ok else "FAIL", r["detail"][:80])

    # I12 两条路径都没有 VERIFIED
    states = [parse_agent_code(x)["state"] for x in (EIGHT, TEN, TEN_BADCRC)]
    states += [read_acps_code(x)["state"] for x in (EIGHT, TEN, TEN_BADCRC)]
    ok = "VERIFIED" not in states
    rec("I12 无 VERIFIED 出口", "PASS" if ok else "FAIL", "states=%s" % sorted(set(states)))

    # I13 profile 标注，不猜
    ok = detect_profile(EIGHT) == "gbz185.2" and detect_profile(TEN) == "aip-acps"
    rec("I13 profile 标注", "PASS" if ok else "FAIL",
        "%s / %s" % (detect_profile(EIGHT), detect_profile(TEN)))

    # I14 第三方那个半边的记录（引用，不冒充复算）
    rec("I14 第三方实跑记录", "REFERENCE",
        "aipmc-basic 0.0.2 于 2026-11-24 实跑：十段 ACCEPT（默认盐校验通过）、八段 REJECT；"
        "错误 CRC 仍 ACCEPT（其 parse 不验校验码）。日志见 uibc-core docs/THIRD-PARTY-DIVERGENCE.md")

    # I15 给定示例盐 → 必须判 VERIFIED，且带可复算 evidence
    r = verify_acps_code(TEN_ALT, SPEC_SALT)
    ev = r.get("evidence") or []
    first = ev[0] if ev else {}
    ok = (r["state"] == "VERIFIED" and str(first.get("id", "")).startswith("acps-arc10:")
          and str(first.get("digest", "")).startswith("sha256:"))
    rec("I15 带盐判通过", "PASS" if ok else "FAIL",
        "%s %s" % (r["state"], first.get("id", "")))

    # I16 段序无关：overview §5.2 的另一种段序同样验过（这两串的校验码都是自洽的）
    r = verify_acps_code(TEN_OVW, SPEC_SALT)
    ok = r["state"] == "VERIFIED"
    rec("I16 段序无关仍判通过", "PASS" if ok else "FAIL",
        "%s（版本段在实例之后，校验码照样对）" % r["state"])

    # I17 改末位 → 必须 INVALID，不能含糊
    r = verify_acps_code(TEN_ALT[:-1] + ("A" if TEN_ALT[-1] != "A" else "B"), SPEC_SALT)
    ok = r["state"] == "INVALID" and "checksum" in r["detail"].lower()
    rec("I17 带盐判篡改", "PASS" if ok else "FAIL", r["state"])

    # I18 不给盐 / 盐不足 2 字节 → 只能 INCONCLUSIVE，且明写"校验码未检查"
    a = verify_acps_code(TEN_ALT, None)
    b = verify_acps_code(TEN_ALT, b"\x12")
    ok = (a["state"] == "INCONCLUSIVE" and "NOT checked" in a["detail"]
          and b["state"] == "INCONCLUSIVE")
    rec("I18 无盐或短盐不判", "PASS" if ok else "FAIL",
        "%s / %s" % (a["state"], b["state"]))

    out = sys.argv[1] if len(sys.argv) > 1 else "s10_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    v = {}
    for r in RESULTS:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    print("=== 汇总 %s ===" % v)


if __name__ == "__main__":
    main()
