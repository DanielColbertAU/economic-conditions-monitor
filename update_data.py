import csv, io, json, urllib.request, datetime, pathlib
SERIES={
 'aus_cli':('AUSLOLITOAASTSAM','Australia OECD leading indicator','index'),
 'us_curve':('T10Y2Y','US 10Y minus 2Y Treasury yield','percentage points'),
 'us_unemployment':('UNRATE','US unemployment rate','percent'),
 'us_credit':('BAMLH0A0HYM2','US high-yield option-adjusted spread','percentage points'),
 'us_vix':('VIXCLS','CBOE volatility index','index'),
 'us_industrial':('INDPRO','US industrial production','index'),
}
def main():
    data={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources':{},'errors':{}}
    for key,(sid,name,unit) in SERIES.items():
        url='https://fred.stlouisfed.org/graph/fredgraph.csv?id='+sid
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'ECM-Research-Dashboard/1.0'})
            with urllib.request.urlopen(req,timeout=30) as resp: content=resp.read().decode('utf-8-sig')
            rows=[]
            for row in csv.DictReader(io.StringIO(content)):
                v=row.get(sid,'')
                try: rows.append([row.get('DATE') or row.get('observation_date'),float(v)])
                except (ValueError,TypeError): pass
            if not rows: raise ValueError('No numeric observations')
            data['sources'][key]={'id':sid,'name':name,'unit':unit,'url':'https://fred.stlouisfed.org/series/'+sid,'observations':rows}
        except Exception as e: data['errors'][key]=str(e)
    path=pathlib.Path(__file__).parent/'data.json'
    if not data['sources'] and path.exists(): raise RuntimeError('No series fetched; retaining prior snapshot')
    if path.exists():
        old=json.loads(path.read_text())
        for k,v in old.get('sources',{}).items():
            if k not in data['sources']: data['sources'][k]=v
    path.write_text(json.dumps(data,separators=(',',':')))
    print('Updated',len(data['sources']),'series;',len(data['errors']),'fetch failures')
if __name__=='__main__': main()
