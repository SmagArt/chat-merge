# BUILD_GUIDE.md — Merge Chat v2.0

## Что нужно для сборки Windows установщика

1. Windows машина с установленным [Inno Setup 6.x](https://jrsoftware.org/isdl.php)
2. Python 3.13 (для запуска prepare_installer.bat)
3. Файл `python-3.13.2-amd64.exe` в папке `python-installer\` (см. ниже)

---

## Пошаговая сборка Windows

### Шаг 1 — Скачать Python для бандлинга
Дважды кликни `prepare_installer.bat`.  
Он скачает `python-3.13.2-amd64.exe` в папку `python-installer\`.  
Без этого файла Inno Setup не соберёт установщик.

### Шаг 2 — Собрать установщик
Открой `installer_windows.iss` в Inno Setup → нажми Build → Compile.  
Готовый файл появится в папке `dist_installer\MergeChat_Setup_v2.0.exe`.

### Шаг 3 — Проверить на чистой системе
Удали папку `C:\Users\...\AppData\Local\Programs\Merge Chat` если есть.  
Запусти собранный .exe и проверь полный флоу установки.

---

## Что делает установщик Windows

1. Устанавливает Python 3.13.2 в `{app}\python\` (тихо, без лишних окон)
2. Запускает `setup_python.bat` — ставит все pip-пакеты
3. Если обнаружена NVIDIA видеокарта — автоматически ставит torch cu124 (CUDA 12.4)
4. Создаёт ярлык на рабочем столе и в меню Пуск
5. Регистрирует в "Программы и компоненты" для нормального удаления

При первом запуске `launcher_win.vbs` дополнительно проверяет CUDA и создаёт `cuda_ok.flag`.

---

## Сборка macOS DMG

### Требования
- Python 3.13 (или 3.12) с установленными зависимостями (`pip install -r requirements.txt`)
- Файл `merge_chat.icns` в корне проекта (уже включён в репо)

### Сборка
```bash
bash build_mac.command
```

Скрипт автоматически:
1. Собирает `dist/MergeChat.app` через PyInstaller
2. Создаёт staging-папку с симлинком на `/Applications`
3. Упаковывает в `dist_mac/MergeChat_v2.0.dmg`

Пользователь открывает DMG → перетаскивает MergeChat в папку Программы.  
При первом запуске: правый клик на иконке → Открыть (обход Gatekeeper).

### Иконка
Иконка для Mac — `merge_chat.icns` (не `.ico`!).  
Сгенерирована из `merge_chat_1024.png` с кропом 1024×1024 (оригинал 1036×1036 имеет белые поля).  
При пересоздании: кропать `src.crop((0, 0, 1024, 1024))` перед генерацией icns.

### Известные особенности macOS
- Apple Silicon MPS иногда даёт NaN при расшифровке Whisper — реализован автофallback на CPU
- Whisper medium на CPU (M4): ~10 мин на 69 файлов (без GPU-ускорения)

---

## Структура файлов в установленном приложении (Windows)

```
C:\Users\...\AppData\Local\Programs\Merge Chat\
├── python\                  <- bundled Python 3.13.2
├── merge_chat.py            <- основной скрипт
├── merge_chat_gui.py        <- GUI
├── launcher_win.vbs         <- запускалка (ярлык указывает сюда)
├── setup_python.bat         <- установщик пакетов (нужен для launcher)
├── merge_chat.ico           <- иконка Windows
├── merge_chat.icns          <- иконка macOS
├── merge_chat.log           <- лог обработки (создаётся при работе)
├── launch_log.txt           <- лог запуска (создаётся при запуске)
├── install_log.txt          <- лог установки пакетов
├── cuda_ok.flag             <- флаг: CUDA уже проверена, не проверять снова
└── merge_chat_config.json   <- настройки GUI (имя, модель, история папок)
```

---

## GitHub Release — шаблон

**Название:** `v2.0 — Merge Chat`

**Описание:**
```
## Merge Chat v2.0 — первый публичный релиз

### Что умеет
- Объединяет переписки Telegram (JSON/HTML) и ВКонтакте (HTML) в TXT/Markdown
- Расшифровывает голосовые через Whisper офлайн
- GPU-ускорение: NVIDIA CUDA, Apple Silicon MPS (с автофallback на CPU)

### Установка Windows
Скачай MergeChat_Setup_v2.0.exe — Python и все зависимости установятся автоматически.
При наличии NVIDIA видеокарты torch с CUDA установится автоматически.

### Установка macOS
Скачай MergeChat_v2.0.dmg, открой, перетащи MergeChat в Программы.
При первом запуске: правый клик → Открыть.
```

**Файлы релиза:**
- `MergeChat_Setup_v2.0.exe` — Windows установщик
- `MergeChat_v2.0.dmg` — macOS DMG
- `MergeChat-2.0-source.zip` — исходники

---

## Версионирование

Версия меняется в: `merge_chat_gui.py` (VERSION), `installer_windows.iss` (AppVersion), `README.md`, `BUILD_GUIDE.md`, `CLAUDE.md`

До публикации на GitHub версию не менять.

---

## Команды git для публикации

```bash
cd папка-проекта
git add .
git commit -m "v2.0 — initial public release"
git push origin main
```

Затем на GitHub: Releases → Draft new release → Tag: v2.0 → загрузить файлы.
