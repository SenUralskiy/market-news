from __future__ import annotations

import json
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent


def main() -> None:
    data = json.loads((SITE_DIR / "data.json").read_text(encoding="utf-8"))
    template = (SITE_DIR / "site_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__DATA_JSON__", payload)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"[render] index.html записан, {len(data.get('news', []))} новостей")


if __name__ == "__main__":
    main()
