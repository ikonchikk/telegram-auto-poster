import os
import re
import sys
import textwrap
import random
import hashlib
import datetime as dt
from zoneinfo import ZoneInfo
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# === Конфиг ===
TZ = ZoneInfo("Europe/Kyiv")
POST_WINDOW_HOURS = (10, 21)  # один случайный час между 10:00 и 21:00 по Киеву
WIKI_API = "https://uk.wikipedia.org/w/api.php"
WIKI_CATEGORY = "Категорія:Штучний інтелект"  # тематику можно заменить
IMG_SIZE = (1080, 1080)
TITLE_MAX = 60
TEXT_MAX_CHARS = 420
HASHTAGS = ["#ШІдлячайників", "#ШІ", "#машинненавчання", "#нейромережі", "#AI"]
BRAND = os.environ.get("CHANNEL_HANDLE", "")  # без @

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # @name или -100...

# === Емодзі по темах (простое сопоставление ключевых слов) ===
EMOJI_MAP = [
    (["ШІ", "AI", "інтелект", "штучний"], "🤖"),
    (["нейрон", "мереж", "transformer", "трансформер"], "🧠"),
    (["дан", "data", "датасет"], "📊"),
    (["навчан", "training", "навчання", "машинне"], "🎓"),
    (["обчисл", "GPU", "паралел"], "⚙️"),
]

def pick_emojis(title: str, text: str, max_n: int = 2) -> str:
    cand = []
    base = (title + " " + text).lower()
    for keys, emo in EMOJI_MAP:
        if any(k.lower() in base for k in keys):
            cand.append(emo)
    import random as _r
    _r.shuffle(cand)
    if not cand:
        cand = ["✨"]
    return "".join(cand[:max_n])

# === Утилиты ===
def scheduled_hour_for_date(d: dt.date, chat_id: str) -> int:
    seed = f"{d.isoformat()}::{chat_id}".encode("utf-8")
    h = int(hashlib.sha256(seed).hexdigest()[:8], 16)
    span = POST_WINDOW_HOURS[1] - POST_WINDOW_HOURS[0] + 1
    return POST_WINDOW_HOURS[0] + (h % span)

def should_post_now(now: dt.datetime, chat_id: str, force: bool = False) -> bool:
    if force:
        return True
    target = scheduled_hour_for_date(now.date(), chat_id)
    return now.hour == target

# === Вікіпедія ===
def pick_random_ai_page():
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": WIKI_CATEGORY,
        "cmtype": "page",
        "cmlimit": 200,
        "format": "json",
    }
    r = requests.get(WIKI_API, params=params, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("categorymembers", [])
    if not pages:
        raise RuntimeError("Не вдалося отримати статті з категорії")
    return __import__("random").choice(pages)["pageid"]

def fetch_page_data(pageid: int):
    params = {
        "action": "query",
        "prop": "extracts|info|pageimages",
        "pageids": pageid,
        "explaintext": 1,
        "exintro": 1,
        "inprop": "url",
        "piprop": "thumbnail",
        "pithumbsize": 1024,
        "format": "json",
    }
    r = requests.get(WIKI_API, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()["query"]["pages"][str(pageid)]
    title = data["title"]
    url = data.get("fullurl")
    extract = (data.get("extract") or "").strip()
    thumb = None
    if "thumbnail" in data and data["thumbnail"].get("source"):
        thumb = data["thumbnail"]["source"]

    sentences = re.split(r"(?<=[.!?])\s+", extract)
    short = " ".join(sentences[:3]).strip()
    if len(short) > TEXT_MAX_CHARS:
        short = short[: TEXT_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    if not short:
        short = "Короткий факт із Вікіпедії."

    return title, short, url, thumb

# === Загрузка шрифта ===
def load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

# === Картинка: фон по теме + текст ===
def make_image(title: str, text: str, out_path: str, thumb_url: str | None):
    W, H = IMG_SIZE
    img = Image.new("RGB", (W, H), (247, 248, 250))

    if thumb_url:
        try:
            resp = requests.get(thumb_url, timeout=30)
            resp.raise_for_status()
            bg = Image.open(BytesIO(resp.content)).convert("RGB")
            bg_ratio = bg.width / bg.height
            canvas_ratio = W / H
            if bg_ratio > canvas_ratio:
                new_h = H
                new_w = int(new_h * bg_ratio)
            else:
                new_w = W
                new_h = int(new_w / bg_ratio)
            bg = bg.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - W) // 2
            top = (new_h - H) // 2
            bg = bg.crop((left, top, left + W, top + H))
            bg = bg.filter(ImageFilter.GaussianBlur(2))
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 80))
            bg = bg.convert("RGBA"); bg.alpha_composite(overlay)
            img = bg.convert("RGB")
        except Exception:
            pass

    draw = ImageDraw.Draw(img)
    font_title = load_font(64)
    font_text = load_font(36)
    font_brand = load_font(28)

    margin = 72
    y = margin

    t = title.strip()
    if len(t) > TITLE_MAX:
        t = t[:TITLE_MAX].rstrip() + "…"
    t_wrapped = textwrap.fill(t, width=18)
    draw.text((margin, y), t_wrapped, font=font_title, fill=(255, 255, 255) if thumb_url else (20, 20, 20))
    y += sum(font_title.getbbox(line)[3] for line in t_wrapped.split("\n")) + 20

    body_wrapped = textwrap.fill(text, width=28)
    draw.text((margin, y), body_wrapped, font=font_text, fill=(235, 235, 235) if thumb_url else (40, 40, 40))

    if BRAND:
        bw = draw.textlength(BRAND, font=font_brand)
        bh = font_brand.getbbox("Ay")[3]
        color = (230, 230, 230) if thumb_url else (120, 120, 120)
        draw.text((IMG_SIZE[0] - margin - bw, IMG_SIZE[1] - margin - bh), BRAND, font=font_brand, fill=color)

    img.save(out_path, format="PNG")

# === Telegram ===
def send_to_telegram(photo_path: str, caption: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Перевір TELEGRAM_BOT_TOKEN і TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        files = {"photo": ("post.png", f, "image/png")}
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_notification": True,
        }
        r = requests.post(url, data=data, files=files, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

def build_caption(title: str, url: str, emojis: str):
    tags = " ".join(HASHTAGS)  # хештеги строго в конце
    lines = [
        f"{emojis} <b>ШІ для чайників</b> — {title}",
        "",
        f'Джерело: <a href="{url}">Вікіпедія</a> (CC BY-SA 4.0)',
        tags,
    ]
    return "\n".join(line for line in lines if line)

def main():
    force = "--force" in sys.argv
    now = dt.datetime.now(TZ)

    if not should_post_now(now, TELEGRAM_CHAT_ID or "unknown", force=force):
        print("Не час постити — виходимо")
        return

    pageid = pick_random_ai_page()
    title, text, url, thumb = fetch_page_data(pageid)
    emojis = pick_emojis(title, text)

    img_path = "out.png"
    make_image(title, text, img_path, thumb)

    caption = build_caption(title, url, emojis)
    send_to_telegram(img_path, caption)
    print("Опубліковано")

if __name__ == "__main__":
    main()
