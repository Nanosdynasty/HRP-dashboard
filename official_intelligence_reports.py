"""Public official publication discovery; evidence is extracted only on request."""
import asyncio
import io
import re
from datetime import datetime,timezone
from urllib.parse import urljoin,urlsplit
import httpx
from pypdf import PdfReader
from intelligence_archive import enrich

SOURCES=[{'id':'usda_reports','name':'USDA AMS Grain Transportation Reports','url':'https://www.ams.usda.gov/resources/grain-transportation-reports','topics':['cargo_trade','chartering'],'commodity_groups':['grains_agri']},{'id':'unctad_reports','name':'UNCTAD Review of Maritime Transport','url':'https://unctad.org/topic/transport-and-trade-logistics/review-of-maritime-transport','topics':['dry_bulk','policy'],'commodity_groups':[]}]
ALLOWED={'www.ams.usda.gov','ams.usda.gov','unctad.org','www.unctad.org','apps.ams.usda.gov'}

def discover(source,html):
    rows=[];seen=set()
    for match in re.finditer(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>',html,re.I|re.S):
        link=urljoin(source['url'],match[1]);title=re.sub(r'<[^>]+>',' ',match[2]);title=re.sub(r'\s+',' ',title).strip()
        if urlsplit(link).hostname not in ALLOWED or link in seen:continue
        if not (urlsplit(link).path.lower().endswith('.pdf') or '/publication/' in link):continue
        if not title or len(title)<8:title=urlsplit(link).path.split('/')[-1]
        if not re.search(r'grain|transport|gtr|maritime|rmt',title+' '+link,re.I):continue
        if source['id']=='usda_reports' and 'grain' not in title.lower():title='Grain Transportation Report — '+title
        seen.add(link);date=None;period=None
        g=re.search(r'GTR(\d{2})(\d{2})(20\d{2}|\d{2})',link,re.I)
        if g:
            try:date=datetime(int(g[3]) if len(g[3])==4 else 2000+int(g[3]),int(g[1]),int(g[2]),tzinfo=timezone.utc).isoformat()
            except ValueError:pass
        year=re.search(r'20\d{2}',title+' '+link)
        if year:period=year[0]
        rows.append(enrich({'title':title,'description':'Official publication. Open the original or review an accessible PDF for page-linked evidence.','link':link,'published_at':date,'date_precision':'day' if date else 'not supplied','reporting_period':period,'source_name':source['name'],'provider_id':source['id'],'provider_name':'Official publication index','content_type':'report','topics':source['topics'],'commodity_groups':source['commodity_groups'],'relevance_score':5,'relevance_reason':'Official research publication','evidence_level':'metadata only','source_index_url':source['url']}))
    return rows[:80]

async def collect_reports():
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as c:
        async def one(source):
            try:
                if source['id']=='usda_reports':
                    year=datetime.now(timezone.utc).year
                    pages=await asyncio.gather(*(c.get(f'https://www.ams.usda.gov/services/transportation-analysis/gtr/archive-{y}') for y in (year,year-1)))
                    rows=[]
                    for response in pages:
                        response.raise_for_status();rows.extend(discover(source,response.text))
                else:
                    response=await c.get(source['url']);response.raise_for_status();rows=discover(source,response.text)
                return rows,{**source,'status':'healthy' if rows else 'healthy with no parsed reports','discovered':len(rows),'checked_at':datetime.now(timezone.utc).isoformat()}
            except Exception as exc:return [],{**source,'status':'failed','error':str(exc),'discovered':0}
        results=await asyncio.gather(*(one(s) for s in SOURCES))
    return [r for rows,_ in results for r in rows],[s for _,s in results]

async def document_evidence(row):
    url=row['link']
    if urlsplit(url).hostname not in ALLOWED or not urlsplit(url).path.lower().endswith('.pdf'):raise ValueError('This item is a publication link. Open the original; automatic PDF review is available only for allowlisted official PDF URLs.')
    async with httpx.AsyncClient(timeout=40,follow_redirects=False) as c:
        for attempt in range(4):
            if urlsplit(url).hostname not in ALLOWED:raise ValueError('Document redirects outside the official source allowlist')
            async with c.stream('GET',url) as response:
                if response.is_redirect:
                    url=urljoin(url,response.headers['location']);continue
                response.raise_for_status();parts=[];size=0
                async for chunk in response.aiter_bytes():
                    size+=len(chunk)
                    if size>12_000_000:raise ValueError('Document exceeds the 12 MB review limit; open the original')
                    parts.append(chunk)
                data=b''.join(parts);break
        else:raise ValueError('Too many document redirects')
    if not data.startswith(b'%PDF'):raise ValueError('Source did not return a PDF document')
    def extract():
        pdf=PdfReader(io.BytesIO(data));evidence=[]
        for i,page in enumerate(pdf.pages[:100]):
            text=re.sub(r'\s+',' ',page.extract_text() or '').strip()
            if text:evidence.append({'page':i+1,'excerpt':text[:3000],'source_url':url+'#page='+str(i+1)})
        return {**row,'evidence_level':'document text reviewed' if len(pdf.pages)<=100 else 'first 100 pages reviewed','document_reviewed_at':datetime.now(timezone.utc).isoformat(),'document_evidence':evidence,'document_hash':__import__('hashlib').sha256(data).hexdigest(),'document_pages':len(pdf.pages),'review_note':'Extracted source text, not a generated executive summary. Tables require contextual review.'}
    return await asyncio.to_thread(extract)
