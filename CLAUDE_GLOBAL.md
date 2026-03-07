# CLAUDE_GLOBAL.md — Общие правила разработки Python-проектов Артёма

Этот файл — в инструкциях каждого Python-проекта.
Содержит правила выработанные на практике.

---

## Про автора

Артём — не программист, контент-менеджер.
- Простой язык, без жаргона
- Объяснять ЗАЧЕМ, не только ЧТО делать
- Числа и шаги — конкретно
- Неочевидное — разжевать

При глобальных изменениях — скидывать все изменённые исходники сразу.
Если собирается zip-архив — без вложенных папок внутри.

---

## Стек

Python 3.10–3.13 (рекомендуется 3.13).
Python 3.14 — не поддерживается PyTorch.

Частые зависимости:
- beautifulsoup4 — парсинг HTML
- customtkinter — GUI
- openai-whisper — расшифровка аудио
- imageio-ffmpeg — ffmpeg без системной установки
- tkinterdnd2 — drag & drop в tkinter

---

## GPU — всегда встраивать если возможно

Порядок определения устройства:
```python
import torch
if torch.cuda.is_available():
    device = "cuda"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device = "mps"
else:
    try:
        import torch_directml
        device = torch_directml.device()
    except ImportError:
        device = "cpu"
```

Если NVIDIA найден, но torch CPU-only — автоматически переустанавливать:
```python
import subprocess, sys, shutil
if torch.__version__.endswith('+cpu') and shutil.which('nvidia-smi'):
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'torch',
                    '--index-url', 'https://download.pytorch.org/whl/cu121',
                    '--force-reinstall', '-q'])
    # Сообщить пользователю перезапустить программу
```

Apple Silicon: НИКОГДА не ставить torch с `--index-url .../whl/cpu` — это x86_64, краш на arm64.
```bash
pip install torch   # PyPI — нативный arm64, включает MPS
```

CUDA torch:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
```
`--force-reinstall` обязателен — иначе CPU-torch не заменится.

---

## Windows bat-файлы — критические правила

### НИКОГДА кириллица в теле bat (кроме значений переменных)
```batch
REM НЕЛЬЗЯ — комментарий по-русски
НЕЛЬЗЯ: echo Загружаю модель...

МОЖНО: set NAME=Артём
МОЖНО: REM English comment only
```
Причина: chcp 65001 + кириллица в теле bat = сдвиг байтовых границ строк = ошибки.

### Кодировка bat — ТОЛЬКО CRLF при генерации на Linux/Mac
```python
content = content.replace('\r\n', '\n').replace('\n', '\r\n')
with open(path, 'wb') as f:
    f.write(content.encode('utf-8'))
```

### PowerShell/PyInstaller в bat — только однострочник
```batch
REM ПРАВИЛЬНО:
python -m PyInstaller --noconfirm --name "App" script.py
```

### Поиск Python — всегда 4 уровня с фильтром WindowsApps
```batch
set "PYTHON="
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" set "PYTHON=..."
if "!PYTHON!"=="" if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" set "PYTHON=..."
if "!PYTHON!"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 if "!PYTHON!"=="" set "PYTHON=%%i"
    )
)
```
WindowsApps — заглушка Microsoft Store, НЕ настоящий Python.

---

## Inno Setup — правила (Windows установщик)

- Compression=lzma (НЕ lzma2/ultra64 — не поддерживается в 6.7.x)
- В [Tasks] нет флага Flags: checked (не существует в этой секции)
- Вместо [Code] с Pascal — через [Run] секцию
- Embedded Python НЕ подходит для GUI — не содержит tkinter!
- Правильно: бандлить ПОЛНЫЙ Python installer (python-3.13.2-amd64.exe, ~26 МБ)
  ```
  ; В [Files]:
  Source: "python-installer\python-3.13.2-amd64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
  ; В [Run]:
  Filename: "{tmp}\python-3.13.2-amd64.exe"; Parameters: "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 TargetDir={app}\python"; Flags: waituntilterminated
  ```

---

## GUI CustomTkinter — правила

### importlib.reload() — НЕЛЬЗЯ (падает "I/O operation on closed file")
```python
# ПРАВИЛЬНО — сброс состояния вручную:
module._cache = None
module._counter["done"] = 0
module._data.clear()
```

### Размер окна — только фиксированный
```python
W, H = 820, 1040
self.update_idletasks()
sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
self.geometry(f"{W}x{H}+{(sw-W)//2}+{max(20,(sh-H)//2-20)}")
```

---

## Принцип установки — пользователь ничего не делает вручную

ЖЕЛЕЗНОЕ ПРАВИЛО: пользователь не вводит команды в терминал/CMD.
Всё через двойной клик: установщик → GUI → готово.

НЕЛЬЗЯ писать в инструкциях:
- "запусти в CMD..."
- "введи в терминале..."
- "выполни pip install..."

МОЖНО: "дважды кликни MergeChat_Setup.exe"

---

## Логирование — всегда включено в продакшне

Минимальный набор логов:
- `launch_log.txt` — лог запуска (launcher/VBS)
- `app_name.log` — лог работы приложения
- `install_log.txt` — лог установки

Формат:
```python
import logging
logging.basicConfig(
    filename="app.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8", force=True
)
```

---

## GitHub релизы

Что публиковать в Releases (НЕ в репозиторий):
- `AppName_Setup_vX.Y.exe` — Windows установщик
- `AppName_vX.Y.dmg` — macOS DMG
- `AppName-X.Y-source.zip` — исходники

Версионирование:
- v1.0 — первый публичный релиз
- Увеличивать только при публикации на GitHub
- До публикации — можно держать рабочую версию

Название релиза: `v2.0 — App Name`
