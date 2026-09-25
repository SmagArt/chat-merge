"""Пути Merge Chat — одно место для GUI, merge_chat.py и сборки.

CODE_DIR — где лежат скрипты. В сборке PyInstaller это _MEIPASS (только чтение).
DATA_DIR — куда программа пишет своё: конфиг, логи, модели Whisper, пакеты.
  • обычная установка (Python-скрипты, Windows): рядом со скриптами, в {app} —
    деинсталлятор уносит всё одной папкой;
  • замороженная сборка Windows: рядом с .exe;
  • замороженная сборка macOS: ~/Library/Application Support/MergeChat.
    Писать внутрь .app нельзя: бандл подписан, а в /Applications у обычного
    пользователя может не быть прав на запись.
"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    CODE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    CODE_DIR = Path(__file__).resolve().parent

if FROZEN and sys.platform == "darwin":
    DATA_DIR = Path.home() / "Library" / "Application Support" / "MergeChat"
elif FROZEN:
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    DATA_DIR = CODE_DIR

# base_packages — customtkinter, bs4, requests… (ставит setup_base.bat).
# local_packages — whisper + torch (ставит GUI, сносит «Удалить Whisper»).
# В замороженной сборке обе не нужны: всё внутри бандла.
BASE_PKGS = CODE_DIR / "base_packages"
LOCAL_PKGS = DATA_DIR / "local_packages"
WHISPER_MODELS = DATA_DIR / "whisper_models"
