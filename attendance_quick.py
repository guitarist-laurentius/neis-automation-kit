#!/usr/bin/env python3
"""한 줄 문장으로 학생 출결을 나이스 일일출결관리에 바로 넣는다 (캘린더 없이).

  python attendance_quick.py 풀이 "홍길동 질병지각 4교시 이후 등교"     나이스는 안 연다 — 어떻게 읽었는지만
  python attendance_quick.py 넣기 "홍길동 질병지각 4교시 이후 등교"     나이스에 넣고 저장 → 그 줄을 다시 읽어 확인
  python attendance_quick.py 넣기 "..." --저장안함                    넣기만 하고 저장 안 함 (다시 조회해 화면 입력을 버린다)
  python attendance_quick.py 명단                                      일일출결관리 화면에서 번호·이름을 읽어 우리반명단.txt 를 만든다

한 줄에 한 학생. 여러 학생이면 줄을 바꾸거나 ; 로 나눈다.
  형식   날짜, 이름, 교시, 분류+종류, 사유: 내용     예) 11월 16일~18일, 홍길동, 7교시부터, 인정조퇴, 사유: 대회 참가
         (쉼표·순서는 자유. 사유는 «사유:» 뒤 줄 끝까지 — 나이스 출결마감구분 «사유» 칸에 들어간다. 안 적으면 비워 둔다)
  분류   질병(아파서·병원·감기…) / 미인정(무단) / 출석인정(인정·체험학습·공결) / 기타  — 안 적으면 묻는다(지어내지 않는다)
  종류   결석 / 지각 / 조퇴 / 결과  (결과는 «5,6교시 인정결과» 처럼 빠진 교시를 적는다)
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

KINDS = ("결석", "지각", "조퇴", "결과")      # 결과는 2026-11-23 더함 — 빠진 교시 칸을 하나씩 누른다
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


# 날짜 한 개: «11월 16일» · «11/16» · «11.16» · «16일»
_ONE = r"(?:(\d{1,2})\s*월\s*(\d{1,2})\s*일?|(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d.])\.?|(?<![\d/.])(\d{1,2})\s*일(?!\s*(?:간|째)))"
# 기간의 뒤쪽을 줄여 쓴 것: «11.16~18» · «11/16~18일» · «16~18일» (~ 뒤 숫자만 = 같은 달)
_TAIL = r"\s*[~\-]\s*(?:" + _ONE + r"|(\d{1,2})(?![\d교번/.]))"


def _mkdate(today: date, mo, d, raw: str) -> date:
    try:
        return date(today.year, int(mo), int(d))
    except ValueError:
        raise ParseError(f"날짜 '{raw}' 이(가) 달력에 없어요")


def _one(m, base: int, today: date, month=None):
    g = m.groups()[base:base + 5]
    if g[0]:
        return _mkdate(today, g[0], g[1], m.group(0))
    if g[2]:
        return _mkdate(today, g[2], g[3], m.group(0))
    return _mkdate(today, month or today.month, g[4], m.group(0))


def _dates(text: str, today: date) -> list[date]:
    """문장 속 날짜들 (적힌 순서). 없으면 [].
    읽지 못한 숫자가 남으면(교시·번호가 아닌데) 오늘로 두지 않고 묻는다 — «11.16~18» 을 오늘 하루로
    읽은 일이 있었다 (11/23)."""
    text = re.sub(r"(?<![\d/.])(\d{1,2})(\s*[~\-]\s*\d{1,2}\s*일)", r"\1일\2", text)   # «16~18일» → «16일~18일»
    found, rest = [], text
    for m in re.finditer(_ONE + r"(?:" + _TAIL + r")?", text):
        start = _one(m, 0, today)
        found.append(start)
        if m.group(6) or m.group(8) or m.group(10) or m.group(11):      # 뒤쪽 날짜가 있다
            if m.group(11):
                found.append(_mkdate(today, start.month, m.group(11), m.group(0)))
            else:
                found.append(_one(m, 5, today, month=start.month))
        rest = rest.replace(m.group(0), " ", 1)
    for word, back in (("그제", 2), ("그저께", 2), ("어제", 1), ("오늘", 0)):
        if word in text:
            found.append(today - timedelta(days=back))
    # 교시·번호·맨 앞 번호를 빼고도 숫자가 남으면 날짜를 잘못 읽은 것이다
    left = re.sub(r"\d+\s*(?:교시|번)|^\s*\d+\s+|\d+(?:\s*(?:,|·|와|과|및|~|-)\s*\d+)+\s*교시", " ", rest)
    odd = re.findall(r"\d[\d\s./~\-]*", left)
    if odd:
        raise ParseError(f"'{odd[0].strip()}' 을(를) 날짜로 못 읽었어요 — «11/16~11/18» · «11월 16일» 처럼 적어 주세요")
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
        m = (re.search(r"(\d+)교시(?:에|부터|때)?(?:등교|출석|옴|왔|도착|들어)", t)
             or re.search(r"(\d+)교시(?:에|부터)(?!조퇴)", t))     # 쉼표 형식 «3교시부터, 질병지각» = 3교시에 옴
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
            m = (re.search(r"(\d+)교시(?:에|부터|때|중)?(?:조퇴|하교|귀가)", t) or re.search(r"(\d+)교시~", t)
                 or re.search(r"(\d+)교시(?:부터|에|때|중)", t))      # 쉼표 형식 «7교시부터, 인정조퇴» = 7교시부터 빠짐
            if not m:
                raise ParseError("조퇴인데 몇 교시에 갔는지 못 읽었어요 (예: «4교시 이후 조퇴» / «5교시에 조퇴»)")
            n = int(m.group(1))
        if n > last_period:
            raise ParseError(f"{n}교시부터 조퇴는 없어요 (하루 {last_period}교시까지) — 조퇴가 맞는지 봐 주세요")
        return f"{n}교시~", f"{n}교시부터 빠짐"
    if kind == "결과":
        # «5,6교시» «5·6교시» «5교시와 6교시» «3~5교시» «2교시» — 교시 글자 앞의 숫자 묶음을 다 모은다
        nums = []
        for m in re.finditer(r"((?:\d+(?:교시)?\s*(?:,|·|와|과|및|~|-)\s*)*\d+)\s*교시", t):
            for a, b in re.findall(r"(\d+)(?:교시)?(?:~|-)(\d+)", m.group(1)):
                nums += range(int(a), int(b) + 1)
            nums += [int(x) for x in re.findall(r"\d+", re.sub(r"(\d+)(?:교시)?(?:~|-)(\d+)", "", m.group(1)))]
        nums = sorted(set(n for n in nums if n >= 1))
        if not nums:
            raise ParseError("결과인데 몇 교시를 빠졌는지 못 읽었어요 (예: «5,6교시 질병결과» / «3교시 미인정결과»)")
        over = [n for n in nums if n > last_period]
        if over:
            raise ParseError(f"{over}교시는 없어요 (하루 {last_period}교시까지) — 교시를 봐 주세요")
        label = ",".join(map(str, nums)) + "교시"
        return label, f"{label} 빠짐"
    return "", "하루 전체"


def parse_line(line: str, roster: list[tuple[str, str]], today: date, last_period: int) -> dict:
    text = line.strip()
    # 사유 — «사유:» 뒤 끝까지. 먼저 떼어 낸다 (사유 속 «병원»·숫자가 분류·날짜로 잘못 읽히지 않게)
    reason = ""
    rm = re.search(r"[,，]?\s*사유\s*[:：]?\s*(.*)$", text)
    if rm:
        reason = rm.group(1).strip().strip(",，.").strip()
        text = text[:rm.start()].strip()
        if not reason:
            raise ParseError("«사유:» 뒤가 비어 있어요 — 사유를 적거나 «사유:» 를 지워 주세요")
        if len(reason) > 100:
            raise ParseError("사유가 너무 길어요 (100자까지)")
    # 종류
    kind = next((k for k in KINDS if k in text), None)
    if not kind:
        raise ParseError("결석·지각·조퇴·결과 중 무엇인지 적어 주세요")
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
    if len(ds) >= 2:                                # 지각·조퇴·결과도 기간이면 그 날마다 같은 교시로 넣는다 (11/23)
        end = ds[1]
        if end < start:
            raise ParseError("끝 날짜가 시작 날짜보다 앞이에요")
    if not any((start + timedelta(days=k)).weekday() < 5 for k in range((end - start).days + 1)):
        raise ParseError(f"{start.month}/{start.day}" + (f"~{end.month}/{end.day}" if end != start else "")
                         + " 은(는) 주말이에요 — 날짜를 봐 주세요")
    # 교시
    note, desc = _period_note(text, kind, last_period)
    label = f"{cat}{kind}"
    return {"number": str(int(number)), "name": name, "att_type": label, "start_date": start, "end_date": end,
            "note": note, "설명": desc, "reason": reason}


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
    days = ""
    if e != s:                                      # 기간이면 주말 빼고 며칠인지
        n = sum(1 for k in range((e - s).days + 1) if (s + timedelta(days=k)).weekday() < 5)
        days = f" ({n}일)"
    return (f"{when}{days} · {it['number']}번 {it['name']} · {it['att_type']} · {it['설명']}"
            + (f" · 사유: {it['reason']}" if it.get("reason") else ""))


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
