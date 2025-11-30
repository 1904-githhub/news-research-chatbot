# news-research-chatbot

<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>News Research Chatbot</title>
  <style>
    :root{
      --bg:#0b0b0c; --panel:#121316; --muted:#a9b0bb; --text:#e9edf2; --accent:#6ea8fe; --ok:#22c55e; --err:#ef4444;
      --shadow: 0 10px 30px rgba(0,0,0,.35);
      --radius: 16px;
    }
    @media (prefers-color-scheme: light){
      :root{ --bg:#f7f8fb; --panel:#fff; --muted:#5b6472; --text:#1b2430; --accent:#365ffd; --shadow:0 10px 30px rgba(0,0,0,.08) }
    }
    *{box-sizing:border-box}
    body{margin:0; background:var(--bg); color:var(--text); font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Ubuntu}
    .wrap{max-width:940px; margin:48px auto; padding:0 20px}
    .hero{display:flex; align-items:center; gap:14px; margin-bottom:22px}
    .logo{width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#9b7bff); box-shadow:var(--shadow)}
    h1{margin:0; font-size:32px; letter-spacing:.2px}
    .card{background:var(--panel); border:1px solid rgba(255,255,255,.06); border-radius:var(--radius); box-shadow:var(--shadow)}
    .panel{padding:20px}
    label{display:block; font-weight:600; margin:4px 0 8px}
    textarea{width:100%; min-height:130px; resize:vertical; padding:14px 16px; border-radius:12px; border:1px solid rgba(255,255,255,.12); background:transparent; color:var(--text); outline:none}
    textarea:focus{border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb, var(--accent) 28%, transparent)}
    .row{display:flex; gap:10px; align-items:center; margin-top:12px; flex-wrap:wrap}
    button{appearance:none; border:0; padding:10px 16px; border-radius:12px; background:var(--accent); color:white; font-weight:600; cursor:pointer}
    button:disabled{opacity:.6; cursor:not-allowed}
    .hint{color:var(--muted); font-size:13px}
    .grid{display:grid; grid-template-columns:2fr 1.2fr; gap:16px; margin-top:18px}
    @media (max-width:900px){ .grid{grid-template-columns:1fr} }
    .result{min-height:160px}
    .status{display:none; margin-top:10px; font-size:14px}
    .status.show{display:block}
    .pill{display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px; background:rgba(255,255,255,.06); font-size:12px; color:var(--muted)}
    .answer p{margin:0 0 10px}
    ul{margin:8px 0 0 18px}
    a{color:var(--accent); text-decoration:none}
    a:hover{text-decoration:underline}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,Monaco,monospace}
    .hl{padding:10px 12px; border:1px dashed rgba(255,255,255,.12); border-radius:12px; margin-bottom:8px}
    .error{color:var(--err)}
    .ok{color:var(--ok)}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="logo"></div>
      <h1>News Research Chatbot</h1>
    </div>

    <div class="card panel">
      <label for="q">Your question</label>
      <textarea id="q" placeholder="e.g. Chandrayaan-3 updates, Apple antitrust case, Israel–Lebanon border latest...">Chandrayaan 3 updates</textarea>
      <div class="row">
        <button id="ask">Ask</button>
        <span class="pill mono" id="backend-pill">API: <span id="api-host">…</span></span>
        <span class="hint">Summaries are generated from live sources (Google News/GDELT) via your FastAPI backend.</span>
      </div>
    </div>

    <div class="grid">
      <div class="card panel result">
        <div class="status" id="status"></div>
        <div id="answer" class="answer"></div>
        <div id="highlights"></div>
      </div>

      <div class="card panel">
        <div style="font-weight:700; margin-bottom:6px;">Sources</div>
        <div id="sources" class="mono" style="font-size:14px; white-space:normal;"></div>
      </div>
    </div>
  </div>

  <script>
    // ======== CONFIG ========
    const BACKEND = "https://news-research-chatbot.onrender.com"; // ⬅️ your Render URL
    // ========================

    const askBtn = document.getElementById('ask');
    const outAns = document.getElementById('answer');
    const outHL  = document.getElementById('highlights');
    const outSrc = document.getElementById('sources');
    const status = document.getElementById('status');
    document.getElementById('api-host').textContent = new URL(BACKEND).host;

    function setStatus(msg, type="info"){
      status.className = "status show " + (type==="error"?"error":"ok");
      status.textContent = msg;
    }
    function clearStatus(){ status.className="status"; status.textContent=""; }

    function linkifySources(list){
      if(!Array.isArray(list) || !list.length) return "<span class='hint'>No sources returned.</span>";
      return "<ul>" + list.map(s=>{
        // s format: "Outlet: URL"
        const idx = s.indexOf(": ");
        const outlet = idx>0 ? s.slice(0, idx) : "Source";
        const url = idx>0 ? s.slice(idx+2) : s;
        try { new URL(url); } catch { return `<li>${outlet}</li>`; }
        return `<li><a href="${url}" target="_blank" rel="noopener">${outlet}</a></li>`;
      }).join("") + "</ul>";
    }

    function render(data){
      const d = typeof data==="string" ? JSON.parse(data) : data;
      outAns.innerHTML = d.answer ? `<p>${d.answer}</p>` : "<span class='hint'>No answer.</span>";
      if(Array.isArray(d.highlights) && d.highlights.length){
        outHL.innerHTML = "<div style='font-weight:700;margin:12px 0 6px'>Highlights</div>" +
          d.highlights.map(h=>`<div class="hl">• ${h}</div>`).join("");
      }else{
        outHL.innerHTML = "";
      }
      outSrc.innerHTML = linkifySources(d.sources||[]);
    }

    async function ask(){
      const q = document.getElementById('q').value.trim();
      if(!q) return;
      askBtn.disabled = true;
      outAns.innerHTML = ""; outHL.innerHTML = ""; outSrc.innerHTML = "";
      setStatus("Fetching news & generating summary…");

      try{
        const url = new URL("/chat", BACKEND);
        url.searchParams.set("query", q);
        const res = await fetch(url);
        const text = await res.text();
        if(!res.ok) throw new Error(text || res.statusText);
        render(text);
        setStatus("Done ✓","ok");
        setTimeout(clearStatus, 1500);
      }catch(err){
        setStatus("Error: " + err.message, "error");
        outAns.innerHTML = `<pre class="mono" style="background:rgba(255,0,0,.08);padding:12px;border-radius:12px">${(err.stack||err.message)}</pre>`;
      }finally{
        askBtn.disabled = false;
      }
    }

    askBtn.addEventListener('click', ask);
    // Optional: submit with ⌘/Ctrl+Enter
    document.getElementById('q').addEventListener('keydown', e=>{
      if((e.metaKey||e.ctrlKey) && e.key==="Enter"){ ask(); }
    });
  </script>
</body>
</html>
