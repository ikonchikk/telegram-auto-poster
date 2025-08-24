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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# =====================
# CONFIG
# =====================
TZ = ZoneInfo("Europe/Kyiv")

# Время постов (Kyiv time): 08:00, 14:30, 17:45
POST_TIMES = [(8, 0), (14, 30), (17, 45)]

# Wikipedia категории строго про ШІ
WIKI_API = "https://uk.wikipedia.org/w/api.php"
WIKI_CATEGORIES = [
    "Категорія:Штучний інтелект",
    "Категорія:Машинне навчання",
    "Категорія:Нейронні мережі",
    "Категорія:Обробка природної мови",
    "Категорія:Комп'ютерний зір",
]

IMG_SIZE = (1280, 720)  # 16:9
HASHTAGS = ["#ШІдлячайників", "#ШІ", "#машинненавчання", "#нейромережі", "#AI"]

BRAND = (os.environ.get("CHANNEL_HANDLE") or "").strip()

TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

# Ключевые слова для жирного выделения
STRONG_KWS = [
    "нейрон", "мереж", "трансформер", "Attention", "GPT", "BERT", "LSTM",
    "класифікац", "регрес", "датасет", "обчислен", "GPU", "Tensor", "NLP", "CV", "модель", "алгоритм"
]

EMOJI_POOL = ["🤖", "🧠", "📊", "⚙️", "✨", "🧪", "📈"]

# =====================
# TIME CHECK
# =====================
def should_post_now(now: dt.datetime, force=False) -> bool:
    if force:
        return True
    return (now.hour, now.minute) in POST_TIMES

# =====================
# WIKIPEDIA
# =====================
def pick_random_ai_page():
    cat = random.choice(WIKI_CATEGORIES)
    r = requests.get(WIKI_API, params={
        "action": "query",
        "list": "categorymembers",
        "cmtitle": cat,
        "cmtype": "page",
        "cmlimit": 200,
        "format": "json"
    }, timeout=30)
    r.raise_for_status()
    pages = r.json()["query"]["categorymembers"]
    bad = ["CAPTCHA", "відеогра", "кіно", "серіал"]
    pages = [p for p in pages if not any(b.lower() in p["title"].lower() for b in bad)]
    return random.choice(pages)["pageid"]

def fetch_page_data(pageid: int):
    r = requests.get(WIKI_API, params={
        "action": "query",
        "prop": "extracts|pageimages|images",
        "pageids": pageid,
        "explaintext": 1,
        "exintro": 1,
        "piprop": "thumbnail",
        "pithumbsize": 1280,
        "imlimit": 50,
        "format": "json",
    }, timeout=30)
    page = r.json()["query"]["pages"][str(pageid)]
    title = page["title"]
    extract = (page.get("extract") or "").strip()
    thumb = page.get("thumbnail", {}).get("source")
    return title, extract, thumb

# =====================
# SIMPLE UNIQ TEXT
# =====================
SYNONYM_MAP = {
    "штучний інтелект": "штучний розум",
    "комп'ютер": "ЕОМ",
    "алгоритм": "алгорuтм",
    "модель": "модeль",
    "дані": "збірка даних",
    "система": "систeма",
    "застосовується": "використовується",
    "визначити": "з’ясувати",
}

def rewrite_text(extract: str) -> str:
    sents = re.split(r"(?<=[.!?])\s+", extract)[:3]
    sents = [re.sub(r"\s+", " ", s).strip() for s in sents if s.strip()]
    text = " ".join(sents)
    for k, v in SYNONYM_MAP.items():
        text = re.sub(k, v, text, flags=re.IGNORECASE)
    return random.choice(["Коротко:", "Просто пояснимо:", "По суті:"]) + " " + text

def emphasize(text: str) -> str:
    for kw in STRONG_KWS:
        text = re.sub(rf"(?i)\b{kw}\w*\b", lambda m: f"<b>{m.group(0)}</b>", text)
    return text

# =====================
# IMAGE
# =====================
def load_font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size)

def generate_ai_image(title, seed, out_path):
    random.seed(seed)
    W, H = IMG_SIZE
    img = Image.new("RGB", (W, H), (15, 20, 40))
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(40):
        x1, y1 = random.randint(0, W), random.randint(0, H)
        x2, y2 = random.randint(0, W), random.randint(0, H)
        draw.line((x1,y1,x2,y2), fill=(120,180,255,80), width=2)
    for _ in range(60):
        x,y = random.randint(0,W), random.randint(0,H)
        r = random.randint(3,7)
        draw.ellipse((x-r,y-r,x+r,y+r), fill=(180,220,255,200))
    if BRAND:
        f = load_font(28)
        draw.text((W-200, H-50), BRAND, font=f, fill=(200,200,200))
    img.save(out_path, "PNG")

# =====================
# TELEGRAM
# =====================
def send_to_telegram(photo_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML"
        }, files={"photo": f})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

# =====================
# MAIN
# =====================
def main():
    force = "--force" in sys.argv
    now = dt.datetime.now(TZ)
    if not should_post_now(now, force):
        print("Не час постити — виходимо")
        return
    pageid = pick_random_ai_page()
    title, extract, thumb = fetch_page_data(pageid)
    text = rewrite_text(extract)
    body = emphasize(text)
    caption = f"{random.choice(EMOJI_POOL)} <b>{title}</b>\n\n{body}\n\n{' '.join(HASHTAGS)}"
    img_path = "out.png"
    generate_ai_image(title, now.toordinal(), img_path)
    send_to_telegram(img_path, caption)
    print("Опубліковано")

if __name__ == "__main__":
    main()
