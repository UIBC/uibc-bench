# -*- coding: utf-8 -*-
"""历史件哈希存证清单（hash_manifest）：把「包不随行」的件转成「可按哈希独立核对」。

起因（52 号）：外人侧复跑时，112 条硬伤里绝大多数指向旧分发物（旧 bundle/zip）与
目录树。这些件**不该随包**（已被新版取代或体量过大），但它们被引用是事实。
两条出路：① 全随（120–160 MB 垃圾托运）；② 全部改文案（31 篇 / 98 处，批量改写
又会自己制造证据债）。本工具提供第三条：**件不随包，哈希随包**。

用法：
    python tools/hash_manifest.py --roots "<测试台>" --out handoff_hash_manifest.json [--dirs runs dist]

产出：
  files[]  每个件：name / relpath / bytes / sha256
  trees[]  每棵目录树：leaf / bytes / files / tree_sha256（按「相对路径+大小+sha256」排序后再哈希）

判定：清单本身不含主张，只含事实（字节数与 SHA256）。核对者拿到清单，可以要求
应证方提供任一原件的副本，并用清单里的哈希逐字节验证——**不必信任应证方的话**。
"""
import argparse
import hashlib
import io
import json
import os


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", required=True, help="分号分隔；清单覆盖这些根下的指定子目录")
    ap.add_argument("--dirs", default="dist", help="根下要收进清单的子目录，分号分隔；用 . 表示整根（排除 .git/__pycache__）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-mb", type=float, default=400.0, help="单棵目录树超过此体积只记 files/bytes，不算 tree_sha256")
    a = ap.parse_args()

    limit = int(a.max_mb * 1024 * 1024)
    files, trees, dirs_all = [], [], []
    for root in [x for x in a.roots.split(";") if x]:
        for sub in [x for x in a.dirs.split(";") if x]:
            base = os.path.join(root, sub)
            if not os.path.isdir(base):
                continue
            tree_rows, total = [], 0
            for dp, dn, fs in os.walk(base):
                if ".git" in dp or "__pycache__" in dp:
                    continue
                for f in sorted(fs):
                    p = os.path.join(dp, f)
                    try:
                        sz = os.path.getsize(p)
                    except Exception:
                        continue
                    total += sz
                    row = {"name": f, "relpath": os.path.relpath(p, root).replace("\\", "/"),
                           "bytes": sz, "sha256": sha_file(p)}
                    files.append(row)
                    tree_rows.append("%s|%d|%s" % (row["relpath"], sz, row["sha256"]))
                for d in sorted(dn):
                    if ".git" == d or "__pycache__" == d:
                        continue
                    dirs_all.append(os.path.relpath(os.path.join(dp, d), root).replace("\\", "/"))
            if total <= limit:
                dig = hashlib.sha256("\n".join(sorted(tree_rows)).encode("utf-8")).hexdigest().upper()
            else:
                dig = ""
            trees.append({"leaf": sub, "root": root, "bytes": total, "files": len(tree_rows),
                          "tree_sha256": dig})

    out = {"generated_for": "历史分发物与目录树的哈希存证（件不随包，哈希随包）",
           "count": len(files), "total_bytes": sum(x["bytes"] for x in files),
           "files": files, "trees": trees, "dirs": dirs_all}
    io.open(a.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print("files=%d total=%.2f MB trees=%d" % (len(files), out["total_bytes"] / 1048576.0, len(trees)))
    for t in trees:
        print("  tree %-12s files=%-5d %.2f MB sha=%s" % (t["leaf"], t["files"], t["bytes"] / 1048576.0, t["tree_sha256"][:12] or "(超限未算)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
