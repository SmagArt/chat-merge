# CLAUDE.md — Merge Chat v2.7

## Контекст
Python GUI: объединяет переписки **Telegram** (JSON/HTML), **VK** (HTML-архив + API-JSON через `tools/vk_fetch_history.py`), **Instagram** (JSON), **WhatsApp** (TXT) в TXT/MD. Расшифровывает голосовые через OpenAI Whisper офлайн. GPU-ускорение: NVIDIA CUDA, Apple Silicon MPS.
GitHub: github.com/SmagArt/chat-merge

**Сценарии:**
- Личные диалоги (объединение нескольких мессенджеров на одного контакта).
- Групповые чаты / форумы (для последующего анализа Клодом по кускам).
- Только-аудио режим (один файл или папка с голосовыми).

---

## Версии

| Версия | Статус |
|--------|--------|
| v2.4   | публичный релиз на GitHub |
| v2.5   | собран локально 26.04.2026 (UI lift, имена в выводе, пресеты, изоляция Whisper) |
| v2.6   | VK API-JSON (`vk_export`) внесён в установщик; пересланные разворачиваются |
| **v2.7** | собран 11.06.2026: кнопка «⬇ Выгрузить из ВК» в GUI + `vk_fetch.bat` + фикс высоты окна/лога; имя установщика без `_admin`. **Текущая** |
| v3.0   | backlog: миграция UI на PySide6 (см. `memory/project_chat_merge_qt_migration.md`) |

**Установщик один** (`installer_windows.iss`, bundled Python, права администратора). Прежнее
деление admin/noadmin убрано — `_noadmin.iss` и `_admin`-суффикс в имени упразднены.

---

## Фиксы 2026-05-16 (в составе v2.5)

Сессия багфиксов перед публикацией:
- **Обрезался низ окна** — кнопка «Запустить» уезжала под таскбар. Геометрия теперь
  считается от рабочей области (`_work_area()` через `SPI_GETWORKAREA`), нижняя панель
  пакуется `side="bottom"` ДО секции 3 — при нехватке высоты ужимается лог, а не кнопки.
- **«О программе» — пустота, потом не открывалось.** Падало с `ValueError`: CustomTkinter
  не принимает `width/height` в `.place()`, только в конструкторе `CTkFrame`.
- **Whisper «скачан и не скачан одновременно»** — детект и worker переведены на изоляцию
  (см. «Изоляция Whisper»).
- **Лог не копировался** — Tk-буфер очищался при выходе из проги. `_copy_log` теперь
  дублирует в системный буфер через `Set-Clipboard` (UTF-8 temp-файл — `clip.exe` ломает
  кириллицу).
- **Статус моделей Whisper** — под селектором tiny…large видно, какая модель скачана
  (зелёная рамка + текст), какая докачается и сколько весит.

---

## Файлы проекта (актуальный состав)

| Файл | Назначение |
|------|-----------|
| `merge_chat.py` | Логика: парсеры, merge, Whisper, `process_folder()` / `process_audio()` |
| `merge_chat_gui.py` | GUI на CustomTkinter |
| `installer_windows.iss` | Inno Setup (bundled Python 3.13.2, ставит Python в `{app}\python`; требует прав администратора) |
| `setup_base.bat` | Установка базовых pip-пакетов после Inno |
| `setup_whisper.bat` | Ручная установка Whisper + torch в `{app}\local_packages\` (legacy-скрипт, не вызывается автоматически; основной путь — кнопка «Установить» в окне «О программе») |
| `launcher_win.vbs` | Запуск без консоли + первичная проверка пакетов |
| `tools/vk_fetch_history.py` | Выгрузка истории ВК через VK API (`--peer`, `--list`, `--account`); источник для merge (JSON с пересланными) |
| `vk_fetch.bat` | Быстрая выгрузка ВК двойным кликом (способ B; только в dev-папке, нужен `py` на PATH) |
| `build_mac.command` | Сборка `.app` + DMG через PyInstaller |
| `merge_chat.ico` / `merge_chat.icns` / `merge_chat_1024.png` | Иконки |
| `requirements.txt` | Зависимости |
| `python-installer/python-3.13.2-amd64.exe` | Бандл Python для Inno (скачать вручную при сборке на новой машине, см. ниже) |
| `dist_installer/MergeChat_Setup_v2.7.exe` | Готовый Windows-инсталлятор |
| `README.md` | Документация пользователя |

---

## Сборка

### Windows (MergeChat_Setup_v2.7.exe)
1. На новой машине — один раз скачать Python-бандл:
   ```
   powershell -Command "Invoke-WebRequest 'https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe' -OutFile 'python-installer\python-3.13.2-amd64.exe'"
   ```
2. Открыть `installer_windows.iss` в [Inno Setup 6](https://jrsoftware.org/isdl.php) → Build → Compile.
   (или из CLI: `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer_windows.iss`)
3. Готовый файл — в `dist_installer/`.

### macOS (MergeChat_v2.5.dmg)
```bash
bash build_mac.command
```
Соберёт `.app` через PyInstaller + DMG со ссылкой на `/Applications`.

### Версионирование
При смене версии правим: `merge_chat_gui.py` (`VERSION`), `installer_windows.iss` (`AppVersion`), `build_mac.command` (имя DMG), `README.md`, `CLAUDE.md`.

---

## Архитектурные решения v2.5

### Изоляция Whisper — пакеты и модели внутри `{app}`
Правило изоляции служебных файлов (`memory/feedback_isolate_app_files.md`): прога владеет
своим Whisper целиком, системный/пользовательский Python не трогает.
- **Пакеты** whisper+torch → `{app}\local_packages\` (`pip install --target … --upgrade`).
- **Модели** (.pt) → `{app}\whisper_models\` через `whisper.load_model(..., download_root=…)`.
  Раньше качались в общий `~/.cache/whisper` и переживали удаление проги.
- **Детект** `_whisper_available()` проверяет ТОЛЬКО `local_packages` (каталоги `whisper`
  И `torch`). НЕ `find_spec` — он находит whisper в чужом Python (в т.ч. в общем
  user-site `%APPDATA%\Python`, общий для всех Python 3.13), из-за чего после
  переустановки баннер «не установлен» не показывался.
- **Worker** (`merge_chat.py`) импортирует whisper только если он в `local_packages`
  (флаг `_whisper_owned`); системный не подхватывает — иначе расшифровка «работает»,
  но служебные файлы вне `{app}` и удаление проги их не вычистит.
- **Деинсталляция:** `[UninstallDelete] {app}` уносит `local_packages` + `whisper_models`.
  Кнопка «Удалить Whisper» в GUI дополнительно чистит legacy `~/.cache/whisper`.
- Общий `~/.cache/whisper` тихий деинсталлятор НЕ трогает (может принадлежать voice-diarizer).
- Цена изоляции: torch (~2.5 ГБ) и модели дублируются между прогами Артёма — осознанная
  плата, платит только разработчик с несколькими прогами, конечный юзер с одной — нет.

### Whisper под `pythonw.exe` — `verbose=None`
`pythonw.exe` запускается без консоли → `sys.stdout = None`. У Whisper `transcribe(verbose=False)` оставляет tqdm активным (`disable=verbose is not False`) → пишет в None → `AttributeError`. Симптом: «(пусто — Whisper не вернул текст)». Фикс: `verbose=None` (полностью отключает tqdm). См. `merge_chat.py:393`.

### WM_DELETE_WINDOW → `os._exit(0)`
Worker-thread с torch/CUDA-моделью держит память, daemon не помогает. После `self.destroy()` процесс висит → следующий запуск падает на `_acquire_lock()`. Фикс: hard-kill после `destroy()`.

### Все диалоги — оверлеи поверх главного окна
Helper `_overlay(title, w, h, backdrop=False)` вместо `CTkToplevel`: карточка
фиксированного размера по центру главного окна, Esc/крестик закрывают. Так выглядит
как одно цельное приложение, а не «куча окон».
- `backdrop=False` (дефолт) — карточка кладётся поверх видимого UI без затемнения.
- `backdrop=True` затемняет всё окно фреймом SURFACE. Раньше был дефолтом — маленькая
  карточка в огромном ровном тёмном поле выглядела как «сломанное пустое окно».
- ВАЖНО: `width/height` оверлею-фрейму передаются в конструктор `CTkFrame`, НЕ в
  `.place()` — CustomTkinter кидает `ValueError` на `place(width=…, height=…)`.

### Имена в выводе — `my_display` + `peer_display`
Поле «Твоё имя» — список через запятую (алиасы в разных мессенджерах). Display name self = первый элемент или явный `my_display`. Если `peer_display` задан — все НЕ-self авторы переименовываются (для 1-на-1 переписок из нескольких мессенджеров — все имена сольются в одно).

В v2.5 поле одно, доп. поля `my_display`/`peer_display` — за чекбоксом «Дополнительно: разные имена для вывода».

### Авто-determine «себя» в Instagram/WhatsApp
Раньше: совпасть с никнеймом вручную, иначе твои сообщения подписывались именем собеседника. Теперь — из метаданных экспорта (IG: `participants[0]`, WA: первая «своя» строка по эвристике).

### Пресеты — три быстрые кнопки
- Диалог: `fmt_md=False, show_ts=True, show_src=False, split_mode=none`
- Группа: `fmt_md=False, show_ts=True, show_src=True, split_mode=none`
- Канал: `fmt_md=True, show_ts=True, show_src=True, split_mode=month`

### Релиз памяти после обработки
После `process_folder` / `process_audio` модель Whisper выгружается, `gc.collect()` + `torch.cuda.empty_cache()` — RAM освобождается ~3–4 ГБ.

### Двухэтапная отмена
1-й клик «Отмена» — дожать текущий файл, остальные пропустить.
2-й клик — мгновенный выход (`os._exit(1)`).

### UI: окно resizable
В v2.5 окно тянется (`resizable(True, True)`, `minsize(900, 720)`), блок «Процесс»/лог растягивается под доступную высоту. На 1920×1080 умещается полностью.

---

## ЖЕЛЕЗНЫЕ правила (этот проект)

### НИКАКИХ терминальных окон
Все subprocess на Windows — с `creationflags=0x08000000` (CREATE_NO_WINDOW), КРОМЕ запуска `explorer.exe` (он сам GUI, флаг ему мешает — открыто `_open_output()` через `subprocess.Popen` без флагов или `os.startfile`).

```python
# Whisper внутри дёргает ffmpeg — патчим subprocess глобально перед transcribe:
import subprocess as _subp
_orig_run = _subp.run
def _run_hidden(*a, **kw):
    kw.setdefault("creationflags", 0x08000000)
    return _orig_run(*a, **kw)
_subp.run = _run_hidden
# Аналогично для _subp.Popen
```

### CUDA — cu124 для Python 3.13
- cu121 — Python 3.8–3.12 (не использовать с 3.13!)
- cu124 — Python 3.9–3.13 ✓
- cu128 — есть, но в этом проекте не нужен (cu124 хватает)

`setup_whisper.bat` детектит NVIDIA через `Get-WmiObject Win32_VideoController` → ставит `torch --index-url cu124` или CPU torch.

### Inno Setup
- `Compression=lzma` (не lzma2/ultra64)
- В `[Tasks]` нет `Flags: checked`
- Bundled Python = ПОЛНЫЙ `python-3.13.2-amd64.exe` тихо в `{app}\python` (embeddable не подходит — нет `pythonw.exe` и tkinter)
- `[InstallDelete]` чистит старые `{app}\python\Lib\site-packages\torch*|whisper*` (на случай старой установки до v2.5)
- `[UninstallDelete] {app}` — уносит `local_packages` + `whisper_models` + конфиг/логи при деинсталляции (всё служебное лежит внутри `{app}`)

### Bat
- `setlocal EnableDelayedExpansion` всегда
- `!ERRORLEVEL!` внутри блоков, никогда `%ERRORLEVEL%`
- Никакой кириллицы в теле .bat (только в значениях `set`)
- Поиск Python — 4 уровня с фильтром `WindowsApps`

---

## Источники: VK через API (обход долгого экспорта)

`tools/vk_fetch_history.py` тянет историю диалогов ВК напрямую через VK API в JSON —
**в обход официальной выгрузки** (Settings → данные, ждать часами). Перенесено из date-agent
05.06.2026 (там это качало все диалоги в автозапуске и срало 400+ МБ в iCloud — здесь как
ручной инструмент).

- Токен: `VK_TOKEN` в окружении / `tools/.env` / `--token`. Получить на vkhost.github.io
  (Kate Mobile, права `messages,offline`).
- `py tools/vk_fetch_history.py --list` — список диалогов с peer_id (узнать ID нужного).
- `py tools/vk_fetch_history.py --peer ID` — один диалог; без аргументов — все.
- Результат: `tools/vk_export/<peer_id>.json` (в .gitignore вместе с токеном). Внутри
  `messages[]` (сырые объекты VK API) + `names{}` (id→имя для атрибуции в беседах).
- Парсер `load_vk_json()` в merge_chat.py читает этот JSON напрямую — папку `vk_export/`
  скармливаешь проге как обычно. Детектится по ключу `peer_id` ДО Telegram-JSON (у обоих есть
  `messages`), источник в выводе — `[VK]` (общий с HTML-путём). Оба пути (HTML и API-JSON)
  поддерживаются параллельно.
- Голосовые через API не приходят (как и в HTML-экспорте) → метятся `[🎤 Голосовое — недоступно]`.

---

## Известные ограничения

- Голосовые из VK не расшифровываются (VK не включает аудио в экспорт).
- Python 3.14 — не поддерживается PyTorch/Whisper.
- Apple Silicon MPS: Whisper medium иногда выдаёт NaN → автофолбэк на CPU.
- Имя файла = `peer_display` если задан, иначе первое слово `contact.split()[0]` — для групп может быть «Чат».
- В Диспетчере задач прога видна как `pythonw.exe` — фиксится только переходом на PyInstaller (планируется вместе с миграцией на Qt v3.0).

---

## Pending

- [ ] Mac DMG v2.7 пересобрать на Mac Mini M4 (`bash build_mac.command`)
- [ ] GitHub Release v2.7 (Windows .exe + Mac .dmg + source)
- [ ] (backlog v3.0) Миграция UI на PySide6 — см. `memory/project_chat_merge_qt_migration.md`. PyInstaller заодно решит «pythonw.exe в Диспетчере задач».

---

## Тестовый чек-лист после пересборки

1. Деинсталляция → пересборка Inno → установка.
2. Окно тянется, минимум 900×720, на 1920×1080 умещается полностью.
3. «Справка» в шапке → оверлей со скроллом.
4. Hover на любой `?` → tooltip справа от виджета, 2-4 строки, без реальных имён.
5. «Выбрать…» → оверлей по центру (не отдельное окно ОС).
6. Жёлтый банннер «Установить Whisper» → оверлей установки тоже встроен.
7. Пресеты «Диалог»/«Группа»/«Канал» переключают связку настроек.
8. «Дополнительно: разные имена для вывода» — раскрывает поля `my_display` / `peer_display`, скрытие очищает значения.
9. «О программе» → открывается карточкой без затемнения, ссылка на GitHub кликабельна.
10. Чисто-аудио: `Устройство расшифровки: NVIDIA …` + прогрессбар видны.
11. Закрытие окна → `python.exe` / `pythonw.exe` не висит в Диспетчере.
12. После обработки RAM освобождается.
13. «Открыть папку» подсвечивает итоговый файл в проводнике.
14. Селектор моделей: у скачанных — зелёная рамка, под ним статус выбранной модели.
15. «Скопировать лог» → текст вставляется в другую прогу даже после закрытия MergeChat.
16. Удаление проги через «Программы и компоненты» → папка `{app}` вычищена целиком.
