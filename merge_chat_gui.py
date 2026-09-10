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

# Точные размеры .pt на CDN — ОДИН источник правды. Из них выводятся и
# подпись на кнопке, и порог «докачано ли». Раньше это были три отдельных
# списка руками, и подпись «75 МБ» расходилась с полоской, которая считала
# те же байты по-своему.
_MODEL_BYTES = {"tiny": 75_572_083, "base": 145_262_807, "small": 483_617_219,
                "medium": 1_528_008_539, "large": 3_087_371_615}
# Файл меньше 90% от точного размера = недокачанный или битый: whisper при
# запуске не сойдётся по SHA256 и молча перекачает. Проверяем тут, чтобы не
# показывать ложное «готова».
_MODEL_MIN_BYTES = {m: int(b * 0.9) for m, b in _MODEL_BYTES.items()}

# Официальные URL моделей OpenAI Whisper. SHA256 модели = предпоследний сегмент
# пути URL (whisper так и хранит). Имя сохраняемого файла = basename URL, чтобы
# совпасть с тем, как whisper.load_model сам кладёт файл (для «large» это
# large-v3.pt) — иначе whisper не найдёт нашу копию и полезет качать заново.
_WHISPER_URLS = {
    "tiny":   "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
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

# ──────────────────────────────────────────────────────────────────────
#  Единый загрузчик файлов — ОДИН на всё, что прога тянет из сети:
#  модели Whisper (.pt) и колёса движка (torch/whisper .whl).
#  Раньше это были два разных механизма с двумя индикаторами: у модели —
#  полоска с мегабайтами, у движка — бегунок вообще без процентов (pip в
#  пайп процентов не отдаёт). Теперь всё качается здесь, и панель одна.
#
#  Почему многопоточно: одно HTTPS-соединение к CDN из РФ шейпится,
#  8 параллельных Range-запросов складывают скорость (замер: 1.2 МБ/с
#  в один поток против 22 МБ/с в восемь). Докачка — через sidecar .idx
#  с индексом готовых кусков, поэтому обрыв не стоит почти ничего.
# ──────────────────────────────────────────────────────────────────────

DL_CONNECTIONS = 8
DL_CHUNK = 8 * 1024 * 1024       # кусок под одно Range-соединение
DL_READ = 256 * 1024             # шаг чтения внутри куска — ради плавного %
DL_RETRIES = 4


class DLItem:
    """Один файл к загрузке. size/sha необязательны: size узнаём пробой,
    sha проверяем только если задан (у моделей он в URL, у колёс нет)."""
    __slots__ = ("url", "dest", "sha", "label", "size")

    def __init__(self, url, dest, sha=None, label=None, size=None):
        self.url = url
        self.dest = Path(dest)
        self.sha = sha
        self.label = label or self.dest.name
        self.size = size


def _fmt_mb(n):
    """Байты → «75 МБ» / «1.53 ГБ». Десятичные, как размеры пишут везде:
    в кнопках моделей, на сайте PyPI и в самом pip. Двоичные МиБ дали бы
    «72 МБ» там, где кнопка обещает 75 — пользователь решит, что недокачано."""
    if not n or n < 0:
        return "0 МБ"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} ГБ"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} МБ"
    return f"{n / 1000:.0f} КБ"


def _fmt_speed(bps):
    return f"{bps / 1_000_000:.1f} МБ/с" if bps and bps > 0 else "—"


# Подписи размеров моделей — тем же форматтером, что и полоска загрузки,
# иначе кнопка обещает одно, а прогресс показывает другое.
_MODEL_SIZE = {m: _fmt_mb(b) for m, b in _MODEL_BYTES.items()}


def _plural(n, forms):
    """n + правильная форма: (файл, файла, файлов). Без этого в интерфейсе
    вылезает «24 файлов» и «24 пакетов»."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        f = forms[0]
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        f = forms[1]
    else:
        f = forms[2]
    return f"{n} {f}"


def _fmt_eta(sec):
    """Секунды → «0:38» / «1:02:15». Мусор и бесконечность → «—»."""
    try:
        sec = int(sec)
    except Exception:
        return "—"
    if sec < 0 or sec > 86400 * 7:
        return "—"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _dl_probe(url, timeout=30):
    """(total_bytes, поддержан_ли_Range). Range-проб 0-0 дешевле HEAD и
    заодно проверяет, что сервер реально умеет докачку."""
    import urllib.request
    rq = urllib.request.Request(url)
    rq.add_header("Range", "bytes=0-0")
    r = urllib.request.urlopen(rq, timeout=timeout)
    try:
        cr = r.headers.get("Content-Range", "")
        code = r.getcode()
        cl = r.headers.get("Content-Length")
    finally:
        r.close()
    if code == 206 and "/" in cr:
        return int(cr.rsplit("/", 1)[-1]), True
    return int(cl or 0), False


class _Cancelled(Exception):
    """Отмена изнутри чтения — не ошибка сети, повторять не надо."""


def dl_fetch(item, cancel, on_bytes, on_log, conns=DL_CONNECTIONS,
             chunk=DL_CHUNK):
    """Скачать один DLItem. Возвращает None при успехе, 'cancelled' при
    отмене, иначе текст ошибки.

    on_bytes(done, total) — абсолютные байты по файлу, зовётся часто
    (каждые ~256 КБ), чтобы процент двигался плавно, а не рывками по куску.
    on_log(str) — строка в лог панели.
    """
    import hashlib, urllib.request, time, json
    import threading as _th, queue as _q

    dest = item.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    idxf = dest.with_name(dest.name + ".idx")

    try:
        total, ranges = _dl_probe(item.url)
    except Exception as e:
        return f"не удалось открыть {item.label}: {e}"
    if total <= 0:
        return f"сервер не сообщил размер {item.label}"
    item.size = total

    # Файл уже на месте и нужного размера — качать нечего.
    if dest.exists() and dest.stat().st_size == total:
        on_bytes(total, total)
        return None

    n_chunks = (total + chunk - 1) // chunk

    def _chunk_len(i):
        """Последний кусок короче остальных. Считать его полным было
        ошибкой: на докачке прогресс уезжал вперёд реальности."""
        return min(chunk, total - i * chunk)

    # Докачка: индекс валиден, только если .part уже нужного размера.
    done_idx = set()
    if ranges and idxf.exists() and part.exists() and part.stat().st_size == total:
        try:
            done_idx = {i for i in json.loads(idxf.read_text())
                        if 0 <= i < n_chunks}
        except Exception:
            done_idx = set()
    if not done_idx:
        try:
            with open(part, "wb") as f:
                f.truncate(total)
        except Exception as e:
            return f"не удалось создать {part.name}: {e}"

    if not ranges:
        on_log(f"{item.label}: сервер без Range — качаю в один поток")
        n_chunks, conns = 1, 1
        done_idx = set()

    committed = [sum(_chunk_len(i) for i in done_idx)]   # целиком готовые куски
    live = [0]                                           # принято в текущих кусках
    if done_idx:
        on_log(f"Докачка {item.label}: готово {_fmt_mb(committed[0])} "
               f"из {_fmt_mb(total)}")

    lock = _th.Lock()
    err = [None]
    last_ui = [0.0]
    tasks = _q.Queue()
    for i in range(n_chunks):
        if i not in done_idx:
            tasks.put(i)

    shown = [committed[0]]   # то, что уже показали пользователю

    def _tick(force=False):
        now = time.time()
        if force or now - last_ui[0] >= 0.2:
            last_ui[0] = now
            # Полоска не должна ехать назад. При обрыве куска мы честно
            # откатываем счётчик (иначе повтор посчитает те же байты дважды),
            # но показывать откат нельзя — пользователь читает это как сбой.
            # Держим достигнутый максимум, пока загрузка его не догонит.
            val = min(committed[0] + live[0], total)
            shown[0] = max(shown[0], val)
            on_bytes(shown[0], total)

    on_bytes(committed[0], total)

    def worker():
        while err[0] is None and not cancel.is_set():
            try:
                i = tasks.get_nowait()
            except _q.Empty:
                return
            start = i * chunk
            want = _chunk_len(i)
            end = start + want - 1
            last_e = None
            for attempt in range(DL_RETRIES):
                if cancel.is_set():
                    return
                got = 0
                try:
                    rq = urllib.request.Request(item.url)
                    if ranges:
                        rq.add_header("Range", f"bytes={start}-{end}")
                    r = urllib.request.urlopen(rq, timeout=30)
                    try:
                        buf = bytearray()
                        while len(buf) < want:
                            if cancel.is_set():
                                raise _Cancelled()
                            b = r.read(min(DL_READ, want - len(buf)))
                            if not b:
                                break
                            buf += b
                            got += len(b)
                            with lock:
                                live[0] += len(b)
                            _tick()
                    finally:
                        r.close()
                    if len(buf) != want:
                        raise IOError(f"неполный кусок {len(buf)}/{want}")
                    with open(part, "r+b") as f:
                        f.seek(start)
                        f.write(buf)
                    with lock:
                        live[0] -= got          # переносим из «в пути» в «готово»
                        committed[0] += want
                        done_idx.add(i)
                        try:
                            idxf.write_text(json.dumps(sorted(done_idx)))
                        except Exception:
                            pass
                    _tick(force=True)
                    last_e = None
                    break
                except _Cancelled:
                    with lock:
                        live[0] -= got
                    return
                except Exception as e:
                    # Откатываем недосчитанное этой попыткой, иначе повтор
                    # посчитает те же байты второй раз и процент перевалит 100.
                    with lock:
                        live[0] -= got
                    last_e = e
                    if attempt < DL_RETRIES - 1:
                        time.sleep(1.5 * (attempt + 1))
            if last_e is not None:
                err[0] = last_e
                return

    threads = [_th.Thread(target=worker, daemon=True)
               for _ in range(max(1, min(conns, n_chunks)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if cancel.is_set():
        return "cancelled"
    if err[0] is not None:
        return f"{item.label}: {err[0]}"

    if item.sha:
        on_log(f"Проверяю контрольную сумму {item.label}…")
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for b in iter(lambda: f.read(1048576), b""):
                h.update(b)
        if h.hexdigest() != item.sha:
            for p in (part, idxf):
                try:
                    p.unlink()
                except Exception:
                    pass
            return f"{item.label}: SHA256 не совпал, файл повреждён"

    try:
        if dest.exists():
            dest.unlink()
        part.replace(dest)
    except Exception as e:
        return f"{item.label}: не удалось сохранить: {e}"
    try:
        idxf.unlink()
    except Exception:
        pass
    on_bytes(total, total)
    return None


def dl_fetch_all(items, cancel, ui):
    """Скачать список DLItem с общим прогрессом. ui — словарь из _dl_panel.
    Возвращает None при успехе, 'cancelled' при отмене, иначе текст ошибки."""
    import time

    # Размеры узнаём заранее — иначе общий процент не с чем сравнивать.
    unknown = [it for it in items if not it.size]
    if unknown:
        ui["status"]("Уточняю размеры: "
                     + _plural(len(unknown), ("файл", "файла", "файлов")) + "…")
        for it in unknown:
            if cancel.is_set():
                return "cancelled"
            try:
                it.size = _dl_probe(it.url)[0]
            except Exception:
                it.size = 0

    grand_total = sum(it.size or 0 for it in items)
    grand_done = [0]

    for n, it in enumerate(items, 1):
        if cancel.is_set():
            return "cancelled"
        ui["item"](n, len(items), it.label)
        t0 = time.time()
        start_grand = grand_done[0]
        seen = [0]

        def on_bytes(done, total, _seen=seen, _t0=t0, _sg=start_grand):
            grand_done[0] += done - _seen[0]
            _seen[0] = done
            el = time.time() - _t0
            # Скорость — по этому файлу, с начала его загрузки. Первые
            # 0.3 с не показываем: там она скачет от нуля до сотен.
            spd = (grand_done[0] - _sg) / el if el > 0.3 else 0
            left = ((grand_total - grand_done[0]) / spd) if spd > 0 else None
            ui["progress"](done, total, grand_done[0], grand_total, spd, left)

        err = dl_fetch(it, cancel, on_bytes, ui["append"])
        if err:
            return err
        # Размер мог уточниться по факту — добираем разницу в общий счётчик.
        if it.size and seen[0] < it.size:
            grand_done[0] += it.size - seen[0]
    return None

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
            text=True, encoding="utf-8", errors="replace", timeout=10)
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
        # Считаем геометрию от РАБОЧЕЙ области (экран минус панель задач), а не
        # от полного экрана — иначе окно с кнопкой «Запустить» уезжает под таскбар.
        wa_w, wa_h = self._work_area()
        self._H_target = H_target
        W = min(W, wa_w - 40)
        self.configure(fg_color=T("BG"))
        # Размер и позиция считаются вместе: сначала обрезаем высоту по рабочей
        # области, и только потом центрируем — иначе окно уезжает под панель задач.
        self._place_in_work_area(W, H_target)

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

    def _work_area_rect(self):
        """(left, top, right, bottom) рабочей области — экран без панели задач.
        Панель может стоять не только снизу, поэтому left/top тоже важны."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if IS_WIN:
            try:
                import ctypes
                from ctypes import wintypes
                rect = wintypes.RECT()
                # SPI_GETWORKAREA = 0x0030 → прямоугольник без панели задач
                if ctypes.windll.user32.SystemParametersInfoW(
                        0x0030, 0, ctypes.byref(rect), 0):
                    if rect.right > rect.left and rect.bottom > rect.top:
                        return rect.left, rect.top, rect.right, rect.bottom
            except Exception:
                pass
        return 0, 0, sw, sh

    def _work_area(self):
        """(width, height) рабочей области экрана — без панели задач Windows."""
        l, t, r, b = self._work_area_rect()
        return r - l, b - t

    # Запас на рамку окна и заголовок, пока окно ещё не создано и померить нечем.
    _CHROME_FALLBACK = 56

    def _chrome_h(self):
        """Сколько пикселей окно занимает СВЕРХ клиентской области: заголовок +
        рамка. Меряем по факту — на разных темах и масштабах это разное число.
        Tk-геометрия задаёт клиентскую высоту, а под панель задач уезжает рамка,
        поэтому без этой поправки окно всегда вылезает вниз."""
        if not IS_WIN:
            return self._CHROME_FALLBACK
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            fr = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(fr)):
                ch = (fr.bottom - fr.top) - self.winfo_height()
                if 0 <= ch < 200:
                    return ch
        except Exception:
            pass
        return self._CHROME_FALLBACK

    def _place_in_work_area(self, w, h, x=None, y=None):
        """Поставить окно размером w×h (клиентская область) так, чтобы вся рамка
        целиком лежала в рабочей области. Высота при необходимости урезается,
        позиция — прижимается. Возвращает фактические (w, h)."""
        l, t, r, b = self._work_area_rect()
        chrome = self._chrome_h()
        w = max(1, min(w, r - l))
        h = max(1, min(h, (b - t) - chrome))
        if x is None:
            x = l + ((r - l) - w) // 2
        if y is None:
            y = t + ((b - t) - (h + chrome)) // 2
        # Прижимаем: сначала не даём вылезти вправо/вниз, потом — влево/вверх.
        x = min(x, r - w)
        y = min(y, b - h - chrome)
        x = max(x, l)
        y = max(y, t)
        self.geometry(f"{w}x{h}+{x}+{y}")
        return w, h

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
            avail_h = self._work_area()[1] - self._chrome_h()
            req = self.winfo_reqheight()
            if req > avail_h:
                over = req - avail_h
                log_h = max(LOG_FLOOR, int(self.log.cget("height")) - over)
                self.log.configure(height=log_h)
                self.update_idletasks()
                req = self.winfo_reqheight()
            H = min(req, avail_h)
            cur_w = max(self.winfo_width(), 900)
            # Позицию НЕ переиспользуем: она была посчитана под старую, меньшую
            # высоту. Окно подросло → низ с кнопкой «Запустить» уезжал под
            # панель задач. Пересчитываем и прижимаем к рабочей области.
            self._place_in_work_area(cur_w, H)
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

    # ──────────────────────────────────────────────────────────
    #  Единая панель загрузки — одна на модели и на движок Whisper
    # ──────────────────────────────────────────────────────────
    def _dl_panel(self, title, subtitle, cancel, multi=False):
        """Панель прогресса. Возвращает (ui, finish).

        ui  — словарь колбэков для dl_fetch_all (все переводят вызов в
              main-thread через after, воркер живёт в отдельном потоке).
        finish(ok, msg) — закрывающий вызов, красит панель и меняет кнопку.

        multi=True добавляет вторую полоску «Всего» — она нужна движку
        (24 колеса) и лишняя для одной модели.
        """
        overlay, content, raw_close = self._overlay(title, width=580,
                                                    height=420 if multi else 380)
        # Панель закрыли — виджетов больше нет, а поток загрузки про это не
        # знает и продолжает слать сюда прогресс. Без флага каждый такой вызов
        # это TclError «invalid command name» в консоль. Заодно закрытие панели
        # означает отмену: качать в никуда смысла нет.
        alive = [True]

        def close():
            alive[0] = False
            cancel.set()
            raw_close()

        ctk.CTkLabel(content, text=subtitle, font=self._f(11),
                     text_color=T("SUB"), justify="center",
                     wraplength=520).pack(pady=(2, 12))

        # ── текущий файл ──
        cur_lbl = ctk.CTkLabel(content, text="Подключение…", font=self._f(12, "bold"),
                               text_color=T("TEXT"), anchor="w")
        cur_lbl.pack(fill="x")
        bar = ctk.CTkProgressBar(content, height=10, fg_color=T("SURFACE"),
                                 progress_color=T("ACCENT"), corner_radius=3)
        bar.pack(fill="x", pady=(4, 2))
        bar.set(0)
        stat_lbl = ctk.CTkLabel(content, text="", font=self._mono(11),
                                text_color=T("SUB"), anchor="w")
        stat_lbl.pack(fill="x")

        # ── общий прогресс (только для многофайловых загрузок) ──
        gbar = gstat = None
        if multi:
            gbar = ctk.CTkProgressBar(content, height=6, fg_color=T("SURFACE"),
                                      progress_color=T("GREEN"), corner_radius=2)
            gbar.pack(fill="x", pady=(12, 2))
            gbar.set(0)
            gstat = ctk.CTkLabel(content, text="", font=self._mono(11),
                                 text_color=T("SUB"), anchor="w")
            gstat.pack(fill="x")

        log_box = ctk.CTkTextbox(content, font=self._mono(11), fg_color=T("SURFACE"),
                                 text_color=T("TEXT"), height=140, corner_radius=8,
                                 border_color=T("BORDER"), border_width=1)
        log_box.pack(fill="both", expand=True, pady=(10, 8))
        log_box.configure(state="disabled")

        bf = ctk.CTkFrame(content, fg_color="transparent")
        bf.pack(fill="x")
        btn = ctk.CTkButton(bf, text="Отмена", width=130, height=36,
                            font=self._f(12), fg_color=T("SURFACE"),
                            hover_color="#882828", text_color=T("SUB"),
                            corner_radius=8, command=cancel.set)
        btn.pack(side="right")

        def _append(line):
            log_box.configure(state="normal")
            log_box.insert("end", str(line) + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def _item(n, total_n, label):
            cur_lbl.configure(text=f"[{n}/{total_n}] {label}" if total_n > 1 else label)
            bar.set(0)

        def _progress(done, total, gdone, gtotal, spd, left):
            pct = (done / total) if total else 0
            bar.set(max(0.0, min(1.0, pct)))
            stat_lbl.configure(
                text=f"{pct*100:3.0f}%  ·  {_fmt_mb(done)} / {_fmt_mb(total)}"
                     f"  ·  {spd/1024/1024:.1f} МБ/с  ·  осталось {_fmt_eta(left)}")
            if gbar is not None:
                gp = (gdone / gtotal) if gtotal else 0
                gbar.set(max(0.0, min(1.0, gp)))
                gstat.configure(
                    text=f"Всего: {_fmt_mb(gdone)} / {_fmt_mb(gtotal)} ({gp*100:.0f}%)")

        def finish(ok, msg):
            _append(msg)
            if ok:
                bar.set(1.0)
                if gbar is not None:
                    gbar.set(1.0)
                cur_lbl.configure(text="Готово", text_color=T("GREEN"))
                stat_lbl.configure(text=msg, text_color=T("GREEN"))
            else:
                cur_lbl.configure(text="Не завершено", text_color="#E8944A")
                stat_lbl.configure(text=msg, text_color="#E8944A")
            btn.configure(text="Закрыть", fg_color=T("SURFACE"),
                          hover_color=T("BORDER"), command=close)

        def _guard(fn):
            """Вызвать в main-thread и промолчать, если панель уже закрыта."""
            def call(*a):
                if not alive[0]:
                    return
                try:
                    fn(*a)
                except Exception:
                    alive[0] = False       # виджет исчез между проверкой и вызовом
            return lambda *a: self.after(0, call, *a)

        ui = {
            "append":   _guard(_append),
            "status":   _guard(lambda s: cur_lbl.configure(text=s)),
            "item":     _guard(_item),
            "progress": _guard(_progress),
        }
        return ui, _guard(finish)

    # ──────────────────────────────────────────────────────────
    #  Загрузка 1: модель Whisper (.pt)
    # ──────────────────────────────────────────────────────────
    def _download_selected_model(self):
        """Скачать выбранную модель в whisper_models/ — тем же загрузчиком,
        что и движок: 8 потоков, докачка, проверка SHA256 из URL."""
        m = self.model_var.get() if hasattr(self, "model_var") else ""
        if m not in _WHISPER_URLS:
            return
        url, sha, dest = _model_url_parts(m)
        cancel = threading.Event()
        ui, finish = self._dl_panel(
            "Загрузка",
            f"Модель Whisper «{m}» (~{_MODEL_SIZE.get(m, '?')}) — в папку программы.\n"
            "Можно прервать и докачать позже: прогресс сохраняется.",
            cancel, multi=False)
        ui["append"](f"Источник: {url}")
        ui["append"](f"Файл: {dest}")

        def worker():
            err = dl_fetch_all([DLItem(url, dest, sha=sha, label=f"{m}.pt")],
                               cancel, ui)
            self._model_dl_active = False
            self.after(0, self._update_model_status)
            if err is None:
                finish(True, "Модель проверена и готова к работе.")
            elif err == "cancelled":
                finish(False, "Отменено — прогресс сохранён, можно докачать.")
            else:
                finish(False, f"{err} — прогресс сохранён, докачайте.")

        self._model_dl_active = True
        self._update_model_status()
        threading.Thread(target=worker, daemon=True).start()

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

    # ──────────────────────────────────────────────────────────
    #  Загрузка 2: движок Whisper (torch + openai-whisper)
    # ──────────────────────────────────────────────────────────
    #  Раньше тут просто дёргался `pip install` и крутился бегунок без
    #  процентов: pip, когда его stdout — не терминал, прогресс-бар не
    #  рисует вообще, только строки «Downloading torch-...whl (2.5 GB)».
    #  Поэтому порядок теперь такой:
    #    1) pip --dry-run --report — узнаём точный список колёс и их URL,
    #       ничего не ставя;
    #    2) качаем колёса своим загрузчиком — те же 8 потоков, докачка,
    #       честный процент по байтам, что и у моделей;
    #    3) pip install --no-index из скачанной папки — уже без сети.
    #  Побочный выигрыш: 2.5 ГБ torch тянутся в 8 потоков, а не в один,
    #  и оборванная установка продолжается с места обрыва.

    WHEELS_DIR_NAME = "_wheels"
    TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"

    def _pip_resolve(self, args, log):
        """Список (имя, версия, url) через `pip install --dry-run --report`.
        Возвращает None, только если pip вообще не смог составить план.

        Исходники (.tar.gz) в списке допустимы: сам openai-whisper приезжает
        именно так. Они весят килобайты, собираются локально, а гигабайты —
        это torch, и он колесом. Так что качаем всё подряд, а pip потом
        ставит из папки офлайн."""
        import tempfile, json
        kw = {"creationflags": 0x08000000} if IS_WIN else {}
        rep = Path(tempfile.gettempdir()) / f"mergechat_pipreport_{os.getpid()}.json"
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run",
               "--ignore-installed", "--quiet", "--report", str(rep)] + args
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", **kw)
            if p.returncode != 0:
                log(f"pip не смог составить план: {(p.stdout or '').strip()[:400]}")
                return None
            data = json.loads(rep.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"Не удалось разобрать план pip: {e}")
            return None
        finally:
            try:
                rep.unlink()
            except Exception:
                pass
        out = []
        for pkg in data.get("install", []):
            url = (pkg.get("download_info") or {}).get("url", "")
            meta = pkg.get("metadata") or {}
            if not url:
                log(f"{meta.get('name', '?')}: pip не дал ссылку — обычный pip")
                return None
            out.append((meta.get("name", "?"), meta.get("version", "?"), url))
        return out

    def _show_install_dialog(self):
        has_nv = _has_nvidia()
        cancel = threading.Event()
        ui, finish = self._dl_panel(
            "Установка Whisper",
            ("Whisper + PyTorch с поддержкой NVIDIA CUDA (~2.6 ГБ)."
             if has_nv else "Whisper + PyTorch, версия для CPU (~300 МБ)."),
            cancel, multi=True)

        wheels_dir = LOCAL_PKGS / self.WHEELS_DIR_NAME

        def worker():
            kw = {"creationflags": 0x08000000} if IS_WIN else {}
            log = ui["append"]
            log(f"Папка установки: {LOCAL_PKGS}")

            # ── 1. План: что именно качать ──
            ui["status"]("Составляю список пакетов…")
            plan = self._pip_resolve(["openai-whisper"], log)
            if plan is not None and has_nv:
                # torch с CUDA живёт только на своём индексе; берём его оттуда
                # и перекрываем им CPU-torch из плана whisper — иначе колесо
                # с PyPI молча положит расшифровку на процессор.
                tplan = self._pip_resolve(
                    ["torch", "--index-url", self.TORCH_CUDA_INDEX], log)
                if tplan is None:
                    plan = None
                else:
                    by_name = {n.lower(): (n, v, u) for n, v, u in plan}
                    by_name.update({n.lower(): (n, v, u) for n, v, u in tplan})
                    plan = list(by_name.values())

            if plan is None:
                log("Перехожу на обычный pip — процентов не будет, "
                    "но установка пройдёт.")
                ok = self._pip_install_fallback(has_nv, log, kw)
                self.after(0, self._on_whisper_installed, ok)
                finish(ok, "Установлено." if ok else
                       "Не удалось установить — смотрите лог.")
                return

            log("В плане " + _plural(len(plan), ("пакет", "пакета", "пакетов")))

            # ── 2. Качаем колёса своим загрузчиком ──
            items = []
            for name, ver, url in plan:
                fname = url.rsplit("/", 1)[-1].split("?")[0]
                from urllib.parse import unquote
                items.append(DLItem(url, wheels_dir / unquote(fname),
                                    label=f"{name} {ver}"))
            err = dl_fetch_all(items, cancel, ui)
            if err == "cancelled":
                finish(False, "Отменено — скачанное сохранено, "
                              "установка продолжится с этого места.")
                return
            if err:
                finish(False, f"{err} — скачанное сохранено, повторите.")
                return

            # ── 3. Ставим из локальной папки, сеть больше не нужна ──
            ui["status"]("Устанавливаю пакеты…")
            ui["progress"](0, 1, 1, 1, 0, None)
            files = [str(it.dest) for it in items]
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--target",
                 str(LOCAL_PKGS), "--upgrade", "--no-deps", "--no-index",
                 "--find-links", str(wheels_dir)] + files,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", **kw)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log(line)
            proc.wait()
            ok = (proc.returncode == 0
                  and (LOCAL_PKGS / "whisper").is_dir()
                  and (LOCAL_PKGS / "torch").is_dir())
            if not ok:
                # Офлайн-сборка исходника может не сойтись (нет компилятора,
                # не хватило build-зависимости). Гигабайты уже скачаны — добираем
                # остаток обычным pip, а не роняем всю установку.
                log("Офлайн-установка не завершилась — добираю обычным pip…")
                ok = self._pip_install_fallback(has_nv, log, kw)
            if ok:
                # Колёса больше не нужны — это ещё столько же гигабайт на диске.
                import shutil
                shutil.rmtree(wheels_dir, ignore_errors=True)
            self.after(0, self._on_whisper_installed, ok)
            finish(ok,
                   "Готово. Голосовые будут расшифровываться сразу, "
                   "перезапуск не нужен." if ok else
                   "pip вернул ошибку — смотрите лог. Скачанные колёса "
                   "сохранены, повтор не будет качать заново.")

        threading.Thread(target=worker, daemon=True).start()

    def _pip_install_fallback(self, has_nv, log, kw):
        """Запасной путь, если план через --report не сложился: обычный pip.
        Порядок для NVIDIA важен — whisper тянет CPU-torch с PyPI и затирает
        CUDA-сборку, поэтому CUDA-torch ставим последним."""
        def run_pip(args, label):
            log(label)
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--target",
                 str(LOCAL_PKGS), "--upgrade"] + args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", **kw)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log(line)
            proc.wait()
            return proc.returncode

        r2 = run_pip(["openai-whisper"], "Устанавливаю Whisper…")
        if has_nv:
            r1 = run_pip(["torch", "--index-url", self.TORCH_CUDA_INDEX,
                          "--force-reinstall"], "Устанавливаю PyTorch CUDA…")
        else:
            r1 = 0
        return r1 == 0 and r2 == 0

    def _on_whisper_installed(self, ok):
        """Обновить состояние UI после установки — строго в main-thread."""
        if not ok:
            return
        self._whisper_installed = True
        try:
            self._whisper_banner.pack_forget()
        except Exception:
            pass
        self._update_model_status()

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

        # Модель должна быть скачана ЗАРАНЕЕ нашим многопоточным загрузчиком.
        # Иначе whisper.load_model полезет качать сам: один поток, без докачки —
        # каждый перезапуск начинает с нуля. Это и есть «качает вечно».
        if _WHISPER_OK and not self._model_downloaded(self.model_var.get()):
            from tkinter import messagebox
            m = self.model_var.get()
            st = self._model_state(m)
            what = ("Модель «%s» скачана не полностью." % m if st == "partial"
                    else "Модель «%s» ещё не скачана." % m)
            if messagebox.askyesno(
                    "Merge Chat",
                    what + " (%s)\n\n"
                    "Скачать её сейчас в 8 потоков с докачкой?\n\n"
                    "Если запустить обработку как есть — whisper будет тянуть "
                    "модель сам, в один поток и без докачки: медленно, а при "
                    "закрытии программы прогресс теряется целиком."
                    % _MODEL_SIZE.get(m, "")):
                self._download_selected_model()
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
