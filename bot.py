import os
import re
import sys
import textwrap
import random
import hashlib
import datetime as dt
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

# =====================
# CONFIG
# =====================
TZ = ZoneInfo("Europe/Kyiv")

# Постим трижды в день по Киеву:
POST_TIMES = [(8, 0), (14, 30), (17, 45)]

# Вики-категории строго про ШІ
WIKI_API = "https://uk.wikipedia.org/w/api.php"
WIKI_CATEGORIES = [
    "Категорія:Штучний інтелект",
    "Категорія:Машинне навчання",
    "Категорія:Нейронні мережі",
    "Категорія:Обробка природної мови",
    "Категорія:Комп'ютерний зір",
]

# Оформление
HASHTAGS = ["#ШІдлячайників", "#ШІ", "#машинненавчання", "#нейромережі", "#AI"]
STRONG_KWS = [
    "нейрон", "мереж", "трансформер", "attention", "gpt", "bert", "lstm",
    "класифікац", "регрес", "датасет", "обчислен", "gpu", "tensor",
    "nlp", "cv", "модель", "алгоритм", "ймовір"
]
EMOJI_POOL = ["🤖", "🧠", "📊", "⚙️", "✨", "🧪", "📈"]

# Картинка (flat-card)
IMG_SIZE = (1280, 720)       # 16:9 — красиво в тг
ADD_TITLE_ON_IMAGE = True    # показывать крупный заголовок на карточке (можно False)
BRAND = (os.environ.get("CHANNEL_HANDLE") or "").strip()  # водяной знак (опц.)

# Секреты
TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID   = (os.environ.get("TELEGRAM_CHAT_ID")   or "").strip()

# =====================
# TIME
# =====================
def should_post_now(now: dt.datetime, force=False) -> bool:
    if force:
        return True
    return (now.hour, now.minute) in POST_TIMES

# =====================
# WIKIPEDIA (ai-only)
# =====================
def pick_random_ai_page():
    cat = random.choice(WIKI_CATEGORIES)
    r = requests.get(WIKI_API, params={
        "action": "query", "list": "categorymembers", "cmtitle": cat,
        "cmtype": "page", "cmlimit": 200, "format": "json"
    }, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("categorymembers", [])
    # отфильтруем явную «не-ШІ»
    bad = ["CAPTCHA", "Капча", "відеогра", "серіал", "фільм", "кіно"]
    pages = [p for p in pages if not any(b.lower() in p["title"].lower() for b in bad)]
    if not pages:
        raise RuntimeError("Немає сторінок у категорії")
    return random.choice(pages)["pageid"]

def fetch_extract(pageid: int):
    r = requests.get(WIKI_API, params={
        "action": "query",
        "prop": "extracts|pageimages|images",
        "pageids": pageid,
        "explaintext": 1, "exintro": 1,
        "piprop": "thumbnail", "pithumbsize": 1280,
        "imlimit": 50, "format": "json",
    }, timeout=30)
    r.raise_for_status()
    page = r.json()["query"]["pages"][str(pageid)]
    title   = page["title"]
    extract = (page.get("extract") or "").strip()
    # картинку из статьи используем только как «настройку темы»
    thumb = page.get("thumbnail", {}).get("source")
    return title, extract, thumb

# =====================
# SIMPLE REWRITER (free)
# =====================
SYNONYM_MAP = {
    "штучний інтелект": "штучний розум",
    "комп'ютер": "ЕОМ",
    "дані": "набір даних",
    "система": "систeма",
    "застосовується": "використовується",
    "модель": "модeль",
    "алгоритм": "алгорuтм",
    "визначити": "з’ясувати",
}

def _sentences(text: str, n=4):
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = [re.sub(r"\s+", " ", s).strip() for s in parts if s.strip()]
    return out[:n]

def rewrite_text(extract: str) -> list[str]:
    sents = _sentences(extract, 3)
    if not sents:
        return ["Коротко про ШІ простими словами."]
    # синонимайзер + «разжёвывание»
    rewritten = []
    for s in sents:
        for k, v in SYNONYM_MAP.items():
            s = re.sub(k, v, s, flags=re.IGNORECASE)
        # чуть упростим сложные обороты
        s = s.replace("—", "—").replace(" - ", " — ")
        rewritten.append(s)
    # добавим дружелюбный лид
    lead = random.choice(["Коротко:", "По суті:", "Як простіше пояснити:"])
    return [lead] + rewritten

def emphasize(html: str) -> str:
    # авто-жирный важных слов
    for kw in sorted(STRONG_KWS, key=len, reverse=True):
        html = re.sub(rf"(?i)\b{kw}\w*\b",
                      lambda m: f"<b>{m.group(0)}</b>", html)
    return html

def build_caption(title: str, lines: list[str]) -> str:
    emoji = random.choice(EMOJI_POOL)
    # заголовок жирным
    header = f"{emoji} <b>{title}</b>"
    # основной блок — маркеры
    body = []
    for i, ln in enumerate(lines):
        if i == 0:
            body.append(ln)  # лид-строка без маркера
        else:
            body.append(f"• {ln}")
    body_html = emphasize("\n".join(body))
    tags = " ".join(HASHTAGS)
    return f"{header}\n\n{body_html}\n\n{tags}"

# =====================
# FLAT-CARD IMAGE
# =====================
def _font(size: int, bold=False):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(path, size)

def draw_icon_robot(draw: ImageDraw.ImageDraw, cx, cy, scale=1.0, color=(60,90,80)):
    # простой плоский «робот»
    r = int(80*scale)
    draw.rounded_rectangle((cx-r, cy-r, cx+r, cy+r), 30, fill=color)
    eye_r = int(12*scale)
    draw.ellipse((cx-int(35*scale)-eye_r, cy-eye_r, cx-int(35*scale)+eye_r, cy+eye_r), fill=(255,255,255))
    draw.ellipse((cx+int(35*scale)-eye_r, cy-eye_r, cx+int(35*scale)+eye_r, cy+eye_r), fill=(255,255,255))
    # гарнитура
    draw.arc((cx-int(110*scale), cy-int(40*scale), cx-int(10*scale), cy+int(40*scale)), 270, 90, fill=color, width=int(10*scale))
    draw.arc((cx+int(10*scale),  cy-int(40*scale), cx+int(110*scale), cy+int(40*scale)), 90, 270, fill=color, width=int(10*scale))
    draw.rectangle((cx-int(15*scale), cy+int(35*scale), cx+int(15*scale), cy+int(50*scale)), fill=color)

def generate_flat_card(title: str, seed: int, out_path: str, hashtag="#ШІ"):
    random.seed(seed)
    W, H = IMG_SIZE
    # пастельные палитры
    palettes = [
        ((246,242,236), (63, 87, 72)),   # беж/зел
        ((239,245,250), (58, 76,105)),   # светло-голубой/индиго
        ((244,240,252), (86, 72,115)),   # лиловый
        ((242,248,244), (70,105,80)),    # мятный
    ]
    bg, fg = random.choice(palettes)
    img  = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # крупный заголовок (опционально)
    if ADD_TITLE_ON_IMAGE:
        f_title = _font(96, bold=True)
        title_clean = title[:40] + ("…" if len(title) > 40 else "")
        tw = draw.textlength(title_clean, font=f_title)
        draw.text(((W-tw)//2, 90), title_clean, font=f_title, fill=fg)

    # иконка
    draw_icon_robot(draw, W//2, H//2 + (40 if ADD_TITLE_ON_IMAGE else 0), scale=1.0, color=fg)

    # нижний тег
    f_tag = _font(44)
    tag_w = draw.textlength(hashtag, font=f_tag)
    draw.text(((W-tag_w)//2, H-120), hashtag, font=f_tag, fill=fg)

    # водяной знак
    if BRAND:
        f_brand = _font(28)
        bw = draw.textlength(BRAND, font=f_brand)
        draw.text((W-24-bw, H-48), BRAND, font=f_brand, fill=(120,120,120))

    img.save(out_path, "PNG")

# =====================
# TELEGRAM
# =====================
def send_photo(photo_path: str, caption: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Порожні TELEGRAM_* секрети.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_notification": True,
        }, files={"photo": ("card.png", f, "image/png")}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

# =====================
# MAIN
# =====================
def main():
    force = "--force" in sys.argv
    now   = dt.datetime.now(TZ)
    if not should_post_now(now, force):
        print("Не час постити — виходимо")
        return

    pageid           = pick_random_ai_page()
    title, extract, _ = fetch_extract(pageid)
    lines            = rewrite_text(extract)        # список строк (лид + 1–2 факта)
    caption          = build_caption(title, lines)  # жирный заголовок + маркеры + жирные ключевые слова

    # плоская карточка
    seed     = int(hashlib.sha256((title + now.date().isoformat()).encode()).hexdigest()[:8], 16)
    img_path = "out.png"
    generate_flat_card(title, seed, img_path, hashtag=HASHTAGS[0])

    send_photo(img_path, caption)
    print("Опубліковано")

if __name__ == "__main__":
    main()
