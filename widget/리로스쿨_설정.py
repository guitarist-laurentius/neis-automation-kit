# -*- coding: utf-8 -*-
"""리로스쿨 자동 로그인 설정 — 검은 창에서 주소·아이디·비밀번호를 받는다.

  python 리로스쿨_설정.py

- 주소·아이디는 %LOCALAPPDATA%\\neis-automation\\teacher_config.json 의 riro_url · riro_id 에
- 비밀번호는 윈도우 «자격 증명 관리자»(keyring) 에만 — 화면·파일·대화에 남기지 않는다
위젯 [리로스쿨] 단추가 이 값으로 로그인한다 (바로가기_엔진.py riro open).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import teacher_config  # noqa: E402


def ask(prompt, default=""):
    v = input(prompt + (" [그대로 두려면 Enter]" if default else "") + ": ").strip()
    return v or default


def main():
    teacher_config.prepare_console_window()      # 빠른 편집 끄기 · 창을 맨 앞으로
    print("=" * 56)
    print(" 리로스쿨 자동 로그인 설정")
    print("=" * 56)
    path = teacher_config.CONFIG_FILE
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    print("\n① 리로스쿨 주소 — 평소 로그인하는 주소창 글자 그대로 (예: https://○○○.riroschool.kr)")
    while True:
        url = ask("   주소", cfg.get("riro_url", ""))
        if url and not url.startswith("http"):
            url = "https://" + url
        if "riroschool" in url:
            break
        print("   ⚠️  riroschool 이 들어간 주소를 넣어 주세요.")
    url = url.rstrip("/")

    print("\n② 리로스쿨 아이디")
    rid = ""
    while not rid:
        rid = ask("   아이디", cfg.get("riro_id", ""))

    print("\n③ 리로스쿨 비밀번호 — 칠 때 글자가 안 보이는 게 정상입니다. 다 치고 Enter.")
    import keyring
    key = "riroschool:" + rid
    has_old = bool(keyring.get_password(teacher_config.KEYRING_SERVICE, key))
    while True:
        pw = teacher_config.secret_input("   비밀번호" + (" [그대로 두려면 Enter]" if has_old else "") + ": ")
        if pw or has_old:
            break
        print("   ⚠️  비밀번호가 비었어요. 다시 쳐 주세요.")
    if pw:
        pw2 = teacher_config.secret_input("   한 번 더: ")
        if pw != pw2:
            print("\n❌ 두 번 친 비밀번호가 달라요. 이 창을 닫고 다시 해 주세요.")
            input("\n(Enter 를 누르면 창이 닫힙니다)")
            return 1
        keyring.set_password(teacher_config.KEYRING_SERVICE, key, pw)

    cfg["riro_url"], cfg["riro_id"] = url, rid
    teacher_config.save_config(cfg)
    print("\n✅ 저장했습니다. (Caps Lock 이 켜져 있었다면 다시 해 주세요)")
    print("   위젯 도넛의 [리로스쿨] 을 누르면 로그인까지 합니다.")
    input("\n(Enter 를 누르면 창이 닫힙니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
