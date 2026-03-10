# Merge Chat v2.1

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
1. Скачай `MergeChat_Setup_v2.1.exe` из [Releases](https://github.com/SmagArt/chat-merge/releases)
2. Запусти и следуй инструкциям
3. Python и все пакеты установятся автоматически
4. При первом запуске автоматически определится и установится GPU-версия PyTorch

**Вариант 2 — если Python уже установлен:**
1. Скачай архив с исходниками
2. Запусти `install_windows.bat`

### macOS

**Вариант 1 — готовый DMG (рекомендуется):**
1. Скачай `MergeChat_v2.1.dmg` из [Releases](https://github.com/SmagArt/chat-merge/releases)
2. Открой DMG, перетащи MergeChat в папку Программы
3. При первом запуске: правый клик → Открыть (обход Gatekeeper)

**Вариант 2 — сборка из исходников:**
```bash
git clone https://github.com/SmagArt/chat-merge.git
cd chat-merge
bash build_mac.command
```
Скрипт соберёт `.app` и создаст `dist_mac/MergeChat_v2.1.dmg` автоматически.

---

## Использование

1. Запусти Merge Chat
2. Укажи папку с экспортом переписки
3. Введи своё имя (как оно записано в Telegram)
4. Выбери модель Whisper для расшифровки голосовых:
   - `tiny` — быстро, менее точно
   - `small` — баланс скорости и качества
   - `medium` — хорошее качество (рекомендуется)
   - `large` — максимальное качество, медленнее
5. Нажми «Запустить»

---

## Как экспортировать переписку

**Telegram:**  
Настройки → Экспорт данных Telegram → выбери нужные чаты → формат JSON

**ВКонтакте:**  
vk.com/data_protection → Запросить данные → Переписки → скачай архив

---

## Системные требования

- Windows 10/11 или macOS 11+
- 4 ГБ RAM (8 ГБ для модели large)
- Для GPU: NVIDIA с CUDA 12.4+ или Apple Silicon
- Интернет нужен только при первой установке пакетов

---

## Автор

Артём Смагин — [github.com/SmagArt](https://github.com/SmagArt)
