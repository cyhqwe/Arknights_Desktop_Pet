"""打包脚本:用 PyInstaller 生成单文件 exe,并把素材复制到 exe 同级。

用法:
    python build.py
产出:
    dist/ArknightsPet.exe       单文件可执行程序
    dist/resources/             素材目录(exe 运行需要,与 exe 同级)
分发:整个 dist 文件夹一起拷贝即可运行。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "ArknightsPet"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# 复制素材时忽略运行期生成物(缓存/变调文件)
IGNORE_PATTERNS = shutil.ignore_patterns("_pet_media_cache.json", "_pitched")


def main() -> int:
    py = sys.executable
    # 1. PyInstaller 单文件、无控制台窗口
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", NAME,
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(ROOT),
        str(ROOT / "main.py"),
    ]
    print(">>> PyInstaller 打包中(约 1-3 分钟)...")
    subprocess.run(cmd, check=True, cwd=ROOT)

    # 2. 复制 resources 到 exe 同级
    src = ROOT / "resources"
    dst = DIST / "resources"
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=IGNORE_PATTERNS)
        print(f">>> 素材已复制到 {dst}")

    exe = DIST / f"{NAME}.exe"
    print("\n打包完成:")
    print(f"  {exe}")
    print(f"  {DIST / 'resources'}")
    print("分发:把整个 dist 文件夹拷贝给用户即可运行(exe 与 resources 需保持同级)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
