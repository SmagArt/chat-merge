"""Merge Chat — GUI v2.3"""
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

APP_USER_MODEL_ID = "com.smagart.mergechat"

if IS_WIN:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD as _TkDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False
    DND_FILES = None

# ── Локальная папка для Whisper/torch — не системная.
# Так удаление MergeChat реально удаляет всё, что прога ставила через UI,
# и `Whisper не установлен` снова показывается после переустановки.
def _local_packages_dir() -> Path:
    return Path(__file__).resolve().parent / "local_packages"

LOCAL_PKGS = _local_packages_dir()
LOCAL_PKGS.mkdir(parents=True, exist_ok=True)
if str(LOCAL_PKGS) not in sys.path:
    sys.path.insert(0, str(LOCAL_PKGS))

# Модели Whisper (tiny…large .pt) храним внутри папки проги — whisper_models/,
# а не в общем ~/.cache/whisper. Так удаление MergeChat уносит модели с собой.
# См. правило изоляции служебных файлов (memory/feedback_isolate_app_files.md).
WHISPER_MODELS = Path(__file__).resolve().parent / "whisper_models"
# Legacy-кэш: до v2.5 модели качались в общий ~/.cache/whisper — чистим его
# при «Удалить Whisper», т.к. на старых установках там осели гигабайты.
WHISPER_CACHE_LEGACY = Path.home() / ".cache" / "whisper"

# Whisper «доступен для MergeChat» — ТОЛЬКО если whisper И torch лежат в
# local_packages самой проги. Системный / пользовательский Python (voice-diarizer,
# pip install --user, общий site-packages) намеренно игнорируем: иначе удаление
# MergeChat не может вычистить Whisper, а баннер врёт о состоянии. Прога владеет
# своим Whisper целиком. Раньше тут был find_spec — он находил whisper в чужом
# Python (в т.ч. в общем %APPDATA%\Python user-site) и баннер не показывался.
def _whisper_available() -> bool:
    try:
        return ((LOCAL_PKGS / "whisper").is_dir()
                and (LOCAL_PKGS / "torch").is_dir())
    except Exception:
        return False

_WHISPER_OK = _whisper_available()

# Размер каждой модели — для подсказки «докачается ~X» в статусе модели.
_MODEL_SIZE = {"tiny": "75 МБ", "base": "145 МБ", "small": "480 МБ",
               "medium": "1.5 ГБ", "large": "2.9 ГБ"}
# Минимальный «здоровый» размер .pt в байтах (~90% от реального). Файл меньше
# этого порога = недокачанный/битый: whisper при запуске не сойдётся по SHA256
# и молча перекачает. Проверяем тут, чтобы не показывать ложное «готова».
_MODEL_MIN_BYTES = {"tiny": 65_000_000, "base": 125_000_000,
                    "small": 430_000_000, "medium": 1_350_000_000,
                    "large": 2_750_000_000}

# Официальные URL моделей OpenAI Whisper. SHA256 модели = предпоследний сегмент
# пути URL (whisper так и хранит). Имя сохраняемого файла = basename URL, чтобы
# совпасть с тем, как whisper.load_model сам кладёт файл (для «large» это
# large-v3.pt) — иначе whisper не найдёт нашу копию и полезет качать заново.
_WHISPER_URLS = {
    "tiny":   "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e/tiny.pt",
    "base":   "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
    "small":  "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
    "medium": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
    "large":  "https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt",
}

def _model_url_parts(m: str):
    """(url, sha256, dest_path) для модели m. dest = whisper_models/<basename>."""
    url = _WHISPER_URLS[m]
    sha = url.rsplit("/", 2)[-2]
    dest = WHISPER_MODELS / url.rsplit("/", 1)[-1]
    return url, sha, dest

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

VERSION = "2.8"
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


def _has_nvidia():
    if not IS_WIN:
        return False
    # wmic удалён начиная с Windows 11 24H2 → powershell + CIM
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            creationflags=0x08000000, stderr=subprocess.DEVNULL,
            text=True, timeout=10)
        if "nvidia" in out.lower():
            return True
    except Exception:
        pass
    # Fallback: nvidia-smi лежит в System32 при установленном драйвере GeForce
    try:
        import shutil
        return shutil.which("nvidia-smi") is not None
    except Exception:
        return False


class App(_BaseApp):
    def __init__(self):
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
        self.resizable(True, True)
        self.minsize(900, 720)

        # WM_DELETE_WINDOW: жёсткий выход (os._exit) — иначе worker-thread с torch/whisper
        # удерживает CUDA/модель в памяти и python.exe висит после закрытия окна.
        # На следующий запуск это приводит к «прога уже запущена».
        def _hard_close():
            try:
                _cancel_event.set()
                self.destroy()
            except Exception:
                pass
            os._exit(0)
        self.protocol("WM_DELETE_WINDOW", _hard_close)

        # Ранняя геометрия + фон — чтобы окно появилось с правильным размером/цветом сразу
        W = 880
        # Стартовая высота — компактно умещается на 1920×1080. Лог растягивается
        # вверх до доступной высоты, юзер тянет окно для большего лога.
        H_target = 960 if _WHISPER_OK else 1020
        sw = self.winfo_screenwidth()
        # Считаем геометрию от РАБОЧЕЙ области (экран минус панель задач), а не
        # от полного экрана — иначе окно с кнопкой «Запустить» уезжает под таскбар.
        wa_w, wa_h = self._work_area()
        self._H_target = H_target
        # ~56px запас на заголовок окна и рамку, чтобы всё окно влезло целиком
        H = min(H_target, wa_h - 56)
        W = min(W, wa_w - 40)
        y = max(0, (wa_h - H - 40) // 2)
        self.configure(fg_color=T("BG"))
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{y}")

        # Иконка сразу — ctypes Load/Send отложим на after(300)
        if IS_WIN:
            _ico = self._find_icon()
            if _ico:
                try:
                    self.iconbitmap(default=str(_ico))
                except Exception:
                    pass
                self.after(300, lambda p=_ico: self._set_win_taskbar_icon(p))

        # Splash overlay — виден пока идёт тяжёлая сборка UI
        self._splash = ctk.CTkLabel(
            self, text="Загрузка…",
            font=ctk.CTkFont("Segoe UI" if IS_WIN else "SF Pro Display", 18),
            text_color=T("SUB"))
        self._splash.place(relx=0.5, rely=0.5, anchor="center")
        self.update()  # принудительная отрисовка splash до тяжёлой работы

        # StringVars (быстро, но нужны _build'у)
        self.folder_var  = ctk.StringVar(value="")
        self.author_var  = ctk.StringVar(value=self._cfg.get("author", "Вы"))
        self.my_display_var   = ctk.StringVar(value=self._cfg.get("my_display", ""))
        self.peer_display_var = ctk.StringVar(value=self._cfg.get("peer_display", ""))
        self.model_var   = ctk.StringVar(value=self._cfg.get("model", "small"))
        self.merge_on    = self._cfg.get("merge_on", False)
        self.fmt_md      = self._cfg.get("fmt_md", False)
        self.show_ts     = self._cfg.get("show_ts", True)
        self.split_mode  = self._cfg.get("split_mode", "none")
        self.auto_open   = self._cfg.get("auto_open", False)
        self.show_src    = self._cfg.get("show_src", False)
        self.date_from   = ctk.StringVar(value="")   # не сохраняем — всегда пустой при старте
        self.date_to     = ctk.StringVar(value="")
        self.running     = False
        self.output_path = None
        self._mbtns      = {}
        self._recent     = self._cfg.get("recent", [])

        # Тяжёлую сборку откладываем — mainloop отрисует splash и вызовет callback
        self.after(10, self._deferred_init)

    def _work_area(self):
        """(width, height) рабочей области экрана — без панели задач Windows."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if IS_WIN:
            try:
                import ctypes
                from ctypes import wintypes
                rect = wintypes.RECT()
                # SPI_GETWORKAREA = 0x0030 → прямоугольник без панели задач
                if ctypes.windll.user32.SystemParametersInfoW(
                        0x0030, 0, ctypes.byref(rect), 0):
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    if w > 0 and h > 0:
                        return w, h
            except Exception:
                pass
        return sw, sh

    def _deferred_init(self):
        self._build()
        self._update_model_status()
        self.update_idletasks()
        # Подгоняем окно по реальной требуемой высоте, гарантируя видимый лог.
        # Логика: измеряем требуемую высоту всего окна (лог при штатных 200px).
        #  • влезает в рабочую область → ставим окно ровно по содержимому
        #    (без пустоты снизу), лог 200px виден целиком;
        #  • не влезает → ужимаем ТОЛЬКО лог до пола 140px, окно = рабочая область.
        # Так нижняя панель «Запустить» никогда не срезается, а лог не схлопывается.
        LOG_FLOOR = 140
        try:
            avail_h = self._work_area()[1] - 56
            req = self.winfo_reqheight()
            if req > avail_h:
                over = req - avail_h
                log_h = max(LOG_FLOOR, int(self.log.cget("height")) - over)
                self.log.configure(height=log_h)
                self.update_idletasks()
                req = self.winfo_reqheight()
            H = min(req, avail_h)
            cur_w = max(self.winfo_width(), 900)
            x, y = self.winfo_x(), self.winfo_y()
            # не даём окну уехать под верх экрана при росте высоты
            if y < 0:
                y = 0
            self.geometry(f"{cur_w}x{H}+{x}+{y}")
        except Exception:
            pass
        try:
            self._splash.destroy()
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

    def _set_win_taskbar_icon(self, ico_path):
        """Ставим иконку в taskbar через ctypes — iconbitmap не всегда работает."""
        try:
            import ctypes
            LR_LOADFROMFILE  = 0x0010
            LR_DEFAULTSIZE   = 0x0040
            IMAGE_ICON       = 1
            WM_SETICON       = 0x0080
            ICON_SMALL       = 0
            ICON_BIG         = 1
            path = str(ico_path)
            # FindWindowW надёжнее GetParent для CustomTkinter
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if not hwnd:
                hwnd = self.winfo_id()
            hicon_big   = ctypes.windll.user32.LoadImageW(
                None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            hicon_small = ctypes.windll.user32.LoadImageW(
                None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,   hicon_big)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            # Также iconbitmap ещё раз — для надёжности
            try:
                self.iconbitmap(default=path)
            except Exception:
                pass
        except Exception:
            pass

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
                "my_display":   self.my_display_var.get(),
                "peer_display": self.peer_display_var.get(),
                "model":    self.model_var.get(),
                "theme":    _theme,
                "fmt_md":    self.fmt_md,
                "show_ts":   self.show_ts,
                "split_mode": self.split_mode,
                "merge_on": self.merge_on,
                "auto_open": self.auto_open,
                "show_src": self.show_src,
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
        p = Path(path)
        if p.is_dir():
            self.folder_var.set(path)
            self.flbl.configure(text=path, text_color=T("TEXT"))
            self._add_recent(path)
            self._save_cfg()
        elif p.is_file():
            # Файл принимаем, режим определит _run по расширению
            self.folder_var.set(path)
            icon = "🎙 " if p.suffix.lower() in {
                ".mp3",".wav",".m4a",".ogg",".oga",".opus",
                ".aac",".flac",".webm",".amr",".mp4"
            } else ""
            self.flbl.configure(text=f"{icon}{path}", text_color=T("TEXT"))
            self._add_recent(path)
            self._save_cfg()

    def _toggle_fmt(self):
        self.fmt_md = not self.fmt_md
        if self.fmt_md:
            self._fmt_btn.configure(text="📝 MD", fg_color=T("ACCENT"), text_color="white")
        else:
            self._fmt_btn.configure(text="📄 TXT", fg_color=T("MUTED"), text_color=T("SUB"))
        self._clear_preset_highlight()

    def _split_labels(self):
        return {"none":  ("📄 один файл",  T("SURFACE"), T("BORDER"), T("SUB")),
                "month": ("📅 по месяцам", T("ACCENT"),  T("ACCENT"), "white"),
                "year":  ("📆 по годам",   T("GREEN"),   T("GREEN"),  "white")}

    def _toggle_split(self):
        cycle = {"none": "month", "month": "year", "year": "none"}
        self.split_mode = cycle[self.split_mode]
        txt, fg, bc, tc = self._split_labels()[self.split_mode]
        self._split_btn.configure(text=txt, fg_color=fg, border_color=bc, text_color=tc)
        self._clear_preset_highlight()

    def _toggle_ts(self):
        self.show_ts = not self.show_ts
        if self.show_ts:
            self._ts_btn.configure(text="🕐 [HH:MM]", fg_color=T("ACCENT"),
                                   border_color=T("ACCENT"), text_color="white")
        else:
            self._ts_btn.configure(text="🕐 без времени", fg_color=T("SURFACE"),
                                   border_color=T("BORDER"), text_color=T("SUB"))
        self._clear_preset_highlight()

    def _toggle_src(self):
        self.show_src = not self.show_src
        if self.show_src:
            self._src_btn.configure(text="🏷 [TG]", fg_color=T("ACCENT"),
                                    border_color=T("ACCENT"), text_color="white")
        else:
            self._src_btn.configure(text="🏷 без меток", fg_color=T("SURFACE"),
                                    border_color=T("BORDER"), text_color=T("SUB"))
        self._clear_preset_highlight()

    def _build(self):
        P = 28

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=P, pady=(26, 0))

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Merge Chat",
                     font=self._f(28, "bold"), text_color=T("TEXT")).pack(side="left")
        ctk.CTkLabel(left, text="  TG · VK · Instagram · WhatsApp → TXT/MD",
                     font=self._f(12), text_color=T("SUB")).pack(side="left", pady=(10, 0))

        right_hdr = ctk.CTkFrame(hdr, fg_color="transparent")
        right_hdr.pack(side="right")



        ctk.CTkButton(right_hdr, text="О программе",
                      width=120, height=32, font=self._f(12),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=10,
                      command=self._show_about).pack(side="right")
        ctk.CTkButton(right_hdr, text="Справка",
                      width=100, height=32, font=self._f(12),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=10,
                      command=self._show_help).pack(side="right", padx=(0, 8))
        ctk.CTkButton(right_hdr, text="⬇ Выгрузить из ВК",
                      width=160, height=32, font=self._f(12, "bold"),
                      fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                      text_color="white", corner_radius=10,
                      command=self._show_vk_fetch_dialog).pack(side="right", padx=(0, 8))

        ctk.CTkFrame(self, fg_color=T("ACCENT"), height=2,
                     corner_radius=1).pack(fill="x", padx=P, pady=(14, 0))
        self._gap(14)

        self._section("1 · Источник: переписка или аудио")
        self._gap(6)

        fc = ctk.CTkFrame(self, fg_color=T("CARD"), corner_radius=14,
                          border_color=T("BORDER"), border_width=1)
        fc.pack(fill="x", padx=P)

        _hint_dnd = " · перетащи сюда" if _HAS_DND else ""
        _src_hint_row = ctk.CTkFrame(fc, fg_color="transparent")
        _src_hint_row.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(_src_hint_row,
                     text=f"Папка переписки или аудио-файл{_hint_dnd}",
                     font=self._f(11), text_color=T("SUB"),
                     anchor="w").pack(side="left")
        self._help_icon(_src_hint_row,
            "Папка с экспортом из мессенджера, отдельный аудиофайл "
            "или папка с аудио. Формат определяется автоматически.\n\n"
            "Подробности — в README."
        ).pack(side="left", padx=(8, 0))

        fi = ctk.CTkFrame(fc, fg_color="transparent")
        fi.pack(fill="x", padx=16, pady=(8, 6))

        hint = " (или перетащи сюда)" if _HAS_DND else ""
        self.flbl = ctk.CTkLabel(fi, text="Не выбрано" + hint,
                                  font=self._mono(12), text_color=T("SUB"),
                                  anchor="w", wraplength=540)
        self.flbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(fi, text="Выбрать…", width=130, height=34,
                      font=self._f(13, "bold"),
                      fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                      corner_radius=8, command=self._pick_source).pack(side="right")

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

        # Пресеты — быстро накатить типичный набор настроек.
        rp = ctk.CTkFrame(si, fg_color="transparent"); rp.pack(fill="x", pady=5)
        ctk.CTkLabel(rp, text="Пресет", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        self._preset_btns = {}
        for label, key, desc in [
            ("💬 Диалог", "dialog",  "1-на-1: время вкл, метки источников выкл, один файл."),
            ("👥 Группа", "forum",   "Групповой чат: метки источников вкл, имена сохранены, один файл."),
            ("📰 Канал",  "channel", "Канал/бот: MD-формат, разбивка по месяцам, время вкл."),
        ]:
            b = ctk.CTkButton(rp, text=label, width=110, height=30,
                              font=self._f(12), fg_color=T("SURFACE"),
                              hover_color=T("BORDER"), text_color=T("SUB"),
                              border_color=T("BORDER"), border_width=1,
                              corner_radius=7,
                              command=lambda k=key: self._apply_preset(k))
            b.pack(side="left", padx=(0, 6))
            self._tip(b, desc)
            self._preset_btns[key] = b
        self._active_preset = None
        self._help_icon(rp,
            "Готовые наборы настроек.\n"
            "Диалог — личная переписка. Группа — общий чат. "
            "Канал — поток сообщений с разбивкой по месяцам."
        ).pack(side="left", padx=(8, 0))

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        # ── Твоё имя ──
        # Используется одновременно: (1) для распознавания твоих сообщений в TG/VK,
        # (2) как подпись в выводе. IG/WA теперь авто-определяют «себя» из participants.
        # Если хочешь разные имена для матчинга и для вывода — раскрой «Дополнительно».
        r1 = ctk.CTkFrame(si, fg_color="transparent"); r1.pack(fill="x", pady=5)
        ctk.CTkLabel(r1, text="Твоё имя", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.author_var, width=220, height=34,
                     font=self._f(13), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), text_color=T("TEXT"),
                     placeholder_text="Ваше имя",
                     corner_radius=8).pack(side="left")
        self._help_icon(r1,
            "Ваше имя в мессенджерах. Нужно чтобы отделить ваши сообщения "
            "от сообщений собеседника, и так же подписать их в готовом файле.\n\n"
            "Если в разных мессенджерах вы под разными вариантами — "
            "перечислите через запятую."
        ).pack(side="left", padx=(8, 0))

        # ── Дополнительно: разные имена для распознавания и для вывода ──
        adv_toggle_var = ctk.BooleanVar(
            value=bool(self.my_display_var.get() or self.peer_display_var.get()))
        self._adv_names_var = adv_toggle_var

        r_adv_h = ctk.CTkFrame(si, fg_color="transparent"); r_adv_h.pack(fill="x", pady=(2, 0))
        adv_chk = ctk.CTkCheckBox(
            r_adv_h, text="Дополнительно: разные имена для вывода",
            variable=adv_toggle_var, onvalue=True, offvalue=False,
            font=self._f(11), text_color=T("SUB"),
            fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
            border_color=T("BORDER"), checkbox_width=16, checkbox_height=16,
            corner_radius=4)
        adv_chk.pack(side="left")
        self._help_icon(r_adv_h,
            "Включите если в готовом файле имена должны выглядеть иначе, "
            "чем в мессенджере. Например, у собеседника в разных мессенджерах "
            "разные имена — задайте одно общее."
        ).pack(side="left", padx=(8, 0))

        # Контейнер с полями вывода — показывается/скрывается по чекбоксу
        r1b = ctk.CTkFrame(si, fg_color="transparent")
        ctk.CTkLabel(r1b, text="Имена в выводе", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        ctk.CTkLabel(r1b, text="Я →", font=self._f(11),
                     text_color=T("SUB")).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(r1b, textvariable=self.my_display_var, width=110, height=32,
                     font=self._f(12), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), text_color=T("TEXT"),
                     placeholder_text="как «Твоё имя»", corner_radius=8).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(r1b, text="Собеседник →", font=self._f(11),
                     text_color=T("SUB")).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(r1b, textvariable=self.peer_display_var, width=160, height=32,
                     font=self._f(12), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), text_color=T("TEXT"),
                     placeholder_text="оставить как есть",
                     corner_radius=8).pack(side="left")

        def _toggle_adv_names(*_):
            if adv_toggle_var.get():
                r1b.pack(fill="x", pady=5, after=r_adv_h)
            else:
                r1b.pack_forget()
                # При выключении — очищаем оба поля чтобы вывод использовал «Твоё имя»
                self.my_display_var.set("")
                self.peer_display_var.set("")
        adv_chk.configure(command=_toggle_adv_names)
        if adv_toggle_var.get():
            r1b.pack(fill="x", pady=5, after=r_adv_h)

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r2 = ctk.CTkFrame(si, fg_color="transparent"); r2.pack(fill="x", pady=5)
        ctk.CTkLabel(r2, text="Модель Whisper", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        mf = ctk.CTkFrame(r2, fg_color="transparent"); mf.pack(side="left")
        # Иконка справки появится после ряда кнопок (см. ниже)
        cur = self._cfg.get("model", "small")
        for m in ["tiny", "base", "small", "medium", "large"]:
            b = ctk.CTkButton(mf, text=m, width=70, height=30, font=self._f(12),
                              fg_color=T("ACCENT") if m == cur else T("SURFACE"),
                              hover_color=T("ACCENT2"),
                              border_color=T("BORDER"), border_width=1, corner_radius=7,
                              command=lambda v=m: self._pick_model(v))
            b.pack(side="left", padx=3)
            self._mbtns[m] = b
        self._help_icon(r2,
            "Качество распознавания голосовых.\n"
            "Больше — точнее, но медленнее и больше места на диске.\n"
            "Для русского рекомендуется medium."
        ).pack(side="left", padx=(8, 0))

        # Статус выбранной модели: скачана / докачается. Модели тянутся при
        # первом запуске в whisper_models/ — тут видно, что уже готово.
        # Зелёная рамка у кнопки = модель скачана (см. _update_model_status).
        self._model_status = ctk.CTkLabel(si, text="", font=self._f(10),
                                          text_color=T("SUB"), anchor="w")
        self._model_status.pack(fill="x", padx=(244, 0), pady=(2, 0))

        # Кнопки управления выбранной моделью — действуют на физический файл
        # whisper_models/<model>.pt. «Скачать» доступна когда модели нет/битая,
        # «Удалить» — когда файл на диске есть. Состояние правит _update_model_status.
        mbtns_row = ctk.CTkFrame(si, fg_color="transparent")
        mbtns_row.pack(fill="x", padx=(244, 0), pady=(4, 0))
        self._model_dl_btn = ctk.CTkButton(
            mbtns_row, text="⬇ Скачать модель", width=170, height=28,
            font=self._f(11), fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
            corner_radius=7, command=self._download_selected_model)
        self._model_dl_btn.pack(side="left", padx=(0, 6))
        self._model_del_btn = ctk.CTkButton(
            mbtns_row, text="🗑 Удалить модель", width=170, height=28,
            font=self._f(11), fg_color=T("SURFACE"), hover_color="#882828",
            border_color=T("BORDER"), border_width=1, corner_radius=7,
            command=self._delete_selected_model)
        self._model_del_btn.pack(side="left")

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        self._whisper_banner = ctk.CTkFrame(si, fg_color="#261A08", corner_radius=10,
                                             border_color="#5A3A10", border_width=1)
        ctk.CTkLabel(self._whisper_banner,
                     text="Whisper не установлен — голосовые не расшифруются",
                     font=self._f(11), text_color="#E8944A").pack(side="left", padx=(12, 4), pady=8)
        ctk.CTkButton(self._whisper_banner, text="Установить", width=100, height=26,
                      font=self._f(11), fg_color="#D07030", hover_color="#B05020",
                      text_color="white", corner_radius=8,
                      command=self._show_install_dialog).pack(side="right", padx=(4, 12), pady=8)

        # Якорь для жёлтого баннера Whisper (раньше тут был тоггл «склеивать подряд»;
        # фича ломает структуру каналов и паттерн переписки — убрана из UI,
        # CLI-флаг --merge остаётся в merge_chat.py для совместимости).
        r3 = ctk.CTkFrame(si, fg_color="transparent", height=1); r3.pack(fill="x")
        self._whisper_banner_anchor = r3
        self._whisper_installed = _WHISPER_OK
        if not self._whisper_installed:
            self._whisper_banner.pack(fill="x", pady=(0, 8), before=r3)

        r4 = ctk.CTkFrame(si, fg_color="transparent"); r4.pack(fill="x", pady=5)
        ctk.CTkLabel(r4, text="Формат · Время · Источник", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        fmt_text = "📝 MD" if self.fmt_md else "📄 TXT"
        fmt_fg   = T("ACCENT") if self.fmt_md else T("MUTED")
        fmt_tc   = "white" if self.fmt_md else T("SUB")
        self._fmt_btn = ctk.CTkButton(
            r4, text=fmt_text, width=90, height=30, font=self._f(12, "bold"),
            fg_color=fmt_fg, hover_color=T("ACCENT2"),
            text_color=fmt_tc, corner_radius=7, command=self._toggle_fmt)
        self._fmt_btn.pack(side="left")
        _ts_fg  = T("ACCENT")  if self.show_ts else T("SURFACE")
        _ts_bc  = T("ACCENT")  if self.show_ts else T("BORDER")
        _ts_tc  = "white"      if self.show_ts else T("SUB")
        _ts_txt = "🕐 [HH:MM]" if self.show_ts else "🕐 без времени"
        self._ts_btn = ctk.CTkButton(
            r4, text=_ts_txt, width=130, height=30, font=self._f(12, "bold"),
            fg_color=_ts_fg, hover_color=T("ACCENT2"), border_color=_ts_bc, border_width=1,
            text_color=_ts_tc, corner_radius=7, command=self._toggle_ts)
        self._ts_btn.pack(side="left", padx=(6, 0))
        _src_fg = T("ACCENT") if self.show_src else T("SURFACE")
        _src_bc = T("ACCENT") if self.show_src else T("BORDER")
        _src_tc = "white"     if self.show_src else T("SUB")
        _src_txt = "🏷 [TG]"  if self.show_src else "🏷 без меток"
        self._src_btn = ctk.CTkButton(
            r4, text=_src_txt, width=120, height=30, font=self._f(12, "bold"),
            fg_color=_src_fg, hover_color=T("ACCENT2"),
            border_color=_src_bc, border_width=1,
            text_color=_src_tc, corner_radius=7, command=self._toggle_src)
        self._src_btn.pack(side="left", padx=(6, 0))
        self._help_icon(r4,
            "Формат файла, показывать ли время рядом с каждым сообщением "
            "и помечать ли мессенджер-источник.\n\n"
            "Подробности — в README."
        ).pack(side="left", padx=(8, 0))

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
        _sp_txt, _sp_fg, _sp_bc, _sp_tc = self._split_labels()[self.split_mode]
        self._split_btn = ctk.CTkButton(
            df, text=_sp_txt, width=120, height=30, font=self._f(11, "bold"),
            fg_color=_sp_fg, hover_color=T("ACCENT2"), border_color=_sp_bc, border_width=1,
            text_color=_sp_tc, corner_radius=7, command=self._toggle_split)
        self._split_btn.pack(side="left", padx=(8, 0))
        self._help_icon(df,
            "Период — взять только сообщения в выбранном диапазоне дат.\n"
            "Разбивка — один файл, или отдельные файлы по месяцам/годам "
            "(удобно для очень длинных переписок)."
        ).pack(side="left", padx=(8, 0))

        ctk.CTkFrame(si, fg_color=T("BORDER"), height=1).pack(fill="x", pady=8)

        r6 = ctk.CTkFrame(si, fg_color="transparent"); r6.pack(fill="x", pady=5)
        ctk.CTkLabel(r6, text="Фильтр (опционально)", font=self._f(13),
                     text_color=T("TEXT"), width=240, anchor="w").pack(side="left")
        self.filter_author = ctk.StringVar(value="")
        self.filter_text   = ctk.StringVar(value="")
        ctk.CTkLabel(r6, text="от:", font=self._f(11),
                     text_color=T("SUB")).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(r6, textvariable=self.filter_author, width=130, height=30,
                     font=self._mono(11), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), border_width=1,
                     placeholder_text="имя автора",
                     text_color=T("TEXT"), corner_radius=7).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(r6, text="содержит:", font=self._f(11),
                     text_color=T("SUB")).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(r6, textvariable=self.filter_text, width=160, height=30,
                     font=self._mono(11), fg_color=T("SURFACE"),
                     border_color=T("BORDER"), border_width=1,
                     placeholder_text="слово/regex",
                     text_color=T("TEXT"), corner_radius=7).pack(side="left")
        self._help_icon(r6,
            "От — оставить только сообщения определённого автора "
            "(можно часть имени, без учёта регистра).\n"
            "Содержит — оставить только сообщения с заданным текстом.\n\n"
            "Подробности и примеры — в README."
        ).pack(side="left", padx=(8, 0))

        self._gap(16)

        # ── Нижняя панель действий: пакуем side="bottom" ДО секции 3.
        # pack отдаёт место expand-виджету (секция 3) и обрезает то, что
        # запаковано после него. Раньше панель с кнопкой «Запустить» паковалась
        # последней — при нехватке высоты её срезало целиком. Теперь она
        # резервирует место снизу, а ужимается первым лог-бокс секции 3.
        self._bf = ctk.CTkFrame(self, fg_color="transparent")
        self._bf.pack(side="bottom", fill="x", padx=P, pady=(12, 24))
        ctk.CTkFrame(self, fg_color=T("BORDER"), height=1).pack(
            side="bottom", fill="x", padx=P, pady=(12, 0))

        self.obtn = ctk.CTkButton(
            self._bf, text="Открыть папку", width=170, height=46,
            font=self._f(13), fg_color=T("MUTED"), hover_color=T("BORDER"),
            text_color=T("SUB"), corner_radius=10, state="disabled",
            command=self._open_output)
        self.obtn.pack(side="left")

        self._auto_open_var = ctk.BooleanVar(value=self.auto_open)
        ctk.CTkCheckBox(
            self._bf, text="открывать сразу после готово",
            variable=self._auto_open_var,
            onvalue=True, offvalue=False,
            font=self._f(11), text_color=T("SUB"),
            fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
            border_color=T("BORDER"), checkbox_width=18, checkbox_height=18,
            corner_radius=4, command=self._toggle_auto_open
        ).pack(side="left", padx=(10, 0))

        self.cbtn = ctk.CTkButton(
            self._bf, text="Отмена", width=130, height=46, font=self._f(13),
            fg_color="#7A1515", hover_color="#5A0F0F",
            text_color="white", corner_radius=10, command=self._cancel)

        self.rbtn = ctk.CTkButton(
            self._bf, text="Запустить", width=190, height=46,
            font=self._f(15, "bold"), fg_color=T("ACCENT"),
            hover_color=T("ACCENT2"), corner_radius=10, command=self._run)
        self.rbtn.pack(side="right")

        # ── Секция 3 — заполняет всё место между настройками и нижней панелью.
        self._section("3 · Процесс")
        self._gap(6)
        pc = ctk.CTkFrame(self, fg_color=T("CARD"), corner_radius=14,
                          border_color=T("BORDER"), border_width=1)
        pc.pack(fill="both", expand=True, padx=P)
        pi = ctk.CTkFrame(pc, fg_color="transparent")
        pi.pack(fill="both", expand=True, padx=4, pady=4)

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
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 4))

        ctk.CTkButton(pi, text="Скопировать лог", height=28, font=self._f(11),
                      fg_color="transparent", hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=6, anchor="w",
                      command=self._copy_log).pack(anchor="w", padx=10, pady=(0, 8))

    def _gap(self, h=12):
        ctk.CTkFrame(self, fg_color="transparent", height=h).pack()

    def _section(self, txt):
        ctk.CTkLabel(self, text=txt, font=self._f(11, "bold"),
                     text_color=T("SUB")).pack(anchor="w", padx=28)

    # ── Тултипы: лёгкое всплывающее окошко рядом с виджетом.
    # Используется и для иконок «?», и для полноценных кнопок (можно повесить на любой widget).
    def _tip(self, widget, text: str):
        if not text:
            return
        state = {"tip": None}

        def _show(_e=None):
            if state["tip"] is not None:
                return
            import tkinter as _tk
            # Размещаем тултип справа от виджета чтобы не перекрывать соседние ряды
            x = widget.winfo_rootx() + widget.winfo_width() + 8
            y = widget.winfo_rooty() - 4
            tip = _tk.Toplevel(widget)
            try:
                tip.wm_overrideredirect(True)
                tip.wm_attributes("-topmost", True)
            except Exception:
                pass
            tip.wm_geometry(f"+{x}+{y}")
            tip.configure(bg="#1A1F2A")
            _tk.Label(tip, text=text, justify="left",
                      bg="#1A1F2A", fg="#E0E6F0",
                      relief="solid", borderwidth=1,
                      padx=12, pady=8, wraplength=300,
                      font=("Segoe UI" if IS_WIN else "SF Pro Display", 10)
                      ).pack()
            state["tip"] = tip

        def _hide(_e=None):
            if state["tip"] is not None:
                try: state["tip"].destroy()
                except Exception: pass
                state["tip"] = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)
        widget.bind("<ButtonPress>", _hide)

    def _help_icon(self, parent, tip_text: str):
        """Маленькая иконка '?' — наводишь, всплывает подсказка."""
        lbl = ctk.CTkLabel(parent, text="?", width=18, height=18,
                           font=self._f(11, "bold"),
                           text_color=T("SUB"), cursor="hand2")
        self._tip(lbl, tip_text)
        # При клике — тоже показать (для тач-устройств)
        lbl.bind("<Button-1>", lambda _e, w=lbl, t=tip_text: self._tip_pin(w, t))
        return lbl

    def _tip_pin(self, anchor_widget, text: str):
        """По клику на '?' — показать тултип на 4 секунды (если hover не сработал)."""
        import tkinter as _tk
        x = anchor_widget.winfo_rootx() + anchor_widget.winfo_width() + 8
        y = anchor_widget.winfo_rooty() - 4
        tip = _tk.Toplevel(anchor_widget)
        try:
            tip.wm_overrideredirect(True)
            tip.wm_attributes("-topmost", True)
        except Exception:
            pass
        tip.wm_geometry(f"+{x}+{y}")
        tip.configure(bg="#1A1F2A")
        _tk.Label(tip, text=text, justify="left",
                  bg="#1A1F2A", fg="#E0E6F0",
                  relief="solid", borderwidth=1,
                  padx=12, pady=8, wraplength=300,
                  font=("Segoe UI" if IS_WIN else "SF Pro Display", 10)).pack()
        tip.after(4000, lambda: tip.destroy() if tip.winfo_exists() else None)

    # ── Единый стиль модальных окон: оверлей-карточка поверх главного окна.
    # Заменяет ctk.CTkToplevel — иначе диалог появляется на случайной позиции
    # ОС, выглядит «отдельной программой». Оверлей всегда центрирован в окне.
    def _overlay(self, title: str, width: int = 520, height: int = 420,
                 backdrop: bool = False):
        """Возвращает (overlay_root, content_frame, close_fn).
        content_frame — куда класть содержимое диалога (pack/grid внутри).
        width/height — желаемый минимум; карточка тянется до 85% окна.
        backdrop=False (по умолчанию) — карточка кладётся поверх главного окна
        без затемнения: главный UI остаётся виден вокруг карточки. Раньше дефолт
        был True и закрашивал всё окно ровным SURFACE — маленькая карточка в
        огромном тёмном поле выглядела как «сломанное пустое окно»."""
        # Закрываем предыдущий оверлей если он есть (чтобы не накладывались)
        prev = getattr(self, "_active_overlay", None)
        if prev is not None:
            try: prev.destroy()
            except Exception: pass

        # Карточка ровно того размера, что запросил вызывающий — не раздуваем
        # на «75% окна», иначе мелкий контент тонет в пустоте.
        self.update_idletasks()
        avail_w = max(self.winfo_width(), 600)
        avail_h = max(self.winfo_height(), 500)
        card_w = min(width, max(420, avail_w - 80))
        card_h = min(height, max(380, avail_h - 80))

        if backdrop:
            # Backdrop — слегка отличный от BG оттенок (SURFACE) чтобы было
            # ощущение «модальный слой над окном», но без чёрного провала.
            overlay = ctk.CTkFrame(self, fg_color=T("SURFACE"), corner_radius=0)
            overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            # Без затемнения: контейнер размером с карточку, центрирован.
            # Главный интерфейс остаётся виден вокруг.
            # width/height — ТОЛЬКО в конструкторе: CTk-виджеты не принимают их в .place().
            overlay = ctk.CTkFrame(self, fg_color="transparent",
                                   width=card_w + 10, height=card_h + 10)
            overlay.place(relx=0.5, rely=0.5, anchor="center")
        self._active_overlay = overlay

        # Имитация тени
        shadow = ctk.CTkFrame(overlay, fg_color=T("BG"), corner_radius=16,
                              width=card_w + 6, height=card_h + 6)
        shadow.place(relx=0.5, rely=0.5, anchor="center", x=2, y=3)

        card = ctk.CTkFrame(overlay, fg_color=T("CARD"), corner_radius=14,
                            border_color=T("BORDER"), border_width=1,
                            width=card_w, height=card_h)
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.pack_propagate(False)

        def _close():
            self._active_overlay = None
            try: self.unbind("<Escape>")
            except Exception: pass
            try: overlay.destroy()
            except Exception: pass

        head = ctk.CTkFrame(card, fg_color="transparent", height=42)
        head.pack(fill="x", padx=16, pady=(10, 0))
        head.pack_propagate(False)
        ctk.CTkLabel(head, text=title, font=self._f(15, "bold"),
                     text_color=T("TEXT")).pack(side="left", pady=4)
        ctk.CTkButton(head, text="✕", width=30, height=28, font=self._f(14),
                      fg_color="transparent", hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=6,
                      command=_close).pack(side="right")
        ctk.CTkFrame(card, fg_color=T("BORDER"), height=1).pack(
            fill="x", padx=16, pady=(6, 0))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=12)

        # Esc → закрыть; клик вне карточки → закрыть
        self.bind("<Escape>", lambda e: _close())
        overlay.bind("<Button-1>",
                     lambda e: _close() if e.widget is overlay else None)
        return overlay, content, _close

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

    def _pick_audio(self):
        from tkinter import filedialog
        types = [("Аудио", "*.mp3 *.wav *.m4a *.ogg *.oga *.opus *.aac *.flac *.webm *.amr *.mp4"),
                 ("Все файлы", "*.*")]
        f = filedialog.askopenfilename(title="Выберите аудио-файл", filetypes=types)
        if f:
            self.folder_var.set(f)
            self.flbl.configure(text=f"🎙 {f}", text_color=T("TEXT"))
            self._add_recent(f)
            self._save_cfg()

    def _pick_source(self):
        """Оверлей с тремя вариантами: переписка / аудио-файл / папка только с аудио."""
        overlay, content, close = self._overlay("Что обрабатываем?", width=480, height=340)

        ctk.CTkLabel(content,
                     text="Программа сама определит режим по содержимому,\n"
                          "но проще выбрать явно.",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack(pady=(2, 14))

        def _do(cmd):
            close()
            cmd()

        ctk.CTkButton(content, text="📁  Папка с перепиской",
                      height=44, font=self._f(13, "bold"),
                      fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                      corner_radius=8,
                      command=lambda: _do(self._pick_folder)
                      ).pack(fill="x", pady=4)
        ctk.CTkButton(content, text="🎙  Аудио-файл (один)",
                      height=44, font=self._f(13),
                      fg_color=T("SURFACE"), hover_color=T("BORDER"),
                      border_color=T("BORDER"), border_width=1,
                      text_color=T("TEXT"), corner_radius=8,
                      command=lambda: _do(self._pick_audio)
                      ).pack(fill="x", pady=4)
        ctk.CTkButton(content, text="📂  Папка только с аудио",
                      height=44, font=self._f(13),
                      fg_color=T("SURFACE"), hover_color=T("BORDER"),
                      border_color=T("BORDER"), border_width=1,
                      text_color=T("TEXT"), corner_radius=8,
                      command=lambda: _do(self._pick_folder)
                      ).pack(fill="x", pady=4)

    def _pick_model(self, m):
        self.model_var.set(m)
        for k, b in self._mbtns.items():
            b.configure(fg_color=T("ACCENT") if k == m else T("SURFACE"))
        self._update_model_status()

    def _model_state(self, m: str) -> str:
        """Состояние модели m: 'ok' | 'partial' | 'absent'.
        Маска со звёздочкой: «large» сохраняется whisper'ом как large-v3.pt.
        'partial' — файл есть, но меньше порога (недокачан/битый): whisper
        не сойдётся по SHA256 и перекачает. Не считать такой файл готовым."""
        try:
            files = list(WHISPER_MODELS.glob(f"{m}*.pt"))
        except Exception:
            return "absent"
        if not files:
            return "absent"
        floor = _MODEL_MIN_BYTES.get(m, 0)
        if any(f.stat().st_size >= floor for f in files):
            return "ok"
        return "partial"

    def _model_downloaded(self, m: str) -> bool:
        """Готова ли модель m к работе (есть и не битая)."""
        return self._model_state(m) == "ok"

    def _update_model_status(self):
        """Подсветить кнопки моделей по факту скачивания (зелёная рамка) и
        показать текстовый статус выбранной модели."""
        if not hasattr(self, "_model_status"):
            return
        for k, b in self._mbtns.items():
            try:
                b.configure(border_color=T("GREEN") if self._model_downloaded(k)
                            else T("BORDER"))
            except Exception:
                pass
        m = self.model_var.get() if hasattr(self, "model_var") else ""
        state = self._model_state(m)
        sz = _MODEL_SIZE.get(m, "?")
        if not getattr(self, "_whisper_installed", False):
            self._model_status.configure(
                text="Whisper не установлен — модели расшифровки недоступны",
                text_color=T("SUB"))
        elif state == "ok":
            self._model_status.configure(
                text=f"✓ модель «{m}» скачана, готова к работе",
                text_color=T("GREEN"))
        elif state == "partial":
            self._model_status.configure(
                text=f"⚠ модель «{m}» скачана не полностью (битый файл) — "
                     f"нажмите «Скачать модель», чтобы докачать (~{sz})",
                text_color="#E8944A")
        else:
            self._model_status.configure(
                text=f"↓ модель «{m}» не скачана — нажмите «Скачать модель» "
                     f"(~{sz}) или она докачается при первом запуске",
                text_color="#E8944A")
        # Кнопки управления моделью: «Скачать» когда не готова, «Удалить» когда
        # файл есть. Во время идущей загрузки обе заблокированы.
        if hasattr(self, "_model_dl_btn"):
            busy = getattr(self, "_model_dl_active", False)
            can_dl = (m in _WHISPER_URLS) and state != "ok" and not busy
            can_del = state != "absent" and not busy
            try:
                self._model_dl_btn.configure(
                    state="normal" if can_dl else "disabled",
                    text="⬇ Докачать модель" if state == "partial" else "⬇ Скачать модель")
                self._model_del_btn.configure(
                    state="normal" if can_del else "disabled")
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────
    #  Управление моделями Whisper — кнопками, с отражением на диске
    # ──────────────────────────────────────────────────────────
    def _delete_selected_model(self):
        """Физически удалить .pt выбранной модели из whisper_models/."""
        m = self.model_var.get() if hasattr(self, "model_var") else ""
        files = list(WHISPER_MODELS.glob(f"{m}*.pt")) + \
                list(WHISPER_MODELS.glob(f"{m}*.pt.part"))
        if not files:
            return
        total_mb = sum(f.stat().st_size for f in files) / 1024 / 1024
        overlay, content, close = self._overlay(
            "Удалить модель", width=460, height=220)
        ctk.CTkLabel(content,
                     text=f"Удалить модель «{m}» с диска?\n"
                          f"Освободится ~{total_mb:.0f} МБ. Скачать заново можно "
                          f"кнопкой «Скачать модель».",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack(pady=(6, 14))
        bf = ctk.CTkFrame(content, fg_color="transparent"); bf.pack()

        def do_del():
            errs = []
            for f in files:
                try:
                    f.unlink()
                except Exception as e:
                    errs.append(str(e))
            close()
            self._update_model_status()
            if errs:
                self._overlay_message("Ошибка удаления", "\n".join(errs))

        ctk.CTkButton(bf, text="Отмена", width=120, height=36, font=self._f(12),
                      fg_color=T("SURFACE"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=8,
                      command=close).pack(side="left", padx=6)
        ctk.CTkButton(bf, text="Удалить", width=120, height=36,
                      font=self._f(12, "bold"), fg_color="#AA3333",
                      hover_color="#882828", corner_radius=8,
                      command=do_del).pack(side="left", padx=6)

    def _overlay_message(self, title: str, msg: str):
        """Простое модальное сообщение с кнопкой «Ок»."""
        overlay, content, close = self._overlay(title, width=460, height=200)
        ctk.CTkLabel(content, text=msg, font=self._f(11), text_color=T("TEXT"),
                     justify="center", wraplength=400).pack(pady=(10, 16))
        ctk.CTkButton(content, text="Ок", width=120, height=36,
                      font=self._f(12, "bold"), fg_color=T("ACCENT"),
                      hover_color=T("ACCENT2"), corner_radius=8,
                      command=close).pack()

    def _download_selected_model(self):
        """Скачать выбранную модель в whisper_models/ — с докачкой и проверкой
        SHA256. Канал к CDN из РФ медленный, поэтому: резюмируемая загрузка
        (Range) + контрольная сумма, чтобы обрыв не оставлял битый файл."""
        m = self.model_var.get() if hasattr(self, "model_var") else ""
        if m not in _WHISPER_URLS:
            return
        url, sha, dest = _model_url_parts(m)
        sz = _MODEL_SIZE.get(m, "?")
        cancel = threading.Event()

        overlay, content, close = self._overlay(
            f"Скачивание модели «{m}»", width=560, height=360)
        ctk.CTkLabel(content,
                     text=f"Модель «{m}» (~{sz}) скачивается в папку программы.\n"
                          "Можно прервать и докачать позже — прогресс сохраняется.",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack(pady=(2, 10))
        pbar = ctk.CTkProgressBar(content, height=8, fg_color=T("SURFACE"),
                                  progress_color=T("ACCENT"), corner_radius=2)
        pbar.pack(fill="x", pady=(4, 2)); pbar.set(0)
        plbl = ctk.CTkLabel(content, text="Подключение…", font=self._f(10),
                            text_color=T("SUB"))
        plbl.pack(anchor="w")
        log_box = ctk.CTkTextbox(content, font=self._mono(11), fg_color=T("SURFACE"),
                                 text_color=T("TEXT"), height=140, corner_radius=8,
                                 border_color=T("BORDER"), border_width=1)
        log_box.pack(fill="both", expand=True, pady=(8, 8))
        log_box.configure(state="disabled")
        bf = ctk.CTkFrame(content, fg_color="transparent"); bf.pack(fill="x")
        action_btn = ctk.CTkButton(bf, text="Отмена", width=130, height=36,
                                   font=self._f(12), fg_color=T("SURFACE"),
                                   hover_color="#882828", text_color=T("SUB"),
                                   corner_radius=8, command=cancel.set)
        action_btn.pack(side="right")

        def _append(line):
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n"); log_box.see("end")
            log_box.configure(state="disabled")

        def progress(frac, done, total, speed):
            pbar.set(max(0.0, min(1.0, frac)))
            plbl.configure(text=f"{done/1024/1024:.0f} / {total/1024/1024:.0f} МБ  "
                                f"·  {speed:.1f} МБ/с")

        def done(success, message):
            self._model_dl_active = False
            self._update_model_status()
            _append(message)
            if success:
                pbar.set(1.0)
                plbl.configure(text="Готово — модель проверена и готова к работе.",
                               text_color=T("GREEN"))
            else:
                plbl.configure(text=message, text_color="#E8944A")
            action_btn.configure(text="Закрыть", fg_color=T("SURFACE"),
                                 hover_color=T("BORDER"), command=close)

        self._model_dl_active = True
        self._update_model_status()
        ui = {
            "append":  lambda s: self.after(0, _append, s),
            "progress": lambda *a: self.after(0, progress, *a),
            "status":  lambda s: self.after(0, plbl.configure, {"text": s}),
            "done":    lambda ok, msg: self.after(0, done, ok, msg),
            "cancel":  cancel,
        }
        threading.Thread(target=self._download_model_worker,
                         args=(m, ui), daemon=True).start()

    # Качаем модель в N параллельных соединений (как менеджер загрузок/торрент):
    # один HTTPS-поток к CDN из РФ шейпится, а 8 потоков складывают скорость.
    _DL_CONNECTIONS = 8
    _DL_CHUNK = 16 * 1024 * 1024   # размер куска под одно Range-соединение

    def _download_model_worker(self, m, ui):
        import hashlib, urllib.request, time, json
        import threading as _th, queue as _q
        try:
            url, sha, dest = _model_url_parts(m)
            WHISPER_MODELS.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            idxf = dest.with_name(dest.name + ".idx")   # индекс готовых кусков
            ui["append"](f"Источник: {url}")
            ui["append"](f"Файл: {dest}")

            # Узнаём полный размер + поддержку Range (Content-Range при 206).
            def _probe():
                rq = urllib.request.Request(url)
                rq.add_header("Range", "bytes=0-0")
                r = urllib.request.urlopen(rq, timeout=30)
                cr = r.headers.get("Content-Range", "")
                code = r.getcode()
                cl = r.headers.get("Content-Length")
                r.close()
                if code == 206 and "/" in cr:
                    return int(cr.rsplit("/", 1)[-1]), True
                return int(cl or 0), False
            total, ranges = _probe()

            if not ranges or total <= 0:
                ui["append"]("Сервер не поддержал многопоточность — качаю в 1 поток")
                return self._download_single_stream(url, sha, dest, part, total, ui)

            n_conn = max(1, min(self._DL_CONNECTIONS, (total // self._DL_CHUNK) + 1))
            n_chunks = (total + self._DL_CHUNK - 1) // self._DL_CHUNK
            ui["append"](f"Размер: {total/1024/1024:.0f} МБ · потоков: {n_conn} · "
                         f"кусков по {self._DL_CHUNK//1024//1024} МБ: {n_chunks}")

            # Докачка: читаем индекс готовых кусков, если .part уже нужного размера.
            done_idx = set()
            if idxf.exists() and part.exists() and part.stat().st_size == total:
                try:
                    done_idx = set(json.loads(idxf.read_text()))
                    ui["append"](f"Докачка: уже готово {len(done_idx)}/{n_chunks} кусков")
                except Exception:
                    done_idx = set()
            else:
                # Свежий старт — преаллоцируем файл на полный размер.
                with open(part, "wb") as f:
                    f.truncate(total)
                done_idx = set()

            lock = _th.Lock()
            done_bytes = [min(len(done_idx) * self._DL_CHUNK, total)]
            init_bytes = done_bytes[0]
            t0 = time.time()
            err = [None]
            tasks = _q.Queue()
            for i in range(n_chunks):
                if i not in done_idx:
                    tasks.put(i)

            def worker():
                while err[0] is None and not ui["cancel"].is_set():
                    try:
                        i = tasks.get_nowait()
                    except _q.Empty:
                        return
                    start = i * self._DL_CHUNK
                    end = min(start + self._DL_CHUNK, total) - 1
                    want = end - start + 1
                    last_e = None
                    for _attempt in range(3):
                        if ui["cancel"].is_set():
                            return
                        try:
                            rq = urllib.request.Request(url)
                            rq.add_header("Range", f"bytes={start}-{end}")
                            r = urllib.request.urlopen(rq, timeout=30)
                            data = r.read(); r.close()
                            if len(data) != want:
                                raise IOError(f"неполный кусок {len(data)}/{want}")
                            with open(part, "r+b") as f:
                                f.seek(start); f.write(data)
                            last_e = None
                            break
                        except Exception as e:
                            last_e = e
                            time.sleep(1.0)
                    if last_e is not None:
                        err[0] = last_e
                        return
                    with lock:
                        done_idx.add(i)
                        done_bytes[0] = min(done_bytes[0] + want, total)
                        try: idxf.write_text(json.dumps(sorted(done_idx)))
                        except Exception: pass
                        now = time.time()
                        spd = (done_bytes[0] - init_bytes) / max(now - t0, 0.01) / 1024 / 1024
                        ui["progress"](done_bytes[0] / total, done_bytes[0], total, spd)

            threads = [_th.Thread(target=worker, daemon=True) for _ in range(n_conn)]
            for t in threads: t.start()
            for t in threads: t.join()

            if ui["cancel"].is_set():
                ui["done"](False, "Отменено — прогресс сохранён, можно докачать.")
                return
            if err[0] is not None:
                ui["done"](False, f"Ошибка сети: {err[0]} — прогресс сохранён, докачайте.")
                return

            ui["status"]("Проверка контрольной суммы (SHA256)…")
            ui["append"]("Скачано, проверяю целостность…")
            h = hashlib.sha256()
            with open(part, "rb") as f:
                for b in iter(lambda: f.read(1048576), b""):
                    h.update(b)
            if h.hexdigest() != sha:
                for p in (part, idxf):
                    try: p.unlink()
                    except Exception: pass
                ui["done"](False, "SHA256 не совпал — файл повреждён. Нажмите «Скачать» ещё раз.")
                return
            if dest.exists():
                dest.unlink()
            part.rename(dest)
            try: idxf.unlink()
            except Exception: pass
            ui["done"](True, "✓ Контрольная сумма верна.")
        except Exception as e:
            ui["done"](False, f"Ошибка загрузки: {e}")

    def _download_single_stream(self, url, sha, dest, part, total, ui):
        """Запасной путь: один поток с докачкой (если сервер не отдаёт Range)."""
        import hashlib, urllib.request, time
        try:
            resume = part.stat().st_size if part.exists() else 0
            req = urllib.request.Request(url)
            if resume:
                req.add_header("Range", f"bytes={resume}-")
            resp = urllib.request.urlopen(req, timeout=30)
            if resume and resp.getcode() != 206:
                resume = 0
                try: part.unlink()
                except Exception: pass
            if not total:
                total = int(resp.headers.get("Content-Length") or 0) + resume
            downloaded = resume
            t0 = time.time(); last = 0.0
            with open(part, "ab" if resume else "wb") as f:
                while True:
                    if ui["cancel"].is_set():
                        ui["done"](False, "Отменено — прогресс сохранён, можно докачать.")
                        return
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last > 0.3:
                        last = now
                        spd = (downloaded - resume) / max(now - t0, 0.01) / 1024 / 1024
                        ui["progress"](downloaded / total if total else 0,
                                       downloaded, total, spd)
            ui["status"]("Проверка контрольной суммы (SHA256)…")
            h = hashlib.sha256()
            with open(part, "rb") as f:
                for b in iter(lambda: f.read(1048576), b""):
                    h.update(b)
            if h.hexdigest() != sha:
                try: part.unlink()
                except Exception: pass
                ui["done"](False, "SHA256 не совпал — файл повреждён. Нажмите «Скачать» ещё раз.")
                return
            if dest.exists():
                dest.unlink()
            part.rename(dest)
            ui["done"](True, "✓ Контрольная сумма верна.")
        except Exception as e:
            ui["done"](False, f"Ошибка загрузки: {e}")

    # ──────────────────────────────────────────────────────────
    #  Выгрузка переписки из ВКонтакте (VK API) прямо из GUI
    # ──────────────────────────────────────────────────────────
    def _vk_accounts(self) -> dict:
        """{подпись: токен}. Источники: tools/.env (dev-машина) + config
        (vk_tokens, сохранённые через диалог; перекрывают .env по подписи)."""
        accts = {}
        label_map = {"VK_TOKEN": "Основной"}
        try:
            env_path = (SCRIPT.parent / "tools" / ".env") if SCRIPT else None
            if env_path and env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = (x.strip() for x in line.split("=", 1))
                    if k.startswith("VK_TOKEN") and v:
                        accts[label_map.get(k, k.replace("VK_TOKEN_", "").title() or "Основной")] = v
        except Exception:
            pass
        for label, tok in (self._cfg.get("vk_tokens") or {}).items():
            if tok:
                accts[label] = tok
        return accts

    def _show_vk_fetch_dialog(self):
        vk_script = (SCRIPT.parent / "tools" / "vk_fetch_history.py") if SCRIPT else None
        overlay, content, close = self._overlay(
            "Выгрузить из ВКонтакте", width=620, height=560)

        if not vk_script or not vk_script.exists():
            ctk.CTkLabel(content,
                         text="Не найден tools/vk_fetch_history.py рядом с программой.",
                         font=self._f(12), text_color="#f87171",
                         wraplength=540, justify="left").pack(pady=20)
            return

        ctk.CTkLabel(content,
                     text="Тянет историю диалога напрямую через VK API (с пересланными).\n"
                          "Токен — на vkhost.github.io (Kate Mobile → Разрешить).",
                     font=self._f(11), text_color=T("SUB"),
                     justify="left", anchor="w").pack(fill="x", pady=(0, 10))

        accounts = self._vk_accounts()
        acc_labels = list(accounts.keys())

        # ── Аккаунт (сохранённые токены) ──
        row_acc = ctk.CTkFrame(content, fg_color="transparent"); row_acc.pack(fill="x", pady=4)
        ctk.CTkLabel(row_acc, text="Аккаунт", font=self._f(12),
                     text_color=T("TEXT"), width=110, anchor="w").pack(side="left")
        acc_var = ctk.StringVar(value=acc_labels[0] if acc_labels else "— вставь токен ниже —")
        acc_menu = ctk.CTkOptionMenu(
            row_acc, values=acc_labels or ["— вставь токен ниже —"], variable=acc_var,
            width=200, height=30, font=self._f(12),
            fg_color=T("SURFACE"), button_color=T("BORDER"),
            button_hover_color=T("ACCENT"), text_color=T("TEXT"),
            dropdown_fg_color=T("SURFACE"))
        acc_menu.pack(side="left")

        # ── Токен вручную (override) + запомнить ──
        row_tok = ctk.CTkFrame(content, fg_color="transparent"); row_tok.pack(fill="x", pady=4)
        ctk.CTkLabel(row_tok, text="или токен", font=self._f(12),
                     text_color=T("SUB"), width=110, anchor="w").pack(side="left")
        tok_var = ctk.StringVar(value="")
        ctk.CTkEntry(row_tok, textvariable=tok_var, height=30, font=self._mono(11),
                     fg_color=T("SURFACE"), border_color=T("BORDER"), text_color=T("TEXT"),
                     placeholder_text="vk1.a.… (перекрывает выбранный аккаунт)",
                     corner_radius=8).pack(side="left", fill="x", expand=True)

        row_rem = ctk.CTkFrame(content, fg_color="transparent"); row_rem.pack(fill="x", pady=(0, 4))
        rem_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row_rem, text="запомнить токен как:", variable=rem_var,
                        font=self._f(11), text_color=T("SUB"),
                        fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                        border_color=T("BORDER"), checkbox_width=16, checkbox_height=16,
                        corner_radius=4).pack(side="left", padx=(110, 6))
        rem_label_var = ctk.StringVar(value="")
        ctk.CTkEntry(row_rem, textvariable=rem_label_var, width=140, height=26,
                     font=self._f(11), fg_color=T("SURFACE"), border_color=T("BORDER"),
                     text_color=T("TEXT"), placeholder_text="подпись",
                     corner_radius=6).pack(side="left")

        # ── peer_id ──
        row_peer = ctk.CTkFrame(content, fg_color="transparent"); row_peer.pack(fill="x", pady=4)
        ctk.CTkLabel(row_peer, text="peer_id", font=self._f(12),
                     text_color=T("TEXT"), width=110, anchor="w").pack(side="left")
        peer_var = ctk.StringVar(value="")
        ctk.CTkEntry(row_peer, textvariable=peer_var, width=200, height=30, font=self._mono(12),
                     fg_color=T("SURFACE"), border_color=T("BORDER"), text_color=T("TEXT"),
                     placeholder_text="напр. 41333773", corner_radius=8).pack(side="left")
        self._help_icon(row_peer,
            "ID собеседника. Открой диалог на vk.com — в адресе im?sel=<peer_id>.\n"
            "Для лички peer_id = id человека. Для беседы = 2000000000 + номер чата."
        ).pack(side="left", padx=(8, 0))

        # ── Куда положить ──
        row_dst = ctk.CTkFrame(content, fg_color="transparent"); row_dst.pack(fill="x", pady=4)
        ctk.CTkLabel(row_dst, text="Папка", font=self._f(12),
                     text_color=T("TEXT"), width=110, anchor="w").pack(side="left")
        _def_dst = self.folder_var.get().strip() or str(Path.home() / "Downloads")
        dst_var = ctk.StringVar(value=_def_dst)
        ctk.CTkEntry(row_dst, textvariable=dst_var, height=30, font=self._mono(11),
                     fg_color=T("SURFACE"), border_color=T("BORDER"), text_color=T("TEXT"),
                     corner_radius=8).pack(side="left", fill="x", expand=True, padx=(0, 6))
        def _browse_dst():
            from tkinter import filedialog
            d = filedialog.askdirectory(title="Куда сохранить выгрузку")
            if d:
                dst_var.set(d)
        ctk.CTkButton(row_dst, text="…", width=36, height=30, font=self._f(13),
                      fg_color=T("MUTED"), hover_color=T("BORDER"), text_color=T("SUB"),
                      corner_radius=7, command=_browse_dst).pack(side="left")

        pbar = ctk.CTkProgressBar(content, height=6, fg_color=T("SURFACE"),
                                   progress_color=T("ACCENT"), corner_radius=2)
        pbar.pack(fill="x", pady=(10, 2))
        pbar.set(0)

        log_box = ctk.CTkTextbox(content, font=self._mono(11), fg_color=T("SURFACE"),
                                  text_color=T("TEXT"), height=150, corner_radius=8,
                                  border_color=T("BORDER"), border_width=1)
        log_box.pack(fill="both", expand=True, pady=(6, 8))
        log_box.configure(state="disabled")

        bf = ctk.CTkFrame(content, fg_color="transparent"); bf.pack(fill="x")
        close_btn = ctk.CTkButton(bf, text="Закрыть", width=110, height=36,
                                   font=self._f(12), fg_color=T("SURFACE"),
                                   hover_color=T("BORDER"), text_color=T("SUB"),
                                   corner_radius=8, command=close)
        close_btn.pack(side="left")
        go_btn = ctk.CTkButton(bf, text="Выгрузить", width=150, height=36,
                               font=self._f(12, "bold"), fg_color=T("ACCENT"),
                               hover_color=T("ACCENT2"), corner_radius=8)
        go_btn.pack(side="right")

        def _append(line):
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def _fetch():
            token = tok_var.get().strip() or accounts.get(acc_var.get(), "")
            if not token:
                _append("Нет токена. Выбери аккаунт или вставь токен.")
                return
            peer_raw = peer_var.get().strip()
            try:
                peer = int(peer_raw)
            except ValueError:
                _append("peer_id должен быть числом (напр. 41333773).")
                return
            dst = dst_var.get().strip()
            if not dst:
                _append("Укажи папку назначения.")
                return

            go_btn.configure(state="disabled", text="Качаю…")
            close_btn.configure(state="disabled")
            pbar.configure(mode="indeterminate"); pbar.start()

            def run():
                kw = {"creationflags": 0x08000000} if IS_WIN else {}
                export_dir = vk_script.parent / "vk_export"
                src_json = export_dir / f"{peer}.json"
                # ВАЖНО: один peer_id у разных аккаунтов пишется в один файл и
                # ДОПИСЫВАЕТСЯ → диалоги смешиваются. Чистим перед выгрузкой.
                try:
                    if src_json.exists():
                        src_json.unlink()
                        self.after(0, _append, "Старый vk_export очищен (избегаем смешивания).")
                except Exception:
                    pass

                env = os.environ.copy()
                # Прямой доступ к VK мимо прокси (Karing и т.п.)
                env["NO_PROXY"] = ".vk.com,.vk.ru,.userapi.com," + env.get("NO_PROXY", "")
                ok = False
                try:
                    self.after(0, _append, f"Тяну диалог {peer}…")
                    proc = subprocess.Popen(
                        [sys.executable, str(vk_script), "--peer", str(peer), "--token", token],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        cwd=str(vk_script.parent), env=env, **kw)
                    for line in proc.stdout:
                        line = line.rstrip()
                        if line:
                            self.after(0, _append, line)
                    proc.wait()
                    ok = (proc.returncode == 0 and src_json.exists())
                except Exception as e:
                    self.after(0, _append, f"Ошибка запуска: {e}")
                    ok = False

                if ok:
                    try:
                        import shutil
                        target_dir = Path(dst) / f"VK_{peer}"
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_json, target_dir / f"{peer}.json")
                        self.after(0, _append, f"Готово → {target_dir}\\{peer}.json")
                        self.after(0, self._vk_fetch_done, str(target_dir),
                                   bool(rem_var.get()), tok_var.get().strip(),
                                   rem_label_var.get().strip())
                    except Exception as e:
                        self.after(0, _append, f"Скачано, но не скопировалось: {e}")
                        ok = False

                def finish():
                    pbar.stop(); pbar.configure(mode="determinate")
                    pbar.set(1.0 if ok else 0)
                    close_btn.configure(state="normal")
                    if ok:
                        go_btn.configure(text="✓ Готово", fg_color=T("GREEN"), state="disabled")
                    else:
                        go_btn.configure(text="Повторить", state="normal")
                self.after(0, finish)

            threading.Thread(target=run, daemon=True).start()

        go_btn.configure(command=_fetch)

    def _vk_fetch_done(self, folder: str, remember: bool, token: str, label: str):
        """После успешной выгрузки: ставим папку источником + (опц.) сохраняем токен."""
        self.folder_var.set(folder)
        self.flbl.configure(text=folder, text_color=T("TEXT"))
        self._add_recent(folder)
        if remember and token:
            toks = dict(self._cfg.get("vk_tokens") or {})
            toks[label or "Сохранённый"] = token
            self._cfg["vk_tokens"] = toks
        self._save_cfg()

    def _show_install_dialog(self):
        has_nv = _has_nvidia()
        size_str = "~2.5 ГБ (NVIDIA CUDA)" if has_nv else "~300 МБ (CPU)"

        overlay, content, close = self._overlay(
            "Установка Whisper", width=560, height=480)

        ctk.CTkLabel(content,
                     text=f"Будет установлено: Whisper + PyTorch  ({size_str})\n"
                          "Нужен интернет. После установки перезапуск не нужен.",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack(pady=(2, 10))

        pbar = ctk.CTkProgressBar(content, height=6, fg_color=T("SURFACE"),
                                   progress_color=T("ACCENT"), corner_radius=2)
        pbar.pack(fill="x", pady=(4, 2))
        pbar.set(0)
        plbl = ctk.CTkLabel(content, text="", font=self._f(10), text_color=T("SUB"))
        plbl.pack(anchor="w")

        log_box = ctk.CTkTextbox(content, font=self._mono(11), fg_color=T("SURFACE"),
                                  text_color=T("TEXT"), height=200, corner_radius=8,
                                  border_color=T("BORDER"), border_width=1)
        log_box.pack(fill="both", expand=True, pady=(8, 8))
        log_box.configure(state="disabled")

        bf = ctk.CTkFrame(content, fg_color="transparent")
        bf.pack(fill="x")

        close_btn = ctk.CTkButton(bf, text="Закрыть", width=110, height=36,
                                   font=self._f(12), fg_color=T("SURFACE"),
                                   hover_color=T("BORDER"), text_color=T("SUB"),
                                   corner_radius=8, state="disabled", command=close)
        close_btn.pack(side="left")

        install_btn = ctk.CTkButton(bf, text="Установить", width=140, height=36,
                                     font=self._f(12, "bold"), fg_color=T("ACCENT"),
                                     hover_color=T("ACCENT2"), corner_radius=8)
        install_btn.pack(side="right")

        def _append(line):
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def on_done(success):
            pbar.stop()
            pbar.configure(mode="determinate")
            close_btn.configure(state="normal")
            if success:
                pbar.set(1.0)
                plbl.configure(text="Готово! Голосовые будут расшифровываться при следующем запуске.")
                install_btn.configure(text="✓ Установлено", fg_color=T("GREEN"), state="disabled")
                self._whisper_installed = True
                self._whisper_banner.pack_forget()
                self._update_model_status()
            else:
                pbar.set(0)
                plbl.configure(text="Ошибка. Проверьте лог выше.")
                install_btn.configure(text="Повторить", state="normal", fg_color="#AA3333",
                                       command=do_install)

        def do_install():
            install_btn.configure(state="disabled", text="Установка...")
            pbar.configure(mode="indeterminate")
            pbar.start()

            def run():
                kw = {"creationflags": 0x08000000} if IS_WIN else {}

                target = str(LOCAL_PKGS)
                base_args = ["--target", target, "--upgrade"]

                def run_pip(args, label):
                    self.after(0, plbl.configure, {"text": label})
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "pip", "install"] + base_args + args,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, **kw)
                    for line in proc.stdout:
                        line = line.rstrip()
                        if line:
                            self.after(0, _append, line)
                            if len(line) < 80:
                                self.after(0, plbl.configure, {"text": line})
                    proc.wait()
                    return proc.returncode

                self.after(0, _append, f"Папка установки: {target}")

                env = os.environ.copy()
                env["PYTHONPATH"] = target + os.pathsep + env.get("PYTHONPATH", "")
                cuda_ok = False
                if has_nv and (LOCAL_PKGS / "torch").is_dir():
                    try:
                        check = subprocess.run(
                            [sys.executable, "-c",
                             "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"],
                            capture_output=True, env=env, **kw)
                        cuda_ok = (check.returncode == 0)
                    except Exception:
                        cuda_ok = False

                # ВАЖНО: для NVIDIA-машин ставим whisper ПЕРВЫМ, потом CUDA-torch с
                # --force-reinstall. Иначе whisper тянет torch из PyPI (CPU-only)
                # и перезаписывает уже установленный CUDA-torch → расшифровка идёт на CPU.
                if has_nv:
                    r2 = run_pip(["openai-whisper"], "Скачивание Whisper...")
                    if cuda_ok and r2 == 0:
                        # Проверим, что whisper не сбил CUDA-torch
                        try:
                            check2 = subprocess.run(
                                [sys.executable, "-c",
                                 "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"],
                                capture_output=True, env=env, **kw)
                            cuda_ok = (check2.returncode == 0)
                        except Exception:
                            cuda_ok = False
                    if cuda_ok:
                        self.after(0, _append, "torch CUDA уже установлен — пропускаем")
                        r1 = 0
                    else:
                        r1 = run_pip(["torch", "--index-url",
                                      "https://download.pytorch.org/whl/cu124",
                                      "--force-reinstall"],
                                     "Скачивание PyTorch CUDA (~2.5 ГБ)...")
                else:
                    r1 = run_pip(["torch"], "Скачивание PyTorch CPU (~300 МБ)...")
                    r2 = run_pip(["openai-whisper"], "Скачивание Whisper...")

                self.after(0, on_done, r1 == 0 and r2 == 0)

            threading.Thread(target=run, daemon=True).start()

        install_btn.configure(command=do_install)

    def _show_whisper_uninstall_dialog(self):
        overlay, content, close = self._overlay(
            "Удаление Whisper", width=560, height=440)

        ctk.CTkLabel(content,
                     text="Будут удалены: пакеты openai-whisper + torch, скачанные\n"
                          "модели и старый общий кэш ~/.cache/whisper (до ~5 ГБ освободится).\n"
                          "После удаления голосовые перестанут расшифровываться.\n"
                          "Установить обратно можно через это же окно «О программе».",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack(pady=(2, 10))

        pbar = ctk.CTkProgressBar(content, height=6, fg_color=T("SURFACE"),
                                   progress_color=T("ACCENT"), corner_radius=2)
        pbar.pack(fill="x", pady=(4, 2))
        pbar.set(0)
        plbl = ctk.CTkLabel(content, text="", font=self._f(10), text_color=T("SUB"))
        plbl.pack(anchor="w")

        log_box = ctk.CTkTextbox(content, font=self._mono(11), fg_color=T("SURFACE"),
                                  text_color=T("TEXT"), height=180, corner_radius=8,
                                  border_color=T("BORDER"), border_width=1)
        log_box.pack(fill="both", expand=True, pady=(8, 8))
        log_box.configure(state="disabled")

        bf = ctk.CTkFrame(content, fg_color="transparent")
        bf.pack(fill="x")

        close_btn = ctk.CTkButton(bf, text="Закрыть", width=110, height=36,
                                   font=self._f(12), fg_color=T("SURFACE"),
                                   hover_color=T("BORDER"), text_color=T("SUB"),
                                   corner_radius=8, command=close)
        close_btn.pack(side="left")

        uninstall_btn = ctk.CTkButton(bf, text="Удалить", width=140, height=36,
                                       font=self._f(12, "bold"), fg_color="#AA3333",
                                       hover_color="#882828", corner_radius=8)
        uninstall_btn.pack(side="right")

        def _append(line):
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def on_done(success):
            pbar.stop()
            pbar.configure(mode="determinate")
            if success:
                pbar.set(1.0)
                plbl.configure(text="Готово. Перезапустите программу, чтобы освободить память.")
                uninstall_btn.configure(text="✓ Удалено", fg_color=T("MUTED"), state="disabled")
                self._whisper_installed = False
                self._whisper_banner.pack(fill="x", pady=(0, 8),
                                          before=self._whisper_banner_anchor)
                self._update_model_status()
            else:
                pbar.set(0)
                plbl.configure(text="Ошибка. Проверьте лог выше.")
                uninstall_btn.configure(text="Повторить", state="normal", command=do_uninstall)

        def do_uninstall():
            uninstall_btn.configure(state="disabled", text="Удаление...")
            pbar.configure(mode="indeterminate")
            pbar.start()

            def run():
                import shutil as _sh
                plbl_after = lambda t: self.after(0, plbl.configure, {"text": t})
                ok = True
                # Три цели: пакеты whisper/torch (local_packages), скачанные
                # модели (whisper_models) и старый общий кэш ~/.cache/whisper.
                # recreate=True — папку оставляем пустой (прога её ждёт).
                targets = [
                    (LOCAL_PKGS,           "пакеты whisper + torch",            True),
                    (WHISPER_MODELS,       "скачанные модели",                  False),
                    (WHISPER_CACHE_LEGACY, "старый общий кэш ~/.cache/whisper", False),
                ]
                for path, label, recreate in targets:
                    plbl_after(f"Удаление: {label} ...")
                    self.after(0, _append, f"rmtree: {path}")
                    try:
                        if path.exists():
                            _sh.rmtree(path, ignore_errors=False)
                            self.after(0, _append, f"✓ удалено: {label}")
                        else:
                            self.after(0, _append, f"— нечего удалять: {label}")
                        if recreate:
                            path.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        self.after(0, _append, f"Ошибка ({label}): {e}")
                        ok = False
                self.after(0, on_done, ok)

            threading.Thread(target=run, daemon=True).start()

        uninstall_btn.configure(command=do_uninstall)

    def _apply_preset(self, key: str):
        """Накатить набор настроек: dialog | forum | channel."""
        presets = {
            "dialog":  {"fmt_md": False, "show_ts": True,  "show_src": False, "split_mode": "none"},
            "forum":   {"fmt_md": False, "show_ts": True,  "show_src": True,  "split_mode": "none"},
            "channel": {"fmt_md": True,  "show_ts": True,  "show_src": True,  "split_mode": "month"},
        }
        p = presets.get(key)
        if not p:
            return
        self.fmt_md     = p["fmt_md"]
        self.show_ts    = p["show_ts"]
        self.show_src   = p["show_src"]
        self.split_mode = p["split_mode"]
        # Перерисовать кнопки. Используем функции toggle, но они инвертируют —
        # выставляем точно нужное состояние через прямые configure.
        if self.fmt_md:
            self._fmt_btn.configure(text="📝 MD", fg_color=T("ACCENT"), text_color="white")
        else:
            self._fmt_btn.configure(text="📄 TXT", fg_color=T("MUTED"), text_color=T("SUB"))
        if self.show_ts:
            self._ts_btn.configure(text="🕐 [HH:MM]", fg_color=T("ACCENT"),
                                   border_color=T("ACCENT"), text_color="white")
        else:
            self._ts_btn.configure(text="🕐 без времени", fg_color=T("SURFACE"),
                                   border_color=T("BORDER"), text_color=T("SUB"))
        if self.show_src:
            self._src_btn.configure(text="🏷 [TG]", fg_color=T("ACCENT"),
                                    border_color=T("ACCENT"), text_color="white")
        else:
            self._src_btn.configure(text="🏷 без меток", fg_color=T("SURFACE"),
                                    border_color=T("BORDER"), text_color=T("SUB"))
        txt, fg, bc, tc = self._split_labels()[self.split_mode]
        self._split_btn.configure(text=txt, fg_color=fg, border_color=bc, text_color=tc)
        self._save_cfg()
        self._highlight_preset(key)
        self.plbl.configure(text=f"✓ Пресет применён: {key}")
        self.after(2500, lambda: self.plbl.configure(text=""))

    def _highlight_preset(self, key: str | None):
        """Подсветить активный пресет, остальные — обычные."""
        self._active_preset = key
        if not hasattr(self, "_preset_btns"):
            return
        for k, btn in self._preset_btns.items():
            if k == key:
                btn.configure(fg_color=T("ACCENT"), text_color="white",
                              border_color=T("ACCENT"))
            else:
                btn.configure(fg_color=T("SURFACE"), text_color=T("SUB"),
                              border_color=T("BORDER"))

    def _clear_preset_highlight(self):
        """Снять подсветку — вызывается при ручном изменении любой настройки,
        входящей в состав пресета (формат/время/источник/разбивка)."""
        if getattr(self, "_active_preset", None) is not None:
            self._highlight_preset(None)

    def _toggle_merge(self):
        self.merge_on = not self.merge_on
        if self.merge_on:
            self.mbtn.configure(text="● ВКЛ", fg_color=T("GREEN"), hover_color=T("GREEN2"),
                                 text_color=T("TEXT"))
            self.plbl.configure(text="⚠ Объединение — только для диалогов, не для групп!",
                                 text_color="#f59e0b")
            self.after(4000, lambda: self.plbl.configure(text="", text_color=T("SUB")))
        else:
            self.mbtn.configure(text="○ ВЫКЛ", fg_color=T("MUTED"), hover_color=T("BORDER"),
                                 text_color=T("SUB"))

    def _copy_log(self):
        text = self.log.get("1.0", "end").strip()
        if not text:
            return
        # Tk-буфер обмена работает только пока окно открыто и очищается при
        # выходе из приложения — вставка «после закрытия проги» давала пустоту.
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
        except Exception:
            pass
        # Windows: дублируем в системный буфер через Set-Clipboard — он
        # переживает закрытие приложения. Текст передаём через временный
        # UTF-8 файл: stdin/clip.exe ломают кириллицу, файл — нет.
        if IS_WIN:
            try:
                import tempfile
                fd, p = tempfile.mkstemp(suffix=".txt")
                os.close(fd)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f'$t=[IO.File]::ReadAllText("{p}",[Text.Encoding]::UTF8);'
                     f'Set-Clipboard -Value $t'],
                    check=False, creationflags=0x08000000)
                os.remove(p)
            except Exception:
                pass
        self.plbl.configure(text="✓ Лог скопирован в буфер")
        self.after(2000, lambda: self.plbl.configure(text=""))

    def _cancel(self):
        # Двухэтапная отмена:
        # 1-й клик — мягкая (флаг, ждём окончания текущего голосового — Whisper нельзя
        #            прервать в середине одного файла, он не отдаёт control).
        # 2-й клик — жёсткая (os._exit) — на случай если файл длинный или Whisper завис.
        if not _cancel_event.is_set():
            _cancel_event.set()
            self._log("--- Отмена: текущий файл будет дораспознан, дальше пропуск... ---")
            self._log("    (нажми «Отмена» ещё раз — жёсткий выход без сохранения)")
            self.cbtn.configure(text="Прервать сейчас", fg_color="#AA3333",
                                 hover_color="#882828")
        else:
            self._log("--- Жёсткий выход ---")
            os._exit(0)

    def _show_help(self):
        """Большая справка по всем фичам — оверлей со скроллом."""
        overlay, content, close = self._overlay(
            "Справка", width=640, height=560)

        scroll = ctk.CTkScrollableFrame(content, fg_color="transparent")
        scroll.pack(fill="both", expand=True, pady=(0, 8))

        sections = [
            ("🚀  Быстрый старт",
             "1. Перетащи папку с перепиской в окно (или «Выбрать…»).\n"
             "2. Введи своё имя как в мессенджере.\n"
             "3. Жми «▶ Запустить». Готовый файл появится рядом с папкой."),
            ("📁  Откуда брать переписки",
             "Telegram → Настройки → Экспорт данных, формат JSON. Скармливай папку чата (с result.json).\n"
             "ВКонтакте (HTML) → vk.com/data_protection → запросить, распаковать. Внутри messages/<ID>/ — нужный диалог.\n"
             "ВКонтакте (быстро, через API) → tools/vk_fetch_history.py: сначала --list (узнать peer_id),\n"
             "   потом --peer <id>. Папку tools/vk_export/ скармливай как обычно.\n"
             "Instagram → instagram.com/accounts/your_data → формат JSON, распаковать.\n"
             "WhatsApp → в чате ⋮ → Ещё → Экспорт чата (С медиа). Распаковать ZIP."),
            ("🎙  Расшифровка голосовых",
             "Whisper работает офлайн, без облаков. Один раз поставь через жёлтый банннер.\n"
             "На NVIDIA — автоматически встанет CUDA-версия (быстрая).\n"
             "Кэш расшифровок сохраняется рядом — повторный запуск пропускает уже сделанные файлы."),
            ("🏷  Метки источников",
             "Если в одной папке несколько мессенджеров (TG+VK+IG+WA одного контакта), включи 🏷 [TG] —\n"
             "будет видно, откуда каждое сообщение."),
            ("🔍  Фильтры",
             "ОТ: оставить только сообщения от автора (по подстроке имени).\n"
             "СОДЕРЖИТ: regex по тексту. Примеры: «работ|деньг», «^привет», «https?://»."),
            ("📅  Период и разбивка",
             "Период: календарь, два клика — начало/конец.\n"
             "Разбивка: один файл / по месяцам / по годам — для длинных переписок."),
            ("⌨  Хоткеи",
             "Esc — закрыть текущий оверлей.\n"
             "Drag & Drop папки/файла — в любое место окна.")
        ]

        for title, body in sections:
            ctk.CTkLabel(scroll, text=title,
                         font=self._f(13, "bold"), text_color=T("ACCENT"),
                         anchor="w").pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(scroll, text=body,
                         font=self._f(11), text_color=T("TEXT"),
                         justify="left", anchor="w",
                         wraplength=580).pack(fill="x", padx=4)

        ctk.CTkLabel(scroll,
                     text=f"Версия {VERSION} · {GITHUB}",
                     font=self._f(10), text_color=T("SUB")).pack(pady=(16, 0))

        ctk.CTkButton(content, text="Закрыть", width=130, height=36,
                      font=self._f(12), fg_color=T("MUTED"),
                      hover_color=T("BORDER"), text_color=T("SUB"),
                      corner_radius=8, command=close).pack(side="bottom")

    def _show_about(self):
        # backdrop=False — не затемняем всё окно (главный UI виден вокруг карточки).
        # height=470 подогнана под реальный объём контента (~430px): раньше было 520
        # и внутри карточки висела пустая распорка.
        overlay, content, close = self._overlay(
            "О программе", width=460, height=470, backdrop=False)

        ctk.CTkLabel(content, text="💬", font=self._f(46)).pack(pady=(0, 0))
        ctk.CTkLabel(content, text="Merge Chat",
                     font=self._f(22, "bold"), text_color=T("TEXT")).pack(pady=(4, 0))
        ctk.CTkLabel(content, text=f"Версия {VERSION}",
                     font=self._f(12), text_color=T("SUB")).pack()

        ctk.CTkFrame(content, fg_color=T("BORDER"), height=1).pack(fill="x", pady=14)

        ctk.CTkLabel(content, text="Автор", font=self._f(11), text_color=T("SUB")).pack()
        ctk.CTkLabel(content, text=AUTHOR, font=self._f(15, "bold"),
                     text_color=T("TEXT")).pack(pady=(2, 0))
        gh_url = GITHUB if GITHUB.startswith("http") else f"https://{GITHUB}"
        gh_lbl = ctk.CTkLabel(content, text=GITHUB, font=self._f(11, "bold"),
                              text_color=T("ACCENT"), cursor="hand2")
        gh_lbl.pack(pady=(2, 0))
        def _open_gh(_e=None):
            try:
                import webbrowser
                webbrowser.open(gh_url)
            except Exception:
                pass
        gh_lbl.bind("<Button-1>", _open_gh)
        # Подчёркивание ссылки — через отдельную тонкую полоску под текстом неудобно;
        # ограничимся курсором hand2 и акцентным цветом.

        ctk.CTkFrame(content, fg_color=T("BORDER"), height=1).pack(fill="x", pady=14)

        ctk.CTkLabel(content,
                     text="Объединяет переписки Telegram, ВКонтакте,\n"
                          "Instagram и WhatsApp в один файл.\n"
                          "Расшифровывает голосовые через Whisper офлайн.",
                     font=self._f(11), text_color=T("SUB"),
                     justify="center").pack()

        dnd_s = "✓ Drag & Drop активен" if _HAS_DND else "○ DnD: pip install tkinterdnd2"
        ctk.CTkLabel(content, text=dnd_s, font=self._f(10),
                     text_color=T("GREEN") if _HAS_DND else T("SUB")).pack(pady=(8, 0))

        wrow = ctk.CTkFrame(content, fg_color="transparent")
        wrow.pack(pady=(10, 0))
        if self._whisper_installed:
            ctk.CTkLabel(wrow, text="✓ Whisper установлен", font=self._f(11),
                         text_color=T("GREEN")).pack(side="left", padx=(0, 10))
            ctk.CTkButton(wrow, text="Обновить", width=100, height=28, font=self._f(11),
                          fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                          text_color="white", corner_radius=6,
                          command=lambda: (close(), self._show_install_dialog())
                          ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(wrow, text="Удалить", width=100, height=28, font=self._f(11),
                          fg_color=T("MUTED"), hover_color="#AA3333",
                          text_color=T("SUB"), corner_radius=6,
                          command=lambda: (close(), self._show_whisper_uninstall_dialog())
                          ).pack(side="left")
        else:
            ctk.CTkLabel(wrow, text="○ Whisper не установлен", font=self._f(11),
                         text_color=T("SUB")).pack(side="left", padx=(0, 10))
            ctk.CTkButton(wrow, text="Установить", width=100, height=28, font=self._f(11),
                          fg_color=T("ACCENT"), hover_color=T("ACCENT2"),
                          text_color="white", corner_radius=6,
                          command=lambda: (close(), self._show_install_dialog())
                          ).pack(side="left")

        # Распорка чтобы кнопка «Закрыть» прижалась к низу карточки
        ctk.CTkFrame(content, fg_color="transparent").pack(fill="both", expand=True)
        ctk.CTkButton(content, text="Закрыть", width=130, height=36, font=self._f(12),
                      fg_color=T("MUTED"), hover_color=T("BORDER"),
                      text_color=T("SUB"), corner_radius=8,
                      command=close).pack(side="bottom", pady=(8, 0))

    def _log(self, msg):
        if IS_WIN:
            for a, b in [("✓","[OK]"),("→","->"),("🎤","[mic]"),
                          ("━","-"),("═","="),("✗","[X]")]:
                msg = msg.replace(a, b)
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _clear_log(self):
        self.log.delete("1.0", "end")

    def _toggle_auto_open(self):
        self.auto_open = self._auto_open_var.get()
        self._save_cfg()

    def _open_output(self):
        # Explorer/open запускаем БЕЗ creationflags — CREATE_NO_WINDOW мешал
        # запуску GUI-процесса explorer.exe (окно не появлялось).
        target_file = None
        target_dir = None
        if self.output_path and Path(self.output_path).exists():
            target_file = Path(self.output_path)
            target_dir = target_file.parent
        else:
            folder = self.folder_var.get()
            if folder and Path(folder).exists():
                p = Path(folder)
                target_dir = p if p.is_dir() else p.parent

        if target_dir is None:
            self._log("[!] Нечего открывать: нет ни выходного файла, ни исходной папки.")
            return

        try:
            if IS_WIN:
                if target_file is not None:
                    # /select, требует абсолютного пути с обратными слэшами
                    subprocess.Popen(
                        f'explorer /select,"{target_file}"', shell=False)
                else:
                    os.startfile(str(target_dir))
            elif IS_MAC:
                if target_file is not None:
                    subprocess.Popen(["open", "-R", str(target_file)])
                else:
                    subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
        except Exception as ex:
            self._log(f"[!] Не удалось открыть проводник: {ex}")
            try:
                if IS_WIN:
                    os.startfile(str(target_dir))
            except Exception:
                pass

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
        self.cbtn.configure(state="normal", text="Отмена")
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

                # Автодетект режима: аудио-файл / папка с аудио / переписка
                _src = Path(folder)
                _audio_exts = getattr(_mc, "AUDIO_EXTS",
                    {".mp3",".wav",".m4a",".ogg",".oga",".opus",
                     ".aac",".flac",".webm",".amr",".mp4"})
                _is_audio = False
                if _src.is_file() and _src.suffix.lower() in _audio_exts:
                    _is_audio = True
                elif _src.is_dir():
                    _has_chat = any(
                        list(_src.rglob(p))[:1]
                        for p in ("result.json", "messages*.html", "_chat.txt", "*.txt", "*.json")
                    )
                    _has_audio = any(
                        p for p in _src.rglob("*")
                        if p.is_file() and p.suffix.lower() in _audio_exts
                    )
                    if _has_audio and not _has_chat:
                        _is_audio = True

                if _is_audio:
                    self.after(0, self._log, "[Режим] Аудио — только транскрипция.")
                    out = _mc.process_audio(
                        source_path=folder,
                        model=self.model_var.get(),
                        output_format=fmt,
                        show_timestamps=self.show_ts,
                        log_cb=log_cb,
                        progress_cb=lambda p: self.after(0, self.pbar.set, min(float(p), 1.0)),
                    )
                    cancelled = _cancel_event.is_set()
                    self.after(0, self._done, bool(out), cancelled)
                    return

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
                    show_timestamps=self.show_ts,
                    split_mode=self.split_mode,
                    show_source=self.show_src,
                    filter_author=self.filter_author.get().strip(),
                    filter_text=self.filter_text.get().strip(),
                    my_display=(self.my_display_var.get().strip()
                                if getattr(self, "_adv_names_var", None) and self._adv_names_var.get()
                                else (self.author_var.get().strip().split(",")[0].strip() or "Я")),
                    peer_display=(self.peer_display_var.get().strip()
                                  if getattr(self, "_adv_names_var", None) and self._adv_names_var.get()
                                  else ""),
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
            self.rbtn.configure(text="Запустить", state="normal",
                                 fg_color=T("ACCENT"), text_color=T("TEXT"))
            self._log("\n[X] Обработка отменена.")
            if self.output_path and Path(self.output_path).exists():
                self._log("[OK] Частичный файл сохранён — нажми «Открыть папку».")
        elif ok and self.output_path:
            self.rbtn.configure(text="Запустить снова", state="normal",
                                 fg_color=T("ACCENT"), text_color=T("TEXT"))
            if self.auto_open:
                self._log("\n[OK] Готово! Открываю папку (галка «сразу» включена).")
                self._open_output()
            else:
                self._log("\n[OK] Готово! Нажми «Открыть папку».")
        else:
            self.rbtn.configure(text="Запустить", state="normal",
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
