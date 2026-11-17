#!/usr/bin/env python3
"""한 줄 문장으로 학생 출결을 나이스 일일출결관리에 바로 넣는다 (캘린더 없이).

  python attendance_quick.py 풀이 "홍길동 질병지각 4교시 이후 등교"     나이스는 안 연다 — 어떻게 읽었는지만
  python attendance_quick.py 넣기 "홍길동 질병지각 4교시 이후 등교"     나이스에 넣고 저장 → 그 줄을 다시 읽어 확인
  python attendance_quick.py 넣기 "..." --저장안함                    넣기만 하고 저장 안 함 (다시 조회해 화면 입력을 버린다)
  python attendance_quick.py 명단                                      일일출결관리 화면에서 번호·이름을 읽어 우리반명단.txt 를 만든다

한 줄에 한 학생. 여러 학생이면 줄을 바꾸거나 ; 로 나눈다.
  분류   질병(아파서·병원·감기…) / 미인정(무단) / 출석인정(인정·체험학습·공결) / 기타  — 안 적으면 묻는다(지어내지 않는다)
  종류   결석 / 지각 / 조퇴  (결과는 아직 안 된다 — 나이스에서 직접)
  교시   지각  «4교시 이후 등교»·«4교시 끝나고 옴» = 1~4교시 빠짐 · «4교시에 등교»·«4교시부터 출석» = 1~3교시 빠짐 · «조회 지각» = 조회만
         조퇴  «4교시 이후 조퇴»·«4교시 끝나고 조퇴» = 5교시부터 빠짐 · «4교시에 조퇴»·«4교시부터 조퇴» = 4교시부터 빠짐
  날짜   안 적으면 오늘 · 어제 · 그제 · 11월 17일 · 11/17 · 17일 · 결석은 «11/17~11/19» 처럼 기간
  학생   이름만 적으면 우리반명단.txt 에서 번호를 찾는다 (동명이인·없는 이름은 묻는다). «3번 홍길동» 도 된다

마지막 줄에 RESULT_JSON= 을 찍는다 (위젯이 읽는다). 학생 이름은 화면·로그에만 — 파일로 남기지 않는다.
"""
import asyncio
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "우리반명단.txt"

KINDS = ("결석", "지각", "조퇴")      # 결과는 main.py 가 아직 못 넣는다
# 앞에 있는 것부터 본다 — «미인정» 을 «인정» 보다 먼저
CATEGORY_WORDS = [
    ("미인정", r"미인정|무단"),
    ("출석인정", r"출석인정|인정|체험학습|현장학습|공결|경조|대회|공가"),
    ("기타", r"기타"),
    ("질병", r"질병|병결|병지각|병조퇴|병원|아파|아픔|감기|두통|복통|발열|열이|몸살|코로나|독감|진료|생리"),
]


# ───────────────────────── 명단 ─────────────────────────

def load_roster() -> list[tuple[str, str]]:
    if not ROSTER.exists():
        return []
    out = []
    for ln in ROSTER.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)", ln)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


# ───────────────────────── 문장 풀이 ─────────────────────────

class ParseError(Exception):
    pass


def _dates(text: str, today: date) -> list[date]:
    """문장 속 날짜들 (적힌 순서). 없으면 []."""
    found = []
    for m in re.finditer(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일|(\d{1,2})\s*/\s*(\d{1,2})|(?<![\d/])(\d{1,2})\s*일(?!\s*(?:간|째))", text):
        if m.group(1):
            mo, d = int(m.group(1)), int(m.group(2))
        elif m.group(3):
            mo, d = int(m.group(3)), int(m.group(4))
        else:
            mo, d = today.month, int(m.group(5))
        try:
            found.append(date(today.year, mo, d))
        except ValueError:
            raise ParseError(f"날짜 '{m.group(0)}' 이(가) 달력에 없어요")
    for word, back in (("그제", 2), ("그저께", 2), ("어제", 1), ("오늘", 0)):
        if word in text:
            found.append(today - timedelta(days=back))
    return found


def _period_note(text: str, kind: str, last_period: int) -> tuple[str, str]:
    """(main.py 가 읽는 note, 사람이 읽는 설명)."""
    t = text.replace(" ", "")
    if kind == "지각":
        if re.search(r"조회", t) and not re.search(r"\d+교시", t):
            return "조회", "조회만 늦음 (1교시부터 출석)"
        m = re.search(r"(\d+)교시(?:이후|후|끝나고|마치고|지나서|끝난뒤)", t) or re.search(r"~(\d+)교시", t)
        if m:
            n = int(m.group(1))
            return f"~{n}교시", f"1~{n}교시 빠짐 ({n + 1}교시부터 출석)"
        m = re.search(r"(\d+)교시(?:에|부터|때)?(?:등교|출석|옴|왔|도착|들어)", t)
        if m:
            n = int(m.group(1)) - 1
            if n <= 0:
                return "조회", "조회만 늦음 (1교시부터 출석)"
            return f"~{n}교시", f"1~{n}교시 빠짐 ({n + 1}교시부터 출석)"
        raise ParseError("지각인데 몇 교시에 왔는지 못 읽었어요 (예: «4교시 이후 등교» / «3교시에 등교» / «조회 지각»)")
    if kind == "조퇴":
        m = re.search(r"(\d+)교시(?:이후|후|끝나고|마치고|끝난뒤)", t)
        if m:
            n = int(m.group(1)) + 1
        else:
            m = re.search(r"(\d+)교시(?:에|부터|때|중)?(?:조퇴|하교|귀가)", t) or re.search(r"(\d+)교시~", t)
            if not m:
                raise ParseError("조퇴인데 몇 교시에 갔는지 못 읽었어요 (예: «4교시 이후 조퇴» / «5교시에 조퇴»)")
            n = int(m.group(1))
        if n > last_period:
            raise ParseError(f"{n}교시부터 조퇴는 없어요 (하루 {last_period}교시까지) — 조퇴가 맞는지 봐 주세요")
        return f"{n}교시~", f"{n}교시부터 빠짐"
    return "", "하루 전체"


def parse_line(line: str, roster: list[tuple[str, str]], today: date, last_period: int) -> dict:
    text = line.strip()
    # 종류
    kind = next((k for k in KINDS if k in text), None)
    if not kind and "결과" in text:
        raise ParseError("결과는 아직 자동으로 못 넣어요 — 나이스에서 직접 넣어 주세요")
    if not kind:
        raise ParseError("결석·지각·조퇴 중 무엇인지 적어 주세요")
    # 분류
    cat = next((c for c, pat in CATEGORY_WORDS if re.search(pat, text)), None)
    if not cat:
        raise ParseError("질병·미인정·출석인정 중 무엇인지 적어 주세요 (예: «질병지각»)")
    # 학생
    num_m = re.search(r"(\d+)\s*번", text) or re.match(r"\s*(\d+)\s+\S", text)
    number = num_m.group(1) if num_m else None
    names = sorted({n for _, n in roster if n in text}, key=len, reverse=True)
    name = names[0] if names else None
    if name:
        same = [no for no, n in roster if n == name]
        if number is None:
            if len(same) != 1:
                raise ParseError(f"'{name}' 이(가) 명단에 {len(same)}명이에요 — 번호를 같이 적어 주세요 (예: «{same[0] if same else 3}번 {name}»)")
            number = same[0]
        elif number not in same:
            raise ParseError(f"명단에서 {number}번은 '{name}' 이(가) 아니에요 — 번호·이름을 확인해 주세요")
    elif number:
        hit = [n for no, n in roster if no == number]
        if not hit:
            raise ParseError(f"{number}번 학생을 명단에서 못 찾았어요" if roster else
                             "우리반명단.txt 가 없어요 — 위젯 오른쪽 클릭 → «반 명단 다시 읽기» 를 먼저 해 주세요")
        name = hit[0]
    else:
        raise ParseError("학생 이름을 명단에서 못 찾았어요" if roster else
                         "우리반명단.txt 가 없어요 — 위젯 오른쪽 클릭 → «반 명단 다시 읽기» 를 먼저 해 주세요")
    # 날짜
    ds = _dates(text, today)
    start = ds[0] if ds else today
    end = start
    if len(ds) >= 2:
        if kind != "결석":
            raise ParseError(f"{kind}은(는) 하루만 넣을 수 있어요 — 날짜를 하나만 적어 주세요")
        end = ds[1]
        if end < start:
            raise ParseError("끝 날짜가 시작 날짜보다 앞이에요")
    # 교시
    note, desc = _period_note(text, kind, last_period)
    label = f"{cat}{kind}"
    return {"number": str(int(number)), "name": name, "att_type": label, "start_date": start, "end_date": end,
            "note": note, "설명": desc}


def parse_text(text: str, roster, today: date, last_period: int):
    items, errors = [], []
    for line in [x for x in re.split(r"[\n;]+", text) if x.strip()]:
        try:
            items.append(parse_line(line, roster, today, last_period))
        except ParseError as e:
            errors.append({"문장": line.strip(), "이유": str(e)})
    return items, errors


def describe(it: dict) -> str:
    s, e = it["start_date"], it["end_date"]
    wd = "월화수목금토일"
    when = f"{s.month}/{s.day}({wd[s.weekday()]})" + (f" ~ {e.month}/{e.day}({wd[e.weekday()]})" if e != s else "")
    return f"{when} · {it['number']}번 {it['name']} · {it['att_type']} · {it['설명']}"


def to_json(it: dict) -> dict:
    return {**it, "start_date": it["start_date"].isoformat(), "end_date": it["end_date"].isoformat(),
            "요약": describe(it)}


# ───────────────────────── 나이스 ─────────────────────────

async def open_neis(p, M):
    import teacher_config
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=str(teacher_config.CONFIG_DIR / "chrome_profile"),
        channel="chrome", headless=False, slow_mo=50,
        args=["--profile-directory=Default", "--disable-blink-features=AutomationControlled",
              "--disable-features=PrivateNetworkAccessForNavigations,PrivateNetworkAccessPermissionPrompt,PermissionChip",
              "--disable-web-security", "--allow-running-insecure-content", "--test-type", "--start-maximized",
              "--noerrdialogs", *teacher_config.window_args()],
        ignore_default_args=["--enable-automation", "--no-sandbox"], viewport=None)
    await ctx.grant_permissions(["notifications"], origin=M._origin_of(M.NEIS_URL))
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    await page.goto(M.NEIS_URL)
    await M.auto_login(page)
    await M.wait_for_attendance_page(page)
    return ctx, page


JS_ROSTER = r"""
() => {
  const out = [];
  for (const r of document.querySelectorAll('.cl-grid-row')) {
    const c = Array.from(r.children).map(d => (d.innerText || '').trim().split(String.fromCharCode(10))[0].trim());
    if (c.length > 2 && /^\d+$/.test(c[0]) && /^[가-힣A-Za-z]{2,}/.test(c[1])) out.push([c[0], c[1].split(/\s+/)[0]]);
  }
  return out;
}
"""


async def cmd_roster(M) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        ctx, page = await open_neis(p, M)
        try:
            d = date.today()
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            await M.set_date_and_search(page, d)
            seen = {}
            grid = page.locator(".cl-grid-body, .cl-grid").first
            for _ in range(12):                       # 가상 스크롤 — 굴리며 모은다
                for no, nm in await page.evaluate(JS_ROSTER):
                    seen[int(no)] = nm
                try:
                    box = await grid.bounding_box()
                    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                except Exception:
                    pass
                await page.mouse.wheel(0, 400)
                await page.wait_for_timeout(300)
            if not seen:
                return {"ok": False, "error": "일일출결관리 화면에서 학생 줄을 못 읽었어요"}
            ROSTER.write_text("".join(f"{no} {seen[no]}\n" for no in sorted(seen)), encoding="utf-8")
            print(f"✅  우리반명단.txt 를 만들었습니다 — {len(seen)}명 (이름은 화면에 늘어놓지 않습니다)")
            return {"ok": True, "명수": len(seen)}
        finally:
            await ctx.close()


async def cmd_enter(M, items: list[dict], save: bool) -> dict:
    from playwright.async_api import async_playwright
    task_map = M.build_task_map(items)
    if not task_map:
        return {"ok": False, "error": "넣을 날이 없어요 (주말만 골랐나요?)"}
    holidays = M.load_holidays(task_map.keys())
    results, failures = [], []
    async with async_playwright() as p:
        ctx, page = await open_neis(p, M)
        try:
            for d, tasks in task_map.items():
                if d in holidays:
                    print(f"  ⏭  {d} 휴업일이라 건너뜀")
                    failures += [M._failure(d, M.FAILED, t, "휴업일") for t in tasks]
                    continue
                print(f"\n📅  {d} ({len(tasks)}건)")
                await M.dismiss_alert_popup(page, timeout=1000)
                if not await M.set_date_and_search(page, d):
                    failures += [M._failure(d, M.FAILED, t, "화면 날짜를 못 맞춤") for t in tasks]
                    continue
                cols = await M.read_day_columns(page)
                before = {t["number"]: await M._row_text(page, t) for t in tasks}
                day_fail, can_save = await M.enter_day(page, d, tasks, cols)
                failures += day_fail
                if not can_save:
                    continue
                if save:
                    st, why = await M.save_page(page)
                    if st != M.SAVE_OK:
                        failures += [M._failure(d, M.UNSURE, t, why) for t in tasks
                                     if not any(f["number"] == t["number"] and f["date"] == d for f in day_fail)]
                        continue
                    await M.set_date_and_search(page, d)          # 저장된 값을 다시 읽어 확인
                    for t in tasks:
                        row = await M._row_text(page, t)
                        results.append({"날짜": d.isoformat(), "번호": t["number"], "줄": row})
                        print(f"  🔎  저장 뒤 {t['number']}번 줄: {row}")
                else:
                    for t in tasks:
                        row = await M._row_text(page, t)
                        results.append({"날짜": d.isoformat(), "번호": t["number"], "줄": row})
                        print(f"  🧪  넣은 뒤(저장 전) {t['number']}번 줄: {row}")
                    await M.set_date_and_search(page, d)          # 저장 안 함 — 다시 조회해 화면 입력을 버린다
                    for t in tasks:
                        back = await M._row_restored(page, t, before[t["number"]])
                        print(f"  🧪  다시 조회 → {t['number']}번 줄이 넣기 전으로 {'돌아옴 ✅' if back else '안 돌아옴 ⚠️'}")
                        if not back:
                            failures.append(M._failure(d, M.UNSURE, t, "저장 안 하고 다시 조회했는데 줄이 넣기 전으로 안 돌아옴 — 나이스에서 봐 주세요"))
        finally:
            await ctx.close()
    fails = [{"날짜": f["date"].isoformat(), "번호": f["number"], "이유": f["reason"]} for f in failures]
    return {"ok": not fails, "저장": save, "확인": results, "실패": fails}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    args = sys.argv[1:]
    if not args or args[0] not in ("풀이", "넣기", "명단"):
        print(__doc__)
        return 2
    cmd = args[0]
    import teacher_config
    import main as M
    try:
        M.load_teacher_settings()
    except teacher_config.ConfigMissingError as e:
        print("RESULT_JSON=" + json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    if cmd == "명단":
        r = asyncio.run(cmd_roster(M))
        print("RESULT_JSON=" + json.dumps(r, ensure_ascii=False))
        return 0 if r.get("ok") else 1
    text = " ".join(a for a in args[1:] if not a.startswith("--"))
    items, errors = parse_text(text, load_roster(), date.today(), M.LAST_PERIOD)
    for it in items:
        print("  📝  " + describe(it))
    for e in errors:
        print(f"  ❓  «{e['문장']}» — {e['이유']}")
    if cmd == "풀이" or errors or not items:
        ok = bool(items) and not errors
        print("RESULT_JSON=" + json.dumps({"ok": ok, "풀이": [to_json(i) for i in items], "물을것": errors},
                                          ensure_ascii=False))
        return 0 if ok else 1
    r = asyncio.run(cmd_enter(M, items, save="--저장안함" not in args))
    r["풀이"] = [to_json(i) for i in items]
    print("RESULT_JSON=" + json.dumps(r, ensure_ascii=False, default=str))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
