# -*- coding: utf-8 -*-
"""交付件随身性检查（handoff_bundle）：把「作者机上的绿」翻译成「外人手上的绿」。

起因（缺陷 #51）：51 号收尾时拿两个交付包在干净目录里从零解包复跑，
总闸直接 RED（硬伤 150 / 缺失 174）。原因是审计的解析根集合（roots）一直
只存在于作者机上——审查目录、测试台、以及 D 盘的标准原件目录。
交付物没有声明根集合，外人手上自然一条都解析不到。

本工具不重新扫描文档（避免两处正则各写一套而慢慢跑偏），
它吃 package_audit.py 产出的 JSON，按「该件有没有随包」重新分类：

  covered_docs   已在审查包（精简包/全量归档）里
  covered_kit    已在测试台分发包里
  required       不在任何包里，体积可控 → 必须随补件包
  hash_only      不在任何包里，体积过大 → 只随哈希与索取说明
  nonexistent    作者机上也不存在（事实性缺件 / 阻塞项）

用法（两步，先审计再分类）：
    python tools/package_audit.py --dir <审查目录> --roots <作者根集合> --json audit.json
    python tools/handoff_bundle.py --audit audit.json --dir <审查目录>
        --kit-zip <测试台分发 zip> --docs-zip <精简包 zip>
        --json handoff_requirements.json --md handoff_requirements.md
        [--max-mb 25] [--copy-to <补件目录>]

判定：--exit-on-required 打开时，若有 required 且未复制 → 退出码 1。
"""
import argparse
import io
import json
import os
import shutil
import zipfile


def rel_in_zip(zpath, abspath):
    """（保留占位，实际未用：包内路径匹配统一走 in_any_zip 的尾部匹配。）"""
    return False


_ZCACHE = {}


def zset(zpath):
    if zpath not in _ZCACHE:
        try:
            _ZCACHE[zpath] = set(zipfile.ZipFile(zpath).namelist())
        except Exception:
            _ZCACHE[zpath] = set()
    return _ZCACHE[zpath]


def in_any_zip(zips, abspath):
    base = os.path.basename(abspath).replace("\\", "/")
    for z in zips:
        names = zset(z)
        if base in names:
            return True
        for n in names:
            if n.endswith("/" + base):
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True, help="package_audit.py 的 --json 产物")
    ap.add_argument("--dir", required=True, help="审查目录")
    ap.add_argument("--kit-zip", default="")
    ap.add_argument("--docs-zip", default="")
    ap.add_argument("--max-mb", type=float, default=25.0)
    ap.add_argument("--copy-to", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--md", default="")
    ap.add_argument("--exit-on-required", action="store_true")
    ap.add_argument("--roots", default="", help="作者根集合（分号分隔）；用于把补件按根归档成 files/<根名>/<相对路径>")
    ap.add_argument("--current-version", default="",
                    help="当前 VERSION；dist 下不含该版本号的历史分发物一律判 hash_only（本体已被新版取代，只随哈希存证）")
    a = ap.parse_args()

    curver = a.current_version
    if not curver:
        vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")
        if os.path.exists(vp):
            curver = io.open(vp, encoding="utf-8").read().strip()

    d = json.load(io.open(a.audit, encoding="utf-8"))
    docs_zips = [a.docs_zip] if a.docs_zip else []
    kit_zips = [a.kit_zip] if a.kit_zip else []
    limit = int(a.max_mb * 1024 * 1024)

    rows, stats = [], {"covered_docs": 0, "covered_kit": 0, "required": 0, "hash_only": 0, "nonexistent": 0}
    need_bytes = 0
    for x in d.get("local", []):
        ref = x["ref"]
        res = x.get("resolved")
        row = {"doc": x["from"], "ref": ref, "status": x["status"]}
        if x["status"] == "OK" and res:
            absp = res if os.path.isabs(res) else os.path.join(a.dir, res)
            if os.path.exists(absp) and os.path.abspath(absp).startswith(os.path.abspath(a.dir)):
                cls = "covered_docs"
            elif in_any_zip(kit_zips, absp) or in_any_zip(docs_zips, absp):
                cls = "covered_docs" if in_any_zip(docs_zips, absp) else "covered_kit"
            else:
                sz = os.path.getsize(absp) if os.path.exists(absp) else -1
                if os.path.isdir(absp):
                    tot = 0
                    for dp, dn, fs in os.walk(absp):
                        if ".git" in dp:
                            continue
                        for f in fs:
                            try:
                                tot += os.path.getsize(os.path.join(dp, f))
                            except Exception:
                                pass
                    sz = tot
                    row["kind"] = "dir"
                row["bytes"] = sz
                is_old_dist = (os.sep + "dist" + os.sep) in absp and curver and curver not in os.path.basename(absp)
                if row.get("kind") == "dir":
                    # 目录型引用（如 runs\ 或某棵子树）：不按整树随包，只按整树哈希存证
                    cls = "hash_only"
                    row["why"] = "目录型引用（整树存证，不逐件随包；实测 %d 字节）" % sz
                elif is_old_dist:
                    cls = "hash_only"
                    row["why"] = "历史分发物（被 %s 取代）" % curver
                elif 0 <= sz <= limit:
                    cls = "required"
                    need_bytes += sz
                else:
                    cls = "hash_only"
            row["path"] = absp
        else:
            cls = "nonexistent"
            row["bucket"] = x.get("bucket", "")
        row["class"] = cls
        stats[cls] += 1
        rows.append(row)

    if a.copy_to:
        os.makedirs(a.copy_to, exist_ok=True)
        copied = 0
        skipped = []
        seen = set()
        tags_seen = set()
        for r in rows:
            if r["class"] != "required" or r["path"] in seen:
                continue
            seen.add(r["path"])
            roots = [os.path.abspath(x) for x in (a.roots or "").split(";") if x]
            hit = None
            for rt in roots:
                if os.path.abspath(r["path"]).startswith(rt):
                    hit = (rt, os.path.relpath(r["path"], rt))
                    break
            if hit:
                tag = ("%s_%s" % (hit[0][0], os.path.basename(hit[0]))).replace(":", "")
                rel = "files/%s/%s" % (tag, hit[1].replace("\\", "/"))
            else:
                rel = "files/misc/" + os.path.basename(r["path"])
            rel = rel.replace("..", "upper").replace(":", "")
            dst = os.path.join(a.copy_to, rel)
            try:
                if os.path.isdir(r["path"]):
                    shutil.copytree(r["path"], dst, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns(".git", "*.pack", "*.idx", "*.rev"))
                else:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(r["path"], dst)
                copied += 1
                if rel.startswith("files/"):
                    parts = rel.split("/")
                    if len(parts) > 2:
                        tags_seen.add(parts[1])
            except Exception as e:
                skipped.append("%s -> %s (%s)" % (r["path"], dst, e))
        if copied or skipped:
            print("copied %d files to %s" % (copied, a.copy_to))
        for s in skipped:
            print("[SKIP] " + s)
        tags = sorted(tags_seen)
        body = ["根集合（作者机）：", "  %s" % a.dir]
        for rt in [x for x in (a.roots or "").split(";") if x]:
            body.append("  %s" % rt)
        body += ["", "补件包解包后，复跑时传这几条 roots（缺一不可）：", "  <解包目录>/files/<根名>"]
        for tg in tags:
            body.append("  <解包目录>/files/%s" % tg)
        body += ["", "作者机原始 roots 与补件根名的对应：files/<盘符_目录名>，例如 files/D_Workbuddy 对应 D:\\Workbuddy。"]
        io.open(os.path.join(a.copy_to, "ROOTS.txt"), "w", encoding="utf-8").write("\n".join(body) + "\n")
        print("copied %d files to %s" % (copied, a.copy_to))

    out = {"audit": a.audit, "dir": a.dir, "max_mb": a.max_mb, "stats": stats,
           "required_bytes": need_bytes, "rows": rows}
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    if a.md:
        L = ["# 交付件随身性清单（handoff_bundle 生成）", "",
             "审查目录 `%s`；阈值 %.1f MB。" % (a.dir, a.max_mb), "",
             "| 分类 | 条数 | 含义 |", "|---|---|---|",
             "| covered_docs | %d | 已随审查包 |" % stats["covered_docs"],
             "| covered_kit | %d | 已随测试台包 |" % stats["covered_kit"],
             "| required | %d | 缺，必须随补件包（合计 %.2f MB） |" % (stats["required"], need_bytes / 1048576.0),
             "| hash_only | %d | 缺且过大，只随哈希与索取说明 |" % stats["hash_only"],
             "| nonexistent | %d | 作者机上也没有（事实性缺件/阻塞） |" % stats["nonexistent"]]
        L += ["", "## required（必须随包）", "", "| 文档 | 引用 | 解析位置 | 字节 |", "|---|---|---|---|"]
        for r in rows:
            if r["class"] == "required":
                L.append("| %s | `%s` | `%s` | %d |" % (r["doc"], r["ref"], r.get("path", ""), r.get("bytes", -1)))
        L += ["", "## hash_only（过大，不随包）", "", "| 文档 | 引用 | 解析位置 | 字节 |", "|---|---|---|---|"]
        for r in rows:
            if r["class"] == "hash_only":
                L.append("| %s | `%s` | `%s` | %d |" % (r["doc"], r["ref"], r.get("path", ""), r.get("bytes", -1)))
        L += ["", "## nonexistent（作者机也没有）", "", "| 文档 | 引用 | 归因 |", "|---|---|---|"]
        for r in rows:
            if r["class"] == "nonexistent":
                L.append("| %s | `%s` | %s |" % (r["doc"], r["ref"], r.get("bucket", "")))
        io.open(a.md, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("stats=%s required=%.2f MB" % (json.dumps(stats, ensure_ascii=False), need_bytes / 1048576.0))
    if a.exit_on_required and stats["required"] and not a.copy_to:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
