import os, re, sys, random, hashlib, math, textwrap
import datetime as dt
from zoneinfo import ZoneInfo
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# =====================
# CONFIG
# =====================
TZ = ZoneInfo("Europe/Kyiv")

# ТРИ ЧАСА ДНЯ (по Киеву)
POST_TIMES = [(8, 0), (14, 30), (17, 45)]

# Темы только про ШІ
WIKI_API = "https://uk.wikipedia.org/w/api.php"
WIKI_CATEGORIES = [
    "Категорія:Штучний інтелект",
    "Категорія:Машинне навчання",
    "Категорія:Нейронні мережі",
    "Категорія:Обробка природної мови",
    "Категорія:Комп'ютерний зір",
]

# Визуал
IMG_SIZE = (1024, 1024)      # КВАДРАТ 1:1
ADD_TITLE_ON_IMAGE = True    # Заголовок на карточке (можно False)
BRAND = (os.environ.get("CHANNEL_HANDLE") or "").strip()

# Текст/хештеги
HASHTAGS = ["#ШІдлячайників", "#ШІ", "#машинненавчання", "#нейромережі", "#AI", "#практика"]
EMOJI_POOL = ["🤖","🧠","⚙️","📊","✨","🧪","📈"]
STRONG_KWS = [
    "нейрон", "мереж", "трансформер", "attention", "gpt", "bert", "lstm",
    "класифікац", "регрес", "датасет", "обчислен", "gpu", "tensor",
    "nlp", "cv", "модель", "алгоритм", "інференс", "навчан", "fine-tune"
]

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
# WIKIPEDIA (AI only)
# =====================
def pick_random_ai_page():
    cat = random.choice(WIKI_CATEGORIES)
    r = requests.get(WIKI_API, params={
        "action":"query","list":"categorymembers","cmtitle":cat,
        "cmtype":"page","cmlimit":200,"format":"json"
    }, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query",{}).get("categorymembers",[])
    if not pages: raise RuntimeError("Порожня категорія Вікі.")
    bad = ["CAPTCHA","Капча","відеогра","серіал","фільм","кіно","помилка","сервіс"]
    pages = [p for p in pages if not any(b.lower() in p["title"].lower() for b in bad)]
    return random.choice(pages)["pageid"]

def fetch_extract(pageid:int):
    r = requests.get(WIKI_API, params={
        "action":"query","prop":"extracts|pageimages|images","pageids":pageid,
        "explaintext":1,"exintro":1,"piprop":"thumbnail","pithumbsize":512,
        "imlimit":20,"format":"json"
    }, timeout=30)
    r.raise_for_status()
    page = r.json()["query"]["pages"][str(pageid)]
    title   = page["title"]
    extract = (page.get("extract") or "").strip()
    return title, extract

# =====================
# TEXT (профессиональный, 2–3× длиннее)
# =====================
SYNONYMS = {
    "штучний інтелект":"штучний розум", "дані":"набір даних", "комп'ютер":"ЕОМ",
    "система":"система", "застосовується":"використовується", "модель":"модель",
    "алгоритм":"алгоритм", "визначити":"з’ясувати", "побудова":"створення"
}

def _split_sents(txt:str, n=6):
    parts = re.split(r"(?<=[.!?])\s+", txt)
    return [re.sub(r"\s+"," ",s).strip() for s in parts if s.strip()][:n]

def _synonymize(s:str)->str:
    out = s
    for k,v in SYNONYMS.items():
        out = re.sub(k, v, out, flags=re.IGNORECASE)
    return out

def make_pro_text(title:str, extract:str)->str:
    """Делаем мини-пост из 3–4 абзацев, каждый по 2–3 предложения."""
    sents = _split_sents(extract, 10)
    if not sents:
        sents = [f"{title} — тема зі світу штучного інтелекту."]

    # разжёвываем, группируем
    blocks = []
    # Вступ
    intro = " ".join(_synonymize(s) for s in sents[:2])
    blocks.append(intro)

    # Суть / як працює
    core = sents[2:5] or sents[:2]
    blocks.append(" ".join(_synonymize(s) for s in core))

    # Навіщо / застосування
    use = sents[5:8] or sents[2:4]
    lead = random.choice(["Практично:", "Для чого це потрібно:", "Де застосовується:"])
    blocks.append(lead+" "+" ".join(_synonymize(s) for s in use))

    # Порада / зауваження
    if len(sents) > 8:
        tip = " ".join(_synonymize(s) for s in sents[8:10])
        blocks.append("Порада: "+tip)

    # форматируем в абзацы и выделяем ключевые слова
    def emphasize(html:str)->str:
        for kw in sorted(STRONG_KWS,key=len,reverse=True):
            html = re.sub(rf"(?i)\b{kw}\w*\b", lambda m:f"<b>{m.group(0)}</b>", html)
        return html

    paras = []
    for b in blocks:
        wrapped = textwrap.fill(b, width=80)
        paras.append(emphasize(wrapped))

    return "\n\n".join(paras)

def build_caption(title:str, pro_text:str)->str:
    emoji = random.choice(EMOJI_POOL)
    header = f"{emoji} <b>{title}</b>"
    tags   = " ".join(HASHTAGS)
    return f"{header}\n\n{pro_text}\n\n{tags}"

# =====================
# IMAGE (flat card 1:1 c «текстурой бумаги»)
# =====================
def _font(sz:int, bold=False):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(path, sz)

def _paper_texture(w,h, seed):
    rnd = random.Random(seed)
    base = Image.new("L", (w,h), 242)  # светлая бумага
    px = base.load()
    for y in range(h):
        for x in range(w):
            # мелкая «зернистость»
            n = rnd.randint(-6, 6)
            px[x,y] = max(232, min(250, px[x,y] + n))
    img = base.filter(ImageFilter.GaussianBlur(0.6))
    return ImageOps.colorize(img, (245,240,232), (248,246,242))

def _draw_icon_ai(draw, cx, cy, scale=1.0, color=(66, 96, 84)):
    # аккуратный «чип/мозг» в flat-стиле
    r = int(140*scale)
    draw.rounded_rectangle((cx-r, cy-r, cx+r, cy+r), 40, outline=color, width=10)
    # контактные ножки
    step = int(40*scale)
    for i in range(-2,3):
        y = cy - r - 22
        draw.line((cx+i*step, y, cx+i*step, y-40), fill=color, width=10)
        draw.line((cx+i*step, cy+r+22, cx+i*step, cy+r+62), fill=color, width=10)
        draw.line((cx-r-22, cy+i*step, cx-r-62, cy+i*step), fill=color, width=10)
        draw.line((cx+r+22, cy+i*step, cx+r+62, cy+i*step), fill=color, width=10)
    # «нейронные связи» внутри
    small = int(10*scale)
    for ang in range(0,360,30):
        x = cx + int((r-40)*math.cos(math.radians(ang)))
        y = cy + int((r-40)*math.sin(math.radians(ang)))
        draw.ellipse((x-small,y-small,x+small,y+small), fill=color)

def generate_flat_card(title:str, seed:int, out_path:str, hashtag="#ШІ"):
    W,H = IMG_SIZE
    # Бумага c зернистостью
    bg = _paper_texture(W,H, seed)
    img = Image.new("RGBA",(W,H))
    img.paste(bg,(0,0))

    draw = ImageDraw.Draw(img, "RGBA")
    theme = (66, 96, 84)   # приглушённый зелёный «как в референсе»

    # Заголовок (опционально)
    if ADD_TITLE_ON_IMAGE:
        f_title = _font(112, bold=True)
        ttl = title if len(title) <= 18 else title[:18].rstrip()+"…"
        tw = draw.textlength(ttl, font=f_title)
        draw.text(((W-tw)//2, 110), ttl, font=f_title, fill=theme)

    # Иконка
    _draw_icon_ai(draw, W//2, H//2 + (40 if ADD_TITLE_ON_IMAGE else 0), scale=1.0, color=theme)

    # Небольшая внутренняя тень, чтобы «панель» читалась
    shade = Image.new("RGBA",(W,H),(0,0,0,0))
    ImageDraw.Draw(shade).rounded_rectangle((50,50,W-50,H-50), 60, outline=(0,0,0,40), width=8)
    img = Image.alpha_composite(img, shade)

    # Хештег
    f_tag = _font(48, bold=False)
    tag_w = draw.textlength(hashtag, font=f_tag)
    draw.text(((W-tag_w)//2, H-140), hashtag, font=f_tag, fill=theme)

    # Водяной знак
    if BRAND:
        f_b = _font(28)
        bw = draw.textlength(BRAND, font=f_b)
        draw.text((W-26-bw, H-46), BRAND, font=f_b, fill=(120,120,120))

    img.convert("RGB").save(out_path, "PNG")

# =====================
# TELEGRAM
# =====================
def send_photo(photo_path:str, caption:str):
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
    now = dt.datetime.now(TZ)
    if not should_post_now(now, force):
        print("Не час постити — виходимо")
        return

    pageid = pick_random_ai_page()
    title, extract = fetch_extract(pageid)

    pro_text = make_pro_text(title, extract)            # длинный профессиональный текст
    caption  = build_caption(title, pro_text)

    seed = int(hashlib.sha256((title + now.date().isoformat()).encode()).hexdigest()[:8], 16)
    img_path = "out.png"
    generate_flat_card(title, seed, img_path, hashtag=HASHTAGS[0])

    send_photo(img_path, caption)
    print("Опубліковано")

if __name__ == "__main__":
    main()
