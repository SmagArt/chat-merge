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

"$PYTHON" -m PyInstaller \
    --noconfirm --clean --onedir --windowed \
    --name "MergeChat" \
    $ICON_ARG \
    --add-data "merge_chat.py:." \
    --add-data "merge_chat.ico:." \
    --collect-all whisper \
    --collect-all customtkinter \
    --collect-all imageio_ffmpeg \
    --hidden-import whisper.audio \
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

hdiutil create \
    -volname "Merge Chat" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    dist_mac/MergeChat_v2.0.dmg 2>&1 | tee -a "$LOG"

rm -rf "$STAGING"

if [ -f "dist_mac/MergeChat_v2.0.dmg" ]; then
    echo ""
    echo "[OK] dist_mac/MergeChat_v2.0.dmg ready" | tee -a "$LOG"
else
    echo "[X] DMG creation failed" | tee -a "$LOG"
fi
read -rp "Enter..."
