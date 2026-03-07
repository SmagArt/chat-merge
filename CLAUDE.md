# CLAUDE.md — Merge Chat v2.0

## Контекст проекта
Python GUI-утилита: объединяет переписки Telegram (JSON/HTML) и ВКонтакте (HTML) в TXT или MD.
Расшифровывает голосовые через OpenAI Whisper офлайн.
GitHub: github.com/SmagArt/chat-merge (v2.0 — первый публичный релиз)

---

## Текущее состояние (март 2026, v2.0) — ФИНАЛЬНОЕ

### Что РАБОТАЕТ (проверено на реальных данных)
- Парсинг TG JSON, TG HTML, VK HTML
- Объединение нескольких папок одного контакта
- Расшифровка голосовых через Whisper
- **GPU: RTX 3060 Ti — 15 файлов medium за 3 мин (CPU было бы ~30 мин)**
- GUI v2.0: выбор папки, drag & drop, история 5 папок, фильтр по датам
- Форматы вывода: TXT и Markdown
- Прогресс-бар, кнопка копирования лога
- Оценка времени с учётом GPU/CPU (реалистичная)
- Блокировка второго экземпляра (fcntl/msvcrt)
- Кеш расшифровок, дедупликация голосовых
- Логирование в merge_chat.log
- FP16 warning подавлен
- Кнопка Отмена — мгновенная (daemon thread + cancel_event)
- Кнопка "Открыть папку" активна даже после отмены если файл создан
- **Установщик: Inno Setup + bundled Python 3.13.2 + автоустановка CUDA**
- **launcher_win.vbs: ноль терминальных окон, cuda_ok.flag для однократной проверки**
- **subprocess CREATE_NO_WINDOW везде, включая внутренние вызовы whisper/ffmpeg**

### Что НЕ тестировалось
- MergeChat_Setup_v2.0.exe на чистой машине без Python
- DMG на Mac (build_mac.command)

### Известные ограничения
- Голосовые из ВКонтакте не расшифровываются (VK не включает аудио в экспорт)
- Python 3.14 НЕ поддерживается PyTorch/Whisper

---

## Файлы проекта

| Файл | Назначение |
|------|-----------|
| `merge_chat.py` | Основной скрипт + process_folder() API |
| `merge_chat_gui.py` | GUI v2.0 |
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

v2.0 — первый публичный релиз на GitHub.
При изменении версии обновлять: `merge_chat_gui.py` (VERSION), `installer_windows.iss` (AppVersion), `README.md`, `BUILD_GUIDE.md`, `CLAUDE.md`.
