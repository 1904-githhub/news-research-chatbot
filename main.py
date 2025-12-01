# main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your GitHub Pages URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
import os, json, time, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = FastAPI(title="News Research Chatbot", version="0.4")

# CORS: allow local dev + GitHub Pages
ALLOWED_ORIGINS = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:3002", "http://127.0.0.1:3002",
    "http://localhost:3003", "http://127.0.0.1:3003",
    "https://santosh559.github.io",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://santosh559\.github\.io.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsResearchBot/0.4)"}

# --- simple in-memory cache ---
_CACHE = {}
TTL = 600
def cache_get(k):
    v = _CACHE.get(k)
    if not v: return None
    data, ts = v
    if time.time() - ts > TTL: _CACHE.pop(k, None); return None
    return data
def cache_set(k, data): _CACHE[k] = (data, time.time())

# --- news fetchers ---
def fetch_news_google_rss(query: str, num: int = 4, lang="en-IN", region="IN"):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={region}&ceid={region}:{lang.split('-')[0]}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        out = []
        for it in items[:num]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            source = (it.findtext("{http://news.google.com}source") or "GoogleNews").strip()
            out.append({"title": title, "url": link, "source": source})
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
    except Exception:
        return []

def fetch_news(query: str, num: int = 4):
    arts = fetch_news_google_rss(query, num=num)
    if len(arts) < num:
        more = fetch_news_gdelt(query, num=num)
        seen = {a["url"] for a in arts}
        arts.extend([m for m in more if m["url"] not in seen])
    return arts[:num]

# --- scraping ---
def scrape_text(url: str, max_chars: int = 800):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        return (text or "")[:max_chars]
    except Exception:
        return ""

def parallel_snippets(urls, max_workers=6):
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(scrape_text, u): u for u in urls}
        for fut in as_completed(futs):
            u = futs[fut]
            try: out[u] = fut.result()
            except Exception: out[u] = ""
    return out

# --- routes ---
@app.get("/")
def health():
    return {"ok": True, "service": "news-research-chatbot", "cache": len(_CACHE)}

@app.get("/chat")
def chat(query: str = Query(..., description="User question about news incident")):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing in backend environment")

    key = f"q:{query}"
    cached = cache_get(key)
    if cached: return JSONResponse(content=cached)

    articles = fetch_news(query, num=4)
    if not articles:
        raise HTTPException(status_code=502, detail="No articles found from providers.")

    urls = [a["url"] for a in articles]
    snippets = parallel_snippets(urls)

    docs = []
    for a in articles:
        docs.append(
            f"Source: {a['source']}\nTitle: {a['title']}\nURL: {a['url']}\nText: {snippets.get(a['url'], '')}"
        )

    system = (
        "You are a news research assistant. Summarize the incident ONLY from the provided sources; "
        "be precise with dates/numbers; note contradictions if any; "
        "Return JSON: {answer: string (2-5 sentences), highlights: string[3], sources: string[] as 'Outlet: URL'}."
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":system},{"role":"user","content":"\n\n".join(docs)}],
        response_format={"type":"json_object"},
        temperature=0.2,
    )

    try:
        payload = json.loads(completion.choices[0].message.content)
    except Exception:
        payload = {"answer": completion.choices[0].message.content,
                   "highlights": [],
                   "sources": [f"{a['source']}: {a['url']}" for a in articles]}

    cache_set(key, payload)
    return JSONResponse(content=payload)
