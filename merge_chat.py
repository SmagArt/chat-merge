"""
merge_chat.py — Универсальный объединитель переписок
=====================================================
Поддерживает: Telegram JSON, Telegram HTML, ВКонтакте HTML
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

# ffmpeg: используем imageio-ffmpeg если системного нет
def _fix_ffmpeg():
    import shutil as _sh, os as _os2
    if _sh.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg as _iff
        from pathlib import Path as _P
        exe = _iff.get_ffmpeg_exe()
        if not exe or not _P(exe).exists():
            return
        _dir = str(_P(exe).parent)
        _os2.environ["PATH"] = _dir + _os2.pathsep + _os2.environ.get("PATH", "")
        import tempfile as _tmp
        _tlink = _P(_tmp.gettempdir()) / "ffmpeg"
        if not _tlink.exists():
            try:
                _tlink.symlink_to(exe)
            except Exception:
                pass
        _tdir = str(_tlink.parent)
        if _tdir not in _os2.environ.get("PATH",""):
            _os2.environ["PATH"] = _tdir + _os2.pathsep + _os2.environ.get("PATH", "")
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


# ── Pre-import для PyInstaller (замороженный режим) ──────
# В frozen сборке _MEIPASS нужно добавить в sys.path до импорта whisper
import sys as _sys_pre
_meipass_pre = getattr(_sys_pre, '_MEIPASS', None)
if _meipass_pre and _meipass_pre not in _sys_pre.path:
    _sys_pre.path.insert(0, _meipass_pre)
del _sys_pre, _meipass_pre

try:
    import whisper as _whisper_module  # noqa
except Exception:
    # ImportError OR OSError (wrong arch torch on Apple Silicon) — handled gracefully
    _whisper_module = None

# ──────────────────────────────────────────────
#  Глобальное состояние
# ──────────────────────────────────────────────

class Config:
    my_name: str        = "Я"
    my_names_lower: list = []
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

def _progress_bar(done: int, total: int, w: int = 25) -> str:
    pct  = done / total if total else 0
    fill = int(w * pct)
    return f"[{'█'*fill}{'░'*(w-fill)}] {done}/{total} ({pct*100:.0f}%)"


def transcribe(file_path: Path) -> Optional[str]:
    if CFG.skip_transcribe:
        return None  # first-pass mode: no transcription
    print(f"  [DBG] transcribe called: use_whisper={CFG.use_whisper}, file={file_path}")
    if not CFG.use_whisper or not file_path or not file_path.exists():
        print(f"  [DBG] transcribe SKIP: use_whisper={CFG.use_whisper}, exists={file_path.exists() if file_path else 'N/A'}")
        return None

    # Check if user pressed Cancel
    if _cancel_event and _cancel_event.is_set():
        return None

    cache_key = str(file_path.resolve())
    if cache_key in _transcribe_cache:
        print(f"  [DBG] transcribe CACHED: {file_path.name}")
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
                _whisper_cache = whisper.load_model(CFG.whisper_model, device=_device)
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
                        _whisper_cache = whisper.load_model(CFG.whisper_model, device="cpu")
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
                    verbose=False,
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
    print(f"  [DBG] media_label: OK, use_whisper={CFG.use_whisper}, file={file_path.name}")
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
            if '"messages"' in head or '"chats"' in head:
                found.add(p.parent)
        except:
            pass

    for p in root.rglob("messages*.html"):
        if re.match(r"messages\d*\.html", p.name, re.I):
            found.add(p.parent)

    def _folder_sort_key(p):
        n = p.name
        if n in (".", "..") or n.startswith("."):
            return "zzz_" + n
        return n.lower()
    return sorted(found, key=_folder_sort_key)


def load_chat_folder(folder: Path) -> Tuple[List[dict], str, str]:
    all_msgs: List[dict] = []
    contact = ""
    srcs = []

    json_path = None
    if (folder / "result.json").exists():
        json_path = folder / "result.json"
    else:
        for p in sorted(folder.glob("*.json")):
            try:
                d = json.loads(p.read_bytes().decode("utf-8", errors="replace"))
                if isinstance(d, dict) and ("messages" in d or "chats" in d):
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

def format_output(messages: list, sources: list, contact: str,
                  fmt: str = "txt") -> str:
    """
    fmt: 'txt' — текстовый формат (по умолчанию)
         'md'  — Markdown формат
    """
    if fmt == "md":
        return _format_markdown(messages, sources, contact)
    return _format_txt(messages, sources, contact)


def _format_txt(messages: list, sources: list, contact: str) -> str:
    lines = [
        "=" * 56,
        f"Переписка: {contact}",
        f"Источники: {', '.join(sources)}",
        f"Сообщений: {len(messages)}",
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

        lines.append(f"{ts} {msg['sender']}:")
        for line in msg["text"].split("\n"):
            lines.append(f"  {line}")

    return "\n".join(lines)


def _format_markdown(messages: list, sources: list, contact: str) -> str:
    lines = [
        f"# Переписка: {contact}",
        "",
        f"**Источники:** {', '.join(sources)}  ",
        f"**Сообщений:** {len(messages)}",
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
        # Первая строка
        first = text_lines[0]
        lines.append(f"`{ts}` {sender_md}: {first}")
        # Остальные строки с отступом
        for line in text_lines[1:]:
            if line.startswith("  ┌ "):
                lines.append(f"> {line.strip()}")
            else:
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
                   date_to: str = "") -> Optional[str]:
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
        CFG.my_name        = author
        CFG.my_names_lower = [_ud.normalize("NFC", author).lower()]
        if author.lower() not in ("вы", "я", "me", "i"):
            CFG.my_names_lower += [author.lower().replace("ём","ем"),
                                   _ud.normalize("NFD", author).lower()]
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
            for _pat in ("voice_messages/*.ogg","voice_messages/*.oga","video_messages/*.mp4","*.ogg","*.oga"):
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
                    # GPU ~5-10x faster than CPU
                    _tmin = max(1, int(_pre_total * _k * 0.05))
                    _tmax = max(1, int(_pre_total * _k * 0.3))
                    if log_cb: log_cb(f"Примерное время расшифровки: {_tmin}–{_tmax} мин (модель '{model}', GPU)")
                else:
                    if log_cb: log_cb(f"Примерное время расшифровки: {max(1,int(_pre_total*_k*0.5))}–{max(2,int(_pre_total*_k*2))} мин (модель '{model}', CPU)")
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
                        if _dev == 'CPU':
                            if log_cb: log_cb(f"  [DBG] torch {_tv} — GPU недоступен, используется CPU")
                except ImportError as _ie:
                    if log_cb: log_cb(f"  [DBG] torch import failed: {_ie}")
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

        for i, v in enumerate(valid):
            if _cancel_event and _cancel_event.is_set():
                if log_cb: log_cb("--- Отменено ---")
                return None
            msgs, c, src = load_chat_folder(v)
            all_messages.extend(msgs)
            if src: sources.extend(src if isinstance(src, list) else [src])
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
                    if log_cb: log_cb(f"Примерное время расшифровки: {max(1,int(_vn*_k2*0.5))}–{max(2,int(_vn*_k2*2))} мин (модель '{model}')")
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
            mp = m.get("media_path")
            if mp:
                p = Path(mp) if not isinstance(mp, Path) else mp
                if p.suffix.lower() in (".ogg", ".oga", ".mp4") and p.exists():
                    voice_paths_in_period.add(p.resolve())
        # Fallback: если у сообщений нет media_path — сканируем папки (без фильтра)
        if not voice_paths_in_period and not (date_from or date_to):
            for v in valid:
                for pat in ("voice_messages/*.ogg","voice_messages/*.oga",
                            "video_messages/*.mp4","*.ogg","*.oga"):
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

        if CFG.do_merge:
            all_messages = merge_consecutive(all_messages)

        if progress_cb: progress_cb(0.8)

        if not contact or contact.strip() in (".", "", ".."):
            contact = valid[0].name if valid[0].name not in (".", "..") else "чат"
        import re as _re
        safe = _re.sub(r'[/*?"<>|.]', "", contact.split()[0]).strip()
        if not safe:
            safe = "chat"

        ext = ".md" if output_format == "md" else ".txt"
        # Save file IN the selected folder (next to voice_messages etc.)
        output_dir = folder  # always save inside the top-level folder user picked
        out_path = output_dir / f"{safe}{ext}"

        result = format_output(all_messages, sources, contact, output_format)
        out_path.write_text(result, encoding="utf-8")

        if progress_cb: progress_cb(1.0)
        kb = out_path.stat().st_size // 1024
        if log_cb: log_cb(f"\n✓ Готово → {out_path} ({kb} КБ)")

        _elapsed=_time.time()-_start_time
        _m,_s=divmod(int(_elapsed),60)
        if log_cb: log_cb(f"  Время обработки: {_m} мин {_s} сек")

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


if __name__ == "__main__":
    main()
