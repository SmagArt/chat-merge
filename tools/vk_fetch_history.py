"""
vk_fetch_history.py — выгрузка истории диалогов ВК напрямую через VK API.

Зачем: обход долгого официального запроса данных ВК (Settings → выгрузка, ждать часами).
Скрипт тянет историю переписок постранично в JSON, который потом скармливается chat-merge
как источник VK (наравне с HTML-экспортом). Перенесено из проекта date-agent 05.06.2026.

Выгрузка:  py tools/vk_fetch_history.py            # все диалоги
           py tools/vk_fetch_history.py --list     # СНАЧАЛА: список peer_id + имена
           py tools/vk_fetch_history.py --peer ID  # потом: только один собеседник
Токен:     VK_TOKEN в окружении, либо в tools/.env, либо --token <...>
           Получить: https://vkhost.github.io → "Kate Mobile" → "Разрешить" →
           скопировать access_token из адресной строки (права: messages,offline).
Результат: tools/vk_export/<peer_id>.json  (инкрементально, новые сообщения дописываются)
           Внутри: messages[] (сырые объекты VK API) + names{} (id→имя для атрибуции).

Как вытянуть КОНКРЕТНЫЙ диалог: peer_id = id человека для лички (можно подсмотреть
в URL vk.com/im?sel=<peer_id> или через --list). Для бесед (групповые чаты) peer_id =
2000000000 + номер чата — тоже виден в --list.

ВАЖНО (18.08.2026): запросы идут НАПРЯМУЮ, мимо прокси (Karing) — сессия с
trust_env=False. С VPN-IP массовые API-запросы Kate-токена ВК считает взломом
аккаунта и блокирует профиль. Прокси вернуть: VK_USE_PROXY=1. Темп — VK_REQUEST_PAUSE
(по умолчанию 0.8с). После выгрузки токен лучше отзывать: vk.com → Безопасность → Сеансы.

ВНИМАНИЕ: тянет ВСЕ диалоги обычного VK-мессенджера. Не запускать в автозапуске —
выгрузка тяжёлая (история всех чатов), гонять руками по необходимости.
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import sys

# requests и прочее ставится в {app}\base_packages, а не в системный Python —
# скрипт лежит в {app}\tools, путь добавляем сами (как merge_chat.py).
_base_pkgs = Path(__file__).resolve().parent.parent / "base_packages"
if _base_pkgs.is_dir() and str(_base_pkgs) not in sys.path:
    sys.path.insert(0, str(_base_pkgs))

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

API = "https://api.vk.com/method"
V = "5.199"
OUT_DIR = Path(__file__).parent / "vk_export"

# Пауза между запросами. 0.35с (формальный лимит VK 3 rps) ровным потоком на тысячах
# сообщений читается антифродом ВК как бот — в августе 2026 профиль за это блокировали
# трижды. Переопределяется VK_REQUEST_PAUSE.
PAUSE = float(os.environ.get("VK_REQUEST_PAUSE", "0.8"))

# Сессия ИГНОРИРУЕТ HTTP(S)_PROXY из окружения: api.vk.com должен идти напрямую,
# мимо Karing. В режиме Global весь трафик уходит в туннель, и ВК видит сотни
# API-запросов Kate-клиента с датацентрового IP → «доступ к аккаунту у третьей стороны».
# Вернуть прокси принудительно: VK_USE_PROXY=1.
_USE_PROXY = os.environ.get("VK_USE_PROXY", "").strip() in ("1", "true", "yes")
SESSION = requests.Session()
SESSION.trust_env = _USE_PROXY
if not _USE_PROXY:
    SESSION.proxies = {}


def vk(method: str, token: str, **params) -> dict:
    params.update({"access_token": token, "v": V})
    backoff = 1.0
    last_exc = None
    for attempt in range(6):
        try:
            r = SESSION.get(f"{API}/{method}", params=params, timeout=30)
            data = r.json()
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                ValueError) as e:       # ValueError — ответ не JSON (502/HTML-заглушка)
            last_exc = e
            time.sleep(backoff)
            backoff *= 2
            continue
        if "error" not in data:
            return data["response"]
        code = data["error"]["error_code"]
        # 6 = too many requests, 9 = flood control — лечатся ожиданием
        if code in (6, 9) and attempt < 5:
            time.sleep(backoff)
            backoff *= 2
            continue
        raise RuntimeError(f"VK error {code}: {data['error']['error_msg']}")
    raise RuntimeError(f"VK: исчерпаны ретраи ({last_exc})")


def fetch_all_conversations(token: str) -> list[dict]:
    """Забирает все диалоги постранично. profiles/groups VK отдаёт одним списком
    на страницу, а не внутри каждого диалога — раскладываем их по диалогам
    (_names), иначе у --list все имена выходили пустыми."""
    conversations = []
    offset = 0
    while True:
        resp = vk("messages.getConversations", token, offset=offset, count=200, extended=1)
        items = resp.get("items", [])
        if not items:
            break
        names = {}
        _collect_names(resp, names)
        for it in items:
            it["_names"] = names
        conversations.extend(items)
        if len(conversations) >= resp["count"]:
            break
        offset += 200
        time.sleep(PAUSE)
    return conversations


def _collect_names(resp: dict, names: dict):
    """Складывает id→имя из extended-ответа (profiles=люди, groups=сообщества)."""
    for p in resp.get("profiles", []):
        full = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if full:
            names[str(p["id"])] = full
    for g in resp.get("groups", []):
        # сообщества в from_id приходят с минусом
        names[str(-g["id"])] = g.get("name", f"club{g['id']}")


def fetch_messages(peer_id: int, token: str, progress=None) -> tuple[list[dict], dict]:
    """Забирает историю диалога + карту id→имя (для атрибуции в групповых чатах).
    progress(done, total) — после каждой страницы (GUI рисует по нему полоску)."""
    messages, names = [], {}
    offset = 0
    while True:
        resp = vk("messages.getHistory", token, peer_id=peer_id,
                  offset=offset, count=200, extended=1)
        items = resp.get("items", [])
        _collect_names(resp, names)
        if not items:
            break
        messages.extend(items)
        if progress:
            progress(len(messages), resp.get("count", 0))
        if len(messages) >= resp["count"]:
            break
        offset += 200
        time.sleep(PAUSE)
    # Пока листали страницы, могли прийти новые сообщения: offset съезжает, и
    # одно и то же сообщение попадает дважды. Дубли по id убираем здесь.
    seen, uniq = set(), []
    for m in reversed(messages):
        if m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        uniq.append(m)
    return uniq, names


def save_dialog(peer_id: int, info: dict, messages: list[dict], names: dict) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{peer_id}.json"
    existing, old_names = [], {}
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        existing = prev.get("messages", [])
        old_names = prev.get("names", {})

    existing_ids = {m["id"] for m in existing}
    new_msgs = [m for m in messages if m["id"] not in existing_ids]

    data = {
        "peer_id": peer_id,
        "info": info,
        "fetched_at": datetime.now().isoformat(),
        "names": {**old_names, **names},
        "messages": existing + new_msgs,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(new_msgs)


def peer_info(peer_id: int, token: str, names: dict) -> dict:
    """info для одного диалога (--peer, кнопка в GUI): имя человека/сообщества
    из names, у беседы — её название (в names его нет, раньше выходило пусто)."""
    name = names.get(str(peer_id), "")
    if not name and peer_id >= 2_000_000_000:
        try:
            resp = vk("messages.getConversationsById", token, peer_ids=peer_id)
            items = resp.get("items") or []
            if items:
                name = (items[0].get("chat_settings") or {}).get("title", "")
        except Exception:
            pass
    return {"peer_id": peer_id, "name": name}


def conv_info(conv: dict) -> dict:
    peer = conv["conversation"]["peer"]
    peer_id = peer["id"]
    last_msg = conv.get("last_message", {})
    if peer.get("type") == "chat":
        # Беседа: имя — её название, в профилях его нет
        name = (conv["conversation"].get("chat_settings") or {}).get("title", "")
    else:
        names = dict(conv.get("_names") or {})
        _collect_names(conv, names)          # на случай, если профили пришли в самом диалоге
        name = names.get(str(peer_id), "")   # люди — id, сообщества — -id (см. _collect_names)
    return {
        "peer_id": peer_id,
        "type": peer.get("type"),
        "name": name,
        "last_message_date": last_msg.get("date"),
    }


def main():
    # UTF-8 в консоль — только при запуске скриптом, не при импорте из GUI
    # (там stdout может быть None). reconfigure, а не TextIOWrapper: второй
    # объект над тем же буфером закрывает его при сборке мусора.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Выгрузка истории ВК через API")
    ap.add_argument("--list", action="store_true",
                    help="показать все диалоги (peer_id + имя), ничего не качая — "
                         "чтобы узнать peer_id нужного человека для --peer")
    ap.add_argument("--peer", type=int, help="peer_id одного собеседника (по умолчанию — все)")
    ap.add_argument("--token", help="VK access_token (иначе берётся из VK_TOKEN / tools/.env)")
    ap.add_argument("--account", help="имя аккаунта → токен из VK_TOKEN_<ИМЯ> в tools/.env "
                                      "(напр. --account marina → VK_TOKEN_MARINA). "
                                      "По умолчанию / 'artem' → VK_TOKEN.")
    args = ap.parse_args()

    # Приоритет: явный --token > --account (VK_TOKEN_<ИМЯ>) > VK_TOKEN
    token = args.token
    if not token and args.account:
        acc = args.account.strip().lower()
        token = os.getenv("VK_TOKEN") if acc in ("", "artem", "основной") \
            else os.getenv(f"VK_TOKEN_{acc.upper()}")
    if not token:
        token = os.getenv("VK_TOKEN")
    if not token:
        sys.exit("Нет токена. Задай VK_TOKEN, положи в tools/.env, передай --token "
                 "или --account <имя>. "
                 "Получить: https://vkhost.github.io (Kate Mobile, права messages,offline).")

    # --list: только справочник peer_id → имя, без выгрузки истории.
    if args.list:
        print(f"[{datetime.now():%H:%M:%S}] Список диалогов:\n")
        conversations = fetch_all_conversations(token)
        rows = sorted((conv_info(c) for c in conversations),
                      key=lambda i: i.get("last_message_date") or 0, reverse=True)
        print(f"{'peer_id':>12}  {'тип':<6}  имя")
        print("-" * 50)
        for i in rows:
            print(f"{i['peer_id']:>12}  {i.get('type','') or '':<6}  {i['name'] or '(без имени)'}")
        print(f"\nВсего: {len(rows)}. Качать конкретный: py tools/vk_fetch_history.py --peer <peer_id>")
        return

    if args.peer:
        print(f"[{datetime.now():%H:%M:%S}] Тяну диалог {args.peer}...")
        messages, names = fetch_messages(args.peer, token)
        info = peer_info(args.peer, token, names)
        added = save_dialog(args.peer, info, messages, names)
        print(f"  {len(messages)} сообщений, {added} новых")
        print(f"Экспорт: {OUT_DIR}")
        return

    print(f"[{datetime.now():%H:%M:%S}] Получаю список диалогов...")
    conversations = fetch_all_conversations(token)
    print(f"  Найдено диалогов: {len(conversations)}")

    total_new = 0
    for conv in conversations:
        info = conv_info(conv)
        peer_id = info["peer_id"]
        print(f"  > {info['name'] or peer_id} ({peer_id})... ", end="", flush=True)
        messages, names = fetch_messages(peer_id, token)
        added = save_dialog(peer_id, info, messages, names)
        total_new += added
        print(f"{len(messages)} сообщений, {added} новых")

    print(f"\nГотово. Новых сообщений: {total_new}")
    print(f"Экспорт: {OUT_DIR}")


if __name__ == "__main__":
    main()
