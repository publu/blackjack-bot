"""Offline browser proof of corner updates; no hardware or station traffic."""
import base64,json,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
from tabletop_server import Handler
from game import Game
from browser_qa import OfflineTelemetry
from playwright.sync_api import sync_playwright

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.game=Game();server.game_lock=threading.RLock();server.telemetry=OfflineTelemetry()
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
  page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  packet={'fresh':True,'revision':1,'captured_at':time.time(),'cards':[{'id':'real-1','rank':'8','suit':'♥','visible':True,'corners':[[.3,.2],[.36,.2],[.36,.31],[.3,.31]]}]}
  packet['frame_jpeg']=base64.b64encode((Path(__file__).parent/'validation/2026-11-08/fresh-1.jpg').read_bytes()).decode()
  packet['cards'][0]['rank']=None;packet['cards'][0]['suit']=None
  state={'active':False,'result':{'scan_id':'old','captured_at':time.time(),'cards':[{'rank':'8','suit':'♥','x':.33,'y':.255}], 'uncertain':False,'reason':'Recorded camera fixture','transfer':{'holder':'none'}}}
  def route(r):
   if packet['fresh']:packet['captured_at']=time.time()
   data=packet if '/tracking' in r.request.url else state
   r.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps(data))
  page.route('**:8204/**',route)
  page.goto('http://127.0.0.1:'+str(server.server_address[1]));page.wait_for_function('window.blackjackView?.observedGroup.children[0]?.userData.tracked')
  page.wait_for_function('window.blackjackView.observedGroup.children[0]?.children[1]?.userData.livePhoto')
  assert page.evaluate('window.blackjackView.observedGroup.children[0].children[1].material.map.image.naturalWidth===640')
  packet['cards'][0].update(rank='8',suit='♥')
  page.wait_for_function("window.blackjackView.observedGroup.children[0]?.userData.card.rank==='8'")
  first=page.evaluate('''()=>{const m=window.blackjackView.observedGroup.children[0];return {position:m.position.toArray(),scale:m.scale.x,corners:m.userData.imageCorners};}''')
  assert abs(first['position'][0]-(-.87075+1.008*.33))<1e-8 and first['scale']==1,first
  packet['captured_at']+=.1;packet['revision']+=1;packet['cards'][0]['corners']=[[.32,.21],[.38,.22],[.36,.33],[.30,.32]]
  page.wait_for_function('Math.abs(window.blackjackView.observedGroup.children[0]?.userData.imageCorners?.[0]?.[0]-.32)<.00001')
  moved=page.evaluate('window.blackjackView.observedGroup.children[0].position.toArray()')
  assert abs(moved[0]-first['position'][0]-.01008)<.0001 and abs(moved[1]-first['position'][1]+.01134)<.0001,(first,moved)
  packet['cards'][0].update(visible=False,held=True)
  page.wait_for_function('window.blackjackView.observedGroup.children[0]?.children[0]?.material.opacity===.35')
  assert page.evaluate('window.blackjackView.observedGroup.children[0].visible')
  packet['fresh']=False;packet['captured_at']+=.1
  page.wait_for_function('!window.blackjackView.observedGroup.children[0].visible')
  packet['fresh']=True;packet['cards']=[];packet['captured_at']+=.1
  page.wait_for_function('window.blackjackView.observedGroup.children.length===0')
  # A slow old rank result must not resurrect a removed tracked card.
  page.wait_for_timeout(2700);assert page.evaluate('window.blackjackView.observedGroup.children.length')==0
  followed=page.evaluate('''()=>{const v=window.blackjackView,n=v.navigation,t=performance.now();n.preset('follow');
   n.sample({fresh:true,measured:{right:{positions_rad:[0,0,0,0,0,0],ee_mm:[250,150,180],gripper:.1}}});
   const before=v.camera.position.clone();n.sample({fresh:true,measured:{right:{positions_rad:[.006,0,0,0,0,0],ee_mm:[252,150,180],gripper:.1}}});
   for(let i=0;i<30;i++)n.tick(t+i*50,v.camera.aspect);return v.camera.position.distanceTo(before)>.1;}''')
  assert followed and server.game.dealt==0 and not errors,(followed,errors)
  print(json.dumps({'camera_pixels_before_rank':'passed','image_corner_translation_rotation':'passed','stale_and_removed_cards':'passed','small_measured_arm_camera_follow':'passed','score_changes':0,'arm_commands':0,'javascript_errors':errors}))
  browser.close()
finally:server.shutdown();server.server_close()
