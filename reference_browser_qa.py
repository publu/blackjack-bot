from playwright.sync_api import sync_playwright
import json,base64,sys,threading,re
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,'tools/blackjack')
from tabletop_server import Handler
from game import Game
from browser_qa import OfflineTelemetry
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.game=Game();server.game_lock=threading.RLock();server.telemetry=OfflineTelemetry();threading.Thread(target=server.serve_forever,daemon=True).start()
saved=[];coverage={'learned_count':7,'back_learned':True};photo=base64.b64encode(Path('tools/blackjack/validation/2026-11-08/fresh-1-card0.png').read_bytes()).decode()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader']);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def mock(route):
   if route.request.url.endswith('/reference/capture'):data={'capture_id':'offline-review','cards':[{'id':'one','rank':None,'suit':None,'jpeg':photo}]}
   elif route.request.url.endswith('/reference/save'):saved.append(json.loads(route.request.post_data));data=coverage
   elif route.request.url.endswith('/references'):data=coverage
   else:data={'active':False,'fresh':False,'cards':[],'result':None}
   route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps(data))
  page.route(re.compile(r'.*:8204/.*'),mock)
  page.goto('http://127.0.0.1:'+str(server.server_address[1]));page.locator('#details-button').click();page.get_by_role('button',name='Learn this deck').click();page.get_by_role('button',name='Capture visible cards').click();page.locator('.reference-card').first.click();assert page.locator('.reference-save').is_disabled();page.locator('.reference-rank').select_option('8');page.locator('.reference-suit').select_option('♥');assert page.locator('.reference-save').is_disabled();page.locator('.reference-checked').check();page.locator('.reference-save').click();page.wait_for_function("document.querySelector('.reference-status').textContent.includes('Reference saved')");assert saved==[{'capture_id':'offline-review','id':'one','rank':'8','suit':'♥','checked':True}],saved;assert not errors,errors
  report={'frozen_reference_selection':'passed','explicit_review_required':'passed','save_payload':'passed','javascript_errors':errors,'live_reference_writes':0,'arm_commands':0};Path('tools/blackjack/validation/2026-11-08/local-cv-final/reference-browser.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));browser.close()
finally:server.shutdown();server.server_close()
