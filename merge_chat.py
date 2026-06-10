"""
merge_chat.py — Универсальный объединитель переписок
=====================================================
Поддерживает: Telegram JSON, Telegram HTML, ВКонтакте HTML, Instagram JSON
Умеет: голосовые, кружочки (Whisper), стикеры, фото, ответы, пересылки

Использование:
  python merge_chat.py <папка> [опции]

Примеры:
  python merge_chat.py "C:\\Переписки\\Иван"
  python merge_chat.py "C:\\Переписки\\Иван" --author "Вы" --model small
  python merge_chat.py "C:\\Иван\\1" "C:\\Иван\\2"

Опции:
  --author NAME     Твоё имя в переписках (по умолчанию: Вы)
  --output FILE     Имя выходного файла (по умолчанию — имя контакта)
  --model MODEL     Модель Whisper: tiny/base/small/medium/large (default: small)
  --no-merge        Не объединять подряд идущие сообщения
  --gap N           Порог объединения в секундах (default: 180)
  --markdown        Сохранять в формате Markdown (.md) вместо TXT

Установка:
  pip install beautifulsoup4
  pip install openai-whisper      # если нужна расшифровка
  winget install ffmpeg            # для кружочков (Windows)
"""

import argparse
from typing import Optional, List, Tuple
import json
import re
import sys
import copy
import unicodedata
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# UTF-8 stdout фиксируется только в main() — не на уровне модуля
# (иначе при importlib.reload() в GUI падает ValueError: I/O operation on closed file)
import io as _io
import sys as _sys
import warnings as _warnings
_warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")


# Fix SSL certificates on macOS (Python from python.org)
import ssl as _ssl
import os as _os

def _fix_ssl():
    try:
        import certifi
        _os.environ['SSL_CERT_FILE']      = certifi.where()
        _os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    except ImportError:
        pass
    # Отключаем верификацию SSL только на macOS (Python from python.org)
    import sys as _sysssl
    if _sysssl.platform == "darwin":
        _ssl._create_default_https_context = _ssl._create_unverified_context

_fix_ssl()

# ── Логирование в файл ──────────────────────────────────
import logging as _logging
try:
    _log_path = Path(__file__).parent / "merge_chat.log"
    _logging.basicConfig(
        filename=str(_log_path),
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
        force=True
    )
    _logging.info("=== merge_chat start ===")
except Exception:
    pass

def _log_info(msg: str):
    try: _logging.info(msg)
    except Exception: pass

def _log_error(msg: str):
    try: _logging.error(msg)
    except Exception: pass

# ffmpeg: используем imageio-ffmpeg если системного нет.
# Whisper (whisper.audio.load_audio) вызывает голый бинарь "ffmpeg" через subprocess —
# то есть ему нужен исполняемый файл с именем ИМЕННО ffmpeg(.exe) в PATH.
# imageio-ffmpeg качает бинарь под именем типа ffmpeg-win-x86_64-v7.1.exe,
# поэтому просто добавить его директорию в PATH недостаточно — Whisper не найдёт.
# Решение: положить копию бинарника под именем ffmpeg.exe в TEMP и подставить эту папку в PATH.
def _fix_ffmpeg():
    import shutil as _sh, os as _os2, sys as _sysf
    if _sh.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg as _iff
        from pathlib import Path as _P
        exe = _iff.get_ffmpeg_exe()
        if not exe or not _P(exe).exists():
            return
        import tempfile as _tmp
        target_name = "ffmpeg.exe" if _sysf.platform == "win32" else "ffmpeg"
        target_dir = _P(_tmp.gettempdir()) / "merge_chat_ffmpeg"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / target_name
        # Копия (быстрее симлинка и не требует прав администратора на Windows).
        # Переcкопировать если бинарь обновился.
        try:
            need_copy = (not target.exists() or
                         target.stat().st_size != _P(exe).stat().st_size)
            if need_copy:
                _sh.copy2(exe, target)
        except Exception:
            pass
        # PATH: и оригинальная директория (на всякий случай), и наша с правильным именем.
        _src_dir = str(_P(exe).parent)
        _dst_dir = str(target_dir)
        cur_path = _os2.environ.get("PATH", "")
        for d in (_dst_dir, _src_dir):
            if d not in cur_path:
                cur_path = d + _os2.pathsep + cur_path
        _os2.environ["PATH"] = cur_path
    except Exception:
        pass

_fix_ffmpeg()


# ──────────────────────────────────────────────
#  Константы
# ──────────────────────────────────────────────

MONTHS_NOM = {
    1:"январь",   2:"февраль",  3:"март",     4:"апрель",
    5:"май",      6:"июнь",     7:"июль",     8:"август",
    9:"сентябрь", 10:"октябрь", 11:"ноябрь",  12:"декабрь",
}
MONTHS_GEN = {
    1:"января",   2:"февраля",  3:"марта",    4:"апреля",
    5:"мая",      6:"июня",     7:"июля",     8:"августа",
    9:"сентября", 10:"октября", 11:"ноября",  12:"декабря",
}
MONTHS_PARSE = {
    "янв":1,"фев":2,"мар":3,"апр":4,
    "май":5,"мая":5,"июн":6,"июл":7,
    "авг":8,"сен":9,"окт":10,"ноя":11,"дек":12,
}

VK_ATTACHMENT_LABELS = {
    "голосовое сообщение": None,
    "видеосообщение":      None,
    "запись со стены":     "[📌 Запись со стены]",
    "видео":               "[🎬 Видео]",
    "фотография":          "[📷 Фото]",
    "фотографии":          "[📷 Фото]",
    "стикер":              "[Стикер]",
    "товар":               "[🛒 Товар]",
    "документ":            "[📄 Документ]",
    "аудиозапись":         "[🎵 Аудио]",
    "опрос":               "[📊 Опрос]",
    "карта":               "[🗺️ Геолокация]",
    "ссылка":              "[🔗 Ссылка]",
    "статья":              "[📝 Статья]",
}

# Типы вложений из VK API (tools/vk_fetch_history.py → vk_export JSON).
# Отличается от HTML-меток выше: там русские подписи, тут англ. type из API.
VK_JSON_ATTACH = {
    "photo":         "[📷 Фото]",
    "video":         "[🎬 Видео]",
    "audio":         "[🎵 Аудио]",
    "audio_message": "[🎤 Голосовое — файл недоступен в выгрузке через API]",
    "doc":           "[📄 Документ]",
    "sticker":       "[Стикер]",
    "link":          "[🔗 Ссылка]",
    "wall":          "[📌 Запись со стены]",
    "wall_reply":    "[💬 Комментарий к записи]",
    "market":        "[🛒 Товар]",
    "market_album":  "[🛒 Товары]",
    "poll":          "[📊 Опрос]",
    "gift":          "[🎁 Подарок]",
    "graffiti":      "[Граффити]",
    "story":         "[Story]",
    "call":          "[📞 Звонок]",
}


# ── Pre-import для PyInstaller (замороженный режим) ──────
# В frozen сборке _MEIPASS нужно добавить в sys.path до импорта whisper
import sys as _sys_pre
_meipass_pre = getattr(_sys_pre, '_MEIPASS', None)
if _meipass_pre and _meipass_pre not in _sys_pre.path:
    _sys_pre.path.insert(0, _meipass_pre)
# Локальная папка с Whisper/torch — лежит рядом с merge_chat.py.
# Должна попасть в sys.path ДО импорта whisper, иначе подтянется системный.
from pathlib import Path as _PathPre
_app_dir_pre = _PathPre(__file__).resolve().parent
_local_pkgs_pre = _app_dir_pre / "local_packages"
if _local_pkgs_pre.is_dir() and str(_local_pkgs_pre) not in _sys_pre.path:
    _sys_pre.path.insert(0, str(_local_pkgs_pre))

# Модели Whisper качаем ВНУТРЬ папки проги (whisper_models/), а не в общий
# ~/.cache/whisper — чтобы удаление MergeChat уносило их с собой.
WHISPER_DOWNLOAD_ROOT = _app_dir_pre / "whisper_models"

# Whisper берём ТОЛЬКО из local_packages самой проги (или из _MEIPASS в frozen-
# сборке). Системный / пользовательский whisper (voice-diarizer, pip --user,
# общий site-packages) намеренно НЕ подхватываем: иначе удаление MergeChat не
# вычистит его — нарушение изоляции служебных файлов. Прога владеет своим
# Whisper. Нет его в local_packages → расшифровка выключится с понятным
# сообщением, пользователь поставит Whisper через GUI («О программе»).
_whisper_owned = (_local_pkgs_pre / "whisper").is_dir() or bool(_meipass_pre)
del _sys_pre, _meipass_pre, _PathPre, _app_dir_pre, _local_pkgs_pre

if _whisper_owned:
    try:
        import whisper as _whisper_module  # noqa
    except Exception:
        # ImportError OR OSError (wrong arch torch on Apple Silicon) — handled gracefully
        _whisper_module = None
else:
    _whisper_module = None

# ──────────────────────────────────────────────
#  Глобальное состояние
# ──────────────────────────────────────────────

class Config:
    my_name: str        = "Я"
    my_names_lower: list = []
    peer_name: str      = ""    # если задано — все НЕ-self авторы переименовываются в это
    use_whisper: bool   = False
    whisper_model: str  = "small"
    merge_gap: int      = 180
    do_merge: bool      = True
    verbose: bool       = False
    output_format: str  = "txt"   # "txt" или "md"
    skip_transcribe: bool = False  # True = первый проход без расшифровки

CFG = Config()
_whisper_cache = None
_loaded_model_name: str = ""   # name of currently loaded whisper model
_voice_counter = {"done": 0, "total": 0}
_transcribe_cache: dict = {}   # path -> text (deduplicate same file)
_cancel_event = None           # set by GUI to interrupt processing


# ──────────────────────────────────────────────
#  Нормализация имён
# ──────────────────────────────────────────────

def normalize_author(name: str) -> str:
    if not name:
        return "неизвестно"
    s = name.strip()
    if s in ("Вы", "Я", "я"):
        return CFG.my_name
    norm = unicodedata.normalize("NFC", s).lower()
    if any(norm == n for n in CFG.my_names_lower):
        return CFG.my_name
    return s


# ──────────────────────────────────────────────
#  Whisper
# ──────────────────────────────────────────────

def _release_whisper_memory():
    """Освобождает Whisper-модель и GPU-кэш после завершения обработки.
    Вызывается из process_folder/process_audio в финале — иначе модель medium на CPU
    держит ~3-4 ГБ RAM пока процесс жив, и при следующем запуске жор удваивается."""
    global _whisper_cache, _loaded_model_name
    try:
        _whisper_cache = None
        _loaded_model_name = None
        import gc as _gc
        _gc.collect()
        try:
            import torch as _t
            if _t.cuda.is_available():
                _t.cuda.empty_cache()
        except Exception:
            pass
    except Exception:
        pass


def _progress_bar(done: int, total: int, w: int = 25) -> str:
    real_total = max(done, total) if total else done or 1
    pct  = done / real_total
    fill = min(int(w * pct), w)
    return f"[{'█'*fill}{'░'*(w-fill)}] {done}/{real_total} ({pct*100:.0f}%)"


def transcribe(file_path: Path) -> Optional[str]:
    if CFG.skip_transcribe:
        return None  # first-pass mode: no transcription
    if not CFG.use_whisper or not file_path or not file_path.exists():
        return None

    # Check if user pressed Cancel
    if _cancel_event and _cancel_event.is_set():
        return None

    cache_key = str(file_path.resolve())
    if cache_key in _transcribe_cache:
        return _transcribe_cache[cache_key]

    global _whisper_cache, _loaded_model_name
    try:
        import whisper as _wmod
    except Exception as _imp_err:
        # ImportError = not installed
        # OSError = torch wrong architecture (e.g. x86_64 torch on arm64 Mac)
        if _whisper_module is not None:
            _wmod = _whisper_module
        else:
            print(f"  [ERR] whisper import failed: {_imp_err}")
            if "incompatible architecture" in str(_imp_err) or "arm64" in str(_imp_err):
                print(f"  [ERR] torch architecture mismatch!")
                print(f"  [ERR] Fix: run install_mac.command again — it will reinstall torch for your CPU")
            _log_error(f"whisper import error: {_imp_err}")
            CFG.use_whisper = False  # не пытаться для остальных файлов
            return None
    whisper = _wmod

    try:
        if _whisper_cache is None or _loaded_model_name != CFG.whisper_model:
            # In frozen PyInstaller build:
            # - Windows .exe: always CPU (torch/CUDA not bundled by default)
            # - Mac .app: MPS works if torch is bundled (which it is via --collect-all torch)
            import sys as _sysf
            _is_frozen = getattr(_sysf, "frozen", False)
            _force_cpu = _is_frozen and _sysf.platform == "win32"
            _device = "cpu"
            _device_name = "CPU"
            if not _force_cpu:
                try:
                    import torch
                    if torch.cuda.is_available():
                        _device = "cuda"
                        _device_name = f"NVIDIA {torch.cuda.get_device_name(0)}"
                    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                        _device = "mps"
                        _device_name = "Apple Silicon MPS"
                    else:
                        try:
                            import torch_directml
                            _device = torch_directml.device()
                            _device_name = "AMD/Intel GPU (DirectML)"
                        except ImportError:
                            pass
                except ImportError:
                    pass

            if _device == "cpu":
                print(f"\n  Whisper '{CFG.whisper_model}' — CPU")
                if _force_cpu:
                    print(f"  (frozen .exe — GPU not supported, use Python install for GPU)")
            else:
                print(f"\n  Whisper '{CFG.whisper_model}' — GPU: {_device_name}")

            try:
                _whisper_cache = whisper.load_model(
                    CFG.whisper_model, device=_device,
                    download_root=str(WHISPER_DOWNLOAD_ROOT))
                _loaded_model_name = CFG.whisper_model
                # MPS: force fp32 — fp16 gives NaN on Apple Silicon
                if str(_device) == "mps":
                    try:
                        import torch as _tt
                        _whisper_cache = _whisper_cache.to(_tt.float32)
                        print(f"  MPS: switched model to float32 (fp16 causes NaN on MPS)")
                    except Exception as _fp_e:
                        print(f"  [!] MPS fp32 conversion failed: {_fp_e}")
                print(f"  Model loaded OK.")
            except Exception as _load_err:
                import traceback as _tb
                print(f"  [ERR] Whisper load_model failed on {_device_name}: {_load_err}")
                print(f"  [ERR] {_tb.format_exc()}")
                _log_error(f"load_model error ({_device}): {_load_err}\n{_tb.format_exc()}")
                if _device != "cpu":
                    # GPU failed — retry on CPU
                    print(f"  Retrying on CPU...")
                    try:
                        _whisper_cache = whisper.load_model(
                            CFG.whisper_model, device="cpu",
                            download_root=str(WHISPER_DOWNLOAD_ROOT))
                        _loaded_model_name = CFG.whisper_model
                        print(f"  Model loaded on CPU OK.")
                    except Exception as _cpu_err:
                        print(f"  [ERR] CPU fallback also failed: {_cpu_err}")
                        _log_error(f"CPU fallback error: {_cpu_err}")
                        # Don't set use_whisper=False — maybe next file will work
                        return None
                else:
                    # CPU also failed — just skip this file, don't disable whisper globally
                    print(f"  [ERR] Skipping this file, whisper stays enabled for next files")
                    return None

        if _FFMPEG_BIN is None:
            _init_ffmpeg()
        try:
            _wa = getattr(whisper, "audio", None)
            if _wa is None:
                import whisper.audio as _wa
            if _FFMPEG_BIN and _wa:
                _wa.FFMPEG_PATH = _FFMPEG_BIN  # type: ignore
            # Patch whisper's subprocess calls to use CREATE_NO_WINDOW on Windows
            # This prevents terminal flashes during every audio file transcription
            import sys as _sys2
            if _sys2.platform == "win32":
                import subprocess as _subp
                _orig_run = _subp.run
                _orig_popen = _subp.Popen
                _CNW = 0x08000000
                def _run_hidden(*a, **kw):
                    kw.setdefault("creationflags", _CNW)
                    return _orig_run(*a, **kw)
                def _popen_hidden(*a, **kw):
                    kw.setdefault("creationflags", _CNW)
                    return _orig_popen(*a, **kw)
                _subp.run = _run_hidden
                _subp.Popen = _popen_hidden
        except Exception:
            pass

        _voice_counter["done"] += 1
        done, total = _voice_counter["done"], _voice_counter["total"]
        name = file_path.name[:30]
        print(f"  [{done}/{total}] Transcribing: {name}")

        # Check cancel one more time right before the heavy computation
        if _cancel_event and _cancel_event.is_set():
            return None

        _use_fp16 = str(getattr(_whisper_cache, 'device', 'cpu')) not in ('cpu', 'mps')

        # Run transcription in a thread so cancel can interrupt it
        import threading as _thr
        _result_box = [None]
        _exc_box = [None]

        def _do_transcribe():
            try:
                _result_box[0] = _whisper_cache.transcribe(
                    str(file_path),
                    language="ru",
                    verbose=None,  # None = полностью отключить tqdm-прогрессбар.
                                   # False оставляет tqdm активным, и под pythonw.exe
                                   # (sys.stdout=None) он падает с AttributeError.
                    fp16=_use_fp16,
                )
            except Exception as _te:
                _exc_box[0] = _te

        _t = _thr.Thread(target=_do_transcribe, daemon=True)
        _t.start()
        # Wait with cancel polling every 0.3s
        while _t.is_alive():
            _t.join(timeout=0.3)
            if _cancel_event and _cancel_event.is_set():
                # Thread still running but we skip this file
                print(f"  [!] Transcription cancelled: {name}")
                return None

        if _exc_box[0] is not None:
            # MPS NaN fallback: Apple Silicon MPS sometimes produces NaN even in fp32.
            # Detect by "nan" in error text and retry on CPU.
            _is_mps_nan = (
                "nan" in str(_exc_box[0]).lower()
                and str(getattr(_whisper_cache, "device", "")).startswith("mps")
            )
            if _is_mps_nan:
                print(f"  [!] MPS NaN detected — falling back to CPU for all remaining files")
                try:
                    import torch as _tt
                    _whisper_cache = whisper.load_model(
                        CFG.whisper_model, device="cpu",
                        download_root=str(WHISPER_DOWNLOAD_ROOT))
                    _loaded_model_name = CFG.whisper_model
                    print(f"  Model reloaded on CPU OK.")
                    # Retry this file on CPU
                    _exc_box[0] = None
                    _result_box[0] = None
                    _use_fp16 = False
                    _t2 = _thr.Thread(target=_do_transcribe, daemon=True)
                    _t2.start()
                    while _t2.is_alive():
                        _t2.join(timeout=0.3)
                        if _cancel_event and _cancel_event.is_set():
                            return None
                    if _exc_box[0] is not None:
                        raise _exc_box[0]
                except Exception as _cpu_err:
                    raise _cpu_err
            else:
                raise _exc_box[0]

        result = _result_box[0]
        text = (result.get("text") or "").strip() or None
        short = (text[:60] + "...") if text and len(text) > 60 else (text or "—")
        bar = _progress_bar(done, total)
        print(f"  {bar}  «{short}»")
        _transcribe_cache[cache_key] = text
        return text

    except Exception as e:
        import traceback as _tb2
        _log_error(f"transcribe error {file_path.name}: {e}\n{_tb2.format_exc()}")
        # NOTE: do NOT increment _voice_counter["done"] here — already incremented above
        print(f"  [ERR] transcribe exception for {file_path.name}: {e}")
        print(f"  [ERR] {_tb2.format_exc()}")
        _transcribe_cache[cache_key] = None
        return None


def _get_ffmpeg() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return "ffmpeg"

_FFMPEG_BIN: Optional[str] = None

def _init_ffmpeg():
    global _FFMPEG_BIN
    _FFMPEG_BIN = _get_ffmpeg()

def extract_audio(video_path: Path) -> Optional[Path]:
    if _FFMPEG_BIN is None:
        _init_ffmpeg()
    tmp = Path(tempfile.mktemp(suffix=".wav"))
    try:
        _cflags = 0x08000000 if __import__('sys').platform == 'win32' else 0  # CREATE_NO_WINDOW
        r = subprocess.run(
            [_FFMPEG_BIN, "-y", "-i", str(video_path),
             "-vn", "-ar", "16000", "-ac", "1", str(tmp)],
            capture_output=True, timeout=120,
            creationflags=_cflags
        )
        return tmp if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0 else None
    except FileNotFoundError:
        print("  ! ffmpeg не найден. Установи: pip3 install imageio-ffmpeg")
        return None
    except Exception as e:
        print(f"  ! ffmpeg: {e}")
        return None


def media_label(file_path: Optional[Path], is_video: bool = False) -> str:
    icon = "📹" if is_video else "🎤"
    kind = "Кружочек" if is_video else "Голосовое"
    if not file_path or not file_path.exists():
        return f"[{icon} {kind} — файл не найден]"
    # Cancel check — stop immediately if user pressed Cancel
    if _cancel_event and _cancel_event.is_set():
        return f"[{icon} {kind} — отменено]"
    if is_video:
        tmp = extract_audio(file_path)
        text = transcribe(tmp) if tmp else None
        if tmp and tmp.exists():
            try: tmp.unlink()
            except: pass
    else:
        text = transcribe(file_path)
    return f"[{icon} {kind}: {text}]" if text else f"[{icon} {kind} — нет расшифровки]"


def find_file(base: Path, href: str) -> Optional[Path]:
    if not href:
        return None
    c = base / href
    if c.exists():
        return c
    name = Path(href).name
    matches = list(base.glob(f"**/{name}"))
    return matches[0] if matches else None


# ──────────────────────────────────────────────
#  Парсинг ВКонтакте HTML
# ──────────────────────────────────────────────

def _parse_vk_date(date_str: str) -> Optional[datetime]:
    try:
        s = re.sub(r"\s+в\s+", " ", date_str.strip().lower())
        m = re.match(r"(\d+)\s+(\S+)\s+(\d{4})\s+(\d+):(\d+):(\d+)", s)
        if not m:
            return None
        d, mon, y, h, mi, sec = m.groups()
        month = MONTHS_PARSE.get(mon[:3])
        return datetime(int(y), month, int(d), int(h), int(mi), int(sec)) if month else None
    except:
        return None


def _parse_vk_message(div, folder: Path) -> Optional[dict]:
    hdr = div.find("div", class_="message__header")
    if not hdr:
        return None

    link = hdr.find("a")
    if link:
        sender_raw = link.get_text(strip=True)
        date_str = hdr.get_text(strip=True).replace(sender_raw, "").lstrip(", ").strip()
    else:
        txt = hdr.get_text(strip=True)
        sender_raw, date_str = (txt.split(",", 1) + [""])[:2]
        sender_raw, date_str = sender_raw.strip(), date_str.strip()

    sender = normalize_author(sender_raw)
    dt = _parse_vk_date(date_str)

    body_divs = [d for d in div.find_all("div", recursive=False)
                 if "message__header" not in (d.get("class") or [])]

    texts, attachments = [], []

    for bd in body_divs:
        kludges = bd.find("div", class_="kludges")
        clone = copy.copy(bd)
        for k in clone.find_all("div", class_="kludges"):
            k.decompose()
        t = clone.get_text(separator=" ", strip=True)
        if t:
            texts.append(t)

        if kludges:
            for att in kludges.find_all("div", class_="attachment"):
                desc_tag = att.find("div", class_="attachment__description")
                link_a   = att.find("a", class_="attachment__link")
                desc  = desc_tag.get_text(strip=True).lower() if desc_tag else ""
                href  = link_a.get("href", "") if link_a else ""

                if desc == "голосовое сообщение":
                    attachments.append("[🎤 Голосовое — файл недоступен в экспорте ВК]")
                elif desc == "видеосообщение":
                    attachments.append("[📹 Кружочек — файл недоступен в экспорте ВК]")
                elif desc == "стикер":
                    attachments.append("[Стикер]")
                elif desc in VK_ATTACHMENT_LABELS:
                    label = VK_ATTACHMENT_LABELS[desc]
                    if label:
                        attachments.append(label + (f" {href[:100]}" if href else ""))
                elif href:
                    attachments.append(f"[🔗 {href[:100]}]")
                elif desc:
                    attachments.append(f"[{desc}]")

    parts = texts + attachments
    if not parts:
        return None

    return {
        "id":     None,
        "dt":     dt,
        "sender": sender,
        "text":   " ".join(parts),
        "source": "vk",
    }


def load_vk(folder: Path) -> Tuple[List[dict], str]:
    files = sorted(
        folder.glob("messages*.html"),
        key=lambda f: int(re.search(r"\d+", f.stem).group()) if re.search(r"\d+", f.stem) else 0
    )
    print(f"  ВКонтакте: файлов — {len(files)}")
    all_msgs, contact = [], ""

    for f in files:
        raw = f.read_bytes()
        meta = re.search(rb'charset[=\" ]+([^\"' + rb"'" + rb' >\s]+)', raw)
        enc = "cp1251"
        if meta:
            c = meta.group(1).decode("ascii", errors="ignore").lower()
            if "utf" in c:
                enc = "utf-8"
        try:
            html = raw.decode(enc)
        except:
            html = raw.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        if not contact:
            crumbs = soup.find_all(class_="ui_crumb")
            if len(crumbs) >= 3:
                contact = crumbs[-1].get_text(strip=True)

        for div in soup.find_all("div", class_="message"):
            p = _parse_vk_message(div, folder)
            if p:
                all_msgs.append(p)

    if not contact:
        for m in all_msgs:
            if m["sender"] != CFG.my_name:
                contact = m["sender"].split()[0]
                break

    print(f"  ВКонтакте: сообщений — {len(all_msgs)}")
    return all_msgs, contact


# ──────────────────────────────────────────────
#  Парсинг Telegram JSON
# ──────────────────────────────────────────────

def _tg_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(i if isinstance(i, str) else i.get("text", "") for i in content)
    return ""


def load_tg_json(json_path: Path, folder: Path) -> Tuple[List[dict], str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    chats = [data] if "messages" in data else data.get("chats", {}).get("list", [data])
    all_msgs: List[dict] = []
    contact = ""

    for chat in chats:
        if not contact:
            contact = chat.get("name", "")

        raw_msgs = chat.get("messages", [])
        id_map = {m["id"]: m for m in raw_msgs if "id" in m}

        for msg in raw_msgs:
            if msg.get("type") != "message":
                continue

            sender = normalize_author(msg.get("from") or str(msg.get("from_id", "")))
            dt = None
            try:
                date_str = msg.get("date", "")
                if date_str:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    dt = dt.replace(tzinfo=None)
            except:
                pass

            text  = _tg_text(msg.get("text", "")).strip()
            mtype = msg.get("media_type", "")
            photo = msg.get("photo", "")
            ffile = msg.get("file", "")
            fname = msg.get("file_name") or Path(str(ffile)).name
            semoji = msg.get("sticker_emoji", "")

            attachment = ""
            _msg_voice_path = None
            if mtype == "voice_message":
                vpath = find_file(folder, str(ffile)) if ffile else None
                attachment = media_label(vpath, is_video=False)
                if vpath and vpath.exists(): _msg_voice_path = str(vpath)
            elif mtype == "video_message":
                vpath = find_file(folder, str(ffile)) if ffile else None
                attachment = media_label(vpath, is_video=True)
                if vpath and vpath.exists(): _msg_voice_path = str(vpath)
            elif mtype == "sticker":
                attachment = f"[Стикер {semoji}]".strip()
            elif photo:
                ppath = find_file(folder, str(photo))
                attachment = f"[📷 Фото: {Path(str(photo)).name}]" if ppath else "[📷 Фото]"
            elif mtype in ("photo", "image"):
                attachment = "[📷 Фото]"
            elif mtype == "video":
                attachment = "[🎬 Видео]"
            elif mtype in ("audio_file", "audio"):
                attachment = "[🎵 Аудио]"
            elif ffile and "(File not included" not in str(ffile):
                attachment = f"[📄 Файл: {fname}]"

            if not text and not attachment:
                continue

            parts = [p for p in [text, attachment] if p]
            full_text = "\n".join(parts)

            # Ответ
            reply_id = msg.get("reply_to_message_id")
            if reply_id:
                orig = id_map.get(reply_id, {})
                osender = normalize_author(orig.get("from") or "")
                otext = _tg_text(orig.get("text", "")).strip()
                if not otext:
                    om = orig.get("media_type", "")
                    if om == "voice_message": otext = "🎤 Голосовое"
                    elif om == "video_message": otext = "📹 Кружочек"
                    elif orig.get("photo"): otext = "📷 Фото"
                    elif om == "sticker": otext = f"Стикер {orig.get('sticker_emoji','')}"
                    else: otext = "сообщение"
                if len(otext) > 75:
                    otext = otext[:72] + "..."
                full_text = f"  ┌ {osender}: {otext}\n{full_text}"

            # Пересланное
            fwd = msg.get("forwarded_from")
            if fwd:
                full_text = f"[переслано от {fwd}]\n{full_text}"

            all_msgs.append({
                "id":          msg.get("id"),
                "dt":          dt,
                "sender":      sender,
                "text":        full_text,
                "source":      "tg_json",
                "_voice_path": _msg_voice_path,
            })

    # Count actual voice files on disk (deduplicated)
    voice_files = set(
        list(folder.glob("voice_messages/*.ogg")) +
        list(folder.glob("voice_messages/*.oga")) +
        list(folder.glob("video_messages/*.mp4")) +
        [f for f in folder.glob("*.ogg")] +
        [f for f in folder.glob("*.oga")]
    )
    voice_cnt = len(voice_files)
    print(f"  Telegram JSON: контакт — {contact}, "
          f"сообщений — {len(all_msgs)}"
          + (f", голосовых файлов на диске — {voice_cnt}" if voice_cnt else ""))
    return all_msgs, contact


# ──────────────────────────────────────────────
#  Парсинг ВКонтакте JSON (vk_export через VK API)
# ──────────────────────────────────────────────

def _vk_json_body(m: dict) -> str:
    """Текст одного VK-сообщения: сам текст + метки вложений + геометка."""
    parts = []
    t = (m.get("text") or "").strip()
    if t:
        parts.append(t)
    for att in m.get("attachments", []) or []:
        atype = att.get("type", "")
        label = VK_JSON_ATTACH.get(atype, f"[{atype}]" if atype else "")
        if atype == "doc" and (att.get("doc") or {}).get("title"):
            label = f"[📄 Документ: {att['doc']['title'][:60]}]"
        elif atype == "link" and (att.get("link") or {}).get("url"):
            label = f"[🔗 {att['link']['url'][:100]}]"
        elif atype == "audio":
            a = att.get("audio") or {}
            who = " — ".join(x for x in [a.get("artist"), a.get("title")] if x)
            if who:
                label = f"[🎵 Аудио: {who[:80]}]"
        if label:
            parts.append(label)
    if m.get("geo"):
        parts.append("[🗺️ Геолокация]")
    return "\n".join(parts)


def _vk_json_sender(m: dict, names: dict, peer_id, contact: str) -> str:
    """Имя отправителя: out=1 → я; иначе из names{} (для бесед), либо контакт/ id."""
    if m.get("out") == 1:
        return CFG.my_name
    fid = m.get("from_id")
    raw = names.get(str(fid)) if fid is not None else None
    if not raw:
        if fid == peer_id and contact:
            raw = contact
        elif isinstance(fid, int) and fid < 0:
            raw = f"club{-fid}"
        else:
            raw = f"id{fid}"
    return normalize_author(raw)


def load_vk_json(json_path: Path, folder: Path) -> Tuple[List[dict], str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    names = {str(k): v for k, v in (data.get("names") or {}).items()}
    peer_id = data.get("peer_id")
    info = data.get("info") or {}
    contact = (info.get("name") or "").strip()
    if not contact and peer_id is not None:
        contact = names.get(str(peer_id), "")

    all_msgs: List[dict] = []
    for m in data.get("messages", []):
        if m.get("action"):          # служебные (создание беседы, инвайты, смена названия)
            continue

        sender = _vk_json_sender(m, names, peer_id, contact)
        dt = None
        ts = m.get("date")
        if ts:
            try:
                dt = datetime.fromtimestamp(ts)
            except:
                pass

        full_text = _vk_json_body(m)

        # Пересланные
        fwds = m.get("fwd_messages") or []
        if fwds:
            inner = []
            for fm in fwds:
                fs = _vk_json_sender(fm, names, peer_id, contact)
                ft = _vk_json_body(fm).strip() or "сообщение"
                if len(ft) > 75:
                    ft = ft[:72] + "..."
                inner.append(f"{fs}: {ft}")
            full_text = (f"[переслано] {'; '.join(inner)}\n{full_text}").strip()

        # Ответ
        reply = m.get("reply_message")
        if reply:
            rs = _vk_json_sender(reply, names, peer_id, contact)
            rt = _vk_json_body(reply).strip() or "сообщение"
            if len(rt) > 75:
                rt = rt[:72] + "..."
            full_text = f"  ┌ {rs}: {rt}\n{full_text}"

        if not full_text.strip():
            continue

        all_msgs.append({
            "id":     m.get("id"),
            "dt":     dt,
            "sender": sender,
            "text":   full_text,
            "source": "vk",          # тот же тег, что и HTML — оба пути сливаются как [VK]
        })

    if not contact:
        for mm in all_msgs:
            if mm["sender"] != CFG.my_name:
                contact = mm["sender"].split()[0]
                break

    print(f"  ВКонтакте (API JSON): контакт — {contact}, сообщений — {len(all_msgs)}")
    return all_msgs, contact


# ──────────────────────────────────────────────
#  Парсинг Telegram HTML
# ──────────────────────────────────────────────

def _parse_tg_html_date(title: str) -> Optional[datetime]:
    try:
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", title)
        if m:
            d, mo, y, h, mi, s = m.groups()
            return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except:
        pass
    return None


def _parse_tg_html_message(div, folder: Path, id_map: dict) -> Optional[dict]:
    if "service" in (div.get("class") or []):
        return None
    body = div.find("div", class_="body")
    if not body:
        return None

    msg_id = None
    m = re.search(r"\d+", div.get("id", ""))
    if m:
        msg_id = int(m.group())

    date_div = body.find("div", class_="date")
    dt = _parse_tg_html_date(date_div.get("title", "")) if date_div else None

    from_div = body.find("div", class_="from_name")
    sender_raw = from_div.get_text(strip=True) if from_div else ""

    text_div = body.find("div", class_="text")
    text = ""
    if text_div:
        for br in text_div.find_all("br"):
            br.replace_with("\n")
        text = text_div.get_text(separator="").strip()

    # Медиа
    attachment = ""
    mw = body.find("div", class_="media_wrap")
    if mw:
        a = mw.find("a", class_="media")
        if a:
            href    = a.get("href", "")
            classes = " ".join(a.get("class", []))
            title_t = (a.find("div", class_="title") or type("", (), {"get_text": lambda *a, **k: ""})()).get_text(strip=True)
            status_t= (a.find("div", class_="status") or type("", (), {"get_text": lambda *a, **k: ""})()).get_text(strip=True)

            if title_t == "Sticker" or "sticker" in href.lower():
                attachment = f"[Стикер {status_t}]".strip()
            elif "voice_message" in classes or "voice_messages" in href:
                vpath = find_file(folder, href)
                attachment = media_label(vpath, is_video=False)
            elif "round_video" in href or (title_t == "Video message"):
                vpath = find_file(folder, href)
                attachment = media_label(vpath, is_video=True)
            elif "media_photo" in classes:
                attachment = "[📷 Фото]"
            elif "media_video" in classes:
                attachment = f"[🎬 Видео {status_t}]".strip()
            elif title_t:
                attachment = f"[📎 {title_t}]"

    # Пересланное
    fwd_div = body.find("div", class_="forwarded")
    fwd_from = ""
    if fwd_div:
        fn = fwd_div.find("div", class_="from_name")
        fwd_from = fn.get_text(strip=True) if fn else "неизвестно"
        if not text:
            ft = fwd_div.find("div", class_="text")
            if ft:
                text = ft.get_text(separator=" ", strip=True)

    parts = [p for p in [text, attachment] if p]
    if not parts:
        return None

    full_text = "\n".join(parts)

    if fwd_from:
        full_text = f"[переслано от {fwd_from}]\n{full_text}"

    # Ответ
    reply_div = body.find("div", class_="reply_to")
    if reply_div:
        link = reply_div.find("a")
        if link:
            rm = re.search(r"message(\d+)", link.get("href", ""))
            if rm:
                rid = int(rm.group(1))
                orig = id_map.get(rid)
                if orig:
                    osender = orig.get("sender_raw", "")
                    otext = orig.get("text", "")[:75]
                else:
                    osender, otext = "", "цитата не найдена"
                full_text = f"  ┌ {osender}: {otext}\n{full_text}"

    return {
        "id":         msg_id,
        "dt":         dt,
        "sender_raw": sender_raw,
        "sender":     normalize_author(sender_raw) if sender_raw else None,
        "text":       full_text,
        "source":     "tg_html",
    }


def load_tg_html(folder: Path) -> Tuple[List[dict], str]:
    pattern = re.compile(r"^messages(\d*)\.html$", re.IGNORECASE)
    files = sorted(
        [f for f in folder.iterdir() if pattern.match(f.name)],
        key=lambda f: int(pattern.match(f.name).group(1) or 0)
    )
    print(f"  Telegram HTML: файлов — {len(files)}")

    all_msgs: dict = {}
    contact = ""
    prev_sender = None

    for html_file in files:
        raw  = html_file.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        id_map: dict = {}
        for div in soup.find_all("div", class_="message"):
            m = re.search(r"\d+", div.get("id", ""))
            if m:
                bid = int(m.group())
                b = div.find("div", class_="body")
                if b:
                    fn = b.find("div", class_="from_name")
                    tt = b.find("div", class_="text")
                    id_map[bid] = {
                        "sender_raw": fn.get_text(strip=True) if fn else "",
                        "text": tt.get_text(separator=" ", strip=True) if tt else "",
                    }

        for div in soup.find_all("div", class_="message"):
            p = _parse_tg_html_message(div, folder, id_map)
            if p:
                if not p["sender"]:
                    p["sender"] = prev_sender or "неизвестно"
                else:
                    prev_sender = p["sender"]
                if p["id"]:
                    all_msgs[p["id"]] = p
                else:
                    all_msgs[-(len(all_msgs)+1)] = p

    for msg in sorted(all_msgs.values(), key=lambda x: x["dt"] or datetime.min):
        if msg["sender"] != CFG.my_name:
            contact = msg["sender"].split()[0]
            break

    msgs_list = list(all_msgs.values())
    print(f"  Telegram HTML: сообщений — {len(msgs_list)}")
    return msgs_list, contact


# ──────────────────────────────────────────────
#  Автоопределение формата папки
# ──────────────────────────────────────────────

def find_all_chat_folders(root: Path) -> List[Path]:
    found = set()

    for p in root.rglob("*.json"):
        try:
            head = p.read_bytes()[:300].decode("utf-8", errors="replace")
            if '"messages"' in head or '"chats"' in head or '"participants"' in head:
                found.add(p.parent)
        except:
            pass

    for p in root.rglob("messages*.html"):
        if re.match(r"messages\d*\.html", p.name, re.I):
            found.add(p.parent)

    for p in root.rglob("_chat.txt"):
        found.add(p.parent)

    def _folder_sort_key(p):
        n = p.name
        if n in (".", "..") or n.startswith("."):
            return "zzz_" + n
        return n.lower()
    return sorted(found, key=_folder_sort_key)


# ──────────────────────────────────────────────
#  Парсинг Instagram JSON
# ──────────────────────────────────────────────

def _fix_instagram_encoding(s: str) -> str:
    """Instagram exports UTF-8 text stored as latin-1 bytes."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s


def load_instagram_json(folder: Path) -> Tuple[List[dict], str]:
    """
    Загружает Instagram JSON-экспорт (message_1.json, message_2.json, ...).
    Аудиофайлы ищет в папке audio/ рядом с JSON.
    """
    from datetime import timezone as _tz
    json_files = sorted(
        folder.glob("message_*.json"),
        key=lambda p: int(re.search(r"\d+", p.stem).group() or 0)
    )
    if not json_files:
        return [], ""

    all_msgs: List[dict] = []
    contact = ""

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Собираем всех участников (для DM их обычно 2: я + собеседник)
        _all_parts: List[str] = []
        for p in data.get("participants", []):
            _nm = _fix_instagram_encoding(p.get("name", ""))
            if _nm and _nm not in _all_parts:
                _all_parts.append(_nm)

        # Имя контакта — тот, кто НЕ совпадает с алиасами «я»
        if not contact:
            _matched_self = None
            for _nm in _all_parts:
                if unicodedata.normalize("NFC", _nm).lower() in CFG.my_names_lower:
                    _matched_self = _nm
                    break
            if _matched_self:
                # Алиас матчнулся — контакт это «другой» участник
                for _nm in _all_parts:
                    if _nm != _matched_self:
                        contact = _nm
                        break
            elif _all_parts:
                # Ни один алиас не подошёл (типичный кейс: пользователь ввёл «Я»,
                # а в IG-экспорте он подписан полным именем «Артём Смагин»).
                # Берём первого как peer-контакт.
                contact = _all_parts[0]

        # КРИТИЧНО: регистрируем всех НЕ-контактных участников как алиасы «себя».
        # Иначе peer_display rename переименует свои сообщения в имя собеседника.
        for _nm in _all_parts:
            if _nm and _nm != contact:
                _norm_n = unicodedata.normalize("NFC", _nm).lower()
                if _norm_n not in CFG.my_names_lower:
                    CFG.my_names_lower.append(_norm_n)

        for m in data.get("messages", []):
            try:
                ts = datetime.fromtimestamp(
                    m["timestamp_ms"] / 1000, tz=_tz.utc
                ).astimezone().replace(tzinfo=None)
            except Exception:
                continue

            sender_raw = m.get("sender_name", "")
            sender = normalize_author(_fix_instagram_encoding(sender_raw))

            voice_path = None
            content = m.get("content", "")
            if content:
                content = _fix_instagram_encoding(content)
            elif "audio_files" in m:
                uri = m["audio_files"][0].get("uri", "") if m["audio_files"] else ""
                fname = Path(uri).name
                candidate = folder / "audio" / fname
                if candidate.exists():
                    content = "[🎤 Голосовое — нет расшифровки]"
                    voice_path = str(candidate)
                else:
                    content = "[🎤 Голосовое — файл не найден]"
            elif "photos" in m:
                content = "[📷 Фото]"
            elif "videos" in m:
                content = "[🎬 Видео]"
            elif "share" in m:
                link = _fix_instagram_encoding(m["share"].get("link", ""))
                content = f"[🔗 Репост: {link}]" if link else "[🔗 Репост]"
            else:
                content = "[Медиа]"

            if not content:
                continue

            msg: dict = {
                "id":     f"ig_{m['timestamp_ms']}_{sender_raw[:8]}",
                "dt":     ts,
                "sender": sender,
                "text":   content,
                "source": "ig",
            }
            if voice_path:
                msg["_voice_path"] = voice_path
            all_msgs.append(msg)

    all_msgs.sort(key=lambda x: x["dt"])
    print(f"  Instagram: сообщений — {len(all_msgs)}")
    return all_msgs, contact


# ──────────────────────────────────────────────
#  Парсинг WhatsApp TXT
# ──────────────────────────────────────────────

def load_whatsapp_txt(folder: Path) -> Tuple[List[dict], str]:
    """
    Загружает экспорт WhatsApp (_chat.txt).
    Форматы: iOS [DD.MM.YYYY, HH:MM:SS] и Android DD.MM.YYYY, HH:MM:SS -
    Голосовые: PTT-*.opus рядом с _chat.txt.
    """
    chat_file = folder / "_chat.txt"
    if not chat_file.exists():
        return [], ""

    _MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

    _PAT_IOS = re.compile(
        r'^\[(\d{2})\.(\d{2})\.(\d{4}),\s+(\d{2}):(\d{2}):(\d{2})\]\s+(.+?): (.*)$'
    )
    _PAT_ANDROID = re.compile(
        r'^(\d{2})\.(\d{2})\.(\d{4}),\s+(\d{2}):(\d{2}):(\d{2})\s+-\s+(.+?): (.*)$'
    )
    _PAT_HDR_IOS = re.compile(r'^\[(\d{2})\.(\d{2})\.(\d{4}),\s+(\d{2}):(\d{2}):(\d{2})\]')
    _PAT_HDR_AND = re.compile(r'^(\d{2})\.(\d{2})\.(\d{4}),\s+(\d{2}):(\d{2}):(\d{2})\s+-')

    def _strip(s):
        for c in _MARKS:
            s = s.replace(c, "")
        return s

    try:
        raw = chat_file.read_bytes()
        if raw.startswith(b'\xef\xbb\xbf'):
            raw = raw[3:]
        content = raw.decode("utf-8", errors="replace")
    except Exception:
        return [], ""

    # Group into (dt, sender_raw, text) chunks handling multiline messages
    chunks = []
    cur_dt = None
    cur_sender = None
    cur_lines: list = []

    for line in content.splitlines():
        clean = _strip(line.strip())
        m = _PAT_IOS.match(clean) or _PAT_ANDROID.match(clean)
        if m:
            if cur_sender is not None:
                chunks.append((cur_dt, cur_sender, "\n".join(cur_lines)))
            d, mo, y, h, mi, sec, sender_raw, text = m.groups()
            try:
                cur_dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec))
            except Exception:
                cur_dt = None
            cur_sender = sender_raw.strip()
            cur_lines = [text.strip()]
        elif _PAT_HDR_IOS.match(clean) or _PAT_HDR_AND.match(clean):
            # System message — flush and skip
            if cur_sender is not None:
                chunks.append((cur_dt, cur_sender, "\n".join(cur_lines)))
            cur_sender = None
            cur_lines = []
        elif cur_sender is not None:
            cur_lines.append(line.rstrip())

    if cur_sender is not None:
        chunks.append((cur_dt, cur_sender, "\n".join(cur_lines)))

    messages = []
    contact = ""

    for dt, sender_raw, raw_text in chunks:
        text = _strip(raw_text.strip())
        if not text:
            continue

        sender = normalize_author(sender_raw)
        voice_path = None

        # Strip "edited" marker
        text = re.sub(r'\s*‎?<Сообщение изменено>$', '', text).strip()
        text = re.sub(r'\s*<Message edited>$', '', text, flags=re.IGNORECASE).strip()

        # Call log entries — label them
        if re.search(r'Аудиозвонок|Видеозвонок|Voice call|Video call', text, re.IGNORECASE):
            answered = not re.search(r'Нет ответа|No answer|Missed', text, re.IGNORECASE)
            kind = "Видеозвонок" if re.search(r'Видеозвонок|Video call', text, re.IGNORECASE) else "Аудиозвонок"
            text = f"[📞 {kind}{'✓' if answered else ': нет ответа'}]"

        # Voice message (any *.opus — iOS: AUDIO-*.opus, Android: PTT-*.opus)
        vm = re.search(
            r'<(?:прикреплено|attached):\s*(\S+\.opus)\s*>',
            text, re.IGNORECASE
        )
        if vm:
            opus_path = folder / vm.group(1)
            if opus_path.exists():
                voice_path = str(opus_path)
                t = transcribe(opus_path)
                text = f"[🎤 Голосовое: {t}]" if t else "[🎤 Голосовое — нет расшифровки]"
            else:
                text = "[🎤 Голосовое — файл не найден]"
        # Photo
        elif re.search(
            r'<(?:прикреплено|attached):\s*\S+\.(?:jpe?g|png|webp|heic)\s*>',
            text, re.IGNORECASE
        ):
            # keep original caption if any (text before <прикреплено:>)
            caption = re.sub(r'\s*<(?:прикреплено|attached):\s*\S+\s*>', '', text, flags=re.IGNORECASE).strip()
            text = f"[📷 Фото{': ' + caption if caption else ''}]"
        # Video
        elif re.search(
            r'<(?:прикреплено|attached):\s*\S+\.(?:mp4|mov|avi)\s*>',
            text, re.IGNORECASE
        ):
            caption = re.sub(r'\s*<(?:прикреплено|attached):\s*\S+\s*>', '', text, flags=re.IGNORECASE).strip()
            text = f"[🎬 Видео{': ' + caption if caption else ''}]"
        # Generic attachment (contacts .vcf, documents, etc.)
        elif re.search(r'<(?:прикреплено|attached):\s*(\S+)\s*>', text, re.IGNORECASE):
            am = re.search(r'<(?:прикреплено|attached):\s*(\S+)\s*>', text, re.IGNORECASE)
            text = f"[📎 {am.group(1)}]"
        # Omitted media — "without files" export (iOS: "отсутствует", EN: "omitted")
        elif re.search(
            r'(?:изображение|аудиофайл|видео|документ|стикер|gif|'
            r'image|audio|video|document|sticker)\s+'
            r'(?:отсутствует|пропущен\w*|omitted)',
            text, re.IGNORECASE
        ):
            if re.search(r'аудиофайл|audio', text, re.IGNORECASE):
                text = "[🎤 Голосовое — файл не включён в экспорт]"
            elif re.search(r'видео|video', text, re.IGNORECASE):
                text = "[🎬 Видео]"
            else:
                text = "[Медиафайл]"

        if sender != CFG.my_name and not contact:
            contact = sender

        msg: dict = {
            "id":     None,
            "dt":     dt,
            "sender": sender,
            "text":   text,
            "source": "wa",
        }
        if voice_path:
            msg["_voice_path"] = voice_path
        messages.append(msg)

    # WA-DM: ровно 2 уникальных отправителя. Если один из них матчит мои алиасы —
    # ОК, другой = контакт. Если ни один не матчит — предупреждаем (полагаемся на
    # старое contact-определение: первый не-self). Группы (3+) не трогаем.
    _distinct = list({m["sender"] for m in messages if m.get("sender")})
    if len(_distinct) == 2:
        _matched_self = None
        for _nm in _distinct:
            if unicodedata.normalize("NFC", _nm).lower() in CFG.my_names_lower:
                _matched_self = _nm
                break
        if _matched_self:
            for _nm in _distinct:
                if _nm != _matched_self:
                    contact = _nm
                    break
            # Перетираем self → CFG.my_name
            for _m in messages:
                _s = _m.get("sender", "")
                if _s and unicodedata.normalize("NFC", _s).lower() in CFG.my_names_lower:
                    _m["sender"] = CFG.my_name
        else:
            print(f"  [!] WhatsApp: ни один отправитель не совпал с алиасами '{CFG.my_name}'. "
                  f"Возможные имена: {_distinct}. Добавь правильное в поле 'Твоё имя' через запятую.")

    print(f"  WhatsApp: сообщений — {len(messages)}")
    return messages, contact


def load_chat_folder(folder: Path) -> Tuple[List[dict], str, str]:
    all_msgs: List[dict] = []
    contact = ""
    srcs = []

    # ── Instagram JSON (message_1.json, message_2.json, ...) ──────────
    ig_files = sorted(folder.glob("message_*.json"))
    _is_instagram = False
    if ig_files:
        try:
            head = ig_files[0].read_bytes()[:300].decode("utf-8", errors="replace")
            if '"participants"' in head:
                _is_instagram = True
                msgs, c = load_instagram_json(folder)
                all_msgs.extend(msgs)
                if not contact and c:
                    contact = c
                srcs.append("Instagram")
        except Exception:
            pass

    # ── VK API JSON (vk_export) ──────────────────────────────────────
    # ДО Telegram JSON: формат vk_export тоже содержит ключ "messages",
    # отличаем по наличию "peer_id" (маркер vk_fetch_history.py).
    vk_json_files = []
    if not _is_instagram:
        for p in sorted(folder.glob("*.json")):
            if re.match(r"message_\d+\.json", p.name):
                continue
            try:
                d = json.loads(p.read_bytes().decode("utf-8", errors="replace"))
            except:
                continue
            if isinstance(d, dict) and "peer_id" in d and isinstance(d.get("messages"), list):
                vk_json_files.append(p)

    for p in vk_json_files:
        msgs, c = load_vk_json(p, folder)
        all_msgs.extend(msgs)
        if not contact and c:
            contact = c
        if "VK" not in srcs:
            srcs.append("VK")

    # ── Telegram / VK HTML JSON ──────────────────────────────────────
    json_path = None
    if not _is_instagram:
        if (folder / "result.json").exists():
            json_path = folder / "result.json"
        else:
            for p in sorted(folder.glob("*.json")):
                if re.match(r"message_\d+\.json", p.name):
                    continue  # уже обработано выше
                if p in vk_json_files:
                    continue  # VK-export уже обработан выше
                try:
                    d = json.loads(p.read_bytes().decode("utf-8", errors="replace"))
                    if (isinstance(d, dict) and ("messages" in d or "chats" in d)
                            and "peer_id" not in d):
                        json_path = p
                        break
                except:
                    pass

    if json_path:
        msgs, c = load_tg_json(json_path, folder)
        all_msgs.extend(msgs)
        if not contact and c:
            contact = c
        srcs.append("TG JSON")

    html_files = sorted(
        [f for f in folder.glob("messages*.html")
         if re.match(r"messages\d*\.html", f.name, re.I)],
        key=lambda f: int(re.search(r"\d+", f.stem).group()) if re.search(r"\d+", f.stem) else 0
    )
    if html_files:
        sample = html_files[0].read_bytes().decode("utf-8", errors="replace")[:2000]
        if "message default clearfix" in sample or "from_name" in sample:
            msgs, c = load_tg_html(folder)
            if not contact and c:
                contact = c
            all_msgs.extend(msgs)
            srcs.append("TG HTML")
        else:
            msgs, c = load_vk(folder)
            if not contact and c:
                contact = c
            all_msgs.extend(msgs)
            srcs.append("VK")

    # ── WhatsApp TXT ──────────────────────────────────────────────────
    if (folder / "_chat.txt").exists():
        msgs, c = load_whatsapp_txt(folder)
        all_msgs.extend(msgs)
        if not contact and c:
            contact = c
        srcs.append("WhatsApp")

    return all_msgs, contact, " + ".join(srcs) if srcs else "unknown"


# ──────────────────────────────────────────────
#  Объединение подряд идущих
# ──────────────────────────────────────────────

def merge_consecutive(messages: list) -> list:
    if not messages:
        return []
    merged = []
    cur = messages[0].copy()
    for msg in messages[1:]:
        same  = msg["sender"] == cur["sender"]
        close = True
        if msg["dt"] and cur["dt"]:
            close = abs((msg["dt"] - cur["dt"]).total_seconds()) <= CFG.merge_gap
        has_quote = msg["text"].startswith("  ┌ ")
        is_fwd    = msg["text"].startswith("[переслано")
        if same and close and not has_quote and not is_fwd:
            cur["text"] += "\n" + msg["text"]
        else:
            merged.append(cur)
            cur = msg.copy()
    merged.append(cur)
    return merged


# ──────────────────────────────────────────────
#  Форматирование вывода
# ──────────────────────────────────────────────

SOURCE_LABELS = {
    "tg_json": "TG", "tg_html": "TG",
    "vk":      "VK",
    "ig":      "IG",
    "wa":      "WA",
}

SOURCE_FULL = {
    "tg_json": "TG JSON",
    "tg_html": "TG HTML",
    "vk":      "VK",
    "ig":      "Instagram",
    "wa":      "WhatsApp",
}


def _src_tag(msg: dict) -> str:
    src = msg.get("source", "")
    label = SOURCE_LABELS.get(src, src.upper() if src else "")
    return f"[{label}] " if label else ""


def _source_counts(messages: list) -> str:
    from collections import Counter as _C
    cnt = _C(m.get("source") or "?" for m in messages)
    known_order = ["tg_json", "tg_html", "vk", "wa", "ig"]
    parts = []
    for code in known_order:
        if cnt.get(code):
            parts.append(f"{SOURCE_FULL[code]} — {cnt[code]}")
    other = sum(v for k, v in cnt.items() if k not in known_order)
    if other:
        parts.append(f"прочее — {other}")
    return ", ".join(parts) if parts else ""


def format_output(messages: list, sources: list, contact: str,
                  fmt: str = "txt", show_timestamps: bool = True,
                  show_source: bool = False) -> str:
    """
    fmt: 'txt' — текстовый формат (по умолчанию)
         'md'  — Markdown формат
    show_timestamps: False — убирает метки времени из вывода
    show_source: True — добавляет метку источника [TG]/[VK]/... перед автором
    """
    if fmt == "md":
        return _format_markdown(messages, sources, contact, show_timestamps, show_source)
    return _format_txt(messages, sources, contact, show_timestamps, show_source)


def _format_txt(messages: list, sources: list, contact: str,
                show_timestamps: bool = True, show_source: bool = False) -> str:
    _sc = _source_counts(messages)
    lines = [
        "=" * 56,
        f"Переписка: {contact}",
        f"Источники: {', '.join(sources)}",
        f"Сообщений: {len(messages)}" + (f"  ({_sc})" if _sc else ""),
        "=" * 56,
    ]

    prev_month = None
    prev_day   = None

    for msg in messages:
        dt = msg["dt"]
        if dt:
            mk = (dt.year, dt.month)
            dk = dt.date()

            if mk != prev_month:
                lines += [
                    "",
                    "━" * 40,
                    f"  {MONTHS_NOM[dt.month].upper()} {dt.year}",
                    "━" * 40,
                ]
                prev_month = mk
                prev_day   = None

            if dk != prev_day:
                lines.append(f"\n  {dt.day} {MONTHS_GEN[dt.month]}")
                prev_day = dk

            ts = dt.strftime("%H:%M:%S")
        else:
            ts = "??:??:??"

        text_lines = msg["text"].split("\n")
        prefix = f"{ts} " if show_timestamps else ""
        src = _src_tag(msg) if show_source else ""
        lines.append(f"{prefix}{src}{msg['sender']}: {text_lines[0]}")
        for line in text_lines[1:]:
            lines.append(f"  {line}")

    return "\n".join(lines)


def _format_markdown(messages: list, sources: list, contact: str,
                     show_timestamps: bool = True, show_source: bool = False) -> str:
    _sc = _source_counts(messages)
    lines = [
        f"# Переписка: {contact}",
        "",
        f"**Источники:** {', '.join(sources)}  ",
        f"**Сообщений:** {len(messages)}" + (f"  _({_sc})_" if _sc else ""),
        "",
        "---",
        "",
    ]

    prev_month = None
    prev_day   = None

    for msg in messages:
        dt = msg["dt"]
        if dt:
            mk = (dt.year, dt.month)
            dk = dt.date()

            if mk != prev_month:
                lines += [
                    "",
                    f"## {MONTHS_NOM[dt.month].capitalize()} {dt.year}",
                    "",
                ]
                prev_month = mk
                prev_day   = None

            if dk != prev_day:
                lines.append(f"### {dt.day} {MONTHS_GEN[dt.month]}")
                lines.append("")
                prev_day = dk

            ts = dt.strftime("%H:%M")
        else:
            ts = "??:??"

        sender_md = f"**{msg['sender']}**"
        text_lines = msg["text"].split("\n")
        # Отделяем цитаты/пересылки (они идут первыми) от основного текста
        prefix_lines = []
        content_start = 0
        for idx, line in enumerate(text_lines):
            if line.startswith("  ┌ ") or line.startswith("[переслано"):
                prefix_lines.append(line)
                content_start = idx + 1
            else:
                break
        content_lines = text_lines[content_start:]
        # Цитаты и пересылки — blockquote перед сообщением
        for line in prefix_lines:
            lines.append(f"> {line.strip()}")
        # Основная строка с меткой времени
        first = content_lines[0] if content_lines else ""
        ts_prefix = f"`{ts}` " if show_timestamps else ""
        src = _src_tag(msg) if show_source else ""
        lines.append(f"{ts_prefix}{src}{sender_md}: {first}")
        for line in content_lines[1:]:
            lines.append(f"  {line}")
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────
#  Главная функция
# ──────────────────────────────────────────────

def main():
    # UTF-8 вывод только для CLI-запуска (не влияет на GUI/reload)
    import io as _io2, sys as _sys2
    if hasattr(_sys2.stdout, 'buffer'):
        try:
            _sys2.stdout = _io2.TextIOWrapper(_sys2.stdout.buffer, encoding='utf-8', errors='replace')
            _sys2.stderr = _io2.TextIOWrapper(_sys2.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Объединитель переписок Telegram и ВКонтакте",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python merge_chat.py "C:\\\\Переписки\\\\Иван"
  python merge_chat.py "C:\\\\Иван\\\\1" "C:\\\\Иван\\\\2" --author "Вы"
  python merge_chat.py "C:\\\\Переписки\\\\Иван" --model medium
  python merge_chat.py "C:\\\\Переписки\\\\Иван" --markdown
        """
    )
    parser.add_argument("folders", nargs="*", default=["."],
                        help="Папки с экспортом (по умолчанию текущая)")
    parser.add_argument("--author",  default="Вы",
                        help="Твоё имя в переписках (default: Вы)")
    parser.add_argument("--output",  default="",
                        help="Имя выходного файла")
    parser.add_argument("--model",   default="small",
                        choices=["tiny","base","small","medium","large"],
                        help="Модель Whisper (default: small)")
    parser.add_argument("--merge", action="store_true",
                        help="Объединять подряд идущие сообщения одного автора")
    parser.add_argument("--gap",     type=int, default=180,
                        help="Порог объединения в секундах (default: 180)")
    parser.add_argument("--verbose", action="store_true",
                        help="Подробный лог")
    parser.add_argument("--markdown", action="store_true",
                        help="Сохранить в формате Markdown (.md)")

    args = parser.parse_args()

    author = args.author.strip() if args.author else "Вы"

    CFG.my_name = author
    CFG.my_names_lower = [unicodedata.normalize("NFC", author).lower()]
    if "ём" in author.lower() or "ем" in author.lower():
        CFG.my_names_lower += [author.lower().replace("ём","ем"),
                                author.lower().replace("ем","ём")]
    CFG.use_whisper   = True
    CFG.whisper_model  = args.model
    CFG.merge_gap      = args.gap
    CFG.do_merge       = args.merge  # по умолчанию ВЫКЛ для CLI
    CFG.verbose        = args.verbose
    CFG.output_format  = "md" if args.markdown else "txt"

    folders = [Path(f) for f in args.folders]
    raw_valid = [f for f in folders if f.exists() and f.is_dir()]
    if not raw_valid:
        print("Ошибка: папки не найдены.")
        sys.exit(1)

    valid = []
    for root_folder in raw_valid:
        chat_folders = find_all_chat_folders(root_folder)
        if chat_folders:
            if len(chat_folders) > 1:
                print(f"Папка '{root_folder.name}': найдено чатов — {len(chat_folders)}")
            valid.extend(chat_folders)
        else:
            print(f"! В папке '{root_folder.name}' не найдено файлов переписки")

    if not valid:
        print("Ошибка: файлы переписки не найдены.")
        print("Проверь что в папке есть result.json или messages*.html")
        sys.exit(1)

    if CFG.use_whisper:
        total = 0
        for f in raw_valid:
            total += len(list(f.rglob("*.ogg")))
            total += len(list(f.rglob("*.opus")))
            total += len(list(f.rglob("round_video_messages/*.mp4")))
        _voice_counter["total"] = total
        if total:
            print(f"Аудиофайлов для расшифровки: {total}")
            print(f"Примерное время: {total}–{total*4} мин (модель '{CFG.whisper_model}')")

    all_messages: List[dict] = []
    sources: List[str] = []
    contact = ""
    seen_ids: set = set()
    _best_contact_count = 0

    print("\nОбработка папок:")
    for folder in valid:
        msgs, c, src = load_chat_folder(folder)
        sources.append(f"{src} ({folder.name})")

        # Берём имя контакта из источника с наибольшим числом его сообщений
        if c:
            _msg_count = len([m for m in msgs if m.get("sender") != CFG.my_name])
            # Также проверяем что имя не кривое (нет символов замены UTF-8)
            c_ok = b"\xef\xbf\xbd" not in c.encode("utf-8", errors="replace")
            if c_ok and _msg_count > _best_contact_count:
                _best_contact_count = _msg_count
                contact = c

        new, dup = 0, 0
        for msg in msgs:
            mid = msg.get("id")
            if mid and mid in seen_ids:
                dup += 1
            else:
                if mid:
                    seen_ids.add(mid)
                all_messages.append(msg)
                new += 1
        if dup:
            print(f"  Дублей пропущено: {dup}")

    if not all_messages:
        print("Нет данных для обработки.")
        sys.exit(1)

    # FIX: правильная сортировка по datetime
    with_dt    = sorted([m for m in all_messages if m["dt"]], key=lambda x: x["dt"])
    without_dt = [m for m in all_messages if not m["dt"]]
    all_messages = with_dt + without_dt

    if CFG.do_merge:
        before = len(all_messages)
        all_messages = merge_consecutive(all_messages)
        print(f"\nMessages: {before} -> {len(all_messages)} (merged)")

    output_dir = raw_valid[0]
    ext = ".md" if CFG.output_format == "md" else ".txt"
    if args.output:
        out_path = Path(args.output)
    else:
        def looks_ok(s: str) -> bool:
            if not s:
                return False
            enc = s.encode("utf-8", errors="replace")
            return b"\xef\xbf\xbd" not in enc and b"?" * 3 not in enc and len(s.strip()) > 0
        name = contact if looks_ok(contact) else output_dir.name
        safe = re.sub(r'[\\/*?:"<>|]', "", name.split()[0])
        out_path = output_dir / f"{safe}{ext}"

    result = format_output(all_messages, sources, contact or "неизвестно", CFG.output_format)
    out_path.write_text(result, encoding="utf-8")
    kb = out_path.stat().st_size // 1024
    print(f"\n✓ Готово → {out_path} ({kb} КБ)")



# ─────────────────────────────────────────────────────────────
# API для GUI
# ─────────────────────────────────────────────────────────────

def process_folder(folder_path: str,
                   author: str = "Вы",
                   model: str = "small",
                   do_merge: bool = True,
                   output_format: str = "txt",
                   log_cb=None,
                   progress_cb=None,
                   date_from: str = "",
                   date_to: str = "",
                   show_timestamps: bool = True,
                   split_mode: str = "none",
                   show_source: bool = False,
                   filter_author: str = "",
                   filter_text: str = "",
                   my_display: str = "",
                   peer_display: str = "") -> Optional[str]:
    """split_mode: 'none' | 'month' | 'year'"""
    """
    Высокоуровневая функция для GUI.
    Возвращает путь к итоговому файлу или None при ошибке.
    output_format: 'txt' или 'md'
    """
    import sys as _sys

    class _LogCapture:
        def write(self, s):
            s = s.rstrip()
            if s and log_cb:
                log_cb(s)
        def flush(self): pass

    old_stdout = _sys.stdout
    old_stderr = _sys.stderr
    if log_cb:
        _sys.stdout = _LogCapture()
        _sys.stderr = _LogCapture()

    try:
        import unicodedata as _ud
        # Поле «Твоё имя» может быть списком через запятую: "Артём, Tema, Artem"
        # — все эти имена считаются "мной" (алиасы). Display = первый элемент,
        # либо явный override через my_display.
        _aliases = [a.strip() for a in (author or "").split(",") if a.strip()]
        if not _aliases:
            _aliases = ["Я"]
        _display_self = my_display.strip() or _aliases[0]
        CFG.my_name = _display_self
        _lows = []
        for _a in _aliases:
            _al = _ud.normalize("NFC", _a).lower()
            _lows.append(_al)
            if _al not in ("вы", "я", "me", "i"):
                _lows.append(_a.lower().replace("ём", "ем"))
                _lows.append(_ud.normalize("NFD", _a).lower())
        # Стандартные «вы»/«я»/«me» всегда считаем собой
        _lows += ["вы", "я", "me", "i"]
        CFG.my_names_lower = list(dict.fromkeys(_lows))  # уникальные с сохранением порядка
        CFG.peer_name = peer_display.strip()
        CFG.use_whisper    = True
        CFG.whisper_model  = model
        CFG.do_merge       = do_merge
        CFG.verbose        = False
        CFG.merge_gap      = 180
        CFG.output_format  = output_format

        folder = Path(folder_path)
        if not folder.exists():
            if log_cb: log_cb(f"Ошибка: папка не найдена: {folder_path}")
            return None

        raw_valid = [folder] if folder.is_dir() else []

        top_folder_name = folder.name.strip()
        top_name_is_real = (top_folder_name not in (".", "..", "") and
                            len(top_folder_name) > 1)

        valid = []
        for rf in raw_valid:
            valid.extend(find_all_chat_folders(rf))
        if not valid:
            valid = raw_valid
        if not valid:
            if log_cb: log_cb("Ошибка: папки с перепиской не найдены.")
            return None

        if progress_cb: progress_cb(0.05)

        # Reset transcription cache before each run
        _voice_counter["done"] = 0
        _voice_counter["total"] = 0
        _transcribe_cache.clear()
        _log_info(f"process_folder: {folder_path}, model={model}")

        _pre_voice: set = set()
        for _vdir in valid:
            for _pat in ("voice_messages/*.ogg","voice_messages/*.oga","video_messages/*.mp4","audio/*.mp4","*.ogg","*.oga","*.opus"):
                _pre_voice.update(_vdir.rglob(_pat) if "/" in _pat else _vdir.glob(_pat))
        _pre_total = len(_pre_voice)
        _voice_counter["total"] = _pre_total
        import time as _time
        _start_time = _time.time()
        if _pre_total:
            _speed={"tiny":0.3,"base":0.5,"small":1,"medium":2,"large":4}
            _k=_speed.get(model,1)
            if log_cb: log_cb(f"Аудиофайлов для расшифровки: {_pre_total}")
            if date_from or date_to:
                if log_cb: log_cb(f"Время расшифровки: зависит от периода (голосовые только из выбранных дат)")
            else:
                # Detect GPU for accurate estimate
                _gpu_est = False
                try:
                    import torch as _te
                    if _te.cuda.is_available() or (hasattr(_te.backends,'mps') and _te.backends.mps.is_available()):
                        _gpu_est = True
                except Exception:
                    pass
                if _gpu_est:
                    # GPU: calibrated on RTX 3060 Ti (241 medium files = 7.6 min → 0.016 min/file/k)
                    _tmin = max(1, int(_pre_total * _k * 0.01))
                    _tmax = max(2, int(_pre_total * _k * 0.02))
                    _tr = f"~{_tmin}" if _tmin == _tmax else f"{_tmin}–{_tmax}"
                    if log_cb: log_cb(f"Примерное время расшифровки голосовых: {_tr} мин (модель '{model}', GPU)")
                else:
                    if log_cb: log_cb(f"Примерное время расшифровки: {max(1,int(_pre_total*_k*0.5))}–{max(2,int(_pre_total*_k*1))} мин (модель '{model}', CPU)")
            _is_frozen=getattr(__import__('sys'),'frozen',False)
            _dev='CPU'
            if not _is_frozen:
                try:
                    import torch as _tp
                    _tv = getattr(_tp, '__version__', '?')
                    if _tp.cuda.is_available():
                        _dev=f'NVIDIA {_tp.cuda.get_device_name(0)}'
                    elif hasattr(_tp.backends,'mps') and _tp.backends.mps.is_available():
                        _dev='Apple Silicon MPS'
                    else:
                        _cuda_info = getattr(getattr(_tp, 'version', None), 'cuda', None)
                        try:
                            import torch_directml as _tdml; _dev='AMD/Intel (DirectML)'
                        except ImportError: pass
                except ImportError:
                    pass
            _is_frozen_win = _is_frozen and __import__('sys').platform == 'win32'
            if log_cb: log_cb(f"  Устройство расшифровки: {_dev}" + (' (exe-сборка Windows — GPU недоступен)' if _is_frozen_win else ''))
        else:
            if log_cb: log_cb("Аудиофайлов для расшифровки: 0")

        all_messages: List[dict] = []
        sources: List[str] = []
        contact = ""
        _best_contact_count = 0

        # Парсинг дат фильтра
        from datetime import datetime as _dt
        _df = _dt_parsed = None
        if date_from:
            try:
                _df = _dt.strptime(date_from.strip(), "%d.%m.%Y")
            except ValueError:
                if log_cb: log_cb(f"[!] Неверный формат даты 'с': {date_from} (нужен ДД.ММ.ГГГГ)")
        if date_to:
            try:
                _dt_parsed = _dt.strptime(date_to.strip(), "%d.%m.%Y").replace(hour=23, minute=59, second=59)
            except ValueError:
                if log_cb: log_cb(f"[!] Неверный формат даты 'по': {date_to} (нужен ДД.ММ.ГГГГ)")

        # Если заданы даты — первый проход БЕЗ расшифровки, чтобы найти нужные сообщения
        # Потом расшифруем только голосовые внутри нужного периода
        needs_date_filter = bool(_df or _dt_parsed)
        if needs_date_filter:
            CFG.skip_transcribe = True

        seen_ids: set = set()
        for i, v in enumerate(valid):
            if _cancel_event and _cancel_event.is_set():
                if log_cb: log_cb("--- Отменено ---")
                _release_whisper_memory()
                return None
            msgs, c, src = load_chat_folder(v)
            if src: sources.extend(src if isinstance(src, list) else [src])
            new_cnt, dup_cnt = 0, 0
            for msg in msgs:
                mid = msg.get("id")
                if mid and mid in seen_ids:
                    dup_cnt += 1
                else:
                    if mid:
                        seen_ids.add(mid)
                    all_messages.append(msg)
                    new_cnt += 1
            if dup_cnt:
                if log_cb: log_cb(f"  Дублей пропущено: {dup_cnt}")
            if c:
                _msg_count = len([m for m in msgs if m.get("sender") != CFG.my_name])
                if _msg_count > _best_contact_count:
                    _best_contact_count = _msg_count
                    contact = c
            if progress_cb: progress_cb(0.1 + 0.4 * (i + 1) / len(valid))

        CFG.skip_transcribe = False  # сбрасываем после первого прохода

        # Имя папки используем только как fallback
        if not contact:
            contact = top_folder_name

        # Сортировка по дате
        with_dt    = sorted([m for m in all_messages if m.get("dt")], key=lambda x: x["dt"])
        without_dt = [m for m in all_messages if not m.get("dt")]
        all_messages = with_dt + without_dt

        # Фильтр по датам
        if needs_date_filter:
            before = len(all_messages)
            all_messages = [
                m for m in all_messages
                if m.get("dt") and
                   (_df is None or m["dt"] >= _df) and
                   (_dt_parsed is None or m["dt"] <= _dt_parsed)
            ]
            after = len(all_messages)
            if log_cb: log_cb(f"Фильтр по датам: {before} → {after} сообщений")
            if not all_messages:
                if log_cb: log_cb("Нет сообщений в выбранном периоде.")
                return None

            # Второй проход: расшифровываем только голосовые в отфильтрованных сообщениях
            if CFG.use_whisper:
                voice_msgs = [m for m in all_messages if m.get("_voice_path")]
                if voice_msgs:
                    _speed2={"tiny":0.3,"base":0.5,"small":1,"medium":2,"large":4}
                    _k2=_speed2.get(model,1)
                    _vn=len(voice_msgs)
                    _voice_counter["total"] = _vn
                    _voice_counter["done"] = 0
                    if log_cb: log_cb(f"Голосовых в выбранном периоде: {_vn}")
                    _gpu2 = False
                    try:
                        import torch as _te2
                        if _te2.cuda.is_available() or (hasattr(_te2.backends,'mps') and _te2.backends.mps.is_available()):
                            _gpu2 = True
                    except Exception:
                        pass
                    if _gpu2:
                        _tmin2 = max(1, int(_vn*_k2*0.01))
                        _tmax2 = max(2, int(_vn*_k2*0.02))
                        _tr2 = f"~{_tmin2}" if _tmin2 == _tmax2 else f"{_tmin2}–{_tmax2}"
                        if log_cb: log_cb(f"Примерное время расшифровки голосовых: {_tr2} мин (модель '{model}', GPU)")
                    else:
                        if log_cb: log_cb(f"Примерное время расшифровки: {max(1,int(_vn*_k2*0.5))}–{max(2,int(_vn*_k2*1))} мин (модель '{model}', CPU)")
                    for j, m in enumerate(voice_msgs):
                        if _cancel_event and _cancel_event.is_set():
                            break
                        vpath = m.get("_voice_path")
                        if vpath:
                            text = transcribe(Path(vpath))
                            if text:
                                m["text"] = m.get("text", "").replace(
                                    "[🎤 Голосовое — нет расшифровки]", f"[🎤 {text}]"
                                ).replace("[🎤 Голосовое — файл не найден]", f"[🎤 {text}]"
                                ).replace("[🎤 Голосовое]", f"[🎤 {text}]")
                        if progress_cb: progress_cb(0.5 + 0.3 * (j + 1) / _vn)
                else:
                    if _pre_total > 0:
                        if log_cb: log_cb(f"Голосовых в выбранном периоде: 0 (все голосовые вне выбранных дат)")

        # Считаем голосовые только из отфильтрованных сообщений
        # (чтобы не расшифровывать файлы вне выбранного периода)
        voice_paths_in_period: set = set()
        for m in all_messages:
            mp = m.get("_voice_path")
            if mp:
                p = Path(mp) if not isinstance(mp, Path) else mp
                if p.exists():
                    voice_paths_in_period.add(p.resolve())
        # Fallback: если у сообщений нет _voice_path — сканируем папки (без фильтра)
        if not voice_paths_in_period and not (date_from or date_to):
            for v in valid:
                for pat in ("voice_messages/*.ogg","voice_messages/*.oga",
                            "video_messages/*.mp4","audio/*.mp4","*.ogg","*.oga"):
                    voice_paths_in_period.update(v.rglob(pat) if "/" in pat else v.glob(pat))
        audio_total = len(voice_paths_in_period)
        if audio_total > _pre_total: _voice_counter["total"] = audio_total

        # Проверяем: нашли ли хоть одно сообщение с именем автора
        # Если нет — пробуем найти реальное имя и подсказать
        if author and all_messages:
            import unicodedata as _ud2
            _my_low = [_ud2.normalize("NFC", author).lower(),
                       author.lower().replace("ём","ем"),
                       author.lower().replace("ем","ём")]
            _found_me = any(
                _ud2.normalize("NFC", (m.get("sender") or "")).lower() in _my_low
                for m in all_messages
            )
            if not _found_me:
                # Собираем всех отправителей и их частоту
                from collections import Counter as _Ctr
                _senders = _Ctr(m.get("sender","") for m in all_messages if m.get("sender"))
                _contact_name = contact or ""
                # "Мой" отправитель — не контакт (его имя в названии папки/переписки)
                _candidates = [s for s in _senders if s and s.lower() != _contact_name.lower()]
                if _candidates:
                    _best = _candidates[0]  # первый попавшийся не-контакт
                    if log_cb: log_cb(
                        f"[!] Имя автора '{author}' не найдено в переписке. "
                        f"Возможно, правильное имя: '{_best}' — проверь поле 'Твоё имя'."
                    )
                else:
                    if log_cb: log_cb(f"[!] Имя автора '{author}' не найдено ни у одного отправителя.")

        if filter_author or filter_text:
            import re as _ref
            _fa = filter_author.strip().lower()
            _ft_pat = None
            if filter_text.strip():
                try:
                    _ft_pat = _ref.compile(filter_text.strip(), _ref.IGNORECASE)
                except _ref.error as _re_err:
                    if log_cb: log_cb(f"[!] Regex в фильтре невалиден: {_re_err}. Фильтр по тексту отключён.")
            before = len(all_messages)
            all_messages = [
                m for m in all_messages
                if (not _fa or _fa in (m.get("sender") or "").lower())
                   and (_ft_pat is None or _ft_pat.search(m.get("text") or ""))
            ]
            if log_cb: log_cb(f"  Фильтр: {before} → {len(all_messages)} сообщений")

        if CFG.do_merge:
            all_messages = merge_consecutive(all_messages)

        # Если задан peer_display — переименовываем всех НЕ-self авторов в это имя.
        # Решает проблему «у одного человека разные подписи в TG/VK/IG/WA».
        if CFG.peer_name:
            _renamed = 0
            for _m in all_messages:
                _s = _m.get("sender") or ""
                if _s and _s != CFG.my_name:
                    _m["sender"] = CFG.peer_name
                    _renamed += 1
            if log_cb and _renamed:
                log_cb(f"  Имена в выводе: «Я» → '{CFG.my_name}', собеседник → '{CFG.peer_name}' ({_renamed} сообщений)")

        if progress_cb: progress_cb(0.8)

        if not contact or contact.strip() in (".", "", ".."):
            contact = valid[0].name if valid[0].name not in (".", "..") else "чат"
        # Имя контакта в шапке/имени файла = peer_display, если задано.
        if CFG.peer_name:
            contact = CFG.peer_name
        import re as _re
        safe = _re.sub(r'[\\/*?:"<>|]', "", contact.split()[0]).strip()
        if not safe:
            safe = "chat"

        ext = ".md" if output_format == "md" else ".txt"
        output_dir = folder
        out_path = None

        if split_mode in ("month", "year"):
            from itertools import groupby
            if split_mode == "month":
                def _key(m): return f"{m['dt'].year}-{m['dt'].month:02d}" if m.get("dt") else ""
            else:
                def _key(m): return str(m["dt"].year) if m.get("dt") else ""
            with_dt    = [m for m in all_messages if m.get("dt")]
            without_dt = [m for m in all_messages if not m.get("dt")]
            files_written = 0
            for label, group in groupby(with_dt, key=_key):
                if not label:
                    continue
                chunk = list(group)
                chunk_path = output_dir / f"{safe}_{label}{ext}"
                result = format_output(chunk, sources, contact, output_format, show_timestamps, show_source)
                chunk_path.write_text(result, encoding="utf-8")
                kb = chunk_path.stat().st_size // 1024
                if log_cb: log_cb(f"  → {chunk_path.name} ({len(chunk)} сообщ., {kb} КБ)")
                files_written += 1
                out_path = chunk_path
            if without_dt:
                nd_path = output_dir / f"{safe}_no_date{ext}"
                result = format_output(without_dt, sources, contact, output_format, show_timestamps, show_source)
                nd_path.write_text(result, encoding="utf-8")
                files_written += 1
            if progress_cb: progress_cb(1.0)
            if log_cb: log_cb(f"\n✓ Готово → {output_dir} ({files_written} файлов)")
        else:
            out_path = output_dir / f"{safe}{ext}"
            result = format_output(all_messages, sources, contact, output_format, show_timestamps, show_source)
            out_path.write_text(result, encoding="utf-8")
            if progress_cb: progress_cb(1.0)
            kb = out_path.stat().st_size // 1024
            if log_cb: log_cb(f"\n✓ Готово → {out_path} ({kb} КБ)")

        _elapsed=_time.time()-_start_time
        _m,_s=divmod(int(_elapsed),60)
        if log_cb: log_cb(f"  Время обработки: {_m} мин {_s} сек")

        _release_whisper_memory()
        return str(out_path)

    except Exception as e:
        import traceback as _tb
        _log_error(f"process_folder error: {e}\n{_tb.format_exc()}")
        if log_cb: log_cb(f"Ошибка: {e}")
        if log_cb: log_cb(_tb.format_exc())
        return None
    finally:
        _sys.stdout = old_stdout
        _sys.stderr = old_stderr


AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus",
              ".aac", ".flac", ".webm", ".amr", ".mp4"}


def process_audio(source_path: str,
                  model: str = "small",
                  output_format: str = "txt",
                  show_timestamps: bool = True,
                  log_cb=None,
                  progress_cb=None) -> Optional[str]:
    """Режим транскрипции аудио: один файл или папка только с аудио.
    Возвращает путь к итоговому .txt/.md или None."""
    src = Path(source_path)
    if not src.exists():
        if log_cb: log_cb(f"Не найден путь: {src}")
        return None

    if src.is_file():
        files = [src] if src.suffix.lower() in AUDIO_EXTS else []
        out_dir = src.parent
        out_name = src.stem
    else:
        files = sorted(
            p for p in src.rglob("*")
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        )
        out_dir = src
        out_name = src.name or "audio"

    if not files:
        if log_cb: log_cb("Аудио-файлов не найдено.")
        return None

    CFG.use_whisper = True
    CFG.whisper_model = model
    _voice_counter["done"] = 0
    _voice_counter["total"] = len(files)

    if log_cb: log_cb(f"Найдено аудио: {len(files)} файл(ов)")
    if log_cb: log_cb(f"  Модель: {model}")

    # Устройство расшифровки — единый формат с process_folder, чтобы пользователь
    # сразу видел, на CPU или GPU будет работать.
    _is_frozen = getattr(__import__('sys'), 'frozen', False)
    _dev = 'CPU'
    _cpu_reason = ''
    if not _is_frozen:
        try:
            import torch as _tp
            _tv = getattr(_tp, '__version__', '?')
            if _tp.cuda.is_available():
                _dev = f'NVIDIA {_tp.cuda.get_device_name(0)}'
            elif hasattr(_tp.backends, 'mps') and _tp.backends.mps.is_available():
                _dev = 'Apple Silicon MPS'
            else:
                _cuda_built = getattr(getattr(_tp, 'version', None), 'cuda', None)
                if _cuda_built is None:
                    _cpu_reason = f' (torch {_tv} без CUDA — переустанови torch с CUDA для GPU)'
                else:
                    _cpu_reason = f' (torch {_tv} CUDA {_cuda_built} собран, но GPU не виден)'
                try:
                    import torch_directml as _tdml; _dev = 'AMD/Intel (DirectML)'; _cpu_reason = ''
                except ImportError:
                    pass
        except ImportError:
            _cpu_reason = ' (torch не установлен)'
    _is_frozen_win = _is_frozen and __import__('sys').platform == 'win32'
    if log_cb:
        _suffix = ' (exe-сборка Windows — GPU недоступен)' if _is_frozen_win else _cpu_reason
        log_cb(f"  Устройство расшифровки: {_dev}{_suffix}")

    # Диагностика окружения — сразу видно если что-то не так с ffmpeg/Whisper.
    try:
        import shutil as _sh
        _ff_sys = _sh.which("ffmpeg")
        _ff_tmp = _sh.which("ffmpeg.exe") if not _ff_sys else _ff_sys
        if log_cb:
            log_cb(f"  ffmpeg: {_ff_tmp or _ff_sys or 'НЕ НАЙДЕН (Whisper упадёт)'}")
        if _whisper_module is None:
            if log_cb: log_cb("  ⚠ Whisper не установлен в саму прогу — голосовые "
                              "не расшифруются. Поставь Whisper через «О программе» в окне MergeChat.")
    except Exception:
        pass

    blocks = []
    _bar_w = 25  # ширина прогресс-бара в символах — как в process_folder
    for i, f in enumerate(files, 1):
        if _cancel_event and _cancel_event.is_set():
            if log_cb: log_cb("--- Отмена ---")
            break
        if log_cb: log_cb(f"  [{i}/{len(files)}] Transcribing: {f.name}")
        if progress_cb:
            progress_cb(0.05 + 0.9 * (i - 1) / max(len(files), 1))
        try:
            size_kb = f.stat().st_size // 1024
        except Exception:
            size_kb = 0
        try:
            raw = transcribe(f)
        except Exception as ex:
            if log_cb: log_cb(f"  Ошибка transcribe(): {ex}")
            raw = None
        text = (raw or "").strip()
        ts = ""
        if show_timestamps:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                ts = mtime.strftime("[%Y-%m-%d %H:%M] ")
            except Exception:
                ts = ""
        head = f"{ts}{f.name}".strip()
        if text:
            body = text
        elif raw is None:
            body = (f"(транскрипция не выполнена — размер {size_kb} КБ; "
                    f"проверь лог выше: ffmpeg / Whisper / GPU)")
        else:
            body = "(Whisper отработал, но текст пустой — тишина или слишком короткое аудио)"
        blocks.append(f"=== {head} ===\n{body}\n")

        # Прогрессбар тем же стилем, что в process_folder — пользователь видит,
        # что расшифровка идёт и сколько примерно осталось.
        if log_cb:
            _pct = i / max(len(files), 1)
            _filled = int(_bar_w * _pct)
            _bar = "█" * _filled + "░" * (_bar_w - _filled)
            _preview = (text[:55] + "...") if len(text) > 55 else (text or "")
            log_cb(f"  [{_bar}] {i}/{len(files)} ({int(_pct*100)}%)" +
                   (f"  «{_preview}»" if _preview else ""))

    if not blocks:
        _release_whisper_memory()
        return None

    ext = ".md" if output_format == "md" else ".txt"
    safe = re.sub(r'[\\/*?:"<>|]', "", out_name).strip() or "audio"
    out_path = out_dir / f"{safe}_audio{ext}"
    header = (f"Расшифровка аудио\nИсточник: {src}\n"
              f"Файлов: {len(blocks)}\nМодель: {model}\n"
              + ("=" * 60) + "\n\n")
    out_path.write_text(header + "\n".join(blocks), encoding="utf-8")
    if progress_cb: progress_cb(1.0)
    kb = out_path.stat().st_size // 1024
    if log_cb: log_cb(f"\n✓ Готово → {out_path} ({kb} КБ)")
    _release_whisper_memory()
    return str(out_path)


if __name__ == "__main__":
    main()
