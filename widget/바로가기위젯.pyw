# -*- coding: utf-8 -*-
"""나이스·에듀파인 바로가기 위젯 — 바탕화면에 떠 있는 작은 단추 넷.

  .\\.venv\\Scripts\\pythonw.exe widget\\바로가기위젯.pyw      (설정하면 바탕화면 바로가기가 생긴다)

  [나이스] [출결] [출결마감] [에듀파인] [물품구입] [문서등록대장] [공람] [검수] [복무]  — 나이스·에듀파인·물품구입·문서등록대장·공람은 누르면 인증서 자동 로그인까지 해서 그 화면을 맨 앞에 띄운다.
  [물품구입]: 업무를 «학교회계» 로 바꿔 품의/정산 > 품의등록 빈 화면을 열고 제목·개요 틀(설정 punui_title·punui_body)만 채운다. 저장은 안 한다.
  [검수]: 밀린 검사검수 건을 조회해 목록을 보여 주고, [등록하기]를 눌러야 등록한다 (edufine_inspect.py --go).
  [복무]: 작은 창에서 종류(조퇴·외출·지각·병조퇴·병외출·병지각)·날짜·시각·사유를 고르고 [상신]을 누르면 나이스에 승인요청까지 올린다
          (main_bokmu.py). 종료 시각 기본값은 설정의 «퇴근 시각»(학교마다 다르다 — 처음 설정에서 묻는다).
  위젯이 뜰 때 두 크롬을 «최소화된 채로» 미리 로그인해 두고 5분마다 세션을 살려 두므로, 클릭은 보통 1~2초.
  오른쪽 클릭: 인증서 설정 · 미리 열어두기 켜고 끄기 · 크롬 창 닫기 · 위젯 끄기.  끌어서 옮길 수 있다.
  위젯이 안 보이면 바탕화면 바로가기를 한 번 더 누른다 — 떠 있던 위젯이 앞으로 나온다 (멈춰 있었으면 새로 뜬다).
  2초마다 «숨었나·화면 밖인가·맨 위가 풀렸나»를 보고 되돌린다 (모니터·프로젝터를 빼거나 해상도가 바뀐 경우).

안 될 때: %LOCALAPPDATA%\\neis-automation\\widget.log 에 무슨 명령이 얼마 걸려 어떻게 끝났는지 한 줄씩 남는다.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "바로가기_엔진.py"
SETUP = HERE / "바로가기_설정.py"
PY = Path(sys.executable).with_name("python.exe")
BASE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "neis-automation"
STATE = BASE / "widget_state.json"
LOG = BASE / "widget.log"
CONFIG = BASE / "teacher_config.json"
NO_WINDOW = 0x08000000
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
WARM_EVERY = 5 * 60 * 1000
RELAUNCH_EVERY = 60 * 1000      # 크롬을 닫았으면 1분 안에 다시 최소화로 띄워 데운다 (안 데우려면 메뉴 «미리 열어두기» 끄기)
PORTS = {"neis": 9322, "edufine": 9324}

BG, INK, LINE = "#fffaf2", "#3b2f25", "#d9ccb8"
BTNS = [("나이스", "neis", "open", "#1b6fb5"),
        ("출결", "attend", "form", "#2a6fdb"), ("출결마감", "monthclose", "form", "#7a5a1f"),   # 나이스 일 — 나이스 바로 옆 (11/18 선생님 요청)
        ("에듀파인", "edufine", "main", "#2f7d4f"),
        ("물품구입", "edufine", "punui", "#1f7a7a"),      # 학교회계 → 품의등록 빈 화면 + 제목·개요 틀 (저장 안 함)
        ("문서등록대장", "edufine", "open", "#8a5a2b"), ("공람", "edufine", "cnrs", "#6b4fb5"),
        ("검수", "inspect", "check", "#d63a30"), ("복무", "bokmu", "form", "#c2417a")]
ATTEND = HERE.parent / "attendance_quick.py"       # 키트의 «한 줄 문장 → 일일출결관리» (풀이 / 넣기 / 명단)
MONTH_CLOSE = HERE.parent / "month_close.py"       # 키트의 월 출결마감 (일마감 + 월마감 한 번에)
INSPECT = HERE.parent / "edufine_inspect.py"      # 키트의 물품 검사검수 (조회만 / --go 등록)
BOKMU = HERE.parent / "main_bokmu.py"             # 키트의 복무(근무상황) 상신
OVERTIME = HERE.parent / "main_overtime.py"         # 키트의 초과근무(평일 시간외) 상신
BOKMU_TYPES = ["조퇴", "외출", "지각", "병조퇴", "병외출", "병지각", "41조연수", "초과근무"]
MUTEX = "neis-edufine-widget"
SHOW_EVENT, ACK_EVENT = "neis-edufine-widget-show", "neis-edufine-widget-shown"   # 바로가기를 또 누르면 «앞으로 나와» / «나왔어»
GUARD_EVERY = 5                 # tick(0.4초) 다섯 번마다 = 2초마다 «보이나·화면 안인가·맨 위인가» 확인


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    BASE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def log(what, lines, t0):
    try:
        steps = " / ".join(ln[5:].split("  (")[0] for ln in lines if ln.startswith("STEP "))[:300]
        last = next((ln for ln in reversed(lines) if ln.startswith(("READY", "FAIL", "CLOSED"))), "(없음)")
        row = "%s  %s  %.1fs  %s  [%s]" % (datetime.now().strftime("%m-%d %H:%M:%S"), what, time.time() - t0, last[:100], steps)
        old = LOG.read_text(encoding="utf-8").splitlines()[-300:] if LOG.exists() else []
        BASE.mkdir(parents=True, exist_ok=True)
        LOG.write_text("\n".join(old + [row]) + "\n", encoding="utf-8")
    except Exception:
        pass


def log_line(text):
    try:
        old = LOG.read_text(encoding="utf-8").splitlines()[-300:] if LOG.exists() else []
        BASE.mkdir(parents=True, exist_ok=True)
        LOG.write_text("\n".join(old + ["%s  %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), text[:300])]) + "\n", encoding="utf-8")
    except Exception:
        pass


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def fit_on_screen(x, y, w, h):
    """위젯 네 귀퉁이가 모두 어떤 모니터 위에 있으면 그대로, 하나라도 밖이면 가장 가까운 모니터의 작업 영역 안으로.
    모니터를 빼거나(TV·프로젝터) 해상도가 바뀌면 저장해 둔 자리가 화면 밖이 된다 — 그러면 위젯은 떠 있는데 안 보인다 (10/23 재현)."""
    u = ctypes.windll.user32
    u.MonitorFromPoint.restype = wt.HMONITOR
    u.MonitorFromRect.restype = wt.HMONITOR
    corners = [(x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)]
    if all(u.MonitorFromPoint(wt.POINT(cx, cy), 0) for cx, cy in corners):     # 0 = MONITOR_DEFAULTTONULL
        return x, y
    hm = u.MonitorFromRect(ctypes.byref(wt.RECT(x, y, x + w, y + h)), 2)       # 2 = MONITOR_DEFAULTTONEAREST
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    if not hm or not u.GetMonitorInfoW(hm, ctypes.byref(mi)):
        return x, y
    a = mi.rcWork
    return max(a.left, min(x, a.right - w)), max(a.top, min(y, a.bottom - h))


def _kernel32():
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = k.CreateEventW.restype = k.OpenEventW.restype = wt.HANDLE
    k.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    k.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    k.SetEvent.argtypes = k.ResetEvent.argtypes = k.CloseHandle.argtypes = [wt.HANDLE]
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    return k


def kill_other_widgets():
    """대답 없는(멈춘) 위젯을 끈다 — 나와 내 부모(venv 의 pythonw 런처)는 빼고."""
    try:
        import psutil
        me = psutil.Process()
        mine = {me.pid} | {p.pid for p in me.parents()}
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            args = p.info.get("cmdline") or []
            if p.info["pid"] not in mine and (p.info.get("name") or "").lower().startswith("python") \
                    and any(a.endswith(("바로가기위젯.pyw", "바로가기위젯_상벌점.pyw")) for a in args[1:3]):
                p.kill()
    except Exception:
        pass


def single_instance():
    """위젯은 하나만. 이미 떠 있으면 그 위젯을 «앞으로 나오게» 하고 True(나는 끝낸다)를 돌려준다.
    예전엔 그냥 꺼졌다 — 작업표시줄 아이콘이 없는 창이라, 숨은 위젯은 설치 파일을 다시 돌려야만 되찾을 수 있었다 (10/23 제보).
    떠 있는 위젯이 5초 안에 대답이 없으면(멈춤) 끄고 내가 대신 뜬다."""
    k = _kernel32()
    globals()["_mutex"] = k.CreateMutexW(None, False, MUTEX)
    if k.GetLastError() != 183:                     # 183 = ERROR_ALREADY_EXISTS
        return False
    show = k.OpenEventW(0x00100002, False, SHOW_EVENT)     # SYNCHRONIZE | EVENT_MODIFY_STATE
    ack = k.OpenEventW(0x00100002, False, ACK_EVENT)
    if show and ack:
        k.ResetEvent(ack)
        k.SetEvent(show)
        if k.WaitForSingleObject(ack, 5000) == 0:
            return True
    log_line("widget  떠 있는 위젯이 대답이 없어 끄고 새로 띄움")
    kill_other_widgets()
    for _ in range(50):                             # 죽은 프로세스의 뮤텍스가 풀릴 때까지
        time.sleep(0.1)
        k.CloseHandle(globals()["_mutex"])
        globals()["_mutex"] = k.CreateMutexW(None, False, MUTEX)
        if k.GetLastError() != 183:
            break
    return False


def port_alive(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1.5) as r:
            return bool(json.load(r).get("Browser"))
    except Exception:
        return False


def configured():
    try:
        return bool(json.loads(CONFIG.read_text(encoding="utf-8")).get("cert_name"))
    except Exception:
        return False


def cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def round5(hm):
    h, m = map(int, hm.split(":"))
    m = round(m / 5) * 5
    if m == 60:
        h, m = (h + 1) % 24, 0
    return "%02d:%02d" % (h, m)


WEEK = "월화수목금토일"


def date_label(iso):
    """2026-10-16 → «2026-10-16 (금) 📅» (단추 글자)"""
    from datetime import date
    try:
        return "%s (%s)  📅" % (iso, WEEK[date.fromisoformat(iso).weekday()])
    except ValueError:
        return iso + "  📅"


def date_picker(parent, var, bg, on_pick=None):
    """작은 달력 — 날짜를 누르면 var 에 YYYY-MM-DD 가 들어간다 (10/16 사용자: 날짜는 치지 말고 달력에서 클릭)"""
    import calendar
    from datetime import date
    f, fb = ("Malgun Gothic", 8), ("Malgun Gothic", 9, "bold")
    try:
        d0 = date.fromisoformat(var.get())
    except ValueError:
        d0 = date.today()
    shown = [d0.year, d0.month]
    box = tk.Frame(parent, bg=bg)
    head = tk.Frame(box, bg=bg)
    head.pack(fill="x")
    title = tk.Label(head, bg=bg, font=fb)
    days = tk.Frame(box, bg=bg)
    days.pack()

    def move(step):
        y, m = shown[0], shown[1] + step
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        shown[:] = [y, m]
        draw()

    def pick(iso):
        var.set(iso)
        draw()
        if on_pick:
            on_pick(iso)

    def draw():
        for w in days.winfo_children():
            w.destroy()
        y, m = shown
        title.config(text="%d년 %d월" % (y, m))
        for i, d in enumerate("일월화수목금토"):           # 일요일부터 — 우리 달력 모양
            tk.Label(days, text=d, bg=bg, font=f, width=3,
                     fg="#c0392b" if i == 0 else "#1b6fb5" if i == 6 else "#8a7a68").grid(row=0, column=i)
        sel, today = var.get(), date.today().isoformat()
        for r, week in enumerate(calendar.Calendar(firstweekday=6).monthdayscalendar(y, m), start=1):
            for c, d in enumerate(week):
                if not d:
                    continue
                iso = "%04d-%02d-%02d" % (y, m, d)
                on = iso == sel
                tk.Button(days, text=str(d), width=3, relief="flat", bd=0, font=f, cursor="hand2",
                          bg="#c2417a" if on else "#fde7f0" if iso == today else "white",
                          fg="white" if on else "#c0392b" if c == 0 else "#1b6fb5" if c == 6 else "#3b2f25",
                          activebackground="#f4c2d7",
                          command=lambda iso=iso: pick(iso)).grid(row=r, column=c, padx=1, pady=1)
    tk.Button(head, text="◀", relief="flat", bd=0, bg=bg, font=f, cursor="hand2", command=lambda: move(-1)).pack(side="left", padx=4)
    tk.Button(head, text="▶", relief="flat", bd=0, bg=bg, font=f, cursor="hand2", command=lambda: move(1)).pack(side="right", padx=4)
    title.pack(side="left", expand=True)
    draw()
    return box


class Widget:
    def __init__(self):
        st = load_state()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        sw = self.root.winfo_screenwidth()
        self.root.geometry("+%d+%d" % (st.get("x", sw - 470), st.get("y", 12)))
        self.prewarm = st.get("prewarm", False)   # 기본 끔 — 누르기 전에 창이 뜨면 «안 누른 문서등록대장이 켜진다»로 보인다 (2026-10-23)
        self.locks = {"neis": threading.Lock(), "edufine": threading.Lock(), "inspect": threading.Lock()}
        self.busy = None
        self.note = ("", INK)
        self.dragging = False
        self.ticks = 0
        self.root.report_callback_exception = lambda *a: log_line("ERROR  " + " ".join(str(x) for x in a[:2]))
        k = _kernel32()
        self.ev_show = k.CreateEventW(None, False, False, SHOW_EVENT)   # 자동 리셋
        self.ev_ack = k.CreateEventW(None, False, False, ACK_EVENT)

        fr = tk.Frame(self.root, bg=BG, highlightbackground=LINE, highlightthickness=1)
        fr.pack()
        grip = tk.Label(fr, text="⋮", bg=BG, fg="#b5a593", font=("Malgun Gothic", 12), cursor="fleur", padx=4)
        grip.pack(side="left", fill="y")
        self.buttons = {}
        for text, site, cmd, color in BTNS:
            b = tk.Label(fr, text=text, bg=BG, fg=color, font=("Malgun Gothic", 10, "bold"), padx=9, pady=6, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, s=site, c=cmd, t=text: self.click(s, c, t))
            b.bind("<Enter>", lambda e, w=b: w.configure(bg="#f3e9da"))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=BG))
            self.buttons[text] = b
        self.status = tk.Label(fr, text="", bg=BG, fg="#8a7a68", font=("Malgun Gothic", 9), padx=6)
        self.spacer = tk.Label(fr, text=" ", bg=BG, font=("Malgun Gothic", 12), padx=4)   # 왼쪽 ⋮ 와 같은 폭 → 좌우 대칭
        self.spacer.pack(side="left", fill="y")
        for w in (fr, grip):
            w.bind("<ButtonPress-1>", self.press)
            w.bind("<B1-Motion>", self.drag)
            w.bind("<ButtonRelease-1>", self.release)
        for w in (fr, grip, self.status, *self.buttons.values()):
            w.bind("<Button-3>", self.menu)

        self.m = tk.Menu(self.root, tearoff=0, font=("Malgun Gothic", 9))
        self.m.add_command(label="인증서 설정 (처음 한 번)", command=self.open_setup)
        self.prewarm_var = tk.BooleanVar(value=self.prewarm)
        self.m.add_checkbutton(label="미리 열어두기 (빠른 클릭)", variable=self.prewarm_var, command=self.toggle_prewarm)
        self.m.add_command(label="지금 미리 열어두기", command=lambda: self.warm_all(True))
        self.m.add_command(label="반 명단 다시 읽기 (출결용)", command=self.attend_roster)
        self.m.add_separator()
        self.m.add_command(label="위젯용 크롬 창 닫기", command=self.close_chrome)
        self.m.add_command(label="위젯 끄기", command=self.root.destroy)

    # ── 끌기 ──
    def press(self, e):
        self.dragging = True
        self.sx, self.sy = e.x_root, e.y_root
        self.wx, self.wy = self.root.winfo_x(), self.root.winfo_y()

    def drag(self, e):
        self.root.geometry("+%d+%d" % (self.wx + e.x_root - self.sx, self.wy + e.y_root - self.sy))

    def release(self, e):
        self.dragging = False
        self.keep_visible()                      # 화면 밖으로 끌어 놓았으면 안으로 되돌린 뒤 저장
        save_state(x=self.root.winfo_x(), y=self.root.winfo_y())

    # ── 안 보이게 되지 않게 ──
    def hwnd(self):
        try:
            return int(self.root.wm_frame(), 16)
        except Exception:
            return 0

    def keep_visible(self, raise_=False):
        """최소화·숨김이면 다시 보이게, 화면 밖이면 안으로, 맨 위(topmost)가 풀렸으면 다시. raise_=True 면 맨 앞으로 꺼낸다.
        저장해 둔 자리는 바꾸지 않는다 — 프로젝터를 잠깐 뺀 것 때문에 선생님이 정한 자리를 잃지 않게 (끌어서 놓을 때만 저장)."""
        try:
            u = ctypes.windll.user32
            h = self.hwnd()
            if self.root.state() != "normal" or (h and (not u.IsWindowVisible(h) or u.IsIconic(h))):
                self.root.deiconify()
                log_line("widget  숨어 있던 위젯을 다시 보이게 함 (state=%s)" % self.root.state())
            self.root.update_idletasks()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            nx, ny = fit_on_screen(x, y, self.root.winfo_width(), self.root.winfo_height())
            if (nx, ny) != (x, y):
                self.root.geometry("+%d+%d" % (nx, ny))
                log_line("widget  화면 밖(%d,%d) → 안(%d,%d)으로 옮김" % (x, y, nx, ny))
            if h and (raise_ or not (u.GetWindowLongW(h, -20) & 0x8)):    # -20 = GWL_EXSTYLE, 8 = WS_EX_TOPMOST
                self.root.attributes("-topmost", True)
                u.SetWindowPos(wt.HWND(h), wt.HWND(-1), 0, 0, 0, 0, 0x0013)   # HWND_TOPMOST · NOSIZE|NOMOVE|NOACTIVATE
        except Exception as e:
            log_line("widget  keep_visible 오류 %r" % e)

    def come_back(self):
        """바로가기를 또 눌렀다 — 숨었든 화면 밖이든 앞으로 꺼내고 «여기 있어요» 라고 알린다."""
        self.keep_visible(raise_=True)
        self.say("여기 있어요!", "#2f7d4f", 3000)
        log_line("widget  바로가기를 다시 눌러 앞으로 꺼냄")

    def menu(self, e):
        self.m.tk_popup(e.x_root, e.y_root)

    # ── 말풍선 ──
    def show_status(self, text, color):
        """상태 글자는 있을 때만 막대에 붙인다 (없을 땐 빼서 단추만 남게)."""
        if text:
            self.status.configure(text=text, fg=color)
            if not self.status.winfo_ismapped():
                self.status.pack(side="left", before=self.spacer)
        else:
            self.status.configure(text="")
            self.status.pack_forget()

    def say(self, text, color=INK, ms=4000):
        self.show_status(text, color)
        self.root.after(ms, lambda: self.show_status("", color) if self.status.cget("text") == text else None)

    def tick(self):
        if self.busy:
            dots = "." * (int(time.time() * 2) % 3 + 1)
            self.show_status(self.busy + dots, "#8a7a68")
            self._shown_busy = self.busy
        elif getattr(self, "_shown_busy", None):     # 일이 끝났는데 «…읽는 중...» 이 남아 있으면 지운다 (11/18)
            if self.status.cget("text").startswith(self._shown_busy):
                self.show_status("", INK)
            self._shown_busy = None
        k = ctypes.windll.kernel32
        if self.ev_show and k.WaitForSingleObject(wt.HANDLE(self.ev_show), 0) == 0:
            self.come_back()
            k.SetEvent(wt.HANDLE(self.ev_ack))
        self.ticks += 1
        if self.ticks % GUARD_EVERY == 0 and not self.dragging:
            self.keep_visible()
        self.root.after(400, self.tick)

    # ── 엔진 부르기 ──
    def run(self, site, cmd, extra=(), what=None, on_step=None):
        t0 = time.time()
        seen, last = [], ""
        with self.locks[site]:
            p = subprocess.Popen([str(PY), "-X", "utf8", str(ENGINE), site, cmd, *extra], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                 env=ENV, cwd=str(HERE), creationflags=NO_WINDOW)
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(p.pid)   # 클릭을 받은 건 위젯 — 창 꺼낼 권한을 넘긴다
            except Exception:
                pass
            for line in p.stdout:
                line = line.strip()
                seen.append(line)
                if line.startswith("STEP ") and on_step:
                    on_step(line[5:].split("  (")[0])
                elif line.startswith(("READY", "FAIL", "CLOSED")):
                    last = line
            p.wait()
        log(what or "%s %s" % (site, cmd), seen, t0)
        return last

    def click(self, site, cmd, text):
        if self.busy:
            return
        if not configured():
            self.say("먼저 오른쪽 클릭 → 인증서 설정", "#c0392b", 6000)
            return
        if site == "inspect":
            self.inspect_check()
            return
        if site == "bokmu":
            self.bokmu_form()
            return
        if site == "attend":
            self.attend_form()
            return
        if site == "monthclose":
            self.close_form()
            return
        self.busy = text + " 여는 중"

        def fn():
            try:
                last = self.run(site, cmd, what="click " + text, on_step=lambda s: setattr(self, "busy", s))
            finally:
                self.busy = None
            if last.startswith("READY"):
                self.root.after(0, self.say, "짠! 열렸어요", "#2f7d4f")
            else:
                self.root.after(0, self.say, "앗, 실패: " + (last[5:] or "알 수 없는 오류"), "#c0392b", 10000)
        threading.Thread(target=fn, daemon=True).start()

    # ── 검수 (물품 검사검수) ──
    def run_inspect(self, go):
        """edufine_inspect.py 를 돌려 RESULT_JSON 을 돌려준다. 자기 크롬(chrome_profile_edufine)을 띄우므로 창이 보인다."""
        t0 = time.time()
        args = [str(PY), "-X", "utf8", str(INSPECT)] + (["--go"] if go else [])
        with self.locks["inspect"]:
            p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=ENV, cwd=str(INSPECT.parent), creationflags=NO_WINDOW, timeout=900)
        lines = (p.stdout or "").splitlines() + (p.stderr or "").splitlines()
        res = next((ln[12:] for ln in reversed(lines) if ln.startswith("RESULT_JSON=")), "")
        log("inspect" + (" --go" if go else ""), ["READY " + res[:80] if res else "FAIL " + " ".join(lines[-3:])[:120]], t0)
        try:
            return json.loads(res)
        except Exception:
            return None

    def inspect_check(self):
        self.busy = "검수 대기 조회 중"

        def fn():
            try:
                r = self.run_inspect(False)
            finally:
                self.busy = None
            if r is None:
                self.root.after(0, self.say, "앗, 검수 목록을 못 읽었어요 (widget.log 참고)", "#c0392b", 10000)
                return
            pend = r.get("대기", [])
            if not pend:
                self.root.after(0, self.say, "검수 대기 0건 — 할 게 없어요", "#2f7d4f", 6000)
                return
            text = "검수 대기 %d건\n\n" % len(pend) + "\n".join(
                "• %s  %s  (요청 %s · 완료요구 %s)" % (x.get("계약번호", ""), x.get("계약명", ""), x.get("요청일자", ""), x.get("완료요구일", ""))
                for x in pend) + "\n\n[등록하기]를 누르면 위 건을 모두 검사검수 등록합니다. 되돌리기 어렵습니다."
            self.root.after(0, self.confirm, text, "등록하기", self.inspect_go)
        threading.Thread(target=fn, daemon=True).start()

    def inspect_go(self):
        self.busy = "검수 등록 중"

        def fn():
            try:
                r = self.run_inspect(True)
            finally:
                self.busy = None
            if r is None:
                self.root.after(0, self.say, "앗, 검수 등록 결과를 못 받았어요 (widget.log 참고)", "#c0392b", 10000)
                return
            done = r.get("처리", [])
            ok = sum(1 for x in done if x.get("성공"))
            bad = [x for x in done if not x.get("성공")]
            msg = "검수 등록 끝 — 성공 %d건" % ok + ("\n실패 %d건:\n" % len(bad) + "\n".join("• %s %s" % (x.get("계약번호", ""), x.get("오류", "")[:80]) for x in bad) if bad else "")
            self.root.after(0, self.info, msg)
        threading.Thread(target=fn, daemon=True).start()

    # ── 출결 (한 줄 문장 → 일일출결관리) ──
    def run_kit(self, script, args, what, timeout=900):
        """키트 스크립트를 돌려 RESULT_JSON(= 또는 공백 뒤)을 돌려준다. 나이스 작업끼리는 겹치지 않게 neis 자물쇠."""
        t0 = time.time()
        with self.locks["neis"]:
            p = subprocess.run([str(PY), "-X", "utf8", str(script), *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=ENV, cwd=str(script.parent),
                               creationflags=NO_WINDOW, timeout=timeout)
        lines = (p.stdout or "").splitlines() + (p.stderr or "").splitlines()
        res = next((ln.split("RESULT_JSON", 1)[1].lstrip("= ") for ln in reversed(lines) if ln.startswith("RESULT_JSON")), "")
        log(what, ["READY " + res[:80] if res else "FAIL " + " ".join(lines[-3:])[:120]], t0)
        try:
            return json.loads(res), lines
        except Exception:
            return None, lines

    def attend_form(self, text=None, note=""):
        """출결 문장 창. 적은 문장은 지우지 않는다 — 고칠 곳이 있거나 [닫기]를 눌러도 다음에 그대로 다시 뜬다.
        다 저장된 뒤에만 비운다 (11/18 선생님 요청)."""
        if text is None:
            text = getattr(self, "attend_text", "")
        tip, fr = self.popup("출결 — 한 줄에 한 학생. 예) 홍길동 질병지각 4교시 이후 등교\n"
                             "[풀어 보기]를 누르면 어떻게 읽었는지 먼저 보여 드리고, [나이스에 넣기]를 눌러야 들어갑니다.")
        if note:
            tk.Label(fr, text=note, bg=BG, fg="#c0392b", font=("Malgun Gothic", 9), justify="left",
                     wraplength=420).pack(padx=12, pady=(0, 4), anchor="w")
        box = tk.Text(fr, font=("Malgun Gothic", 10), width=46, height=4, wrap="word")
        box.pack(padx=12, pady=(0, 4))
        if text:
            box.insert("1.0", text)

        def keep():
            self.attend_text = box.get("1.0", "end").strip()
        tk.Label(fr, text="분류: 질병·미인정·출석인정(체험학습) · 종류: 결석·지각·조퇴\n"
                          "지각 «4교시 이후 등교»=1~4교시 빠짐 · «3교시에 등교»=1~2교시 빠짐 · 조퇴 «4교시 이후 조퇴»=5교시부터\n"
                          "날짜를 안 적으면 오늘 · «어제» «11/17» · 결석 기간 «11/17~11/19»",
                 bg=BG, fg="#8a7a68", font=("Malgun Gothic", 8), justify="left", wraplength=420).pack(padx=12, anchor="w")
        btns = tk.Frame(fr, bg=BG)
        btns.pack(pady=(4, 10))

        def go():
            keep()
            if not self.attend_text:
                self.say("출결 문장을 적어 주세요", "#c0392b", 4000)
                return
            tip.destroy()
            self.attend_parse(self.attend_text)

        def close():
            keep()                                  # 닫아도 적은 문장은 남겨 둔다
            tip.destroy()

        def clear():
            box.delete("1.0", "end")
            self.attend_text = ""
            box.focus_set()
        tk.Button(btns, text="풀어 보기", font=("Malgun Gothic", 9, "bold"), bg="#2a6fdb", fg="white", relief="flat",
                  padx=12, command=go).pack(side="left", padx=4)
        tk.Button(btns, text="지우기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=clear).pack(side="left", padx=4)
        tk.Button(btns, text="닫기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=close).pack(side="left", padx=4)
        box.focus_set()
        box.mark_set("insert", "end")

    def attend_parse(self, text):
        self.busy = "출결 문장 읽는 중"

        def fn():
            try:
                r, lines = self.run_kit(ATTEND, ["풀이", text], "attend parse", timeout=60)
            finally:
                self.busy = None
            self.root.after(0, self.attend_show, text, r, lines)
        threading.Thread(target=fn, daemon=True).start()

    def attend_show(self, text, r, lines):
        if r is None:
            self.attend_form(text, "앗, 문장을 못 풀었어요: " + " ".join(lines[-2:])[:200])
            return
        ok_lines = "\n".join("• " + x["요약"] for x in r.get("풀이", []))
        ask = "\n".join("❓ «%s» — %s" % (x["문장"], x["이유"]) for x in r.get("물을것", []))
        if ask:                                     # 문장을 그대로 다시 띄워 고칠 곳만 고치게
            self.attend_form(text, ("이렇게 읽었어요:\n" + ok_lines + "\n" if ok_lines else "") + ask
                             + "\n아래 문장에서 고칠 곳만 고쳐 다시 [풀어 보기]를 눌러 주세요. (아무것도 넣지 않았어요)")
            return
        tip, fr = self.popup("이렇게 나이스 일일출결관리에 넣고 저장합니다:\n\n" + ok_lines
                             + "\n\n맞으면 [나이스에 넣기]. 틀렸으면 [고치기] — 적은 문장이 그대로 다시 뜹니다.")
        btns = tk.Frame(fr, bg=BG)
        btns.pack(pady=(0, 10))
        tk.Button(btns, text="나이스에 넣기", font=("Malgun Gothic", 9, "bold"), bg="#2a6fdb", fg="white", relief="flat",
                  padx=12, command=lambda: (tip.destroy(), self.attend_enter(text))).pack(side="left", padx=4)
        tk.Button(btns, text="고치기", font=("Malgun Gothic", 9), relief="flat", padx=10,
                  command=lambda: (tip.destroy(), self.attend_form(text))).pack(side="left", padx=4)
        tk.Button(btns, text="닫기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=tip.destroy).pack(side="left", padx=4)

    def attend_enter(self, text):
        self.busy = "출결 넣는 중"

        def fn():
            try:
                r, lines = self.run_kit(ATTEND, ["넣기", text], "attend enter")
            finally:
                self.busy = None
            if r is None:
                self.root.after(0, self.info, "앗, 결과를 못 받았어요. 나이스 일일출결관리에서 직접 확인해 주세요.\n\n"
                                + "\n".join(lines[-4:])[:400])
                return
            got = "\n".join("• %s %s번: %s" % (x["날짜"][5:], x["번호"], x.get("줄") or "(줄을 못 읽음)") for x in r.get("확인", []))
            bad = "\n".join("❌ %s %s번: %s" % (x["날짜"][5:], x["번호"], x["이유"][:90]) for x in r.get("실패", []))
            if r.get("ok"):
                self.attend_text = ""               # 다 들어갔을 때만 문장을 비운다
                self.root.after(0, self.info, "출결 저장 끝 — 나이스에서 다시 읽은 줄:\n\n" + got)
            else:                                   # 문장은 남겨 둔다 — [출결]을 다시 누르면 그대로 뜬다
                self.root.after(0, self.info, "일부가 안 들어갔어요:\n\n" + got + ("\n\n" + bad if bad else "")
                                + "\n\n적은 문장은 남겨 두었어요. [출결]을 다시 누르면 그대로 뜹니다.\n"
                                  "(이미 들어간 학생은 문장에서 그 줄만 지우고 다시 넣으세요 — 두 번 넣지 않게)")
        threading.Thread(target=fn, daemon=True).start()

    def attend_roster(self):
        if self.busy:
            return
        self.busy = "반 명단 읽는 중"

        def fn():
            try:
                r, lines = self.run_kit(ATTEND, ["명단"], "attend roster")
            finally:
                self.busy = None
            if r and r.get("ok"):
                self.root.after(0, self.say, "반 명단 %d명 읽었어요" % r.get("명수", 0), "#2f7d4f", 6000)
            else:
                self.root.after(0, self.info, "앗, 반 명단을 못 읽었어요.\n\n" + ((r or {}).get("error") or "\n".join(lines[-3:]))[:300])
        threading.Thread(target=fn, daemon=True).start()

    # ── 마감 (월 출결마감: 일마감 + 월마감 한 번에) ──
    def close_form(self):
        t = datetime.now()
        prev = (t.replace(day=1) - timedelta(days=1))
        default = t if t.day >= 25 else prev          # 말일 무렵이면 이번 달, 아니면 지난달
        tip, fr = self.popup("월 출결마감 — 그 달의 일마감(한 번에)과 월마감을 합니다.\n"
                             "[상태 보기]는 아무것도 누르지 않고 마감 상태만 읽습니다.")
        g = tk.Frame(fr, bg=BG)
        g.pack(padx=12, anchor="w")
        tk.Label(g, text="달", bg=BG, fg=INK, font=("Malgun Gothic", 9)).pack(side="left")
        v = tk.StringVar(value=default.strftime("%Y-%m"))
        tk.Entry(g, textvariable=v, font=("Malgun Gothic", 10), width=9).pack(side="left", padx=8)
        btns = tk.Frame(fr, bg=BG)
        btns.pack(pady=(8, 10))

        def run(commit):
            ym = v.get().strip()
            if not re.fullmatch(r"\d{4}-\d{1,2}", ym):
                self.say("달은 2026-10 처럼 적어 주세요", "#c0392b", 5000)
                return
            tip.destroy()
            if commit:
                self.confirm("%s 일마감 + 월마감을 합니다.\n마감한 날은 출결을 더 넣을 수 없어요 (나이스에서 마감취소 해야 함).\n"
                             "그 달 출결을 다 넣으셨으면 [마감하기]." % ym, "마감하기", lambda: self.close_run(ym, True))
            else:
                self.close_run(ym, False)
        tk.Button(btns, text="상태 보기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=lambda: run(False)).pack(side="left", padx=4)
        tk.Button(btns, text="마감하기", font=("Malgun Gothic", 9, "bold"), bg="#7a5a1f", fg="white", relief="flat",
                  padx=12, command=lambda: run(True)).pack(side="left", padx=4)
        tk.Button(btns, text="닫기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=tip.destroy).pack(side="left", padx=4)

    def close_run(self, ym, commit):
        self.busy = "%s 마감 중" % ym if commit else "%s 마감 상태 보는 중" % ym

        def fn():
            try:
                r, lines = self.run_kit(MONTH_CLOSE, [ym] + (["--close"] if commit else []), "monthclose %s%s" % (ym, " --close" if commit else ""))
            finally:
                self.busy = None
            if r is None:
                self.root.after(0, self.info, "앗, 결과를 못 받았어요.\n\n" + "\n".join(lines[-4:])[:400])
                return
            why = {"future_month": "아직 오지 않은 달이에요", "month_not_over": "그 달 마지막 평일 전이라 마감하지 않았어요",
                   "config": "설정이 없어요"}.get(r.get("error"), r.get("error"))
            dcs = r.get("day_close") or {}
            dc = {"saved": "다 마감됨", "dry": "상태만 봄 (안 누름)", "not_all": "일부가 안 됨",
                  "month_not_set": "달을 못 골랐어요"}.get(dcs.get("status"), dcs.get("status", "?"))
            if dcs.get("status") == "dry" and dcs.get("before") is not None:
                dc += " — %s" % str(dcs["before"])[:80]
            rows = (r.get("month_close") or {}).get("rows") or []
            mc = ", ".join("%s학기 %s" % (x.get("semester", ""), x.get("state", "")) for x in rows) or \
                {"skipped": "일마감이 안 돼서 안 함", "no_row": "그 달 줄을 못 찾음"}.get((r.get("month_close") or {}).get("status"), "?")
            msg = ("%s %s\n\n일마감: %s\n월마감: %s" % (ym, "마감 끝" if (commit and r.get("ok")) else ("상태" if not commit else "마감이 다 안 됐어요"), dc, mc)
                   + ("\n\n⛔ " + why if why else "") + "\n\n나이스 출결마감 화면에서 한 번 확인해 주세요.")
            self.root.after(0, self.info, msg)
        threading.Thread(target=fn, daemon=True).start()

    # ── 복무 (근무상황 상신) ──
    def bokmu_form(self):
        c = cfg()
        now = round5(datetime.now().strftime("%H:%M"))
        end_default = c.get("work_end") or "16:20"
        tip, fr = self.popup("복무 상신 — 고르고 [상신]을 누르면 나이스에 승인요청까지 올립니다")
        g = tk.Frame(fr, bg=BG)
        g.pack(padx=12, pady=(0, 6), anchor="w")
        kind = tk.StringVar(value="조퇴")
        v_date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        v_start = tk.StringVar(value=now)
        v_end = tk.StringVar(value=end_default)
        v_reason = tk.StringVar(value="")
        v_contact = tk.StringVar(value=c.get("contact", ""))
        v_line = tk.StringVar(value=c.get("approval_line", ""))
        v_end_date = tk.StringVar(value=v_date.get())                    # 41조 연수 종료일
        v_dest = tk.StringVar(value=c.get("training_destination", ""))   # 41조 연수 목적지
        f = ("Malgun Gothic", 9)

        def row(r, label, var, width=12):
            tk.Label(g, text=label, bg=BG, fg=INK, font=f).grid(row=r, column=0, sticky="w", pady=2)
            e = tk.Entry(g, textvariable=var, font=f, width=width)
            e.grid(row=r, column=1, sticky="w", padx=(8, 0), pady=2)
            return e
        tk.Label(g, text="종류", bg=BG, fg=INK, font=f).grid(row=0, column=0, sticky="w", pady=2)
        kinds = tk.Frame(g, bg=BG)
        kinds.grid(row=0, column=1, sticky="w", padx=(8, 0))
        for i, k in enumerate(BOKMU_TYPES):      # 두 줄 × 셋 — 한 줄로 늘어놓으면 창 밖으로 나간다
            tk.Radiobutton(kinds, text=k, variable=kind, value=k, bg=BG, font=f, activebackground=BG, width=7, anchor="w").grid(row=i // 3, column=i % 3, sticky="w")
        # 날짜 — 치지 않고 단추를 눌러 달력에서 고른다
        def date_row(r, label, var):
            tk.Label(g, text=label, bg=BG, fg=INK, font=f).grid(row=r, column=0, sticky="nw", pady=2)
            df = tk.Frame(g, bg=BG)
            df.grid(row=r, column=1, sticky="w", padx=(8, 0), pady=2)
            db = tk.Button(df, text=date_label(var.get()), font=f, relief="groove", bg="white", cursor="hand2", anchor="w")
            db.pack(anchor="w")
            cal = {"box": None}

            def picked(iso):
                db.config(text=date_label(iso))
                toggle_cal()

            def toggle_cal():
                if cal["box"]:
                    cal["box"].destroy(); cal["box"] = None
                else:
                    cal["box"] = date_picker(df, var, BG, picked)
                    cal["box"].pack(anchor="w", pady=(4, 2))
                self.place_tip(tip)                    # 크기가 바뀌었으니 다시 가운데로
            db.config(command=toggle_cal)
            return db
        date_row(1, "날짜", v_date)
        row(2, "시작", v_start, 7)
        row(3, "종료", v_end, 7)
        e_reason = row(4, "사유", v_reason, 30)
        row(5, "연락처", v_contact, 16)
        row(6, "결재선", v_line, 24)
        db_end = date_row(7, "종료일", v_end_date)
        row(8, "목적지", v_dest, 16)
        hint = tk.Label(g, text="조퇴 종료 = 설정의 퇴근 시각 %s · 지각 시작 = 출근 시각 %s · 5분 단위\n"
                                "결재선 = 나이스 «개인결재선»에 이름 붙여 저장해 둔 그 이름 (없으면 나이스에서 먼저 만들어 두세요)\n"
                                "41조연수 = 날짜(시작일)~종료일 종일, 시각은 안 씀 · 목적지 필수 (예: 자택)\n"
                                "초과근무 = 평일 시간외 근무만 · 사유 칸이 «하여야 할 일» 로 들어감 · 종료일·목적지는 41조에만 씀" % (end_default, c.get("work_start") or "08:40"),
                        bg=BG, fg="#8a7a68", font=("Malgun Gothic", 8), justify="left", wraplength=420)
        hint.grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 0))

        def on_kind(*_):
            k = kind.get()
            # 결재선 — 초과근무·41조는 조퇴와 다른 결재선을 쓰는 학교가 많다
            if k == "초과근무":
                v_line.set(c.get("overtime_approval_line", ""))
            elif k == "41조연수":
                v_line.set(c.get("training_approval_line") or c.get("approval_line", ""))
            else:
                v_line.set(c.get("approval_line", ""))
            if k == "41조연수":                    # 종일 — 시각은 건드리지 않는다
                if not v_reason.get().strip() and c.get("training_reason"):
                    v_reason.set(c["training_reason"])
                if v_end_date.get() < v_date.get():
                    v_end_date.set(v_date.get()); db_end.config(text=date_label(v_date.get()))
                return
            if k == "초과근무":                    # 퇴근 시각부터 2시간
                t = datetime.strptime(end_default, "%H:%M")
                v_start.set(round5(end_default)); v_end.set(round5((t + timedelta(hours=2)).strftime("%H:%M")))
                return
            if k in ("조퇴", "병조퇴"):
                v_start.set(round5(datetime.now().strftime("%H:%M"))); v_end.set(end_default)
            elif k in ("외출", "병외출"):
                t = datetime.now(); v_start.set(round5(t.strftime("%H:%M"))); v_end.set(round5((t + timedelta(hours=1)).strftime("%H:%M")))
            else:
                v_start.set(c.get("work_start") or "08:40"); v_end.set(round5(datetime.now().strftime("%H:%M")))
        kind.trace_add("write", on_kind)
        e_reason.focus_set()
        btns = tk.Frame(fr, bg=BG)
        btns.pack(pady=(0, 10))
        tk.Button(btns, text="상신", font=("Malgun Gothic", 9, "bold"), bg="#c2417a", fg="white", relief="flat", padx=12,
                  command=lambda: self.bokmu_submit(tip, kind.get(), v_date.get().strip(), v_start.get().strip(), v_end.get().strip(), v_reason.get().strip(), v_contact.get().strip(), v_line.get().strip(),
                                                    v_end_date.get().strip(), v_dest.get().strip())).pack(side="left", padx=4)
        tk.Button(btns, text="닫기", font=f, relief="flat", padx=10, command=tip.destroy).pack(side="left", padx=4)

    def bokmu_submit(self, tip, kind, d, start, end, reason, contact, line, end_date="", dest=""):
        training, overtime = kind == "41조연수", kind == "초과근무"
        if not training:                           # 41조는 종일 — 시각을 안 본다
            for hm in (start, end):
                if not re.fullmatch(r"\d{1,2}:\d{2}", hm):
                    self.say("시각은 15:30 처럼 적어 주세요", "#c0392b", 5000); return
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            self.say("날짜는 2026-10-16 처럼 적어 주세요", "#c0392b", 5000); return
        if training:
            end_date = end_date or d
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_date) or end_date < d:
                self.say("종료일이 시작 날짜보다 앞이에요", "#c0392b", 5000); return
            if not dest:
                self.say("41조 연수는 목적지를 적어 주세요 (예: 자택)", "#c0392b", 6000); return
        if not reason:
            self.say("하여야 할 일을 사유 칸에 적어 주세요" if overtime else "사유를 적어 주세요", "#c0392b", 5000); return
        if not overtime and not re.fullmatch(r"[\d-]{9,14}", contact):
            self.say("연락처를 010-1234-5678 처럼 적어 주세요 (나이스가 요구해요)", "#c0392b", 6000); return
        if not line:
            self.say("결재선 이름을 적어 주세요 (나이스 개인결재선에 저장한 이름)", "#c0392b", 7000); return
        tip.destroy()
        self.busy = "복무 상신 중"
        c = cfg()
        line_key = "overtime_approval_line" if overtime else ("training_approval_line" if training else "approval_line")
        new = {line_key: line}                     # 다음부터 기본값으로
        if not overtime:
            new["contact"] = contact
        if training:
            new["training_destination"], new["training_reason"] = dest, reason
        if any(c.get(k) != v for k, v in new.items()):
            try:
                c.update(new)
                CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        if overtime:
            args = [str(PY), "-X", "utf8", str(OVERTIME), "--date", d, "--start", round5(start), "--end", round5(end),
                    "--task", reason, "--approval-line", line]
        elif training:
            args = [str(PY), "-X", "utf8", str(BOKMU), "--type", kind, "--date", d, "--end-date", end_date,
                    "--destination", dest, "--reason", reason, "--contact", contact, "--approval-line", line]
        else:
            args = [str(PY), "-X", "utf8", str(BOKMU), "--type", kind, "--date", d, "--start", round5(start), "--end", round5(end),
                    "--reason", reason, "--contact", contact, "--approval-line", line]
        when = "%s~%s" % (d, end_date) if training else "%s %s~%s" % (d, start, end)

        def fn():
            t0 = time.time()
            try:
                with self.locks["neis"]:        # 나이스 크롬 프로필을 쓰는 동안 위젯의 나이스 데우기와 겹치지 않게
                    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                       env=ENV, cwd=str(BOKMU.parent), creationflags=NO_WINDOW, timeout=900)
                lines = [ln for ln in ((p.stdout or "") + "\n" + (p.stderr or "")).splitlines() if ln.strip()]
                ok = p.returncode == 0 and any("상신 완료" in ln for ln in lines)
                log("bokmu %s %s" % (kind, when), ["READY" if ok else "FAIL " + " / ".join(lines[-3:])[:200]], t0)
            except Exception as e:
                ok, lines = False, [str(e)]
            finally:
                self.busy = None
            if ok:
                where = "개인초과근무관리" if overtime else "개인근무상황관리"
                self.root.after(0, self.info, "상신 완료 — %s %s\n사유: %s\n\n나이스 %s에서 한 번 확인하세요." % (kind, when, reason, where))
            else:
                self.root.after(0, self.info, "앗, 상신이 안 됐어요.\n\n" + "\n".join(lines[-4:])[:500] + "\n\n(크롬 창이 남아 있으면 거기서 직접 마무리할 수 있어요)")
        threading.Thread(target=fn, daemon=True).start()

    # ── 작은 창 ──
    def popup(self, text):
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        fr = tk.Frame(tip, bg=BG, highlightbackground=LINE, highlightthickness=2)
        fr.pack()
        tk.Label(fr, text=text, font=("Malgun Gothic", 9), bg=BG, fg=INK, wraplength=420, justify="left", padx=12, pady=10).pack(anchor="w")
        self.place_tip(tip)
        tip.after(30, lambda: tip.winfo_exists() and self.place_tip(tip))   # 단추·입력칸이 다 붙은 뒤 한 번 더
        return tip, fr

    def place_tip(self, tip):
        """작은 창은 위젯 가운데 바로 아래 (한쪽으로 치우치지 않게). 밑에 자리가 없으면 위젯 위로."""
        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = min(max(0, self.root.winfo_x() + self.root.winfo_width() // 2 - w // 2), sw - w)
        y = self.root.winfo_y() + self.root.winfo_height() + 6
        if y + h > sh - 56:
            y = max(0, self.root.winfo_y() - h - 6)
        tip.geometry("+%d+%d" % (x, y))

    def confirm(self, text, ok_label, on_ok):
        tip, fr = self.popup(text)
        row = tk.Frame(fr, bg=BG)
        row.pack(pady=(0, 10))
        tk.Button(row, text=ok_label, font=("Malgun Gothic", 9, "bold"), bg="#e5484d", fg="white", relief="flat", padx=10,
                  command=lambda: (tip.destroy(), on_ok())).pack(side="left", padx=4)
        tk.Button(row, text="닫기", font=("Malgun Gothic", 9), relief="flat", padx=10, command=tip.destroy).pack(side="left", padx=4)

    def info(self, text):
        tip, fr = self.popup(text)
        tk.Button(fr, text="확인", font=("Malgun Gothic", 9), relief="flat", command=tip.destroy).pack(pady=(0, 10))

    # ── 미리 열어두기 ──
    def warm(self, site, launch):
        if not configured() or not self.locks[site].acquire(blocking=False):
            return
        self.locks[site].release()
        self.run(site, "warm", ["--launch"] if launch else [], what="warm %s%s" % (site, " --launch" if launch else ""))

    def warm_all(self, launch):
        for site in ("neis", "edufine"):
            threading.Thread(target=self.warm, args=(site, launch), daemon=True).start()

    def loop_warm(self):
        if self.prewarm and not self.busy:
            self.warm_all(False)
        self.root.after(WARM_EVERY, self.loop_warm)

    def loop_relaunch(self):
        """닫힌 크롬을 다시 데운다 — 1분마다 포트만 보고, 없을 때만 warm --launch."""
        if self.prewarm and not self.busy and configured():
            for site, port in PORTS.items():
                if not port_alive(port):
                    threading.Thread(target=self.warm, args=(site, True), daemon=True).start()
        self.root.after(RELAUNCH_EVERY, self.loop_relaunch)

    def toggle_prewarm(self):
        self.prewarm = bool(self.prewarm_var.get())
        save_state(prewarm=self.prewarm)
        self.say("미리 열어둘게요" if self.prewarm else "미리 안 열어요")
        if self.prewarm:
            self.warm_all(True)

    # ── 설정·닫기 ──
    def open_setup(self):
        # 마우스로 고르는 설정 창 (클로드 없이 쓰는 선생님도 같은 창). 검은 창판(바로가기_설정.py)은 클로드 지시서용으로 남겨 둔다
        subprocess.Popen([str(PY.with_name("pythonw.exe")), str(HERE / "바로가기_설정창.pyw")], cwd=str(HERE), env=ENV)
        self.say("설정 창에서 마쳐 주세요", INK, 8000)

    def close_chrome(self):
        def fn():
            for site in ("neis", "edufine"):
                self.run(site, "close", what="close " + site)
            self.root.after(0, self.say, "닫았어요")
        threading.Thread(target=fn, daemon=True).start()

    def mainloop(self):
        self.root.after(200, self.keep_visible)      # 저장해 둔 자리가 지금 화면 밖이면 바로 안으로 (크기가 잡힌 뒤)
        self.tick()
        self.root.after(WARM_EVERY, self.loop_warm)
        self.root.after(RELAUNCH_EVERY, self.loop_relaunch)
        if not configured():
            self.root.after(800, lambda: self.say("오른쪽 클릭 → 인증서 설정부터 해 주세요", "#c0392b", 15000))
        elif self.prewarm:
            self.root.after(1500, lambda: self.warm_all(True))
        self.root.mainloop()


def breakaway():
    """클로드(코드 화면)가 띄운 명령은 «잡(job)»으로 묶여서, 클로드 쪽 프로세스가 끝나거나 죽으면 같이 죽는다
    (10/16 엔드투엔드 실측: 클로드 프로세스를 끊자 위젯도 사라짐). 잡 안에서 시작됐으면 잡 밖으로 나를 다시 띄우고 끝낸다."""
    if "--unjobbed" in sys.argv:
        return False
    try:
        k = ctypes.windll.kernel32
        injob = ctypes.c_int(0)
        if not k.IsProcessInJob(k.GetCurrentProcess(), None, ctypes.byref(injob)) or not injob.value:
            return False
        flags = 0x01000000 | 0x00000008 | 0x00000200          # CREATE_BREAKAWAY_FROM_JOB | DETACHED | NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--unjobbed"], cwd=str(HERE),
                         creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False          # 잡이 breakaway 를 안 허용하면 그냥 이대로 돈다


if __name__ == "__main__":
    if breakaway():
        sys.exit(0)
    if single_instance():      # 이미 떠 있다 → 그 위젯을 앞으로 꺼내고 나는 끝
        sys.exit(0)
    Widget().mainloop()
