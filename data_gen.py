from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

import feedparser
import pandas as pd
import requests
from dotenv import load_dotenv

SITE_DIR = Path(__file__).resolve().parent
STATE_PATH = SITE_DIR / "state.json"
ISS = "https://iss.moex.com/iss"

load_dotenv()
_dev_env = Path(r"D:\traiding\.env")
if _dev_env.exists():
    load_dotenv(_dev_env)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
DEEPSEEK_FLASH = os.getenv("DEEPSEEK_FLASH_MODEL") or "deepseek-v4-flash"

UA = {"User-Agent": "market-news/1.0"}

INDEX_MAP = {"IMOEX": "Индекс МосБиржи", "RTSI": "Индекс РТС", "MOEX10": "Индекс МосБиржи 10"}
METALS_MAP = {
    "GLDRUB_TOM": ("GOLD", "Золото, ₽/г", 1),
    "SLVRUB_TOM": ("SILVER", "Серебро, ₽/г", 1),
    "PLDRUB_TOM": ("PALLADIUM", "Палладий, ₽/г", 1),
    "PLTRUB_TOM": ("PLATINUM", "Платина, ₽/г", 1),
}
MAJOR_FX = ["USD", "EUR", "CNY", "GBP", "JPY", "CHF", "HKD"]

RSS_SOURCES = [
    {"name": "TASS", "url": "https://tass.ru/rss/v2.xml"},
    {"name": "RIA", "url": "https://ria.ru/export/rss2/archive/index.xml"},
    {"name": "Interfax", "url": "https://www.interfax.ru/rss.asp"},
    {"name": "RBC", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"},
    {"name": "Kommersant", "url": "https://www.kommersant.ru/RSS/news.xml"},
    {"name": "Vedomosti", "url": "https://www.vedomosti.ru/rss/news"},
    {"name": "Investing", "url": "https://ru.investing.com/rss/news.rss"},
    {"name": "Forbes", "url": "https://www.forbes.ru/newrss.xml"},
    {"name": "Lenta", "url": "https://lenta.ru/rss/news"},
    {"name": "Izvestia", "url": "https://iz.ru/xml/rss/all.xml"},
    {"name": "Prime", "url": "https://1prime.ru/export/rss2/index.xml"},
    {"name": "Finam", "url": "https://www.finam.ru/rss/news.rss"},
    {"name": "SmartLab", "url": "https://smart-lab.ru/rss/all.xml"},
]

URGENT_KEYWORDS = [
    "санкци", "банкрот", "делистинг", "убыт", "арест", "суд", "допэмисс", "дивиденд", "отчёт",
    "выкуп", "поглощ", "размещ", "останов", "приостанов", "сделк", "смена", "назначен", "увольн",
    "разворот", "обвал", "ставк", "цб", "центробанк",
]
CAT_RULES = [
    ("oil", ["нефть", "нефти", "газ", "газа", "бензин", "добыч", "лукойл", "газпром", "роснефть"]),
    ("fx", ["рубл", "доллар", "юан", "евро", "курс", "валюта", "иена"]),
    ("bond", ["облигац", "офз", "доходност", "купон", "гособлигац"]),
    ("commodity", ["золото", "серебро", "металл", "сырьё", "сырье", "паллади", "платин"]),
    ("index", ["индекс", "мосбирж", "биржа", "листинг"]),
    ("macro", ["ставк", "цб ", "центробанк", "инфляц", "бюджет", "ввп", "санкц", "налог", "правительств"]),
]
RU_MONTHS = ["", "ЯНВ", "ФЕВ", "МАР", "АПР", "МАЙ", "ИЮН", "ИЮЛ", "АВГ", "СЕН", "ОКТ", "НОЯ", "ДЕК"]
RU_WD = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
TOP_TICKERS = ["SBER", "GAZP", "LKOH", "ROSN", "GMKN", "YDEX", "T", "MGNT", "MTSS", "NVTK", "ALRS", "CHMF", "TATN", "VTBR", "SNGS", "AFLT", "OZON", "PLZL"]

# реферальная ссылка Т-Банка (партнёрская программа) — заполни, когда получишь
REFERRAL_URL = os.getenv("TBANK_REFERRAL_URL", "")


def iss_json(path: str, params: dict | None = None) -> dict:
    r = requests.get(ISS + path, params=params, timeout=20, headers=UA)
    r.raise_for_status()
    return r.json()


# ── ключевая ставка ЦБ ──
def key_rate() -> dict:
    try:
        r = requests.get("https://www.cbr.ru/hd_base/KeyRate/", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.encoding = "utf-8"
        m = re.findall(r"([\d]{2}\.[\d]{2}\.[\d]{4})</td>\s*<td[^>]*>([\d]+,[\d]+)", r.text)
        if not m:
            return {}
        return {"date": m[0][0], "rate": float(m[0][1].replace(",", "."))}
    except Exception:
        return {}


# ── индексы ──
def index_candles(secid: str) -> list[float]:
    try:
        from_date = (pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        r = iss_json(f"/engines/stock/markets/index/securities/{secid}/candles.json",
                     {"interval": 24, "from": from_date})
        rows = r["candles"]["data"]
        if not rows:
            return []
        ci = r["candles"]["columns"].index("close")
        return [round(float(row[ci]), 2) for row in rows[-30:]]
    except Exception:
        return []


def indexes() -> list[dict]:
    out: dict[str, dict] = {}
    for board in ("SNDX", "RTSI"):
        j = iss_json(f"/engines/stock/markets/index/boards/{board}/securities.json")
        md = {m[0]: m for m in j["marketdata"]["data"]}
        ci = j["marketdata"]["columns"]
        for secid, name in INDEX_MAP.items():
            if secid in md and secid not in out:
                m = md[secid]
                out[secid] = {
                    "sym": "RTS" if secid == "RTSI" else secid,
                    "name": name,
                    "price": m[ci.index("CURRENTVALUE")],
                    "chg": m[ci.index("LASTCHANGEPRC")],
                    "dec": 2,
                    "spark": index_candles(secid),
                }
    return [out[k] for k in INDEX_MAP if k in out]


# ── валюты (все по курсу ЦБ) и металлы (валютный рынок MOEX) ──
def all_fx() -> list[dict]:
    import xml.etree.ElementTree as ET

    try:
        r = requests.get("https://www.cbr.ru/scripts/XML_daily.asp", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.encoding = "windows-1251"
        root = ET.fromstring(r.content)
        items = []
        for val in root.findall("Valute"):
            code = (val.find("CharCode").text or "").strip()
            name = (val.find("Name").text or "").strip()
            nominal = float(val.find("Nominal").text.replace(",", "."))
            value = float(val.find("Value").text.replace(",", "."))
            price = round(value / nominal, 4)
            dec = 2 if price >= 10 else (3 if price >= 1 else 4)
            items.append({"sym": code, "name": name, "price": price, "chg": None, "dec": dec})
        def rank(x: dict) -> tuple[int, str]:
            return (MAJOR_FX.index(x["sym"]) if x["sym"] in MAJOR_FX else len(MAJOR_FX), x["name"])
        items.sort(key=rank)
        return items
    except Exception:
        return []


def metals() -> list[dict]:
    j = iss_json("/engines/currency/markets/selt/securities.json")
    ci = j["marketdata"]["columns"]
    secid_i = ci.index("SECID")
    md = {m[secid_i]: m for m in j["marketdata"]["data"]}
    out = []
    for secid, (sym, name, dec) in METALS_MAP.items():
        m = md.get(secid)
        price = m[ci.index("LAST")] if m and "LAST" in ci else None
        if price is None and m and "CLOSEPRICE" in ci:
            price = m[ci.index("CLOSEPRICE")]
        chg = m[ci.index("LASTCHANGEPRCNT")] if m and "LASTCHANGEPRCNT" in ci else None
        if price is not None:
            out.append({"sym": sym, "name": name, "price": price, "chg": chg, "dec": dec})
    return out


# ── изменение за день у основных валют (валютный рынок MOEX) ──
def moex_fx_change() -> dict[str, float]:
    try:
        j = iss_json("/engines/currency/markets/selt/securities.json")
        ci = j["marketdata"]["columns"]
        secid_i = ci.index("SECID")
        md = {m[secid_i]: m for m in j["marketdata"]["data"]}
        mapping = {"USD000UTSTOM": "USD", "EUR_RUB__TOM": "EUR", "CNY000000TOD": "CNY", "HKDRUB_TOM": "HKD"}
        out = {}
        for secid, code in mapping.items():
            m = md.get(secid)
            if m and "LASTCHANGEPRCNT" in ci:
                v = m[ci.index("LASTCHANGEPRCNT")]
                if v is not None:
                    out[code] = v
        return out
    except Exception:
        return {}


def selt_candles(secid: str, days: int = 90) -> list[float]:
    try:
        from_date = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
        r = iss_json(f"/engines/currency/markets/selt/securities/{secid}/candles.json",
                     {"interval": 24, "from": from_date})
        rows = r["candles"]["data"]
        if not rows:
            return []
        ci = r["candles"]["columns"].index("close")
        return [round(float(row[ci]), 2) for row in rows[-30:]]
    except Exception:
        return []


def forts_candles(assetcode: str) -> list[float]:
    try:
        j = iss_json("/engines/futures/markets/forts/securities.json")
        df = pd.DataFrame(j["securities"]["data"], columns=j["securities"]["columns"])
        today = pd.Timestamp.today()
        sub = df[df["ASSETCODE"] == assetcode].copy()
        sub["LASTTRADEDATE"] = pd.to_datetime(sub["LASTTRADEDATE"], errors="coerce")
        sub = sub[sub["LASTTRADEDATE"] >= today].sort_values("LASTTRADEDATE")
        if sub.empty:
            return []
        secid = sub.iloc[0]["SECID"]
        c = iss_json(f"/engines/futures/markets/forts/securities/{secid}/candles.json", {"interval": 24})
        rows = c["candles"]["data"]
        if not rows:
            return []
        ci = c["candles"]["columns"].index("close")
        return [round(float(row[ci]), 2) for row in rows[-30:]]
    except Exception:
        return []


def trends() -> dict[str, list[float]]:
    return {"gold": selt_candles("GLDRUB_TOM"), "usd": selt_candles("USD000UTSTOM"), "brent": forts_candles("BR")}


# ── товары (нефть, газ) ──
def commodities() -> list[dict]:
    out = []
    try:
        j = iss_json("/engines/futures/markets/forts/securities.json")
        df = pd.DataFrame(j["securities"]["data"], columns=j["securities"]["columns"])
        today = pd.Timestamp.today()
        for asset, sym, name in [("BR", "BRENT", "Нефть Brent, $"), ("NG", "NG", "Газ, $")]:
            sub = df[df["ASSETCODE"] == asset].copy()
            sub["LASTTRADEDATE"] = pd.to_datetime(sub["LASTTRADEDATE"], errors="coerce")
            sub = sub[sub["LASTTRADEDATE"] >= today].sort_values("LASTTRADEDATE")
            if sub.empty:
                continue
            secid = sub.iloc[0]["SECID"]
            c = iss_json(f"/engines/futures/markets/forts/securities/{secid}/candles.json", {"interval": 24})
            rows = c["candles"]["data"]
            if rows:
                ci = c["candles"]["columns"].index("close")
                out.append({"sym": sym, "name": name, "price": round(float(rows[-1][ci]), 2), "chg": None, "dec": 2})
    except Exception:
        pass
    return out


# ── акции (все ликвидные + волатильность) ──
def all_stocks() -> list[dict]:
    j = iss_json("/engines/stock/markets/shares/boards/TQBR/securities.json")
    sec = pd.DataFrame(j["securities"]["data"], columns=j["securities"]["columns"])
    md = pd.DataFrame(j["marketdata"]["data"], columns=j["marketdata"]["columns"])
    sec = sec[["SECID", "SHORTNAME", "PREVPRICE"]]
    md = md[["SECID", "LAST", "LASTCHANGEPRCNT", "LASTTOPREVPRICE", "VALTODAY", "HIGH", "LOW"]]
    base = sec.merge(md, on="SECID", how="inner")
    base = base[base["VALTODAY"].notna() & (base["VALTODAY"] > 0) & base["LAST"].notna() & (base["LAST"] > 0)]
    base = base.sort_values("VALTODAY", ascending=False)
    out = []
    for _, r in base.iterrows():
        price = float(r["LAST"])
        raw_chg = r["LASTTOPREVPRICE"] if "LASTTOPREVPRICE" in base.columns else None
        if raw_chg is None or pd.isna(raw_chg):
            raw_chg = r["LASTCHANGEPRCNT"] if not pd.isna(r["LASTCHANGEPRCNT"]) else None
        chg = float(raw_chg) if raw_chg is not None and not pd.isna(raw_chg) else None
        volatility = None
        try:
            prev, hi, lo = r["PREVPRICE"], r["HIGH"], r["LOW"]
            if prev and hi and lo and not pd.isna(hi) and not pd.isna(lo) and float(prev) > 0:
                volatility = round((float(hi) - float(lo)) / float(prev) * 100, 2)
        except Exception:
            pass
        out.append({
            "sym": r["SECID"], "name": r["SHORTNAME"], "price": price, "chg": chg,
            "dec": 0 if price >= 1000 else 2,
            "vol": f"{float(r['VALTODAY']) / 1e9:.2f} млрд ₽", "volatility": volatility,
        })
    return out


def total_volume() -> float:
    try:
        j = iss_json("/engines/stock/markets/shares/boards/TQBR/securities.json")
        md = pd.DataFrame(j["marketdata"]["data"], columns=j["marketdata"]["columns"])
        return float(md["VALTODAY"].sum()) if "VALTODAY" in md else 0.0
    except Exception:
        return 0.0


# ── данные с ПК через T-Bank (опционально, лежат в tbank_data.json) ──
def load_tbank() -> dict:
    p = SITE_DIR / "tbank_data.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── дивиденды (T-Bank будущие → фолбэк на MOEX) ──
def moex_dividend(ticker: str) -> dict | None:
    try:
        j = iss_json(f"/securities/{ticker}/dividends.json")
        cols = [c.lower() for c in j["dividends"]["columns"]]
        rows = j["dividends"]["data"]
        date_i = next((i for i, c in enumerate(cols) if "registry" in c or "record" in c), None)
        val_i = next((i for i, c in enumerate(cols) if c == "value"), None)
        if date_i is None or val_i is None:
            return None
        today = date.today().isoformat()
        for r in rows:
            d = str(r[date_i])
            if d >= today:
                return {"record_date": d, "value": r[val_i]}
    except Exception:
        pass
    return None


def calendar() -> list[dict]:
    tb = load_tbank()
    divs = tb.get("dividends", [])
    today = date.today().isoformat()
    out = []
    for d in divs:
        rec = str(d.get("record_date") or "")
        if not rec or rec < today:
            continue
        try:
            dt = datetime.strptime(rec, "%Y-%m-%d")
            out.append({
                "day": dt.strftime("%d"), "mon": RU_MONTHS[dt.month], "wd": RU_WD[dt.weekday()],
                "title": f"Дивидендная отсечка «{d.get('ticker', '')}»",
                "sub": f"{float(d.get('per_share', 0)):.2f} ₽ · доходность {float(d.get('yield_pct', 0) or 0):.1f}%",
                "cat": "company",
            })
        except Exception:
            continue
    out.sort(key=lambda x: (RU_MONTHS.index(x["mon"]), x["day"]))
    if out:
        return out[:7]
    # фолбэк на MOEX
    for t in TOP_TICKERS:
        d = moex_dividend(t)
        if d:
            try:
                dt = datetime.strptime(d["record_date"], "%Y-%m-%d")
                out.append({
                    "day": dt.strftime("%d"), "mon": RU_MONTHS[dt.month], "wd": RU_WD[dt.weekday()],
                    "title": f"Дивидендная отсечка «{t}»",
                    "sub": f"{float(d['value']):.2f} ₽ на акцию", "cat": "company",
                })
            except Exception:
                continue
    out.sort(key=lambda x: (RU_MONTHS.index(x["mon"]), x["day"]))
    return out[:7]


# ── новости ──
def entry_image(e) -> str:
    for enc in (e.get("enclosures") or []):
        href = enc.get("href", "")
        if href and (enc.get("type", "").startswith("image") or href.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
            return href
    for l in (e.get("links") or []):
        href = l.get("href", "")
        if l.get("rel") == "enclosure" and href and href.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return href
    mc = e.get("media_content") or []
    if mc:
        return mc[0].get("url", "") or ""
    return ""


def fetch_rss() -> list[dict]:
    out = []
    for src in RSS_SOURCES:
        try:
            for e in feedparser.parse(src["url"]).entries[:25]:
                title = re.sub(r"\s+", " ", (e.get("title") or "")).strip()
                if title:
                    out.append({"source": src["name"], "published_at": e.get("published") or e.get("updated") or "",
                                "title": title, "url": e.get("link", ""), "image": entry_image(e)})
        except Exception:
            continue
    return out


def fetch_moex_news() -> list[dict]:
    try:
        j = iss_json("/sitenews.json")
        cols = j["sitenews"]["columns"]
        out = []
        for row in j["sitenews"]["data"]:
            d = dict(zip(cols, row))
            t = (d.get("title") or "").strip()
            if t:
                out.append({"source": "MOEX", "published_at": str(d.get("published_at", "")),
                            "title": t, "url": ""})
        return out
    except Exception:
        return []


def fetch_all_news() -> list[dict]:
    items = fetch_rss() + fetch_moex_news()
    seen: set[str] = set()
    out = []
    for it in items:
        key = re.sub(r"\W+", " ", it["title"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def classify(title: str) -> str:
    t = title.lower()
    for cat, kws in CAT_RULES:
        if any(k in t for k in kws):
            return cat
    return "company"


def norm(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\W+", " ", title.lower())).strip()


def h(title: str) -> str:
    return hashlib.sha1(norm(title).encode("utf-8")).hexdigest()


def seen_hashes() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {r["h"] for r in data.get("seen", [])}
    except Exception:
        return set()


def mark_published(items: list[dict]) -> None:
    data: dict = {"seen": []}
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"seen": []}
    now = time.time()
    existing = {r["h"]: r["ts"] for r in data.get("seen", [])}
    for it in items:
        existing[h(it["title"])] = now
    existing = {k: v for k, v in existing.items() if now - v < 86400 * 7}
    data["seen"] = [{"h": k, "ts": v} for k, v in existing.items()]
    STATE_PATH.write_text(json.dumps(data), encoding="utf-8")


def _assess_chunk(items: list[dict]) -> dict[str, dict]:
    if not DEEPSEEK_API_KEY:
        return {}
    from openai import OpenAI

    numbered = "\n".join(f"{i + 1}. {it['title']}" for i, it in enumerate(items))
    system = (
        "Ты — финансовый редактор. Для каждой новости верни ТОЛЬКО валидный JSON-объект вида "
        '{"1": {"t": "фраза", "s": "up", "i": 2}, ...} для ВСЕХ пунктов, где: '
        't — оценка новости одной фразой (до 15 слов), что произошло и что это значит для рынка; '
        's — настроение для рынка: "up" (позитив), "down" (негатив), "flat" (нейтрально); '
        'i — влияние на рынок: 1 (низкое), 2 (среднее), 3 (высокое). '
        'Без лишнего текста. Без выдуманных цифр.'
    )
    client = OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY, timeout=90.0)
    try:
        r = client.chat.completions.create(
            model=DEEPSEEK_FLASH,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": numbered}],
            temperature=0.3, max_tokens=2000,
        )
        text = r.choices[0].message.content or ""
    except Exception:
        return {}
    out: dict[str, dict] = {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            for k, v in parsed.items():
                try:
                    idx = int(str(k)) - 1
                except ValueError:
                    continue
                if not (0 <= idx < len(items)):
                    continue
                if isinstance(v, str):
                    out[items[idx]["title"]] = {"note": v.strip(), "sent": "flat", "impact": 2}
                elif isinstance(v, dict):
                    note = (v.get("t") or "").strip()
                    sent = str(v.get("s") or "flat").lower()
                    if sent not in ("up", "down", "flat"):
                        sent = "flat"
                    try:
                        impact = int(v.get("i", 2))
                    except (TypeError, ValueError):
                        impact = 2
                    impact = max(1, min(3, impact))
                    if note:
                        out[items[idx]["title"]] = {"note": note, "sent": sent, "impact": impact}
            return out
        except json.JSONDecodeError:
            pass
    for k, v in re.findall(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        try:
            idx = int(k) - 1
        except ValueError:
            continue
        if 0 <= idx < len(items):
            out[items[idx]["title"]] = {"note": v.encode().decode("unicode_escape"), "sent": "flat", "impact": 2}
    return out


def assess(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(items), 10):
        out.update(_assess_chunk(items[i:i + 10]))
        if i + 10 < len(items):
            time.sleep(1.5)
    return out


def build_news(max_items: int = 40) -> list[dict]:
    items = fetch_all_news()
    seen = seen_hashes()
    fresh = [it for it in items if h(it["title"]) not in seen][:max_items]
    if not fresh:
        fresh = items[:max_items]
    top = fresh[:30]
    notes = assess(top)
    out = []
    now = time.time()
    for it in top:
        title = it["title"]
        ts = now
        try:
            p = (it.get("published_at") or "")[:10]
            ts = time.mktime(datetime.strptime(p, "%Y-%m-%d").timetuple())
        except Exception:
            pass
        a = notes.get(title, {})
        out.append({
            "cat": classify(title), "title": html.unescape(title), "text": a.get("note", ""),
            "sent": a.get("sent", "flat"), "impact": a.get("impact", 2),
            "time": datetime.fromtimestamp(ts).strftime("%H:%M") if ts != now else "",
            "ts": int(ts), "urgent": any(k in title.lower() for k in URGENT_KEYWORDS),
            "url": it.get("url", ""), "source": it.get("source", ""), "image": it.get("image", ""),
        })
    mark_published(top)
    return out


def build_digest(news: list[dict]) -> str:
    if not DEEPSEEK_API_KEY or not news:
        return ""
    from openai import OpenAI

    titles = "\n".join(f"- {n['title']}" for n in news[:25])
    client = OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY, timeout=90.0)
    try:
        r = client.chat.completions.create(
            model=DEEPSEEK_FLASH,
            messages=[
                {"role": "system", "content": "Ты — аналитик российского рынка. Дай сводку дня: 3-5 тезисов о том, что важно сегодня и как это влияет на рынок. По-русски, без воды, до 150 слов."},
                {"role": "user", "content": titles},
            ],
            temperature=0.4, max_tokens=800,
        )
        return (r.choices[0].message.content or "").strip()
    except Exception:
        return ""


def main() -> None:
    stocks = all_stocks()
    gainers = sorted([s for s in stocks if s["chg"] is not None and s["chg"] > 0], key=lambda x: -x["chg"])[:10]
    losers = sorted([s for s in stocks if s["chg"] is not None and s["chg"] < 0], key=lambda x: x["chg"])[:10]
    volatile = sorted([s for s in stocks if s["volatility"] is not None], key=lambda x: -x["volatility"])[:10]
    fx = all_fx()
    fx_chg = moex_fx_change()
    for item in fx:
        if item["sym"] in fx_chg:
            item["chg"] = fx_chg[item["sym"]]
    news = build_news()
    digest = build_digest(news)
    tb = load_tbank()
    data = {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "key_rate": key_rate().get("rate"),
        "indices": indexes(),
        "fx": fx,
        "metals": metals(),
        "commodities": commodities(),
        "stocks": stocks,
        "gainers": gainers,
        "losers": losers,
        "volatile": volatile,
        "trends": trends(),
        "bonds": tb.get("bonds", []),
        "referral_url": REFERRAL_URL,
        "news": news,
        "digest": digest,
        "calendar": calendar(),
        "volume": round(total_volume() / 1e9, 1),
        "movers_up": gainers[:4],
        "movers_down": losers[:4],
    }
    (SITE_DIR / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[data] индексов {len(data['indices'])}, акций {len(stocks)}, валют {len(data['fx'])}, "
          f"металлов {len(data['metals'])}, товаров {len(data['commodities'])}, новостей {len(news)} "
          f"(срочных {sum(1 for n in news if n['urgent'])}), дивидендов {len(data['calendar'])}, "
          f"сводка {'есть' if digest else 'нет'}")


if __name__ == "__main__":
    main()
