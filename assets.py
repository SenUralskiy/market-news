from __future__ import annotations

import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

SITE_DIR = Path(__file__).resolve().parent
load_dotenv()
load_dotenv(Path(r"D:\traiding\.env"))

AGNES_BASE = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
AGNES_KEY = os.getenv("AGNES_API_KEY", "")
AGNES_IMG = os.getenv("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash")
ASSETS = SITE_DIR / "assets"

PROMPTS = {
    "hero": (
        "Dark futuristic financial news banner. Abstract glowing candlestick charts ascending, "
        "Moscow City skyline silhouette at night, deep navy and charcoal palette, subtle amber accents, "
        "professional stock trading terminal atmosphere, cinematic lighting, wide composition, no text"
    ),
    "macro": "Macroeconomic concept: central bank building and interest rate arrow, dark moody finance illustration, navy and amber, no text",
    "oil": "Oil pump jack silhouette at dusk with a red sun, energy sector, dark industrial finance illustration, no text",
    "fx": "Currency exchange concept: dollar, euro and yuan banknotes with a rate chart, dark finance illustration, no text",
    "bond": "Government bonds and paper certificates with a rising yield curve, dark finance illustration, no text",
    "index": "Stock index graph ascending on trading floor screens, dark finance illustration, no text",
    "commodity": "Gold bars and silver coins, precious metals, dark moody finance illustration, no text",
    "company": "Glass corporate skyscrapers at night, business headquarters, dark finance illustration, no text",
}


def generate(prompt: str, path: Path) -> None:
    from openai import OpenAI

    if not AGNES_KEY:
        print("AGNES_API_KEY не задан — пропускаю")
        return
    client = OpenAI(base_url=AGNES_BASE, api_key=AGNES_KEY, timeout=240)
    r = client.images.generate(model=AGNES_IMG, prompt=prompt, size="1024x1024", n=1)
    d = r.data[0]
    if getattr(d, "b64_json", None):
        img = base64.b64decode(d.b64_json)
    elif getattr(d, "url", None):
        img = requests.get(d.url, timeout=90).content
    else:
        print(f"[agnes] нет данных для {path.name}")
        return
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(img)).convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "WEBP", quality=80, method=6)
    print(f"[agnes] сохранено {path} ({path.stat().st_size // 1024} КБ)")


def main() -> None:
    for name, prompt in PROMPTS.items():
        generate(prompt, ASSETS / f"{name}.webp")


if __name__ == "__main__":
    main()
