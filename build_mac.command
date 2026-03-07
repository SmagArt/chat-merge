#!/bin/bash
# Merge Chat v2.0 — build .app via PyInstaller
# Produces: dist/MergeChat.app
# For DMG: drag dist/MergeChat.app to Disk Utility and create image manually,
# or use: hdiutil create -volname MergeChat -srcfolder dist/MergeChat.app -ov -format UDZO MergeChat_v2.0.dmg
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

"$PYTHON" -m PyInstaller \
    --noconfirm --clean --onedir --windowed \
    --name "MergeChat" \
    --add-data "merge_chat.py:." \
    --add-data "merge_chat.ico:." \
    --collect-all whisper \
    --collect-all customtkinter \
    --collect-all imageio_ffmpeg \
    --hidden-import whisper.audio \
    merge_chat_gui.py 2>&1 | tee -a "$LOG"

echo ""
if [ -d "dist/MergeChat.app" ]; then
    echo "[OK] dist/MergeChat.app" | tee -a "$LOG"
    echo ""
    echo "To create DMG:"
    echo "  hdiutil create -volname MergeChat -srcfolder dist/MergeChat.app -ov -format UDZO dist_mac/MergeChat_v2.0.dmg"
else
    echo "[X] Build failed — see $LOG"
fi
read -rp "Enter..."
