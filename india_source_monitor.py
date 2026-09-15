"""Daily official-report discovery and validated incremental coal refresh.

Discovery is distinct from numeric integration. Last good observations survive
network and parser failures; cached timestamps never stand in for report dates.
"""
from __future__ import annotations
import asyncio
import csv
import io
import json
import logging
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx
import pandas as pd
from pypdf import PdfReader

def parse_checked_coal(period, url, content):
    result={'period':period,'status':'provisional','source_url':url}
    raw_pages=[page.extract_text() or '' for page in PdfReader(io.BytesIO(content)).pages]
    pages=[text+'\n'+(raw_pages[i+1] if i+1<len(raw_pages) else '') for i,text in enumerate(raw_pages)]
    for metric,heading in [('production','Coal Production'),('dispatch','Coal Dispatch')]:
        candidates=[]
        for text in pages:
            if heading.lower() not in text.lower() or (metric=='production' and 'Coking Coal Production' in text):continue
            for total in re.finditer(r'Grand\s+Total',text,re.I):
                for window in [text[max(0,total.start()-350):total.start()],text[total.end():total.end()+220]]:
                    tokens=re.findall(r'[▲▼+-]?\s*\d+(?:\.\d+)?',window)
                    values=[float(re.sub(r'[^0-9.]','',v))*(-1 if '▼' in v or '-' in v else 1) for v in tokens]
                    for i in range(max(0,len(values)-12),len(values)-5):
                        current,prior,yoy,ytd,prior_ytd,ytd_yoy=values[i:i+6]
                        if not (40<current<150 and 40<prior<150 and ytd>=current and prior_ytd>=prior):continue
                        if abs((current/prior-1)*100-yoy)>.2 or abs((ytd/prior_ytd-1)*100-ytd_yoy)>.2:continue
                        candidates.append((current,prior,yoy,ytd))
        unique=set(candidates)
        if len(unique)!=1:raise ValueError(f'{metric}: national total could not be uniquely reconciled ({sorted(unique)})')
        current,prior,yoy,ytd=unique.pop()
        result.update({f'{metric}_mt':current,f'{metric}_prior_year_mt':prior,f'{metric}_yoy_pct':yoy,f'{metric}_ytd_mt':ytd})
    return result

SOURCES = [
    ("coal", "Coal production and dispatch", "https://coal.gov.in/public-information/monthly-statistics-at-glance", "Monthly", "incremental coal parser"),
    ("steel", "Steel production, consumption and trade", "https://steel.gov.in/monthly-summary?page=0", "Monthly", "report discovery; numeric extraction pending"),
    ("ports", "Major-port cargo traffic", "https://shipmin.gov.in/en/node/2017", "Monthly", "report discovery; numeric extraction pending"),
    ("trade", "DGCI&S commodity / country trade", "https://tradestat.commerce.gov.in/meidb/region_wise_all_commodities_import", "Monthly", "interactive official query; automated extraction pending"),
    ("power", "Electricity generation", "https://npp.gov.in/publishedReports", "Monthly", "existing NPP integration"),
    ("renewables", "Renewable electricity generation", "https://cea.nic.in/renewable-generation-report/?lang=en", "Monthly", "report discovery; existing historical series"),
]

def report_links(html, base):
    found=[]
    for href,label in re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>', html, re.I|re.S):
        url=urljoin(base,unescape(href))
        if urlparse(url).scheme not in {"https", "http"}: continue
        text=unescape(re.sub('<[^>]+>', ' ', label))
        text=' '.join(text.split())
        if re.search(r'\.(pdf|xls|xlsx)(?:[?#]|$)',url,re.I): found.append({"title":text or url.rsplit('/',1)[-1],"url":url})
    return list({r['url']:r for r in found}.values())[:40]

class IndiaSourceMonitor:
    def __init__(self, root: Path, cache: Path):
        self.root,self.cache=root,cache
        self.task=None
        self.lock=asyncio.Lock()
        try:self.payload=json.loads(cache.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.payload={}

    def start(self):
        if self.task is None:self.task=asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
            self.task=None

    async def run(self):
        while True:
            try:await self.refresh()
            except Exception:logging.getLogger(__name__).exception('India source monitor failed')
            await asyncio.sleep(86400)

    def response(self):
        return {**self.payload,"refresh_interval_hours":24,"sources": self.payload.get('sources') or [{"id":k,"label":label,"url":url,"frequency":freq,"integration":integration,"status":"Not checked"} for k,label,url,freq,integration in SOURCES]}

    async def refresh(self):
        async with self.lock:
            async with httpx.AsyncClient(timeout=25,follow_redirects=True) as client:
                async def discover(spec):
                    key,label,url,freq,integration=spec
                    item={"id":key,"label":label,"url":url,"frequency":freq,"integration":integration}
                    try:
                        response=await client.get(url);response.raise_for_status()
                        reports=report_links(response.text,url)
                        item.update(status='Reachable',reports=reports,checked_at=datetime.now(timezone.utc).isoformat())
                    except (httpx.HTTPError,ValueError):
                        previous=next((s for s in self.payload.get('sources',[]) if s['id']==key),{})
                        item.update(status='Fetch failed',reports=previous.get('reports',[]),checked_at=datetime.now(timezone.utc).isoformat(),last_success_at=previous.get('last_success_at') or previous.get('checked_at'),reports_cached=True)
                    return item
                sources=await asyncio.gather(*(discover(s) for s in SOURCES))
                coal=next(item for item in sources if item['id']=='coal')
                coal['refresh_result']=await self.refresh_coal(client,coal.get('reports',[]))
            self.payload={"checked_at":datetime.now(timezone.utc).isoformat(),"sources":sources}
            self.cache.parent.mkdir(parents=True,exist_ok=True)
            staging=self.cache.with_suffix('.tmp');staging.write_text(json.dumps(self.payload,indent=2),encoding='utf-8');staging.replace(self.cache)
            return self.response()

    async def refresh_coal(self, client, reports):
        path=self.root/'data/india_coal_master/canonical/coal_monthly_official.csv'
        if not path.exists():return {'status':'No baseline dataset'}
        frame=await asyncio.to_thread(pd.read_csv,path)
        latest=str(frame.period.max())
        months={name:i+1 for i,name in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'])}
        additions=[];failures=[]
        for report in reports:
            match=re.search(r'(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)[\s_%.-]*(20\d{2}|\d{2})(?!\d)',report['title']+' '+report['url'].rsplit('/',1)[-1],re.I)
            if not match:continue
            year=int(match[2]);year=year+2000 if year<100 else year
            period=f'{year}-{months[match[1][:3].lower()]:02d}'
            if period < latest or period >= datetime.now().strftime('%Y-%m'):continue
            try:
                res=await client.get(report['url']);res.raise_for_status()
                row=await asyncio.to_thread(parse_checked_coal,period,report['url'],res.content)
                if row.get('production_mt') is None:raise ValueError('No validated production value')
                additions.append(row)
            except (httpx.HTTPError,ValueError,KeyError):failures.append(period)
        if additions:
            # New missing fields cannot erase already validated observations.
            indexed=frame.set_index('period')
            for row in additions:
                period=row.pop('period')
                for key,value in row.items():
                    if value is not None:indexed.loc[period,key]=value
            output=indexed.sort_index().reset_index()
            staging=path.with_suffix('.tmp');await asyncio.to_thread(output.to_csv,staging,index=False,encoding='utf-8-sig');staging.replace(path)
            latest=str(output.period.max())
        return {'status':'Updated' if additions else 'No newer validated observations','latest_observation':latest,'validated_reports':len(additions),'failed_periods':failures}
