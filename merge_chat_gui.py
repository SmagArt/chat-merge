"""Merge Chat — GUI v2.1"""
import sys, os, threading, subprocess, re, platform, multiprocessing, json
from pathlib import Path

try:
    import customtkinter as ctk
except ImportError:
    kw = {"creationflags": 0x08000000} if platform.system() == "Windows" else {}
    subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter", "-q"],
                   check=False, **kw)
    import customtkinter as ctk

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD as _TkDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False
    DND_FILES = None

# ВСЕГДА ctk.CTk - DnD инжектируется через _require() после создания окна
_BaseApp = ctk.CTk

THEMES = {
    "dark": {
        "BG":      "#0A0C10",  # глубокий тёмно-синий
        "SURFACE": "#111418",
        "CARD":    "#181D24",
        "BORDER":  "#252D38",
        "ACCENT":  "#2B7FFF",
        "ACCENT2": "#1A65D6",
        "GREEN":   "#2DCF6E",
        "GREEN2":  "#1FA050",
        "TEXT":    "#E8EDF5",
        "SUB":     "#5A6478",
        "MUTED":   "#171D26",
        "DECO":    "#1E2630",
    }
}
# Только одна тема — тёмная.

_theme = "dark"  # единственная тема

def T(key):
    return THEMES[_theme][key]

VERSION = "2.1.1"
AUTHOR  = "Смагин Артём"
GITHUB  = "github.com/SmagArt/chat-merge"
MAX_RECENT = 5

_LOCK_FILE = None

def _acquire_lock():
    global _LOCK_FILE
    try:
        if IS_WIN:
            import msvcrt
            lp = Path(os.environ.get("TEMP", ".")) / "merge_chat.lock"
            _LOCK_FILE = open(lp, "w")
            msvcrt.locking(_LOCK_FILE.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            lp = Path("/tmp/merge_chat.lock")
            _LOCK_FILE = open(lp, "w")
            fcntl.flock(_LOCK_FILE, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:
        return False

def find_script():
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    for p in [base/"merge_chat.py", Path(sys.executable).parent/"merge_chat.py"]:
        if p.exists():
            return p
    return None

SCRIPT = find_script()
_cancel_event = threading.Event()


class App(_BaseApp):
    def __init__(self):
        # Taskbar icon fix: Windows needs AppUserModelID set BEFORE window creation
        if sys.platform == "win32":
            try:
                import ctypes as _ct
                _ct.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "com.smagart.mergechat"
                )
            except Exception:
                pass
        ctk.CTk.__init__(self)

        global _theme
        # Config always next to exe or script (not inside _MEIPASS — it is read-only)
        if getattr(sys, "frozen", False):
            cfg_dir = Path(sys.executable).parent
        else:
            cfg_dir = Path(__file__).resolve().parent
        self._cfg_path = cfg_dir / "merge_chat_config.json"
        self._cfg = self._load_cfg()
        _theme = self._cfg.get("theme", "dark")
        ctk.set_appearance_mode(_theme)
        ctk.set_default_color_theme("blue")

        self.title("Merge Chat")
        self.resizable(False, False)

        self.folder_var  = ctk.StringVar(value="")
        self.author_var  = ctk.StringVar(value=self._cfg.get("author", "Вы"))
        self.model_var   = ctk.StringVar(value=self._cfg.get("model", "small"))
        self.merge_on    = self._cfg.get("merge_on", False)
        self.fmt_md      = self._cfg.get("fmt_md", False)
        self.date_from       = ctk.StringVar(value="")   # не сохраняем — всегда пустой при старте
        self.date_to         = ctk.StringVar(value="")
        self.running     = False
        self.output_path = None
        self._mbtns      = {}
        self._recent     = self._cfg.get("recent", [])

        self._build()

        W, H = 820, 1040
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.configure(fg_color=T("BG"))
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{max(20,(sh-H)//2-20)}")

        # Иконка — только Windows (.ico). На Mac без .app bundle иконку не задать
        if IS_WIN:
            _ico = self._find_icon()
            if _ico:
                try:
                    self.iconbitmap(str(_ico))
                except Exception:
                    pass

        if _HAS_DND:
            try:
                _TkDnD._require(self)
                self._register_dnd_recursive(self)
            except Exception:
                pass

    def _register_dnd_recursive(self, widget):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._register_dnd_recursive(child)

    def _find_icon(self):
        """Ищем merge_chat.ico рядом со скриптом или в _MEIPASS (PyInstaller)"""
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "merge_chat.ico")
            candidates.append(Path(sys.executable).parent / "merge_chat.ico")
        candidates.append(Path(__file__).parent / "merge_chat.ico")
        for p in candidates:
            if p.exists():
                return p
        return None

    def _f(self, size=13, w="normal"):
        return ctk.CTkFont("Segoe UI" if IS_WIN else "SF Pro Display", size, w)

    def _mono(self, size=12):
        return ctk.CTkFont("Consolas" if IS_WIN else "SF Mono", size)

    def _load_cfg(self):
        try:
            return json.loads(self._cfg_path.read_text(encoding="utf-8"))
        except:
            return {}

    def _save_cfg(self):
        try:
            self._cfg.update({
                "author":   self.author_var.get(),
                "model":    self.model_var.get(),
                "theme":    _theme,
                "fmt_md":   self.fmt_md,
                "merge_on": self.merge_on,
                "recent":   self._recent,
                # dates not saved — always empty on start
            })
            self._cfg_path.write_text(
                json.dumps(self._cfg, ensure_ascii=False), encoding="utf-8")
        except:
            pass

    def _add_recent(self, path: str):
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        self._recent = self._recent[:MAX_RECENT]
        self._update_recent_menu()

    def _update_recent_menu(self):
        if not hasattr(self, "_recent_menu"):
            return
        _ph = "— выбрать из истории —"
        vals = [_ph] + self._recent if self._recent else [_ph]
        self._recent_menu.configure(values=vals)
        self._recent_menu.set(_ph)

    def _on_recent_select(self, val):
        if val and val not in ("(история пуста)", "— выбрать из истории —"):
            if Path(val).exists():
                self.folder_var.set(val)
                self.flbl.configure(text=val, text_color=T("TEXT"))
            else:
                self.flbl.configure(text=f"Папка не найдена: {val}", text_color="#f87171")

    def _on_dnd_drop(self, event):
        path = event.data.strip().strip("{}")
        if Path(path).is_dir():
            self.folder_var.set(path)
            self.flbl.configure(text=path, text_color=T("TEXT"))

    def _toggle_fmt(self):
        self.fmt_md = not self.fmt_md
        if self.fmt_md:
            self._fmt_btn.configure(text="📝 MD", fg_color=T("ACCENT"), text_color="white")
        else:
            self._fmt_btn.configure(text="📄 TXT", fg_color=T("MUTED"), text_color=T("SUB"))

    def _build(self):
        P = 28

        # Декоративная вертикальная полоска справа
        deco_panel = ctk.CTkFrame(self, fg_color=T("SURFACE"),
                                   width=22, height=980, corner_radius=0)
        deco_panel.place(x=798, y=0)
        deco_panel.lower()
        for txt, ypos, fs in [("TG", 140, 12), ("VK", 300, 10), ("💬", 480, 13), ("✈", 660, 17)]:
            lbl = ctk.CTkLabel(deco_panel, text=txt,
                               font=ctk.CTkFont("Arial", fs, "bold"),
                               text_color=T("SUB"), fg_color="transparent",
                               width=22, height=30, anchor="center")
            lbl.place(x=0, y=ypos)
            lbl.lower()

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=P, pady=(26, 0))

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Merge Chat",
                     font=self._f(28, "bold"), text_color=T("TEXT")).pack(side="left")
        ctk.CTkLabel(left, text="  Telegram & ВКонтакте → TXT/MD",
                     font=self._f(12), text_color=T("SUB")).pack(side="left", pady=(10, 0))

        right_hdr = ctk.CTkFrame(hdr, fg_color="transparent")
        right_hdr.pack(side="right")



        ctk.CTkButton(right_hdr, text="ℹ  О программе",
                      width=136, height=34, font=self._f(12),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=8,
                      command=self._show_about).pack(side="right")

        ctk.CTkFrame(self, fg_color=T("ACCENT"), height=2,
                     corner_radius=1).pack(fill="x", padx=P, pady=(14, 0))
        self._gap(14)

        self._section("1 · Папка с перепиской")
        self._gap(6)

        fc = ctk.CTkFrame(self, fg_color=T("CARD"), corner_radius=14,
                          border_color=T("BORDER"), border_width=1)
        fc.pack(fill="x", padx=P)

        fi = ctk.CTkFrame(fc, fg_color="transparent")
        fi.pack(fill="x", padx=16, pady=(14, 6))

        hint = " (или перетащи сюда)" if _HAS_DND else ""
        self.flbl = ctk.CTkLabel(fi, text="Папка не выбрана" + hint,
                                  font=self._mono(12), text_color=T("SUB"),
                                  anchor="w", wraplength=540)
        self.flbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(fi, text="Выбрать…", width=110, height=34,
                      font=self._f(13, "bold"),
                      fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                      corner_radius=8, command=self._pick_folder).pack(side="right")

        fr = ctk.CTkFrame(fc, fg_color="transparent")
        fr.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(fr, text="Недавние:", font=self._f(11),
                     text_color=T("SUB"), width=80, anchor="w").pack(side="left")
        _placeholder = "— выбрать из истории —"
        vals = [_placeholder] + self._recent if self._recent else [_placeholder]
        self._recent_menu = ctk.CTkOptionMenu(
            fr, values=vals, width=330, height=28, font=self._f(11),
            fg_color=T("SURFACE"), button_color=T("BORDER"),
            button_hover_color=T("ACCENT"), text_color=T("SUB"),
            dropdown_fg_color=T("SURFACE"), command=self._on_recent_select)
        self._recent_menu.set(_placeholder)
        self._recent_menu.pack(side="left", padx=(6, 6))
        ctk.CTkButton(fr, text="✕ очистить", width=90, height=28,
                      font=self._f(10), fg_color=T("MUTED"),
                      hover_color=T("BORDER"), text_color=T("SUB"),
                      corner_radius=7, command=self._clear_history).pack(side="left")

        self._gap(16)

        self._section("2 · Настройки")
        self._gap(6)
        sc = ctk.CTkFrame(self, fg_color=T("CARD"), corner_radius=14,
                          border_color=T("BORDER"), border_width=1)
        sc.pack(fill="x", padx=P)
        si = ctk.CTkFrame(sc, fg_color="transparent")
        si.pack(fill="x", padx=16, pady=14)

        r1 = ctk.CTkFrame(si, fg_color="transparent"); r1.pack(fill="x", pady=5)
        ctk.CTkLabel(r1, text="Твоё имя (как в Telegram)", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.author_var, width=220, height=34,
                     font=self._f(13), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), text_color=T("TEXT"),
                     corner_radius=8).pack(side="left")

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r2 = ctk.CTkFrame(si, fg_color="transparent"); r2.pack(fill="x", pady=5)
        ctk.CTkLabel(r2, text="Модель Whisper", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        mf = ctk.CTkFrame(r2, fg_color="transparent"); mf.pack(side="left")
        cur = self._cfg.get("model", "small")
        for m in ["tiny", "base", "small", "medium", "large"]:
            b = ctk.CTkButton(mf, text=m, width=70, height=30, font=self._f(12),
                              fg_color=T("ACCENT") if m == cur else T("SURFACE"),
                              hover_color=T("ACCENT2"),
                              border_color=T("BORDER"), border_width=1, corner_radius=7,
                              command=lambda v=m: self._pick_model(v))
            b.pack(side="left", padx=3)
            self._mbtns[m] = b

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r3 = ctk.CTkFrame(si, fg_color="transparent"); r3.pack(fill="x", pady=5)
        ctk.CTkLabel(r3, text="Объединять подряд идущие", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        _m_text = "● ВКЛ"  if self.merge_on else "○ ВЫКЛ"
        _m_fg   = T("GREEN") if self.merge_on else T("MUTED")
        _m_hov  = T("GREEN2") if self.merge_on else T("BORDER")
        _m_tc   = T("TEXT") if self.merge_on else T("SUB")
        self.mbtn = ctk.CTkButton(r3, text=_m_text, width=90, height=30,
                                   font=self._f(12, "bold"),
                                   fg_color=_m_fg, hover_color=_m_hov,
                                   text_color=_m_tc,
                                   corner_radius=7, command=self._toggle_merge)
        self.mbtn.pack(side="left")

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r4 = ctk.CTkFrame(si, fg_color="transparent"); r4.pack(fill="x", pady=5)
        ctk.CTkLabel(r4, text="Формат вывода", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        fmt_text = "📝 MD" if self.fmt_md else "📄 TXT"
        fmt_fg   = T("ACCENT") if self.fmt_md else T("MUTED")
        fmt_tc   = "white" if self.fmt_md else T("SUB")
        self._fmt_btn = ctk.CTkButton(
            r4, text=fmt_text, width=90, height=30, font=self._f(12, "bold"),
            fg_color=fmt_fg, hover_color=T("ACCENT2"),
            text_color=fmt_tc, corner_radius=7, command=self._toggle_fmt)
        self._fmt_btn.pack(side="left")
        ctk.CTkLabel(r4, text="  TXT — простой текст · MD — Markdown (Obsidian, Notion)",
                     font=self._f(10), text_color=T("SUB")).pack(side="left", padx=(8, 0))

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r5 = ctk.CTkFrame(si, fg_color="transparent"); r5.pack(fill="x", pady=5)
        ctk.CTkLabel(r5, text="Период переписки", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        df = ctk.CTkFrame(r5, fg_color="transparent"); df.pack(side="left")
        self._period_btn = ctk.CTkButton(
            df, text="вся переписка", width=220, height=30,
            font=self._mono(12), fg_color=T("SURFACE"),
            border_color=T("BORDER"), border_width=1,
            text_color=T("SUB"), hover_color=T("BORDER"), corner_radius=7,
            command=self._pick_date)
        self._period_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(df, text="✕", width=28, height=30, font=self._f(11),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=7,
                      command=self._clear_dates).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(df, text="пусто = вся переписка",
                     font=self._f(10), text_color=T("SUB")).pack(side="left")

        self._gap(16)

        self._section("3 · Процесс")
        self._gap(6)
        pc = ctk.CTkFrame(self, fg_color=T("CARD"), corner_radius=14,
                          border_color=T("BORDER"), border_width=1)
        pc.pack(fill="x", padx=P)
        pi = ctk.CTkFrame(pc, fg_color="transparent")
        pi.pack(fill="both", padx=4, pady=4)

        self.pbar = ctk.CTkProgressBar(pi, height=5, fg_color=T("SURFACE"),
                                        progress_color=T("ACCENT"), corner_radius=2)
        self.pbar.pack(fill="x", padx=12, pady=(10, 3))
        self.pbar.set(0)
        self.plbl = ctk.CTkLabel(pi, text="", font=self._f(11), text_color=T("SUB"))
        self.plbl.pack(anchor="w", padx=14)

        self.log = ctk.CTkTextbox(
            pi, font=self._mono(12), fg_color=T("SURFACE"), text_color=T("TEXT"),
            border_color=T("BORDER"), border_width=1, corner_radius=10,
            wrap="word", height=200, activate_scrollbars=True)
        self.log.pack(fill="x", padx=10, pady=(4, 4))

        ctk.CTkButton(pi, text="📋  Скопировать лог", height=28, font=self._f(11),
                      fg_color="transparent", hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=6, anchor="w",
                      command=self._copy_log).pack(anchor="w", padx=10, pady=(0, 8))

        ctk.CTkFrame(self, fg_color=T("BORDER"), height=1).pack(fill="x", padx=P, pady=(12, 0))
        self._bf = ctk.CTkFrame(self, fg_color="transparent")
        self._bf.pack(fill="x", padx=P, pady=(12, 24))

        self.obtn = ctk.CTkButton(
            self._bf, text="📂  Открыть папку", width=170, height=46,
            font=self._f(13), fg_color=T("MUTED"), hover_color=T("BORDER"),
            text_color=T("SUB"), corner_radius=12, state="disabled",
            command=self._open_output)
        self.obtn.pack(side="left")

        self.cbtn = ctk.CTkButton(
            self._bf, text="✕  Отмена", width=130, height=46, font=self._f(13),
            fg_color="#7A1515", hover_color="#5A0F0F",
            text_color="white", corner_radius=12, command=self._cancel)

        self.rbtn = ctk.CTkButton(
            self._bf, text="▶  Запустить", width=190, height=46,
            font=self._f(15, "bold"), fg_color=T("ACCENT"),
            hover_color=T("ACCENT2"), corner_radius=12, command=self._run)
        self.rbtn.pack(side="right")

    def _gap(self, h=12):
        ctk.CTkFrame(self, fg_color="transparent", height=h).pack()

    def _section(self, txt):
        ctk.CTkLabel(self, text=txt, font=self._f(11, "bold"),
                     text_color=T("SUB")).pack(anchor="w", padx=28)

    def _pick_date(self):
        """Range-picker: клик 1 = начало, клик 2 = конец."""
        import tkinter as tk
        import calendar as _cal
        from datetime import date, datetime

        def _parse(s):
            try: return datetime.strptime(s.strip(), "%d.%m.%Y").date()
            except: return None

        d1 = _parse(self.date_from.get())
        d2 = _parse(self.date_to.get())
        today = date.today()

        sel = {"clicks": [x for x in [d1, d2] if x]}
        nav = {"y": (d1 or today).year, "m": (d1 or today).month}

        # ── Цвета ─────────────────────────────────────────────────────
        BG      = "#1a1f35"
        HDR_BG  = "#252d50"
        CELL_BG = "#20263c"
        TEXT_C  = "#b8c4e0"   # будни — серо-голубой
        WKND_C  = "#e07070"   # выходные — розово-красный
        TODAY_C = "#34d399"   # сегодня — изумрудный
        SEL_BG  = "#2563eb"   # выбранный — синий фон
        SEL_FG  = "#ffffff"   # выбранный — белый текст
        RNG_BG  = "#172554"   # диапазон — тёмно-синий
        RNG_FG  = "#7dd3fc"   # диапазон — голубой
        NAV_C   = "#7c8fc4"   # стрелки — серо-синий
        NAV_HOV = "#ffffff"   # стрелки hover
        LBL_C   = "#d0d8f0"   # месяц/год лейбл
        SUB_C   = "#4a5678"   # дни недели
        HINT_C  = "#5a6a9a"   # подсказка
        SEPC    = "#2a3255"   # разделитель

        MONTHS = ["Январь","Февраль","Март","Апрель","Май","Июнь",
                  "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
        DAYS   = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

        win = tk.Toplevel(self)
        win.title("Выбор периода")
        win.resizable(False, False)
        win.transient(self)
        win.configure(bg=BG)
        win.focus_force()

        # ── Хелпер: Label-кнопка (не ломается на Mac) ────────────────
        def _lbtn(parent, text, cmd, font=("Arial",15,"bold"), fg=NAV_C, padx=10, pady=6):
            lbl = tk.Label(parent, text=text, bg=HDR_BG, fg=fg,
                           font=font, cursor="hand2", padx=padx, pady=pady)
            def _enter(_): lbl.configure(fg=NAV_HOV)
            def _leave(_): lbl.configure(fg=fg)
            def _click(_): cmd()
            lbl.bind("<Enter>",  _enter)
            lbl.bind("<Leave>",  _leave)
            lbl.bind("<Button-1>", _click)
            return lbl

        # ── Навигация: ◄ месяц ►  ◄ год ► ───────────────────────────
        hf = tk.Frame(win, bg=HDR_BG); hf.pack(fill="x")

        # Левый блок: месяц
        mf = tk.Frame(hf, bg=HDR_BG); mf.pack(side="left", padx=8, pady=4)
        _lbtn(mf, "◄", lambda: _nav(dm=-1)).pack(side="left")
        lbl_m = tk.Label(mf, text="", bg=HDR_BG, fg=LBL_C,
                         font=("Arial",13,"bold"), width=11, anchor="center")
        lbl_m.pack(side="left", padx=2)
        _lbtn(mf, "►", lambda: _nav(dm=1)).pack(side="left")

        # Разделитель
        tk.Frame(hf, bg=SEPC, width=1).pack(side="left", fill="y", pady=4)

        # Правый блок: год
        yf = tk.Frame(hf, bg=HDR_BG); yf.pack(side="left", padx=8, pady=4)
        _lbtn(yf, "◄", lambda: _nav(dy=-1)).pack(side="left")
        lbl_y = tk.Label(yf, text="", bg=HDR_BG, fg=LBL_C,
                         font=("Arial",13,"bold"), width=5, anchor="center")
        lbl_y.pack(side="left", padx=2)
        _lbtn(yf, "►", lambda: _nav(dy=1)).pack(side="left")

        # ── Подсказка ─────────────────────────────────────────────────
        # ── Пошаговая подсказка ──────────────────────────────────────
        steps_frame = tk.Frame(win, bg=BG)
        steps_frame.pack(fill="x", padx=10, pady=(4,0))

        step1_frame = tk.Frame(steps_frame, bg="#172554", relief="ridge", bd=1)
        step1_frame.pack(side="left", fill="x", expand=True, padx=(0,3))
        step1_num = tk.Label(step1_frame, text="1", bg="#2563eb", fg="white",
                             font=("Arial",11,"bold"), width=2, pady=4)
        step1_num.pack(side="left")
        step1_lbl = tk.Label(step1_frame, text=" Начало",
                             bg="#172554", fg="#7dd3fc",
                             font=("Arial",10,"bold"), anchor="w")
        step1_lbl.pack(side="left", fill="x", expand=True)
        step1_val = tk.Label(step1_frame, text="не выбрано",
                             bg="#172554", fg="#5a7aaa",
                             font=("Arial",9), padx=6)
        step1_val.pack(side="right")

        step2_frame = tk.Frame(steps_frame, bg="#1e2635", relief="ridge", bd=1)
        step2_frame.pack(side="left", fill="x", expand=True, padx=(3,0))
        step2_num = tk.Label(step2_frame, text="2", bg="#374151", fg="#9ca3af",
                             font=("Arial",11,"bold"), width=2, pady=4)
        step2_num.pack(side="left")
        step2_lbl = tk.Label(step2_frame, text=" Конец",
                             bg="#1e2635", fg="#5a6a8a",
                             font=("Arial",10,"bold"), anchor="w")
        step2_lbl.pack(side="left", fill="x", expand=True)
        step2_val = tk.Label(step2_frame, text="не выбрано",
                             bg="#1e2635", fg="#5a6a8a",
                             font=("Arial",9), padx=6)
        step2_val.pack(side="right")

        hint = tk.Label(win, text="↑ Кликни дату — начало периода",
                        bg=BG, fg=HINT_C, font=("Arial",9), pady=3)
        hint.pack()

        # Разделитель
        tk.Frame(win, bg=SEPC, height=1).pack(fill="x", padx=8)

        # ── Дни недели ────────────────────────────────────────────────
        dw = tk.Frame(win, bg=BG); dw.pack(fill="x", padx=10, pady=(6,2))
        for i, d in enumerate(DAYS):
            fg = WKND_C if i >= 5 else SUB_C
            tk.Label(dw, text=d, bg=BG, fg=fg, width=4,
                     font=("Arial",9,"bold"), anchor="center").grid(row=0, column=i)

        # ── Сетка дней ────────────────────────────────────────────────
        gf = tk.Frame(win, bg=BG); gf.pack(padx=10, pady=(0,4))

        def _render():
            for w in gf.winfo_children(): w.destroy()
            y, m = nav["y"], nav["m"]
            lbl_m.configure(text=MONTHS[m-1])
            lbl_y.configure(text=str(y))

            c = sel["clicks"]
            d_from = min(c) if len(c)==2 else (c[0] if c else None)
            d_to   = max(c) if len(c)==2 else None

            for row, week in enumerate(_cal.monthcalendar(y, m)):
                for col, day in enumerate(week):
                    if day == 0:
                        tk.Label(gf, text="", bg=BG, width=4, height=1
                                 ).grid(row=row, column=col, padx=1, pady=1)
                        continue
                    d_obj    = date(y, m, day)
                    is_sel   = d_obj in (d_from, d_to)
                    in_rng   = d_from and d_to and d_from < d_obj < d_to
                    is_today = d_obj == today
                    is_wknd  = col >= 5

                    if is_sel:
                        bg2, fg2, fw = SEL_BG, SEL_FG, "bold"
                    elif in_rng:
                        bg2, fg2, fw = RNG_BG, RNG_FG, "normal"
                    elif is_today:
                        bg2, fg2, fw = CELL_BG, TODAY_C, "bold"
                    elif is_wknd:
                        bg2, fg2, fw = CELL_BG, WKND_C, "normal"
                    else:
                        bg2, fg2, fw = CELL_BG, TEXT_C,  "normal"

                    # Label-кнопка — не ломается на Mac
                    lbl = tk.Label(gf, text=str(day), width=4, height=1,
                                   bg=bg2, fg=fg2, relief="flat",
                                   font=("Arial",11,fw), cursor="hand2")
                    lbl.bind("<Button-1>", lambda e, d=d_obj: _click(d))
                    lbl.bind("<Enter>",    lambda e, l=lbl: l.configure(bg=SEL_BG, fg=SEL_FG))
                    lbl.bind("<Leave>",    lambda e, l=lbl, b=bg2, f=fg2: l.configure(bg=b, fg=f))
                    lbl.grid(row=row, column=col, padx=1, pady=1)

        def _fmt_d(d):
            return f"{d.day:02d}.{d.month:02d}.{d.year}"

        def _click(d):
            c = sel["clicks"]
            if len(c) == 0 or len(c) == 2:
                sel["clicks"] = [d]
                step1_num.configure(bg="#16a34a"); step1_frame.configure(bg="#14532d")
                step1_lbl.configure(bg="#14532d", fg="#4ade80")
                step1_val.configure(bg="#14532d", fg="#86efac", text=_fmt_d(d))
                step2_num.configure(bg="#2563eb", fg="white"); step2_frame.configure(bg="#172554")
                step2_lbl.configure(bg="#172554", fg="#7dd3fc")
                step2_val.configure(bg="#172554", fg="#5a7aaa", text="не выбрано")
                hint.configure(text="↑ Теперь кликни дату — конец периода", fg="#f59e0b")
            else:
                sel["clicks"] = sorted([c[0], d])
                f, t = sel["clicks"]
                step1_val.configure(text=_fmt_d(f))
                step2_num.configure(bg="#16a34a", fg="white"); step2_frame.configure(bg="#14532d")
                step2_lbl.configure(bg="#14532d", fg="#4ade80")
                step2_val.configure(bg="#14532d", fg="#86efac", text=_fmt_d(t))
                hint.configure(text=f"✓ {_fmt_d(f)}  —  {_fmt_d(t)}", fg=TODAY_C)
            _render()

        def _nav(dm=0, dy=0):
            m, y = nav["m"]+dm, nav["y"]+dy
            if m < 1:  m=12; y-=1
            if m > 12: m=1;  y+=1
            nav["m"]=m; nav["y"]=y; _render()

        # ── Кнопки снизу ──────────────────────────────────────────────
        tk.Frame(win, bg=SEPC, height=1).pack(fill="x", padx=8, pady=(4,0))
        bf = tk.Frame(win, bg=BG); bf.pack(fill="x", padx=10, pady=8)

        def _laction(parent, text, cmd, bg_c, fg_c, bg_h):
            lbl = tk.Label(parent, text=text, bg=bg_c, fg=fg_c,
                           font=("Arial",11,"bold"), cursor="hand2",
                           padx=16, pady=7, relief="flat")
            lbl.bind("<Enter>",    lambda e: lbl.configure(bg=bg_h))
            lbl.bind("<Leave>",    lambda e: lbl.configure(bg=bg_c))
            lbl.bind("<Button-1>", lambda e: cmd())
            return lbl

        def _confirm():
            c = sel["clicks"]
            if len(c) == 2:   f, t = c
            elif len(c) == 1: f = t = c[0]
            else: _clear_and_close(); return
            s1 = f"{f.day:02d}.{f.month:02d}.{f.year}"
            s2 = f"{t.day:02d}.{t.month:02d}.{t.year}"
            self.date_from.set(s1); self.date_to.set(s2)
            lbl = f"{s1}  —  {s2}" if s1 != s2 else s1
            self._period_btn.configure(text=lbl, text_color=T("TEXT"))
            self._save_cfg(); win.destroy()

        def _clear_and_close():
            self.date_from.set(""); self.date_to.set("")
            self._period_btn.configure(text="вся переписка", text_color=T("SUB"))
            self._save_cfg(); win.destroy()

        _laction(bf, "✕  Очистить", _clear_and_close,
                 bg_c="#2e3650", fg_c="#7a8ab0", bg_h="#3a4465").pack(side="left")
        _laction(bf, "✓  Применить", _confirm,
                 bg_c=SEL_BG, fg_c="white", bg_h="#1d4ed8").pack(side="right")

        _render()
        win.update_idletasks()
        wx = self.winfo_x() + (self.winfo_width()  - win.winfo_reqwidth())  // 2
        wy = self.winfo_y() + (self.winfo_height() - win.winfo_reqheight()) // 2
        win.geometry(f"+{max(0,wx)}+{max(0,wy)}")
    def _clear_dates(self):
        self.date_from.set("")
        self.date_to.set("")
        if hasattr(self, "_period_btn"):
            self._period_btn.configure(text="вся переписка", text_color=T("SUB"))
        self._save_cfg()
    def _clear_history(self):
        self._recent.clear()
        self._update_recent_menu()
        self._save_cfg()

    def _pick_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Выберите папку с перепиской")
        if d:
            self.folder_var.set(d)
            self.flbl.configure(text=d, text_color=T("TEXT"))
            self._add_recent(d)
            self._save_cfg()

    def _pick_model(self, m):
        self.model_var.set(m)
        for k, b in self._mbtns.items():
            b.configure(fg_color=T("ACCENT") if k == m else T("SURFACE"))

    def _toggle_merge(self):
        self.merge_on = not self.merge_on
        if self.merge_on:
            self.mbtn.configure(text="● ВКЛ", fg_color=T("GREEN"), hover_color=T("GREEN2"),
                                 text_color=T("TEXT"))
        else:
            self.mbtn.configure(text="○ ВЫКЛ", fg_color=T("MUTED"), hover_color=T("BORDER"),
                                 text_color=T("SUB"))

    def _copy_log(self):
        text = self.log.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.plbl.configure(text="✓ Лог скопирован в буфер")
            self.after(2000, lambda: self.plbl.configure(text=""))

    def _cancel(self):
        _cancel_event.set()
        self._log("--- Отмена: текущий файл будет пропущен... ---")
        self.cbtn.configure(state="disabled", text="⏳ Отмена...")

    def _show_about(self):
        win = ctk.CTkToplevel(self)
        win.title("О программе"); win.resizable(False, False)
        win.configure(fg_color=T("SURFACE")); win.grab_set()
        win.after(60, win.lift)
        ctk.CTkLabel(win, text="💬", font=self._f(52)).pack(pady=(28, 0))
        ctk.CTkLabel(win, text="Merge Chat",
                     font=self._f(24, "bold"), text_color=T("TEXT")).pack(pady=(6, 2))
        ctk.CTkLabel(win, text=f"Версия {VERSION}",
                     font=self._f(12), text_color=T("SUB")).pack()
        ctk.CTkFrame(win, fg_color=T("BORDER"), height=1).pack(fill="x", padx=40, pady=16)
        ctk.CTkLabel(win, text="Автор", font=self._f(11), text_color=T("SUB")).pack()
        ctk.CTkLabel(win, text=AUTHOR, font=self._f(17, "bold"),
                     text_color=T("TEXT")).pack(pady=(2, 0))
        ctk.CTkLabel(win, text=GITHUB, font=self._f(11),
                     text_color=T("ACCENT")).pack(pady=(2, 0))
        ctk.CTkFrame(win, fg_color=T("BORDER"), height=1).pack(fill="x", padx=40, pady=16)
        ctk.CTkLabel(win, text="Объединяет переписки Telegram и ВКонтакте\n"
                               "в один файл.\n"
                               "Расшифровывает голосовые через Whisper\n"
                               "офлайн, без облаков.",
                     font=self._f(12), text_color=T("SUB"), justify="center").pack(padx=36)
        dnd_s = "✓ Drag & Drop активен" if _HAS_DND else "○ DnD: pip install tkinterdnd2"
        ctk.CTkLabel(win, text=dnd_s, font=self._f(10),
                     text_color=T("GREEN") if _HAS_DND else T("SUB")).pack(pady=(8, 0))
        ctk.CTkButton(win, text="Закрыть", width=130, height=36, font=self._f(13),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      command=win.destroy).pack(pady=24)
        win.update_idletasks()
        ww = max(340, win.winfo_reqwidth() + 60); wh = win.winfo_reqheight() + 24
        win.geometry(f"{ww}x{wh}+{self.winfo_x()+(self.winfo_width()-ww)//2}+"
                     f"{self.winfo_y()+(self.winfo_height()-wh)//2}")

    def _log(self, msg):
        if IS_WIN:
            for a, b in [("✓","[OK]"),("→","->"),("🎤","[mic]"),
                          ("━","-"),("═","="),("✗","[X]")]:
                msg = msg.replace(a, b)
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _clear_log(self):
        self.log.delete("1.0", "end")

    def _open_output(self):
        _cnw = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
        if self.output_path and Path(self.output_path).exists():
            if IS_WIN:
                subprocess.Popen(["explorer", "/select,", str(Path(self.output_path))], creationflags=_cnw)
            elif IS_MAC:
                subprocess.Popen(["open", "-R", str(Path(self.output_path))])
        else:
            folder = self.folder_var.get()
            if folder and Path(folder).exists():
                if IS_WIN:
                    subprocess.Popen(["explorer", str(Path(folder))], creationflags=_cnw)
                elif IS_MAC:
                    subprocess.Popen(["open", str(Path(folder))])

    def _run(self):
        if self.running: return
        folder = self.folder_var.get()
        if not folder:
            from tkinter import messagebox
            messagebox.showwarning("Merge Chat", "Сначала выбери папку с перепиской")
            return
        if not SCRIPT:
            from tkinter import messagebox
            messagebox.showerror("Merge Chat", "Не найден merge_chat.py рядом с программой.")
            return

        self._save_cfg()
        self._add_recent(folder)
        _cancel_event.clear()

        self.running = True; self.output_path = None
        self.rbtn.configure(text="⏳  Обработка…", state="disabled",
                             fg_color=T("MUTED"), text_color=T("SUB"))
        self.obtn.configure(state="disabled", fg_color=T("MUTED"), text_color=T("SUB"))
        self.cbtn.pack(in_=self._bf, side="right", padx=(0, 8))
        self.cbtn.configure(state="normal", text="✕  Отмена")
        self.pbar.set(0); self.plbl.configure(text="")
        self._clear_log(); self._log("Запуск…")

        fmt = "md" if self.fmt_md else "txt"

        def worker():
            try:
                if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                    base = sys._MEIPASS
                    if base not in sys.path: sys.path.insert(0, base)
                elif SCRIPT:
                    sd = str(SCRIPT.parent)
                    if sd not in sys.path: sys.path.insert(0, sd)

                import merge_chat as _mc

                # Reset state before each run (no reload — it breaks stdout)
                # Whisper model: keep cached unless model changed
                cur_model = self.model_var.get()
                if getattr(_mc, "_loaded_model_name", None) != cur_model:
                    _mc._whisper_cache = None
                    _mc._loaded_model_name = cur_model
                # Always clear transcription cache (new files may have been added)
                _mc._transcribe_cache.clear()
                _mc._voice_counter["done"] = 0
                _mc._voice_counter["total"] = 0
                # Reset use_whisper in case it was disabled by a previous import error
                _mc.CFG.use_whisper = True

                _mc._cancel_event = _cancel_event

                def log_cb(line):
                    if not line: return
                    if re.search(r"\d+%\|", line) or "MiB/s" in line:
                        m = re.search(r"(\d+)%.*?(\d+\.?\d*)/(\d+\.?\d*)([MG]iB)", line)
                        if m:
                            pct = int(m.group(1)) / 100
                            self.after(0, self.pbar.set, pct)
                            self.after(0, self.plbl.configure,
                                {"text": f"Скачиваю модель: {m.group(2)}/{m.group(3)} {m.group(4)} ({int(pct*100)}%)"})
                        return
                    if "Примерное время" in line:
                        self.after(0, self.plbl.configure, {"text": line.strip()})
                    vm = re.match(r"\s*\[(\d+)/(\d+)\]\s*(Расшифровка|Transcribing)", line)
                    if vm:
                        done, total = int(vm.group(1)), int(vm.group(2))
                        if total > 0:
                            pct = done / total
                            self.after(0, self.pbar.set, 0.1 + pct * 0.8)
                            self.after(0, self.plbl.configure,
                                {"text": f"Расшифровка голосовых: {done}/{total}"})
                    if any(x in line for x in ("Готово →", "[OK] Готово", "✓ Готово")):
                        self.after(0, self.pbar.set, 1.0)
                        self.after(0, self.plbl.configure, {"text": ""})
                        for sep in ["→", "->"]:
                            if sep in line:
                                self.output_path = line.split(sep)[1].strip().split(" (")[0].strip()
                                break
                    self.after(0, self._log, line)

                out = _mc.process_folder(
                    folder_path=folder,
                    author=self.author_var.get() or "Вы",
                    model=self.model_var.get(),
                    do_merge=self.merge_on,
                    output_format=fmt,
                    log_cb=log_cb,
                    progress_cb=lambda p: self.after(0, self.pbar.set, min(float(p), 1.0)),
                    date_from=self.date_from.get().strip(),
                    date_to=self.date_to.get().strip(),
                )
                cancelled = _cancel_event.is_set()
                self.after(0, self._done, bool(out), cancelled)
            except Exception as ex:
                import traceback
                self.after(0, self._log, f"Ошибка: {ex}")
                self.after(0, self._log, traceback.format_exc())
                self.after(0, self._done, False, False)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, ok: bool, cancelled: bool = False):
        self.running = False
        self.cbtn.pack_forget()
        # Enable "Открыть папку": output file → green; fallback to source folder → muted
        if self.output_path and Path(self.output_path).exists():
            self.obtn.configure(state="normal", fg_color=T("GREEN"),
                                hover_color=T("GREEN2"), text_color="white")
        elif self.folder_var.get() and Path(self.folder_var.get()).exists():
            self.obtn.configure(state="normal", fg_color=T("MUTED"),
                                hover_color=T("BORDER"), text_color=T("SUB"))
        if cancelled:
            self.rbtn.configure(text="▶  Запустить", state="normal",
                                 fg_color=T("ACCENT"), text_color=T("TEXT"))
            self._log("\n[X] Обработка отменена.")
            if self.output_path and Path(self.output_path).exists():
                self._log("[OK] Частичный файл сохранён — нажми «Открыть папку».")
        elif ok and self.output_path:
            self.rbtn.configure(text="▶  Запустить снова", state="normal",
                                 fg_color=T("ACCENT"), text_color=T("TEXT"))
            self._log("\n[OK] Готово! Нажми «Открыть папку».")
        else:
            self.rbtn.configure(text="▶  Запустить", state="normal",
                                 fg_color=T("ACCENT"), text_color=T("TEXT"))
            self._log("\n[X] Завершено с ошибкой.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if not _acquire_lock():
        import tkinter as tk; from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showwarning("Merge Chat", "Программа уже запущена!")
        root.destroy(); sys.exit(0)
    app = App(); app.mainloop()
