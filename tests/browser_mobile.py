"""Exercise the real example-mode map/chat on phones and desktop; provider calls are fenced."""
from pathlib import Path
import argparse,json,os,socket,subprocess,time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
args=argparse.ArgumentParser();args.add_argument('--base-url');args.add_argument('--serve-build',type=Path);args.add_argument('--out-dir',type=Path,default=Path('/tmp/geospatial-mobile-proof'));args.add_argument('--narrow-map-regression',action='store_true');opts=args.parse_args();opts.out_dir.mkdir(parents=True,exist_ok=True);server=None
if opts.serve_build:
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 env={k:os.environ[k]for k in ['PATH','HOME','LANG']if k in os.environ};env.update({'HOSTNAME':'127.0.0.1','PORT':str(port),'NEXT_TELEMETRY_DISABLED':'1'})
 log=open(opts.out_dir/'next-server.log','w');server=subprocess.Popen(['node','server.js'],cwd=opts.serve_build.resolve(),env=env,stdout=log,stderr=subprocess.STDOUT);url=f'http://127.0.0.1:{port}/'
else:url=opts.base_url
assert url,'Choose --base-url or --serve-build'
r={'url':url,'scope':'Real public example-mode UI; original three retained queries and data; zero provider calls','checks':{},'page_errors':[],'http_errors':[],'blocked_provider_requests':[],'examples':[]}
def check(key,value):
 r['checks'][key]=bool(value);(opts.out_dir/'checks-partial.json').write_text(json.dumps(r,indent=2)+'\n');assert value,key
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader']);ctx=browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True)
  def fence(route):
   req=route.request;u=req.url;host=urlparse(u).hostname or ''
   if req.method not in ['GET','HEAD'] or host.endswith(('openai.com','anthropic.com','googleapis.com','mapbox.com')) or ':8000/' in u:
    r['blocked_provider_requests'].append({'method':req.method,'url':u.split('?')[0]});route.abort();return
   if opts.narrow_map_regression and '/_next/static/css/' in u:
    response=route.fetch();text=response.text();route.fulfill(response=response,body=text+'\n@media(max-width:880px){.geo-main>.geo-map{left:45%!important;width:55%!important}}');return
   route.continue_()
  ctx.route('**/*',fence);page=ctx.new_page();page.on('pageerror',lambda e:r['page_errors'].append(str(e)));page.on('response',lambda res:r['http_errors'].append({'status':res.status,'path':res.url})if res.url.startswith(url.rstrip('/'))and res.status>=400 else None)
  def load():
   for attempt in range(40):
    try:page.goto(url,wait_until='domcontentloaded');break
    except Exception:
     if not server or attempt==39:raise
     time.sleep(.1)
   page.wait_for_selector('.geo-map .maplibregl-canvas',state='attached' if opts.narrow_map_regression else 'visible',timeout=60000);page.wait_for_timeout(1500)
  def bounds(selector):return page.locator(selector).bounding_box()
  def fullscreen(selector,w,h):
   try:
    page.wait_for_function("([selector,w,h])=>{const e=document.querySelector(selector);if(!e)return false;const r=e.getBoundingClientRect();return Math.abs(r.x)<1&&Math.abs(r.y)<1&&Math.abs(r.width-w)<1&&Math.abs(r.height-h)<1}",arg=[selector,w,h],timeout=5000,polling=50)
   except Exception:
    # Capture the actual matched element and viewport before changing a strict geometry assertion.
    info=page.evaluate("selector=>{const e=document.querySelector(selector),s=e&&getComputedStyle(e),r=e&&e.getBoundingClientRect();return {selector,id:e?.id,label:e?.getAttribute('aria-label'),open:e?.open,modal:e?.matches(':modal'),rect:r&&{x:r.x,y:r.y,width:r.width,height:r.height},active:document.activeElement?.outerHTML.slice(0,200),workspaceStyle:document.querySelector('.geo-workspace')?.getAttribute('style'),navHeight:getComputedStyle(document.documentElement).getPropertyValue('--atelier-nav-height'),viewport:{width:innerWidth,height:innerHeight,visualWidth:visualViewport?.width,visualHeight:visualViewport?.height,top:visualViewport?.offsetTop,scale:visualViewport?.scale},css:s&&{top:s.top,height:s.height,width:s.width,display:s.display,position:s.position,margin:s.margin,maxHeight:s.maxHeight}}}",selector)
    (opts.out_dir/'fullscreen-failure.json').write_text(json.dumps(info,indent=2)+'\n');print('FULLSCREEN_GEOMETRY_DIAGNOSTIC',json.dumps(info),flush=True);page.screenshot(path=str(opts.out_dir/'fullscreen-failure.png'));raise
   b=bounds(selector);return b and abs(b['x'])<1 and abs(b['y'])<1 and abs(b['width']-w)<1 and abs(b['height']-h)<1
  def map_fits(name,w,h):
   b=bounds('.geo-map');nav=page.evaluate("parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--atelier-nav-height'))||0");r.setdefault('geometry',{})[name]={'map':b,'native_nav_height':nav}
   check(name+'_map_full_viewport',b and abs(b['x'])<1 and abs(b['width']-w)<1 and abs(b['y']-nav)<1 and abs(b['height']-(h-nav))<1);check(name+'_no_overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight'))
  for i in range(3):
   load();map_fits('example'+str(i),390,844);opener=page.get_by_role('button',name='Ask about a place',exact=True);check('chat_opener44_'+str(i),bounds('.geo-mobile-tools button')['height']>=44 if page.locator('.geo-mobile-tools button').count()==1 else page.locator('.geo-mobile-tools button').first.bounding_box()['height']>=44)
   if i==0:page.screenshot(path=str(opts.out_dir/'map-390.png'))
   opener.click();check('chat_fullscreen_'+str(i),fullscreen('#geo-chat',390,844));check('chat_native_modal_'+str(i),page.locator('#geo-chat').evaluate("e=>e.matches(':modal')"));choices=page.locator('.geo-chat-empty button');check('three_native_choices_'+str(i),choices.count()==3);r['examples'].append(choices.nth(i).inner_text())
   if i==0:page.screenshot(path=str(opts.out_dir/'chat-choices-390.png'))
   choices.nth(i).click();page.get_by_text('30 locations match the Covent Garden reference.',exact=False).wait_for(timeout=10000);check('retained_example_answer_'+str(i),True);draft=page.get_by_placeholder('Ask about a place');draft.fill('Keep this draft');page.get_by_role('button',name='Return to map').click();page.wait_for_function("!document.querySelector('#geo-chat').open");map_fits('result'+str(i),390,844);page.wait_for_timeout(2200)
   if i==0:page.screenshot(path=str(opts.out_dir/'result-map-390.png'))
   opener.click();check('draft_survives_close_'+str(i),draft.input_value()=='Keep this draft');check('messages_survive_close_'+str(i),page.get_by_text('30 locations match the Covent Garden reference.',exact=False).is_visible());page.keyboard.press('Escape');page.wait_for_function("!document.querySelector('#geo-chat').open");check('escape_restores_opener_'+str(i),opener.evaluate('(e)=>e===document.activeElement'))
  page.set_viewport_size({'width':320,'height':568});page.wait_for_timeout(100);map_fits('phone320',320,568);opener.click();check('chat_fullscreen320',fullscreen('#geo-chat',320,568));draft=page.get_by_placeholder('Ask about a place');check('composer_full_width320',bounds('textarea')['width']>=270);check('composer16px',draft.evaluate('e=>getComputedStyle(e).fontSize')=='16px');check('composer_one_line_fit',44<=bounds('textarea')['height']<70);check('send_button44',page.get_by_role('button',name='Send message',exact=True).bounding_box()['width']>=44);page.screenshot(path=str(opts.out_dir/'chat-320.png'))
  page.set_viewport_size({'width':320,'height':400});draft.focus();send=page.get_by_role('button',name='Send message',exact=True);check('short_viewport_send_reachable',send.bounding_box()['y']+send.bounding_box()['height']<=400.5);check('short_viewport_map_close_reachable',page.get_by_role('button',name='Return to map').bounding_box()['y']>=0)
  page.evaluate("()=>{Object.defineProperty(visualViewport,'height',{configurable:true,value:300});Object.defineProperty(visualViewport,'offsetTop',{configurable:true,value:20});visualViewport.dispatchEvent(new Event('resize'))}");page.wait_for_timeout(50);check('visual_viewport_keyboard_height',abs(bounds('#geo-chat')['height']-300)<1);check('visual_viewport_keyboard_offset',abs(bounds('#geo-chat')['y']-20)<1);page.evaluate("()=>{delete visualViewport.height;delete visualViewport.offsetTop;visualViewport.dispatchEvent(new Event('resize'))}")
  page.set_viewport_size({'width':1600,'height':1000});page.wait_for_function("document.querySelector('#geo-chat').open&&!document.querySelector('#geo-chat').matches(':modal')");check('desktop_original400_chat',abs(bounds('#geo-chat')['width']-400)<1);check('desktop_map1200',abs(bounds('.geo-map')['width']-1200)<1);check('desktop_draft_preserved',draft.input_value()=='Keep this draft');check('desktop_no_overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.wait_for_timeout(1500);page.screenshot(path=str(opts.out_dir/'desktop-1600.png'))
  page.set_viewport_size({'width':390,'height':844});page.wait_for_function("!document.querySelector('#geo-chat').open");map_fits('phone_after_resize',390,844);page.get_by_role('button',name='Show process',exact=True).click();check('process_fullscreen390',fullscreen('.geo-thought-drawer',390,844));check('process_native_modal',page.locator('.geo-thought-drawer').evaluate("e=>e.matches(':modal')"));page.screenshot(path=str(opts.out_dir/'process-390.png'));page.keyboard.press('Escape');page.wait_for_selector('.geo-thought-drawer',state='detached');check('process_escape_closes',True)
  page.get_by_role('button',name='Toggle layer panel',exact=True).click();check('native_retained_layer_present',page.get_by_role('button',name='Hide Synthetic similarity results',exact=True).is_visible());page.get_by_role('button',name='Hide Synthetic similarity results',exact=True).click();check('native_layer_toggle_works',page.get_by_role('button',name='Show Synthetic similarity results',exact=True).is_visible());page.get_by_role('button',name='Show Synthetic similarity results',exact=True).click();check('native_layer_restore_works',page.get_by_role('button',name='Hide Synthetic similarity results',exact=True).is_visible());check('layer_touch44',page.get_by_role('button',name='Toggle layer panel',exact=True).bounding_box()['height']>=44)
  page.set_viewport_size({'width':320,'height':568});page.wait_for_timeout(100);legend=bounds('.geo-layer-panel');zoom=bounds('.maplibregl-ctrl-zoom-in');check('phone320_layers_clear_zoom_controls',legend['x']+legend['width']+8<=zoom['x']);badge=bounds('.geo-example-label');attribution=bounds('.maplibregl-ctrl-attrib');r['attribution_geometry']={'badge':badge,'attribution':attribution};check('phone320_example_label_clears_attribution',badge['y']+badge['height']<=attribution['y'] or badge['x']+badge['width']<=attribution['x']);page.screenshot(path=str(opts.out_dir/'layers-320.png'))
  page.emulate_media(reduced_motion='reduce');check('reduced_motion_css',page.locator('.geo-map button').first.evaluate('e=>parseFloat(getComputedStyle(e).transitionDuration)<.01'));check('no_page_errors',not r['page_errors']);check('no_local_http_errors',not r['http_errors']);check('no_provider_requests',not r['blocked_provider_requests']);browser.close()
 r['passed']=True;(opts.out_dir/'checks.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
finally:
 if server:server.terminate();server.wait(timeout=10)
