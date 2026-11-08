"""Isolated offline browser checks. Requires playwright + system Chromium.
Run: PYTHONPATH=/tmp/armstrong-blackjack-qa python3 tools/blackjack/browser_qa.py
Does not talk to the station. All telemetry is deliberately unavailable.
"""
import json,threading,time
from http.server import ThreadingHTTPServer
from tabletop_server import Handler
from game import Game
from observation_gate import ObservationGate
from test_observation_gate import Reader

class OfflineTelemetry:
    frames={}
    def read(self):return {'connected':False,'fresh':False,'measured':{},'motion_enabled':False}

def main():
    from playwright.sync_api import sync_playwright
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.game=Game();server.game_lock=threading.RLock();server.telemetry=OfflineTelemetry()
    server.observation=ObservationGate(server.game,server.game_lock,Reader())
    server.game.shoe=[{'rank':r,'suit':'♠'} for r in reversed(['8','6','8','3','10','10','10','10'])]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_address[1])
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            boot_camera={'active':False,'result':{'scan_id':'boot','captured_at':time.time(),'cards':[{'rank':'A','suit':'♠','x':.5,'y':.2,'evidence':'Fixture'}],'uncertain':False,'reason':'Fixture','transfer':{'holder':'none'}},'motion_enabled':False}
            page.route('**:8204/**',lambda route:route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps(boot_camera)))
            page.on('dialog',lambda d:d.accept())
            page.goto(url);page.wait_for_function('!!window.blackjackView')
            assert page.evaluate('window.blackjackView.deck.faces.size')==52
            assert page.evaluate('document.querySelector("#scene").clientHeight===innerHeight')
            page.wait_for_function("window.cameraViewing && window.blackjackView.observedGroup.children[0]?.userData.card.rank==='A'")
            assert page.is_disabled('#deal') and server.game.dealt==0
            page.click('#details-button');page.click('.camera-source-toggle');page.click('#close-details')
            worst=page.evaluate('''async()=>{const v=window.blackjackView,f=await fetch('/robot-fk-fixtures.json').then(r=>r.json());let worst=0;for(const t of f){const a=v.arms.right;a.update(t.q);a.base.updateMatrixWorld(true);for(let i=0;i<v.spec.bodies.length;i++){const n=a.links[v.spec.bodies[i].name],e=n.matrixWorld.elements;for(let k=0;k<3;k++)worst=Math.max(worst,Math.abs(e[12+k]-t.positions[i][k]));const q=n.getWorldQuaternion(n.quaternion.clone()),z=t.quaternions[i];worst=Math.max(worst,Math.abs(1-Math.abs(q.w*z[0]+q.x*z[1]+q.y*z[2]+q.z*z[3])));}}return worst;}''')
            assert worst<1e-6,worst
            page.click('#deal');page.wait_for_function('window.blackjackView.animations.some(a=>a.kind==="practice")')
            first=page.evaluate('''()=>{const a=window.blackjackView.animations.find(a=>a.kind==='practice');return {rotation:a.mesh.rotation.y,path:a.path.points.length,scale:a.mesh.scale.x,size:a.mesh.userData.physicalSize};}''')
            assert first['rotation']>3 and first['path']==6 and first['size']['width']==.063 and first['size']['height']==.088,first
            page.wait_for_function("!document.querySelector('#split').disabled")
            assert page.evaluate('[...window.blackjackView.cards.values()].every(m=>Math.abs(m.rotation.y)<.001)')
            page.click('#split');page.wait_for_function("!document.querySelector('#double').disabled")
            page.click('#double');page.wait_for_function("!document.querySelector('#stand').disabled")
            page.click('#stand');page.wait_for_function("!document.querySelector('#deal').hidden && !document.querySelector('#deal').disabled")
            assert server.game.bankroll==57500,server.game.snapshot()
            assert len(server.game.hands)==2
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.click('#details-button');page.click('#mode')
            page.wait_for_function("document.querySelector('#details-button').textContent.includes('Observation')")
            page.click('#deal');page.wait_for_selector('#operator[open]')
            assert server.game.dealt==0
            server.observation.reader.decision.update(verified=False,evidence='Glare covers the pending rank')
            page.click('#camera-prepare');page.wait_for_function("!document.querySelector('#camera-verify').disabled")
            page.click('#camera-verify');page.wait_for_function("document.querySelector('#camera-gate-status').textContent.includes('Glare')")
            assert server.game.dealt==0
            page.fill('#card-text','QH');page.check('#checked');page.click('#confirm-card')
            page.wait_for_function("document.querySelector('#player-labels').textContent.includes('Q♥')")
            assert server.game.dealt==1
            assert server.game.hands[0].cards[0]['source']=='operator'
            server.observation.reader.decision.update(verified=True,evidence='One new 9 of hearts fully visible on the table')
            page.click('#camera-prepare');page.wait_for_function("!document.querySelector('#camera-verify').disabled")
            page.click('#camera-verify');page.wait_for_function("document.querySelector('#dealer-accessible').textContent.includes('9♥')")
            assert server.game.dealt==2 and server.game.dealer[0]['source']=='camera'
            # Close keeps pending round; no automatic game progress without confirmation.
            page.click('#close-operator');page.wait_for_timeout(800);assert server.game.dealt==2
            # Camera observations are visual evidence, never anonymous scoring events.
            observation={'scan_id':'fixture','captured_at':time.time(),'cards':[{'rank':'7','suit':'♦','x':.5,'y':.5,'evidence':'Clear printed index'}],
                'uncertain':False,'reason':'Fixture','transfer':{'holder':'both','rank':None,'suit':None},
                'measured':{side:{'positions_rad':[0]*6,'gripper':.2,'ee_mm':[300,150,200]} for side in ('left','right')}}
            camera_state={'active':False,'result':observation,'motion_enabled':False}
            page.unroute('**:8204/**')
            page.route('**:8204/**',lambda route:route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps(camera_state)))
            page.click('#details-button');page.click('.camera-source-toggle');page.click('#close-details')
            page.wait_for_function("window.blackjackView.observedGroup.children[0]?.userData.card.rank==='7'")
            assert page.evaluate('window.blackjackView.observedGroup.children.length')==1
            assert page.is_disabled('#hit')
            page.click('#details-button');page.click('.transfer-replay');page.click('#close-details')
            assert page.evaluate("window.blackjackView.observedGroup.children.some(m=>m.userData.transfer&&m.userData.holder==='both'&&m.userData.card.rank==='?')")
            assert page.evaluate('window.transferReplay && window.blackjackView.observedGroup.children.length===2')
            assert server.game.dealt==2
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            camera_state['result']={**observation,'scan_id':'unknown','transfer':{'holder':'unknown'}}
            page.wait_for_function('!window.transferReplay')
            assert page.locator('.transfer-replay').is_hidden()
            assert page.evaluate("window.blackjackView.observedGroup.children.map(m=>m.userData.card.rank).join(',')==='7'")
            camera_state['result']={**observation,'scan_id':'glare','cards':[],'transfer':{'holder':'none'},'uncertain':True,'reason':'Reflection hides a card','unreadable':[{'x':.5,'y':.5,'cause':'glare','evidence':'Reflection covers both corner indices'}]}
            page.wait_for_function("document.querySelector('.control-zone>.camera-read-reason').textContent.includes('glare')")
            assert page.locator('.control-zone>.camera-read-reason').is_visible()
            assert server.game.dealt==2
            camera_state['result']={**observation,'scan_id':'two-rows','transfer':{'holder':'none'},'cards':[
                {'rank':'A','suit':'♠','x':.4,'y':.15,'evidence':'Upper row'},
                {'rank':'9','suit':'♥','x':.6,'y':.5,'evidence':'Lower row'}]}
            page.wait_for_function("window.blackjackView.observedGroup.children.length===2")
            rows=page.evaluate('window.blackjackView.observedGroup.children.map(m=>({rank:m.userData.card.rank,row:m.userData.cameraRow,y:m.position.y}))')
            assert rows[0]['rank']=='A' and rows[0]['row']=='top' and rows[0]['y']>rows[1]['y'],rows
            assert rows[1]['rank']=='9' and rows[1]['row']=='bottom',rows
            assert page.evaluate("getComputedStyle(document.documentElement).colorScheme==='dark'")
            page.set_viewport_size({'width':1440,'height':1000})
            page.wait_for_timeout(500)
            before=page.evaluate('window.blackjackView.camera.position.toArray()')
            box=page.locator('#scene').bounding_box();x=box['x']+box['width']*.55;y=box['y']+box['height']*.5
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+110,y+35,steps=10);page.mouse.up();page.wait_for_timeout(400)
            assert page.evaluate("window.blackjackView.navigation.mode==='manual'")
            after=page.evaluate('window.blackjackView.camera.position.toArray()')
            assert sum(abs(a-b) for a,b in zip(before,after))>.1
            page.mouse.wheel(0,-120);page.wait_for_timeout(400)
            zoom=page.evaluate('window.blackjackView.camera.position.toArray()')
            assert sum(abs(a-b) for a,b in zip(after,zoom))>.05
            page.locator('#scene').focus();page.keyboard.press('o');page.wait_for_timeout(1200)
            assert page.evaluate("window.blackjackView.navigation.mode==='overhead'")
            page.keyboard.press('f')
            followed=page.evaluate('''()=>{const v=window.blackjackView,n=v.navigation,t=performance.now();
                n.sample({fresh:true,measured:{left:{positions_rad:[0,0,0,0,0,0],ee_mm:[250,150,180]}}});
                n.sample({fresh:true,measured:{left:{positions_rad:[.2,0,0,0,0,0],ee_mm:[250,150,180]}}});
                const before=v.camera.position.clone();for(let i=0;i<30;i++)n.tick(t+i*50,v.camera.aspect);
                return n.mode==='follow'&&v.camera.position.distanceTo(before)>.1;}''')
            assert followed
            page.locator('#scene').focus();page.keyboard.press('ArrowLeft')
            assert page.evaluate("window.blackjackView.navigation.mode==='manual'")
            page.keyboard.press('r')
            assert page.evaluate("window.blackjackView.navigation.mode==='table'")
            page.screenshot(path='/tmp/blackjack-camera-desktop.png')
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(500)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path='/tmp/blackjack-camera-mobile.png')
            touch=page.context.new_cdp_session(page)
            touch.send('Emulation.setTouchEmulationEnabled',{'enabled':True})
            box=page.locator('#scene').bounding_box();y=box['y']+box['height']*.55
            before=page.evaluate('window.blackjackView.camera.position.toArray()')
            touch.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':150,'y':y,'id':1},{'x':230,'y':y,'id':2}]})
            touch.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':120,'y':y,'id':1},{'x':260,'y':y,'id':2}]})
            touch.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(400)
            after=page.evaluate('window.blackjackView.camera.position.toArray()')
            assert sum(abs(a-b) for a,b in zip(before,after))>.1
            assert page.evaluate("window.blackjackView.navigation.mode==='manual'")
            page.emulate_media(reduced_motion='reduce');page.reload();page.wait_for_function('!!window.blackjackView')
            assert page.evaluate("window.blackjackView.navigation.mode==='table'")
            assert page.locator('.observed-rank').count()==0
            assert not errors,errors
            print(json.dumps({'urdf_fk_max_error':worst,'split_double_round':'passed','bankroll':57500,'operator_typed_card':'passed','uncertainty_pause':'passed','manual_camera_confirmation':'passed','visible_glare_notice':'passed','camera_ranks':'passed','shared_grip_snapshot':'passed','unknown_holder_returns_live':'passed','orbit_zoom_follow_keyboard':'passed','touch_pinch_reduced_motion':'passed','mobile':'passed','motion_calls':0}))
            browser.close()
    finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()
