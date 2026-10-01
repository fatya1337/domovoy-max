const test = require('node:test');
const assert = require('node:assert/strict');
const {createDomovoyClient} = require('./web/request.js');
const ok = data => ({ok: true, status: 200, json: async () => data});
const write = {body: {title:'Учебная заявка'}, identity:'anna'};

test('lost committed response and manual retry reuse one mutation id', async () => {
  const saved = new Map(); const seen = []; let delivery = false;
  const api = createDomovoyClient({uuid: () => String(saved.size + 1), fetchImpl: async (_, request) => {
    const payload = JSON.parse(request.body); seen.push(payload.request_id);
    if (!saved.has(payload.request_id)) saved.set(payload.request_id, {ticket_id: saved.size + 1});
    if (!delivery) throw new TypeError('connection lost after commit');
    return ok(saved.get(payload.request_id));
  }});
  await assert.rejects(api('/api/tickets', write), /Ответ сервера/);
  delivery = true;
  assert.equal((await api('/api/tickets', write)).ticket_id, 1);
  assert.equal(saved.size, 1); assert.deepEqual(seen, ['1','1','1']);
  assert.equal((await api('/api/tickets', write)).ticket_id, 2);
});

test('pending writes remain separate for different users and changed fields', async () => {
  const seen=[]; let n=0;
  const api=createDomovoyClient({uuid:()=>String(++n),fetchImpl:async (_,r)=>{seen.push(JSON.parse(r.body).request_id);throw Error('offline')}});
  for(const options of [write,{...write,identity:'boris'},{...write,body:{title:'Другая заявка'}},write]) await assert.rejects(api('/api/tickets',options));
  assert.deepEqual(seen,['1','1','2','2','3','3','1','1']);
});

test('definitive validation failure is shown without automatic replay',async()=>{
  let calls=0;
  const api=createDomovoyClient({uuid:()=>String(calls),fetchImpl:async()=>{calls++;return {ok:false,status:400,json:async()=>({error:'Укажите адрес'})}}});
  await assert.rejects(api('/api/tickets',write),/Укажите адрес/);assert.equal(calls,1);
});

test('HTML proxy failures preserve id until JSON response arrives',async()=>{
  let n=0;const seen=[];let online=false;
  const api=createDomovoyClient({uuid:()=>String(++n),fetchImpl:async(_,r)=>{seen.push(JSON.parse(r.body).request_id);return online?ok({ok:true}):{ok:false,status:502,json:async()=>{throw SyntaxError('html')}}}});
  await assert.rejects(api('/api/tickets',write),/Ответ сервера/);online=true;
  await api('/api/tickets',write);assert.deepEqual(seen,['1','1','1']);
});

test('read retries carry no write payload or id',async()=>{
  let calls=0;
  const api=createDomovoyClient({uuid:()=>{throw Error('unexpected uuid')},fetchImpl:async(_,r)=>{assert.equal(r.method,'GET');assert.equal(r.body,undefined);if(++calls===1)throw Error('offline');return ok({mode:'max'})}});
  assert.deepEqual(await api('/api/config'),{mode:'max'});assert.equal(calls,2);
});

test('timeout aborts both attempts and preserves a safe retry',async()=>{
  let calls=0;
  const api=createDomovoyClient({uuid:()=> 'fixed',timeoutMs:5,fetchImpl:async(_,r)=>new Promise((_,reject)=>{calls++;r.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true})})});
  await assert.rejects(api('/api/tickets',write),/Ответ сервера/);assert.equal(calls,2);
});
