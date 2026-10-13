"""Explicit localhost-only preview; not registered in production app startup."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from app.repositories.forecasts import ForecastRepository
from app.services.forecasts import ForecastService
from app.services.errors import ServiceError

RESULTS = Path(__file__).resolve().parents[2] / 'data/artifacts/forecasting/walkforward-xgboost-2026-09-18'
PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>StockSense local demo</title>
<style>body{font:16px system-ui;background:#f5f7fb;color:#17243b;padding:24px}main{max-width:1000px;margin:auto}
input,button{font:inherit;padding:10px;border-radius:6px;border:1px solid #a6b4c8}button{background:#203b70;color:white}
label{display:block;margin:20px 0 8px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
article{background:white;padding:20px;border:1px solid #ccd5e1;border-radius:12px}.note{background:#fff4d6;padding:16px}#status{white-space:pre-line}dt{font-weight:600}dd{margin:4px 0 16px}</style>
<main><h1>StockSense forecast demo</h1><p class="note">Local preview only. No login or database.
Manual ticker selection until the recommender is connected. Saved experimental forecasts, not live prices or financial advice.</p>
<form id="form"><label for="tickers">Selected tickers, separated by commas</label><input id="tickers" value="AAPL,NVDA" maxlength="1600" required>
<button>Show forecasts</button></form><p id="status" role="status" aria-live="polite"></p><div id="cards" class="cards"></div></main>
<script>
const status=document.getElementById('status'),cards=document.getElementById('cards'),pct=v=>(v*100).toFixed(2)+'%';
document.getElementById('form').addEventListener('submit',async e=>{e.preventDefault();cards.replaceChildren();status.textContent='Loading…';
try{const tickers=[...new Set(document.getElementById('tickers').value.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean))];
const res=await fetch('/api/forecasts?tickers='+encodeURIComponent(tickers.join(',')));const data=await res.json();
if(!res.ok)throw new Error(data.detail||'Unable to load forecasts');
status.textContent='Model: '+data.model+' | Snapshot: '+data.as_of+'\nNominal coverage: '+pct(data.nominal_coverage)+
(data.empirical_coverage!==null?' | Retrospective coverage: '+pct(data.empirical_coverage):'')+
'\nUncertainty width is in percentage points, not confidence or accuracy.'+
(data.unavailable_tickers.length?'\nUnavailable: '+data.unavailable_tickers.join(', '):'');
for(const f of data.forecasts){const article=document.createElement('article'),title=document.createElement('h2');title.textContent=f.ticker;article.append(title);
const dl=document.createElement('dl');for(const [label,value] of [['Forecast origin',f.date],['10-session predicted return',pct(f.predicted_return_10d)],
['Prediction interval',pct(f.lower_return)+' to '+pct(f.upper_return)],['Uncertainty width',f.uncertainty_width_pp.toFixed(2)+' percentage points'],
['Data status',f.stale_snapshot?'Stale snapshot':'Recent snapshot']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dl.append(dt,dd);}article.append(dl);cards.append(article);}
}catch(err){status.textContent=err.message;}});document.getElementById('form').requestSubmit();
</script></html>'''

class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request=urlparse(self.path)
        if request.path=='/':
            self.reply(200,PAGE.encode(),'text/html; charset=utf-8'); return
        if request.path!='/api/forecasts':
            self.reply(404,b'{"detail":"Not found"}'); return
        selected=parse_qs(request.query).get('tickers',[''])[0].split(',')
        try:
            payload=ForecastService(ForecastRepository(RESULTS)).get_snapshot(selected).model_dump(mode='json'); code=200
        except ServiceError as exc:
            payload,code={'detail':str(exc)},exc.status_code
        self.reply(code,json.dumps(payload,allow_nan=False).encode())

    def reply(self,code,body,content_type='application/json'):
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(body)

    def log_message(self,*_):
        pass

if __name__=='__main__':
    # Fixed loopback binding. This server does not replace app.main or real auth.
    server=HTTPServer(('127.0.0.1',8001),DemoHandler)
    print('Local forecast demo: http://127.0.0.1:8001',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
