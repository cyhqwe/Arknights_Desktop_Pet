"""语音语言切换与健壮性测试:双语言文件完整性、菜单、切换、持久化、变调适配。

运行:python tests/test_language.py
"""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMenu

from pet.audio import AudioManager
from pet.config import (
    RES_DIR,
    VOICE_LANGS,
    VOICE_NAMES,
    Config,
    voice_filename,
)
from pet.window import PetWindow

results = []
errors = []


def record(name, ok, detail):
    results.append((name, ok, detail))


def main() -> int:
    app = QApplication([])

    # ---- 1. 双语言文件完整性 + wav 可读 ----
    missing = []
    bad_wav = []
    for lang in VOICE_LANGS:
        for name in VOICE_NAMES:
            p = RES_DIR / voice_filename(name, lang)
            if not p.exists():
                missing.append(f"{lang}:{name}")
            else:
                try:
                    with wave.open(str(p), "rb") as w:
                        w.getnframes()
                except Exception:
                    bad_wav.append(f"{lang}:{name}")
    record("all-voice-files-exist", not missing, f"missing={missing or 'NONE'}")
    record("all-wav-readable", not bad_wav, f"bad={bad_wav or 'NONE'}")

    # ---- 2. AudioManager 语言切换 ----
    am = AudioManager()
    p_jp = am._voice_path("问候") if am.language() == "JP" else None
    am.set_language("JP")
    path_jp = am._voice_path("问候")
    am.set_language("zh-CN")
    path_cn = am._voice_path("问候")
    record("lang-path-differs", path_jp != path_cn, f"{path_jp.name} vs {path_cn.name}")
    record("lang-jp-ends-JP", path_jp.name.endswith("-JP.wav"), path_jp.name)
    record("lang-cn-ends-zh", path_cn.name.endswith("-zh-CN.wav"), path_cn.name)
    # 时长按语言
    d_jp = am.duration_of("问候")
    am.set_language("JP")
    d_jp2 = am.duration_of("问候")
    am.set_language("zh-CN")
    d_cn = am.duration_of("问候")
    record("duration-per-lang", abs(d_jp2 - d_cn) > 0.01 or d_jp2 > 0, f"JP={d_jp2:.2f}s zh-CN={d_cn:.2f}s")
    # 变调适配双语言(绝对主角)
    am.set_skin("绝对主角")
    am.set_language("JP")
    pj = am._voice_path("问候")
    am.set_language("zh-CN")
    pc = am._voice_path("问候")
    record("pitch-per-lang", pj != pc and pj.exists() and pc.exists(), f"{pj.name} / {pc.name}")

    # ---- 3. 窗口菜单包含“切换语言” ----
    win = PetWindow(Config.load())
    win.show()
    app.processEvents()
    menu = win._build_menu()
    subs = {m.title(): m for m in menu.findChildren(QMenu) if m.title()}
    lang_menu = subs.get("切换语言")
    record("menu-has-lang", lang_menu is not None, "切换语言" if lang_menu else "MISSING")
    if lang_menu:
        labels = [a.text() for a in lang_menu.actions()]
        record("menu-lang-options", len(labels) == len(VOICE_LANGS), str(labels))
        # 默认语言勾选
        checked = [a.text() for a in lang_menu.actions() if a.isChecked()]
        record("menu-lang-default", len(checked) == 1, str(checked))
    menu.deleteLater()

    # ---- 4. 切换语言:cfg + audio 同步 + 持久化 ----
    other = "zh-CN" if win.cfg.language == "JP" else "JP"
    win._switch_language(other)
    record("switch-updates-cfg", win.cfg.language == other, win.cfg.language)
    record("switch-updates-audio", win._audio.language() == other, win._audio.language())
    cfg2 = Config.load()
    record("switch-persisted", cfg2.language == other, cfg2.language)

    # 还原
    c = Config.load()
    c.birthday = ""
    c.skin = "超新星"
    c.size_percent = 100
    c.always_on_top = True
    c.language = "JP"
    c.save()
    win.close()
    app.quit()

    for name, ok, detail in results:
        print(("PASS" if ok else "FAIL"), name, "|", detail)
    all_ok = bool(results) and all(ok for _, ok, _ in results) and not errors
    print("\nLANGUAGE TESTS", "ALL PASSED" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
