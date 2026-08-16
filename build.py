from __future__ import annotations

import hashlib
import html
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
TRADING_ROOT = Path(r"D:\traiding")
sys.path.insert(0, str(TRADING_ROOT))
sys.path.insert(0, str(TRADING_ROOT / "src"))

from config.settings import settings  # noqa: E402
from traiding.news.sources import fetch_all  # noqa: E402

DB_PATH = SITE_DIR / "published.db"
MAX_ITEMS = 60
TOP_N = 30
SITE_TITLE = "Рынок сегодня"
SITE_SUBTITLE = "Новости рынка и ценных бумаг с короткой оценкой ИИ"


def normalize(title: str) -> str:
    t = re.sub(r"\W+", " ", title.lower()).strip()
    return re.sub(r"\s+", " ", t)


def title_hash(title: str) -> str:
    return hashlib.sha1(normalize(title).encode("utf-8")).hexdigest()


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS published (hash TEXT PRIMARY KEY, title TEXT, source TEXT, published_at TEXT)"
    )
    return c


def seen_hashes() -> set[str]:
    c = _conn()
    out = {r[0] for r in c.execute("SELECT hash FROM published")}
    c.close()
    return out


def mark_published(items: list[dict]) -> None:
    c = _conn()
    c.executemany(
        "INSERT OR IGNORE INTO published (hash, title, source, published_at) VALUES (?, ?, ?, ?)",
        [(title_hash(i["title"]), i["title"], i["source"], i["published_at"]) for i in items],
    )
    c.commit()
    c.close()


def _assess_chunk(items: list[dict]) -> dict[str, str]:
    if not settings.deepseek_api_key or not items:
        return {}
    numbered = "\n".join(f"{i + 1}. {it['title']}" for i, it in enumerate(items))
    system = (
        "Ты — финансовый редактор. Для каждой новости дай ровно одну короткую фразу (до 15 слов) "
        "на русском: что произошло и что это значит для рынка. Верни ТОЛЬКО валидный JSON-объект "
        'вида {"1": "фраза", "2": "фраза", ...} — для ВСЕХ пунктов, без лишнего текста. Без выдуманных цифр.'
    )
    from openai import OpenAI

    client = OpenAI(base_url=settings.deepseek_base_url, api_key=settings.deepseek_api_key, timeout=90.0)
    try:
        r = client.chat.completions.create(
            model=settings.deepseek_flash_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": numbered}],
            temperature=0.3,
            max_tokens=1500,
        )
        text = r.choices[0].message.content or ""
    except Exception as e:
        print(f"[assess] ошибка: {e}")
        return {}

    out: dict[str, str] = {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        import json

        try:
            parsed = json.loads(m.group(0))
            for k, v in parsed.items():
                try:
                    idx = int(str(k)) - 1
                except ValueError:
                    continue
                if 0 <= idx < len(items) and isinstance(v, str) and v.strip():
                    out[items[idx]["title"]] = v.strip()
            return out
        except json.JSONDecodeError:
            pass
    pairs = re.findall(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    for k, v in pairs:
        try:
            idx = int(k) - 1
        except ValueError:
            continue
        if 0 <= idx < len(items):
            out[items[idx]["title"]] = v.encode().decode("unicode_escape")
    return out


def assess(items: list[dict]) -> dict[str, str]:
    """Батч-оценка DeepSeek по частям (по 10 пунктов), чтобы ответ не обрезался."""
    import time

    out: dict[str, str] = {}
    for i in range(0, len(items), 10):
        chunk = items[i:i + 10]
        got = _assess_chunk(chunk)
        out.update(got)
        print(f"[assess] {i + 1}-{i + len(chunk)}: {len(got)}/{len(chunk)}")
        if i + 10 < len(items):
            time.sleep(2)
    return out


def render(items: list[dict], notes: dict[str, str]) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    cards = []
    for it in items:
        note = notes.get(it["title"], "")
        source = html.escape(it["source"])
        title = html.escape(html.unescape(it["title"]))
        date = html.escape(str(it["published_at"])[:10])
        url = html.escape(it.get("url", ""))
        note_html = f'<div class="note">{html.escape(note)}</div>' if note else ""
        link_html = f'<a class="src" href="{url}" target="_blank" rel="noopener">{source}</a>' if url else f'<span class="src">{source}</span>'
        cards.append(
            f"""
    <article class="card">
      <div class="meta">{date} · {link_html}</div>
      <h2>{title}</h2>
      {note_html}
    </article>"""
        )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{SITE_TITLE}</title>
<style>
:root {{ --bg:#0f1117; --card:#181b24; --text:#e7e9ee; --muted:#8b90a0; --accent:#4da3ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }}
header {{ padding:32px 20px 20px; max-width:820px; margin:0 auto; }}
header h1 {{ margin:0 0 6px; font-size:28px; }}
header .sub {{ color:var(--muted); font-size:14px; }}
main {{ max-width:820px; margin:0 auto; padding:0 20px 60px; }}
.card {{ background:var(--card); border-radius:12px; padding:18px 20px; margin-bottom:14px; }}
.card h2 {{ margin:0 0 8px; font-size:18px; font-weight:600; }}
.meta {{ color:var(--muted); font-size:12px; margin-bottom:8px; }}
.src {{ color:var(--accent); text-decoration:none; }}
.src:hover {{ text-decoration:underline; }}
.note {{ color:var(--text); font-size:14px; border-left:3px solid var(--accent); padding-left:12px; margin-top:4px; }}
footer {{ max-width:820px; margin:0 auto; padding:0 20px 40px; color:var(--muted); font-size:12px; }}
.disclaimer {{ color:var(--muted); font-size:11px; margin-top:8px; }}
</style>
</head>
<body>
<header>
  <h1>{SITE_TITLE}</h1>
  <div class="sub">{SITE_SUBTITLE} · обновлено {now}</div>
</header>
<main>
{"".join(cards)}
</main>
<footer>
  <div class="disclaimer">Контент сгенерирован автоматически на основе публичных источников. Не является индивидуальной инвестиционной рекомендацией.</div>
</footer>
</body>
</html>"""


def main() -> None:
    items = fetch_all()
    if not items:
        print("Новости не загрузились")
        return

    seen = seen_hashes()
    fresh = [it for it in items if title_hash(it["title"]) not in seen][:MAX_ITEMS]
    print(f"Всего новостей: {len(items)}, новых: {len(fresh)}")

    if not fresh:
        print("Новых новостей нет, оставляю текущий index.html")
        return

    notes = assess(fresh[:TOP_N])
    page = render(fresh[:TOP_N], notes)
    (SITE_DIR / "index.html").write_text(page, encoding="utf-8")
    mark_published(fresh[:TOP_N])
    print(f"index.html обновлён ({len(fresh[:TOP_N])} постов, оценок: {len(notes)})")


if __name__ == "__main__":
    main()
