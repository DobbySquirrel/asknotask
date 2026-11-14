"""Optional paid parser replay. Credentials from environment only; frozen outputs are never overwritten."""
import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from common import load,dump
def parse_sql(content):
    if isinstance(content, list):
        content = '\n'.join(x.get('text', '') for x in content if isinstance(x, dict))
    content = content or ''
    fenced = re.search(r'```(?:sql|sqlite)?\s*(.*?)```', content, re.I | re.S)
    text = fenced.group(1).strip() if fenced else content.strip()
    start = re.search(r'\b(?:SELECT|WITH)\b', text, re.I)
    return text[start.start():].strip().rstrip(';') if start else ''

def request_once(job, key):
    request = urllib.request.Request(job['base_url'].rstrip('/') + '/chat/completions',
        data=json.dumps(job['request'], ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    started = time.monotonic()
    # Match the working native HTTPS route. The Windows registry's local proxy
    # terminates this host's Python TLS connection; keep certificate validation on.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=180) as response:
                body = json.loads(response.read().decode('utf-8'))
            content = body['choices'][0]['message'].get('content')
            result = {'request_key': job['request_key'], 'id': job['id'], 'side': job['side'], 'cohort_first_request': job['cohort'],
                'requested_model': job['request']['model'], 'response_model': body.get('model'),
                'response_id': body.get('id'), 'usage': body.get('usage'),
                'finish_reason': body['choices'][0].get('finish_reason'), 'content': content,
                'predicted_sql': parse_sql(content), 'elapsed_seconds': round(time.monotonic() - started, 3),
                'completed_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'transport_attempts': attempt + 1}
            if key in json.dumps(result, ensure_ascii=False):
                raise RuntimeError('Credential unexpectedly reflected by service; response not saved')
            dump(OUT / 'responses' / (job['request_key'] + '.json'), result)
            return result
        except urllib.error.HTTPError as exc:
            status = exc.code
            # Do not log headers or response body that could reflect credentials.
            if status not in [429, 500, 502, 503, 504] or attempt == 2:
                raise RuntimeError(f'API HTTP {status}') from None
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, 'reason', None)
            code = getattr(reason, 'winerror', getattr(reason, 'errno', None))
            if attempt == 2 or code in [10013, 13]:
                raise RuntimeError(f'API connection failure ({type(reason).__name__}, code={code})') from None
            time.sleep(2 ** attempt)

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser(description=__doc__);p.add_argument("--requests",type=Path,default=root/"outputs/user_study/analysis_results/requests.json");p.add_argument("--output-dir",type=Path,default=root/"outputs/user_study/new_replay");p.add_argument("--limit",type=int,default=0);a=p.parse_args();OUT=a.output_dir
    if OUT.resolve().is_relative_to((root/"outputs/user_study/replay_eval/paired_current").resolve()):raise SystemExit("Do not overwrite frozen results")
    key=os.environ.get("OPENAI_API_KEY");assert key,"Set OPENAI_API_KEY in environment"
    jobs=load(a.requests);unique={j["request_key"]:j for j in jobs};todo=[j for k,j in unique.items() if not (OUT/"responses"/(k+".json")).exists()]
    if a.limit:todo=todo[:a.limit]
    for n,job in enumerate(todo,1):
        request_once(job,key);print(f"Completed {n}/{len(todo)}",flush=True)
    missing=[k for k in unique if not (OUT/"responses"/(k+".json")).exists()]
    if missing:raise SystemExit(f"{len(missing)} requests remain; no complete new score file yet")
    rows=[]
    for j in jobs:
        response=load(OUT/"responses"/(j["request_key"]+".json"));rows.append({k:j[k] for k in ["id","group","dataset","side","cohort","request_key"]}|{"predicted_sql":response["predicted_sql"],"response_model":response["response_model"],"finish_reason":response["finish_reason"]})
    dump(OUT/"predictions.json",rows)
