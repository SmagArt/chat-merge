# CLAUDE.md — Merge Chat v2.2

## Контекст проекта
Python GUI-утилита: объединяет переписки Telegram (JSON/HTML) и ВКонтакте (HTML) в TXT или MD.
Расшифровывает голосовые через OpenAI Whisper офлайн.
GitHub: github.com/SmagArt/chat-merge

**Два сценария использования:**
- **Личные диалоги** — объединение переписки с конкретным человеком
- **Групповые чаты / форумы** — анализ большого числа участников, потом скармливать Клоду по кускам

---

## Версии

| Версия | Статус | GitHub |
|--------|--------|--------|
| v2.1   | публичный релиз | ✓ |
| v2.1.1 | bugfix: DnD fix | ✓ released |
| v2.2   | фичи для анализа | ✗ **только локально** |

### v2.1.1 — что исправлено (на GitHub)
- DnD: `drop_target_register` регистрировался только на корневом окне. CTk дочерние виджеты перехватывали события. Фикс: рекурсивная регистрация на всех дочерних виджетах (`_register_dnd_recursive`).

### v2.2 — новые фичи (локально, не на GitHub)
- **Метки времени** (`show_ts`): переключатель вкл/выкл времени сообщений (HH:MM:SS). Дневные/месячные заголовки остаются всегда. Для рабочих переписок и форумов — удобно выключить.
- **Предупреждение про объединение**: при включении "Объединять подряд идущие" — жёлтый тост на 4 секунды "только для диалогов, не для групп".
- **Разбивка на файлы** (`split_mode: none/month/year`): трёхстатусная кнопка. Один файл → по месяцам (`Чат_2026-01.md`) → по годам (`Чат_2026.md`). Для форумов + последующего анализа Клодом по кускам.

### Что НЕ тестировалось
- MergeChat_Setup_v2.1.1.exe на чистой машине без Python
- v2.2 фичи на реальном большом групповом чате

### Протестировано (март 2026)
- macOS (Mac mini M4): сборка .app + DMG через build_mac.command ✓
- Apple Silicon MPS: NaN fallback на CPU работает, 69 файлов за ~11 мин ✓
- merge_chat.icns: иконка корректная (кроп 1024×1024 из PNG)
- DnD fix: перетаскивание папки работает (v2.1.1) ✓
- v2.2 GUI: timestamps toggle, split mode — запускается без ошибок ✓
- v2.2 macOS DMG собран 17 марта 2026: dist_mac/MergeChat_v2.2.dmg ✓ (установлен в /Applications)

### Известные ограничения
- Голосовые из ВКонтакте не расшифровываются (VK не включает аудио в экспорт)
- Python 3.14 НЕ поддерживается PyTorch/Whisper
- Apple Silicon MPS: Whisper medium иногда даёт NaN → автофallback на CPU (реализовано в v2.0)
- Имя файла = первое слово контакта (`contact.split()[0]`) — для групп может быть "Чат"

### Для релиза v2.2 нужно
- Протестировать split_mode на реальном форумном чате
- Обновить README (новые опции)
- Собрать MergeChat_Setup_v2.2.exe через Inno Setup
- Mac DMG пересобрать на Mac

---

## Файлы проекта

| Файл | Назначение |
|------|-----------|
| `merge_chat.py` | Основной скрипт + process_folder() API |
| `merge_chat_gui.py` | GUI v2.1.1 |
| `installer_windows.iss` | Inno Setup: bundled Python 3.13.2 |
| `prepare_installer.bat` | Скачивает python-3.13.2-amd64.exe для Inno Setup |
| `setup_python.bat` | pip-пакеты + CUDA torch при установке |
| `launcher_win.vbs` | Запуск без консоли; CUDA проверка; cuda_ok.flag |
| `install_windows.bat` | Установка для пользователей с Python |
| `build_exe.bat` | Сборка PyInstaller .exe (CPU only) |
| `build_mac.command` | Сборка .app + DMG (Mac) |
| `merge_chat.ico` | Иконка Windows |
| `merge_chat_1024.png` | Исходник иконки |
| `requirements.txt` | Зависимости pip |
| `README.md` | Документация пользователя |
| `BUILD_GUIDE.md` | Инструкции сборки + GitHub Release шаблон |
| `CLAUDE.md` | Этот файл |
| `CLAUDE_GLOBAL.md` | Общие правила для всех Python-проектов Артёма |

---

## ЖЕЛЕЗНОЕ ПРАВИЛО — НИКАКИХ терминальных окон

**Это правило не обсуждается. Нарушение = баг.**

Все subprocess вызовы на Windows ОБЯЗАНЫ иметь `creationflags=0x08000000` (CREATE_NO_WINDOW).

```python
# Python:
subprocess.run([...], creationflags=0x08000000)
subprocess.Popen([...], creationflags=0x08000000)
```

```vbs
' VBS — запуск с окном style=0:
WshShell.Run "команда", 0, True

' Для .bat файлов:
WshShell.Run "powershell -WindowStyle Hidden -Command ""Start-Process cmd -ArgumentList '/c bat' -Wait -WindowStyle Hidden"""
```

Whisper внутри вызывает ffmpeg — патчим глобально перед transcribe:
```python
import subprocess as _subp
_orig_run = _subp.run
def _run_hidden(*a, **kw):
    kw.setdefault("creationflags", 0x08000000)
    return _orig_run(*a, **kw)
_subp.run = _run_hidden
# То же для _subp.Popen
```

---

## CUDA — итоговая схема

- **cu121** — Python 3.8–3.12 (не использовать с Python 3.13!)
- **cu124** — Python 3.9–3.13 ✓ (наш вариант)

**Двухуровневая установка:**

1. `setup_python.bat` (при установке приложения):
   - `wmic` проверяет наличие NVIDIA
   - Если есть — ставит `torch --index-url .../cu124 --force-reinstall`

2. `launcher_win.vbs` (первый запуск):
   - Проверяет `torch.cuda.is_available()`
   - Если нет — проверяет NVIDIA через PowerShell, доустанавливает
   - Создаёт `cuda_ok.flag` → последующие запуски мгновенные

**Итог: RTX 3060 Ti — 15 файлов medium Whisper за 3 мин вместо ~30.**

---

## GPU — порядок определения
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

---

## Критические правила GUI (CustomTkinter)

### importlib.reload() — НЕЛЬЗЯ (I/O on closed file)
```python
# Сброс вручную:
_mc._whisper_cache = None
_mc._transcribe_cache.clear()
_mc._voice_counter["done"] = 0
_mc._voice_counter["total"] = 0
```

### Размер окна — только фиксированный
```python
W, H = 820, 1040
self.update_idletasks()
self.geometry(f"{W}x{H}+{(sw-W)//2}+{max(20,(sh-H)//2-20)}")
```

---

## Inno Setup — правила

- `Compression=lzma` (НЕ lzma2/ultra64)
- В `[Tasks]` нет `Flags: checked`
- Embedded Python НЕ подходит для GUI (нет tkinter!)
- Bundled = полный `python-3.13.2-amd64.exe` установленный тихо в `{app}\python`
- Embeddable Python: только `python.exe` (нет `pythonw.exe`!)

---

## Bat-файлы — критические правила

- НИКОГДА кириллица в теле bat (только в значениях `set`)
- Кодировка bat — CRLF при генерации на Linux/Mac
- PyInstaller в bat — только однострочник
- Python поиск — 4-уровневый с фильтром WindowsApps

---

## Версионирование

v2.2 — текущая локальная версия, не опубликована.
v2.1.1 — последний публичный релиз на GitHub.
При изменении версии обновлять: `merge_chat_gui.py` (VERSION), `installer_windows.iss` (AppVersion), `README.md`, `BUILD_GUIDE.md`, `CLAUDE.md`.

## Известные технические долги

- Папка `chat-merge/chat-merge/` — дубликат репо внутри репо, удалить вручную
- `build_exe.bat` — отсутствует (был удалён), Windows сборка только через Inno Setup
- `process_folder()` возвращает `Optional[str]` — при split_mode возвращает путь к последнему файлу, не к папке (GUI обходит это через фоллбек на folder_var)

## Рекомендации по использованию для анализа форумов

- **Объединение** — ВЫКЛ (теряется кто что сказал)
- **Метки времени** — по вкусу (выкл = чище для Claude)
- **Разбивка** — по месяцам (каждый кусок = отдельная сессия с Claude)
- **Формат** — TXT чуть лучше MD для Claude (меньше токенов на разметку)
- **Рабочий процесс**: кусок → Claude с одним промптом → сохранить выжимку → следующий кусок → финальный синтез
- Промпт для анализа: `Projects/prompt-engineering/tg_chat_tools.md`
