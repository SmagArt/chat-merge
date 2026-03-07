# Merge Chat v2.0

Объединяет переписки **Telegram** и **ВКонтакте** в один файл TXT или Markdown.  
Расшифровывает голосовые сообщения офлайн через OpenAI Whisper.  
Поддерживает GPU-ускорение (NVIDIA CUDA, Apple Silicon MPS).

---

## Возможности

- Парсинг Telegram (JSON и HTML) и ВКонтакте (HTML)
- Объединение нескольких папок одного контакта
- Расшифровка голосовых и кружочков через Whisper
- GPU-ускорение: NVIDIA CUDA, Apple Silicon MPS, AMD/Intel DirectML
- Фильтр по датам
- Форматы вывода: TXT и Markdown
- Кэш расшифровок — повторный запуск мгновенный

---

## Установка

### Windows

**Вариант 1 — установщик (рекомендуется):**
1. Скачай `MergeChat_Setup_v2.0.exe` из [Releases](https://github.com/SmagArt/chat-merge/releases)
2. Запусти и следуй инструкциям
3. Python и все пакеты установятся автоматически
4. При первом запуске автоматически определится и установится GPU-версия PyTorch

**Вариант 2 — если Python уже установлен:**
1. Скачай архив с исходниками из [Releases](https://github.com/SmagArt/chat-merge/releases)
2. Распакуй и дважды кликни `install_windows.bat`

### macOS

```bash
git clone https://github.com/SmagArt/chat-merge.git
cd chat-merge
pip3 install -r requirements.txt
pip3 install torch  # нативный arm64 с MPS для Apple Silicon
python3 merge_chat_gui.py
```

Или собери .app самостоятельно:
```bash
chmod +x build_mac.command
./build_mac.command
```

---

## Использование

### Через графический интерфейс (GUI)

1. Запусти Merge Chat (ярлык на рабочем столе или в меню Пуск)
2. Укажи папку с экспортом переписки (или перетащи папку в окно)
3. Введи своё имя (как оно записано в Telegram)
4. Выбери модель Whisper для расшифровки голосовых:
   - `tiny` — быстро, менее точно
   - `small` — баланс скорости и качества
   - `medium` — хорошее качество (рекомендуется)
   - `large` — максимальное качество, медленнее
5. Нажми «Запустить»

### Через командную строку (CLI)

```bash
# Базовое использование
python merge_chat.py "C:\Переписки\Иван"

# Несколько папок одного контакта
python merge_chat.py "C:\Иван\1" "C:\Иван\2" --author "Вы"

# Выбор модели и формата
python merge_chat.py "C:\Переписки\Иван" --model medium --markdown

# Объединять подряд идущие сообщения одного автора
python merge_chat.py "C:\Переписки\Иван" --merge

# Все опции
python merge_chat.py --help
```

**Опции CLI:**

| Опция | По умолчанию | Описание |
|-------|-------------|----------|
| `--author NAME` | `Вы` | Твоё имя в переписке |
| `--output FILE` | имя контакта | Имя выходного файла |
| `--model MODEL` | `small` | Модель Whisper: tiny/base/small/medium/large |
| `--merge` | выкл | Объединять подряд идущие сообщения |
| `--gap N` | `180` | Порог объединения в секундах |
| `--markdown` | выкл | Сохранить в Markdown вместо TXT |
| `--verbose` | выкл | Подробный лог |

---

## Как экспортировать переписку

**Telegram:**  
Настройки → Экспорт данных Telegram → выбери нужные чаты → формат JSON

**ВКонтакте:**  
vk.com/data_protection → Запросить данные → Переписки → скачай архив

---

## Пример выходного файла

```
10:25:25 Саша:
  По Железноводску гуляли при вообще дубаке 7 градусов и туман
10:25:43 Маша:
  Тоже поздно в этом году, весна поздняя.
10:30:13 Саша:
    ┌ Маша: Ты в видео с Кисловодском перепутал)
  я в сториз это обыграл шуткой) а так да, знаю
10:30:26 Саша:
  [📷 Фото]
```

---

## Системные требования

- Windows 10/11 или macOS 11+
- Python 3.10–3.13 (для CLI/самосборки)
- 4 ГБ RAM (8 ГБ для модели large)
- Для GPU: NVIDIA с CUDA 12.4+ или Apple Silicon
- ffmpeg не нужен отдельно — встроен через пакет imageio-ffmpeg

---

## Автор

Артём Смагин — [github.com/SmagArt](https://github.com/SmagArt)
