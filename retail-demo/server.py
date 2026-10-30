"""Private loopback HTTP preview; one bounded similarity query at a time."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,os,threading,math,hashlib
import h3
import multiprocessing
from diem_batch import search,MATRIX
BASE=Path(__file__).resolve().parent
LOCK=threading.Lock()
REAL='london-res10.parquet'==MATRIX.name
if REAL:
 with MATRIX.open('rb') as source: digest=hashlib.file_digest(source,'sha256').hexdigest()
 if digest!='3e56da16150bc01b7b8a9e84d7d68c85eb76210fc0a0d2916801aafd1dabab5f':raise RuntimeError('London matrix hash mismatch')
def calculate(pipe,lat,lng,top):
 try:pipe.send((True,search(lat,lng,top)))
 except Exception as e:pipe.send((False,str(e)))
 finally:pipe.close()
class Handler(BaseHTTPRequestHandler):
 def send_json(self,data,status=200):
  payload=json.dumps(data,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(payload)
 def do_GET(self):
  if self.path=='/api/source':return self.send_json({'dataset':'London historical matrix' if REAL else 'Synthetic example data','coverage':'London H3 resolution 10' if REAL else '90 synthetic feature records around three London locations','features':1956 if REAL else 5,'source':'Contains information from Overture Maps Foundation and © OpenStreetMap contributors, available under the Open Database License 1.0. Historical source release: Overture 2025-12-17; exact per-record provenance was not retained' if REAL else 'Deterministically generated examples','license':'ODbL attribution and source review pending' if REAL else 'Synthetic values','method':'Historic Leo calibrated distance inspired by DIEM; not the published authors’ reference implementation','matrix_sha256':'3e56da16150bc01b7b8a9e84d7d68c85eb76210fc0a0d2916801aafd1dabab5f' if REAL else None})
  if self.path not in ('/','/index.html'):self.send_error(404);return
  data=(BASE/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(data)
 def do_POST(self):
  if self.path!='/api/search':self.send_error(404);return
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=2048:raise ValueError('Invalid request size')
   req=json.loads(self.rfile.read(length));lat=float(req['lat']);lng=float(req['lng'])
   if not math.isfinite(lat) or not math.isfinite(lng) or not 51.0<=lat<=52.0 or not -1.0<=lng<=1.0:raise ValueError('Choose a location within London coverage')
   top=max(1,min(int(req.get('top_k',100)),100))
   cache=BASE / "preset-cache.json"
   if REAL and top==100 and cache.is_file():
    entry=json.loads(cache.read_text()).get(h3.latlng_to_cell(lat,lng,10))
    if entry and entry.get("cache_provenance",{}).get("matrix_sha256")=="3e56da16150bc01b7b8a9e84d7d68c85eb76210fc0a0d2916801aafd1dabab5f":return self.send_json(entry)
   if not LOCK.acquire(blocking=False):return self.send_json({'error':'Another search is running. Try again shortly.'},429)
   try:
    parent,child=multiprocessing.Pipe(duplex=False);worker=multiprocessing.Process(target=calculate,args=(child,lat,lng,top));worker.start();child.close()
    if not parent.poll(180):
     worker.terminate();worker.join();raise TimeoutError("Search exceeded three minutes")
    ok,result=parent.recv();worker.join();parent.close()
    if not ok:raise ValueError(result)
   finally:LOCK.release()
   self.send_json(result)
  except Exception as e:self.send_json({'error':str(e)},400)
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.getenv('PORT','18869'))),Handler).serve_forever()
