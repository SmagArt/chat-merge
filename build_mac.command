#!/bin/bash
cd "$(dirname "$0")"
LOG="$(pwd)/build_log.txt"
echo "Build: $(date)" > "$LOG"

PYTHON=""
for p in \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /opt/homebrew/bin/python3 python3; do
    command -v "$p" &>/dev/null || [ -x "$p" ] || continue
    PYTHON="$p"; break
done
[ -z "$PYTHON" ] && { echo "[X] Python not found"; read -rp "Enter..."; exit 1; }
echo "[OK] $("$PYTHON" --version)" | tee -a "$LOG"

"$PYTHON" -c "import PyInstaller" &>/dev/null 2>&1 || \
    "$PYTHON" -m pip install pyinstaller -q --break-system-packages

ICON_ARG=""
[ -f "merge_chat.icns" ] && ICON_ARG="--icon merge_chat.icns"

# Версия — из merge_chat_gui.py (VERSION = "X.Y.Z"), одно место на всё.
# Раньше имя DMG было зашито как v2.5 и не менялось с версиями.
VERSION=$(sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p' merge_chat_gui.py | head -1)
[ -z "$VERSION" ] && { echo "[X] VERSION не найден в merge_chat_gui.py"; read -rp "Enter..."; exit 1; }
DMG="dist_mac/MergeChat_v${VERSION}.dmg"
echo "[OK] version $VERSION" | tee -a "$LOG"

# merge_chat.py лежит в бандле ДАННЫМИ и импортируется на лету — PyInstaller
# не видит его импортов. bs4/requests/certifi перечисляем явно, иначе сборка
# падала бы на первой же обработке («No module named bs4»).
# tools/vk_fetch_history.py — внутрь .app: кнопка «Выгрузить из ВК» грузит его
# модулем (в сборке нет отдельного python для запуска скрипта).
"$PYTHON" -m PyInstaller \
    --noconfirm --clean --onedir --windowed \
    --name "MergeChat" \
    $ICON_ARG \
    --add-data "merge_chat.py:." \
    --add-data "merge_chat.ico:." \
    --add-data "tools/vk_fetch_history.py:tools" \
    --collect-all whisper \
    --collect-all customtkinter \
    --collect-all imageio_ffmpeg \
    --collect-all bs4 \
    --collect-data certifi \
    --hidden-import whisper.audio \
    --hidden-import requests \
    --hidden-import certifi \
    --hidden-import app_paths \
    merge_chat_gui.py 2>&1 | tee -a "$LOG"

if [ ! -d "dist/MergeChat.app" ]; then
    echo "[X] Build failed — see $LOG"
    read -rp "Enter..."; exit 1
fi
echo "[OK] dist/MergeChat.app built" | tee -a "$LOG"

# Build DMG with Applications symlink (drag-and-drop install)
mkdir -p dist_mac
STAGING="$(pwd)/dist_mac_staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -r dist/MergeChat.app "$STAGING/"
ln -s /Applications "$STAGING/Applications"
# Скрипт выгрузки ВК через API (запускать своим python3: pip install requests; см. README).
# Только сам файл — без tools/.env и tools/vk_export (личные данные).
mkdir -p "$STAGING/tools"
cp tools/vk_fetch_history.py "$STAGING/tools/" 2>/dev/null || true

hdiutil create \
    -volname "Merge Chat" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$DMG" 2>&1 | tee -a "$LOG"

rm -rf "$STAGING"

if [ -f "$DMG" ]; then
    echo ""
    echo "[OK] $DMG ready" | tee -a "$LOG"
else
    echo "[X] DMG creation failed" | tee -a "$LOG"
fi
read -rp "Enter..."
