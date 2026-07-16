# Reading Digest

A simple daily digest of interesting articles from Hacker News and a few quality publications.

After you push this repo to GitHub, enable **Settings → Pages → Deploy from branch → `/docs`**.
The live page will be `docs/index.html`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/update.py
```

Regenerate the page without fetching:

```bash
python scripts/update.py --skip-fetch
```

Preview locally:

```bash
python -m http.server 8000 --directory docs
# open http://localhost:8000
```

## Data

Articles are stored in [`data/articles.json`](data/articles.json) as:

```json
{
  "articles": [
    {
      "title": "Example title",
      "text": "Short summary or snippet",
      "url": "https://example.com/article"
    }
  ]
}
```

The static page at [`docs/index.html`](docs/index.html) embeds this list as simple cards (title, text, URL).

## Customize

- Topics and fetch limits: [`config/interests.yaml`](config/interests.yaml)
- Publication domains: [`config/sources.txt`](config/sources.txt)

## Automation

GitHub Actions (`.github/workflows/update-articles.yml`) runs daily at 08:00 UTC and on manual dispatch. It fetches articles, regenerates `docs/index.html`, and commits changes to `data/articles.json` and `docs/index.html`.
