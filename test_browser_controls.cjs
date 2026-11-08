// Run the actual app action/draw functions without sockets or WebGL.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync(__dirname+'/tabletop/app.js','utf8');
const functions = src.slice(src.indexOf('async function action('),src.indexOf("$('deal').onclick="));
function setup(game) {
  const sent=[];
  const ctx={game,busy:false,drawing:false,window:{cameraViewing:true},view:null,
    report(){},render(){},async json(){return ctx.game;},
    async send(make){sent.push(make());return ctx.game;},setTimeout};
  vm.createContext(ctx);vm.runInContext(functions,ctx);
  return {ctx,sent};
}
(async()=>{
  const live=setup({mode:'observe',phase:'player',live:false,pending:null,
                    session:{active:true,phase:'player',decision_id:'turn7'}});
  await live.ctx.action('hit');
  assert.equal(live.sent.length,1);
  assert.equal(live.sent[0].decision_id,'turn7');
  assert.equal(live.sent[0].action,'hit');
  for(const phase of ['dealing','player','stopped','recovery']) {
    const s=setup({mode:'practice',pending:{id:'card1'},session:{active:phase==='dealing',phase}});
    await s.ctx.drawQueue();
    assert.equal(s.sent.length,0,`browser must not drive ${phase}`);
  }
  console.log('5 browser control checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
