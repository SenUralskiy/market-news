from __future__ import annotations

import json
from datetime import date
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
BASE_URL = "https://senuralskiy.github.io/market-news"


def _write_sitemap() -> None:
    (SITE_DIR / "sitemap.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE_URL}/</loc><lastmod>{date.today().isoformat()}</lastmod><changefreq>always</changefreq><priority>1.0</priority></url>
</urlset>
""",
        encoding="utf-8",
    )


def _write_robots() -> None:
    (SITE_DIR / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: " + BASE_URL + "/sitemap.xml\n",
        encoding="utf-8",
    )


def main() -> None:
    data = json.loads((SITE_DIR / "data.json").read_text(encoding="utf-8"))
    template = (SITE_DIR / "site_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__DATA_JSON__", payload)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    _write_sitemap()
    _write_robots()
    print(f"[render] index.html записан, {len(data.get('news', []))} новостей")


if __name__ == "__main__":
    main()
