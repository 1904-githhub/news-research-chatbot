import os, json, time, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from dotenv import load_dotenv

# Load env (.env file for Render/Local)
load_dotenv(dotenv_path=Path(_file_).with_name(".env"))

# ----------------------------------------------------------
# FASTAPI APP (MUST BE AT THE TOP BEFORE CORS)
# ----------------------------------------------------------
app = FastAPI(title="News Research Chatbot", version="1.0")

# ----------------------------------------------------------
# CORS — ALLOW FRIEND'S GITHUB PAGES
# ----------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://1904-github.github.io",               # Friend's GitHub main domain
        "https://1904-github.github.io/news-research-chatbot",  # Project path
    ],
    allow_origin_regex=r"https://1904-github\.github\.io.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------
# OPENAI CLIENT
# ----------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY missing in Render environment variables!")

client = OpenAI(api_key=OPENAI_API_KEY)

# ----------------------------------------------------------
# CACHE
# ----------------------------------------------------------
_CACHE = {}
TTL = 600

def cache_get(k):
    v = _CACHE.get(k)
    if not v:
        return None
    data, ts = v
    if time.time() - ts > TTL:
        _CACHE.pop(k, None)
        return None
    return data

def cache_set(k, data):
    _CACHE[k] = (data, time.time())

# ----------------------------------------------------------
# HEADERS
# ----------------------------------------------------------
HEADERS = {"User-Agent": "Mozilla/5.0 (NewsResearchBot/1.0)"}

# ----------------------------------------------------------
# FETCH NEWS
# ----------------------------------------------------------
def fetch_news_google_rss(query: str, num: int = 4, lang="en-IN", region="IN"):
    q = urllib.parse.quote(query)
    url = (
        f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={region}"
        f"&ceid={region}:{lang.split('-')[0]}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        out = []
        for it in items[:num]:
            out.append({
                "title": (it.findtext("title") or "").strip(),
                "url": (it.findtext("link") or "").strip(),
                "source": (it.findtext("{http://news.google.com}source") or "Google News")
            })
        return out
    except Exception:
        return []

def fetch_news_gdelt(query: str, num: int = 4):
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "maxrecords": num, "format": "json", "sort": "datedesc"}

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=6)
        r.raise_for_status()
        data = r.json()
        out = []

        for a in data.get("articles", []):
            out.append({
                "title": a.get("title"),
                "url": a.get("url"),
                "source": a.get("domain") or a.get("sourceCommonName") or "GDELT"
            })
        return out[:num]
    except:
        return []

def fetch_news(query: str, num: int = 4):
    articles = fetch_news_google_rss(query, num)
    if len(articles) < num:
        more = fetch_news_gdelt(query, num)
        seen = {a["url"] for a in articles}
        articles.extend([m for m in more if m["url"] not in seen])
    return articles[:num]

# ----------------------------------------------------------
# SCRAPER
# ----------------------------------------------------------
def scrape_text(url: str, max_chars: int = 800):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        return text[:max_chars]
    except:
        return ""

def parallel_snippets(urls, max_workers=6):
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(scrape_text, u): u for u in urls}
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                out[u] = fut.result()
            except:
                out[u] = ""
    return out

# ----------------------------------------------------------
# ROUTES
# ----------------------------------------------------------
@app.get("/")
def health():
    return {"ok": True, "service": "news-research-chatbot", "cache": len(_CACHE)}

@app.get("/chat")
def chat(query: str = Query(..., description="News incident to analyze")):

    key = f"cache:{query}"
    cached = cache_get(key)
    if cached:
        return JSONResponse(content=cached)

    articles = fetch_news(query, num=4)
    if not articles:
        raise HTTPException(status_code=502, detail="No articles found.")

    urls = [a["url"] for a in articles]
    snippets = parallel_snippets(urls)

    docs = []
    for a in articles:
        docs.append(
            f"Source: {a['source']}\nTitle: {a['title']}\nURL: {a['url']}\nText: {snippets.get(a['url'], '')}"
        )

    system_msg = (
        "You are a news research expert. Summarize the event STRICTLY using the provided sources. "
        "Return JSON with: answer (3–5 sentences), highlights (3 bullet points), and sources."
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "\n\n".join(docs)},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    try:
        output = json.loads(completion.choices[0].message.content)
    except:
        output = {"answer": completion.choices[0].message.content, "highlights": [], "sources": []}

    cache_set(key, output)
    return JSONResponse(content=output)
