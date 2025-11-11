import os, json, urllib.parse, xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="News Research Chatbot", version="0.3")

# Allow Next.js on localhost:3000
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsResearchBot/0.3)"}

def fetch_news_gdelt(query: str, num: int = 5):
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "maxrecords": num, "format": "json", "sort": "datedesc"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        arts = []
        for a in data.get("articles", []):
            arts.append({
                "title": a.get("title"),
                "url": a.get("url"),
                "source": a.get("domain") or a.get("sourceCommonName")
            })
        return arts
    except Exception:
        return []

def fetch_news_google_rss(query: str, num: int = 5, lang="en-IN", region="IN"):
    """
    Fallback: Google News RSS (no API key). Parses XML and returns top links.
    """
    q = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={region}&ceid={region}:{lang.split('-')[0]}"
    try:
        r = requests.get(rss_url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        out = []
        for it in items[:num]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            source = (it.findtext("{http://news.google.com}source") or "")
            out.append({"title": title, "url": link, "source": source or "GoogleNews"})
        return out
    except Exception:
        return []

def fetch_news(query: str, num: int = 5):
    arts = fetch_news_gdelt(query, num)
    if arts:
        return arts
    return fetch_news_google_rss(query, num)

def scrape_text(url: str, max_chars: int = 900):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        return (text or "")[:max_chars]
    except Exception:
        return ""

@app.get("/")
def health():
    return {"ok": True, "service": "news-research-chatbot"}

@app.get("/chat")
def chat(query: str = Query(..., description="User question about news incident")):
    articles = fetch_news(query, num=5)
    if not articles:
        raise HTTPException(status_code=502, detail="No articles found from both providers.")

    docs = []
    for art in articles:
        snippet = scrape_text(art["url"])
        docs.append(f"Source: {art.get('source')}\nTitle: {art.get('title')}\nURL: {art.get('url')}\nText: {snippet}")

    system_prompt = (
        "You are a news research assistant. Summarize the incident ONLY from the provided sources; "
        "highlight agreements/disagreements and possible bias; keep dates/numbers exact; "
        "return JSON with keys: answer (string, 2-5 sentences), highlights (array of 3 bullets), sources (array of strings with Source+URL)."
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(docs)}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    content = completion.choices[0].message.content
    try:
        payload = json.loads(content)
    except Exception:
        payload = {"answer": content, "highlights": [], "sources": [d.splitlines()[0] for d in docs]}
    return JSONResponse(content=payload)
