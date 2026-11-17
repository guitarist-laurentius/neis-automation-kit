#!/usr/bin/env python3
"""나이스 초과근무(평일 시간외 근무) 신청 스크립트.

복무 > 개인초과근무관리 > [신청] 창(초과근무신청)에 일자·시각·하여야 할 일을 넣고
승인요청(상신)까지 한다. 로그인·결재선 지정·상신 확인창 처리는 main_bokmu.py 의 것을 그대로 쓴다.

평일 시간외 근무만 다룬다 — 주말·휴일·대체휴무·방과후차감은 다루지 않는다.
인정시간 합은 나이스가 계산하므로 건드리지 않고 읽어서 보여 주기만 한다.

사용 예:
    python main_overtime.py --date 2026-11-16 --start 16:30 --end 18:30 --task "학년말 성적 처리" --dry-run
"""
import argparse
import asyncio
import os
import sys
from datetime import date

from playwright.async_api import async_playwright, Page

import teacher_config
import main as neis          # 로그인/알림팝업 로직 재사용
import main_bokmu as mb      # 클릭·입력·결재선·상신 재사용


async def open_overtime_modal(page: Page):
    """복무 > 개인초과근무관리 진입 후 '신청' 버튼을 눌러 초과근무신청 창을 연다."""
    await mb.click(page, page.locator("a").filter(has_text="복무 0단계 메뉴항목").first, timeout=8000)
    await page.wait_for_timeout(600)
    await mb.click(page, page.locator("a").filter(has_text="개인초과근무관리").first, timeout=8000)
    await page.wait_for_timeout(1000)
    await mb.wait_loading(page, 60)

    apply_btns = page.get_by_text("신청", exact=True)
    for i in range(await apply_btns.count()):
        cand = apply_btns.nth(i)
        if await cand.is_visible():
            await mb.click(page, cand, timeout=5000)
            break
    else:
        raise RuntimeError("보이는 '신청' 버튼을 찾지 못함")

    dialog = page.locator('[role="dialog"][aria-label="초과근무신청"]')
    await dialog.wait_for(state="visible", timeout=10_000)
    await page.wait_for_timeout(1500)
    return dialog


async def fill_and_tab(page: Page, loc, value: str):
    await mb.fill_text_input(page, loc, value)
    await loc.press("Tab")
    await page.wait_for_timeout(300)


async def fill_overtime_form(page: Page, dialog, d: date, start_hm: str, end_hm: str, task: str):
    """신청창에 미리 들어 있는 줄(오늘 16:00~21:00)을 아래 입력칸으로 고친다."""
    sh, sm = start_hm.split(":")
    eh, em = end_hm.split(":")

    # 날짜를 먼저 넣는다 — 날짜를 바꾸면 시각이 다시 그려질 수 있다
    await fill_and_tab(page, dialog.locator('input[aria-label="초과근무일자"]').first, d.strftime("%Y-%m-%d"))
    await page.wait_for_timeout(500)
    for label, value in (("신청시작시", sh), ("신청시작분", sm), ("신청종료시", eh), ("신청종료분", em)):
        await fill_and_tab(page, dialog.locator(f'input[aria-label="{label}"]').first, value)

    await mb.fill_text_input(page, dialog.locator('textarea[aria-label="하여야 할 일"]').first, task)
    await page.wait_for_timeout(500)


async def read_back(dialog) -> dict:
    """나이스에 실제로 들어간 값을 읽는다 (인정시간 합은 나이스가 계산한 값)."""
    async def val(label, tag="input"):
        loc = dialog.locator(f'{tag}[aria-label="{label}"]').first
        try:
            return (await loc.input_value(timeout=2000)).strip()
        except Exception:
            return "?"
    sh, sm = await val("신청시작시"), await val("신청시작분")
    eh, em = await val("신청종료시"), await val("신청종료분")
    th, tm = await val("초과근무시간 합 시"), await val("초과근무시간 합 분")
    return {
        "일자": await val("초과근무일자"),
        "시작": f"{sh}:{sm}",
        "종료": f"{eh}:{em}",
        "인정시간합": f"{th}시간 {tm}분",
        "하여야할일": await val("하여야 할 일", tag="textarea"),
    }


async def run(args):
    neis.load_teacher_settings()
    PROFILE_DIR = str(teacher_config.CONFIG_DIR / "chrome_profile")
    cfg = teacher_config.load_config()

    if not args.approval_line:
        args.approval_line = cfg.get("overtime_approval_line")
    if not args.approval_line and not args.dry_run:
        print("❌  초과근무용 개인결재선 이름이 없습니다. --approval-line 으로 주거나")
        print("    설정 파일의 overtime_approval_line 값을 채우세요 (나이스에 미리 저장해 둔 결재선 이름).")
        sys.exit(1)

    d = date.fromisoformat(args.date)
    if d.weekday() >= 5:
        print(f"❌  {d} 은(는) 주말입니다. 이 도구는 평일 시간외 근무만 다룹니다.")
        sys.exit(1)
    start_hm = mb.round_to_step(args.start)
    end_hm = mb.round_to_step(args.end)
    if end_hm <= start_hm:
        print(f"❌  종료 시각({end_hm})이 시작 시각({start_hm})보다 늦어야 합니다.")
        sys.exit(1)

    async with async_playwright() as p:
        # 크롬 연결·로그인은 main_bokmu.run 과 같은 방식 — 위젯이 띄운 크롬(9222)이 있으면 탭으로 붙는다
        browser = None
        port = int(os.environ.get("NEIS_CDP_PORT", "9222"))
        if mb._cdp_alive(port):
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            print(f"🔗  이미 떠 있는 나이스 크롬(포트 {port})에 붙습니다")
        context = browser.contexts[0] if browser else await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="chrome",
            headless=False,
            slow_mo=50,
            args=[
                "--profile-directory=Default",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=PrivateNetworkAccessForNavigations,PrivateNetworkAccessPermissionPrompt,PermissionChip",
                "--disable-web-security",
                "--allow-running-insecure-content",
                "--test-type",
                "--noerrdialogs",
                *teacher_config.window_args(),
            ],
            ignore_default_args=["--enable-automation", "--no-sandbox"],
            viewport=None,
        )
        await context.grant_permissions(["notifications"], origin=neis._origin_of(neis.NEIS_URL))
        if browser:
            page = await context.new_page()
            if not os.environ.get("NEIS_HIDE"):
                try:
                    s = await context.new_cdp_session(page)
                    wid = (await s.send("Browser.getWindowForTarget"))["windowId"]
                    await s.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                    await s.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "maximized"}})
                    await page.bring_to_front()
                except Exception:
                    pass
        else:
            page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        # 0 은 «상신 확인창까지 눌렀다» 일 때만. 1 은 «확인 필요» — 자동으로 다시 돌리지 말 것 (두 번 상신)
        exit_code = 0
        try:
            await page.goto(neis.NEIS_URL)
            await neis.auto_login(page)
            await page.wait_for_selector("text=로그아웃", timeout=120_000)
            await page.wait_for_timeout(1000)
            print("✅  로그인 완료")
            await neis.dismiss_notice_popup(page, timeout=2000)

            dialog = await open_overtime_modal(page)
            print("✅  초과근무신청 창 진입")

            await fill_overtime_form(page, dialog, d, start_hm, end_hm, args.task)
            got = await read_back(dialog)
            print(f"✅  폼 입력 완료: 시간외 근무 {d} {start_hm}~{end_hm} 하여야 할 일='{args.task}'")
            print(f"🔎  나이스에 들어간 값: 일자 {got['일자']} · {got['시작']}~{got['종료']} · "
                  f"인정시간 합 {got['인정시간합']} · 하여야 할 일 '{got['하여야할일']}'")

            await page.screenshot(path="overtime_form_filled.png")
            print("📸  스크린샷 저장: overtime_form_filled.png")

            if args.dry_run:
                print("🧪  --dry-run 모드: 승인요청을 누르지 않고 종료합니다.")
            else:
                ok = await mb.submit(page, dialog, approval_line=args.approval_line, dump_popup=args.dump_popup)
                if ok:
                    print("🎉  결재선 지정 + 상신 완료!")
                else:
                    exit_code = 1
                    print("⚠️  자동 상신을 끝내지 못해 사람에게 넘겼습니다.")
                    print("    나이스에서 상신 상태를 꼭 직접 확인하세요.")

            print("\n브라우저는 15초 후 자동으로 닫힙니다...")
            try:
                await page.wait_for_timeout(15_000)
            except Exception:
                pass   # 그사이 창을 닫으셔도 결과는 그대로다
        except Exception as e:
            import traceback
            print(f"\n❌  오류 발생: {e}")
            traceback.print_exc()
            head = [ln.strip() for ln in str(e).splitlines() if ln.strip()][:3]
            print("❌  멈춘 곳: " + " / ".join(head)[:300], file=sys.stderr, flush=True)
            exit_code = 1
            print("\n⚠️  브라우저는 열려 있습니다. 확인 후 Enter를 누르세요.")
            try:
                input("브라우저 닫으려면 Enter...")
            except EOFError:
                pass
        finally:
            try:
                if browser:
                    await page.close()      # 남의 크롬 — 내 탭만 닫는다
                else:
                    await context.close()
            except Exception:
                pass
        return exit_code


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="나이스 초과근무(평일 시간외 근무) 신청")
    parser.add_argument("--date", required=True, help="초과근무일자 YYYY-MM-DD (평일만)")
    parser.add_argument("--start", required=True, help="시작 시각 HH:MM")
    parser.add_argument("--end", required=True, help="종료 시각 HH:MM")
    parser.add_argument("--task", required=True, help="하여야 할 일")
    parser.add_argument("--approval-line", default=None,
                        help="개인결재선 이름 (없으면 설정 파일의 overtime_approval_line)")
    parser.add_argument("--dry-run", action="store_true", help="폼만 채우고 승인요청은 누르지 않음")
    parser.add_argument("--dump-popup", action="store_true",
                        help="상신 뒤 뜨는 확인창의 outerHTML 을 남긴다 (진단용)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)) or 0)


if __name__ == "__main__":
    main()
