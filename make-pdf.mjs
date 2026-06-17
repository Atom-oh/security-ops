// Drives a headless Chromium over CDP to print HTML files to PDF.
// Run with: node --experimental-websocket make-pdf.mjs
import fs from 'node:fs';
import path from 'node:path';

const CDP = 'http://127.0.0.1:9333';
const here = process.cwd();

const JOBS = [
  ['20260601 - Claude Mythos 분석 및 국내 금융사 적용 방안 - v2.html', 'claude-mythos-analysis-v2.pdf'],
  ['20260601 - Claude Mythos 분석 및 국내 금융사 적용 방안 - v1.html', 'claude-mythos-analysis-v1.pdf'],
  ['20260602 - FSI-MythosARCHITECTURE.html', 'fsi-mythos-architecture.pdf'],
  ['20260602 - FSI-Mythos - BENCHMARK.html', 'fsi-mythos-benchmark.pdf'],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getBrowserWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`${CDP}/json/version`);
      const j = await r.json();
      if (j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error('CDP not reachable');
}

function rpc(ws) {
  let id = 0;
  const pending = new Map();
  const loadWaiters = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else if (msg.method === 'Page.loadEventFired') {
      while (loadWaiters.length) loadWaiters.shift()();
    }
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const m = { id: ++id, method, params };
      if (sessionId) m.sessionId = sessionId;
      pending.set(m.id, { resolve, reject });
      ws.send(JSON.stringify(m));
    });
  const waitLoad = (ms = 8000) =>
    new Promise((resolve) => {
      const t = setTimeout(resolve, ms);
      loadWaiters.push(() => { clearTimeout(t); resolve(); });
    });
  return { send, waitLoad };
}

const fileUrl = (f) => 'file://' + path.join(here, f).split('/').map(encodeURIComponent).join('/');

async function main() {
  const wsUrl = await getBrowserWs();
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const { send, waitLoad } = rpc(ws);

  for (const [src, out] of JOBS) {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Page.enable', {}, sessionId);
    const lp = waitLoad();
    await send('Page.navigate', { url: fileUrl(src) }, sessionId);
    await lp;
    await sleep(1200); // let fonts/JS settle
    const { data } = await send('Page.printToPDF', {
      printBackground: true,
      preferCSSPageSize: false,
      paperWidth: 8.27, paperHeight: 11.69, // A4
      marginTop: 0.4, marginBottom: 0.4, marginLeft: 0.4, marginRight: 0.4,
      scale: 0.85,
    }, sessionId);
    fs.writeFileSync(out, Buffer.from(data, 'base64'));
    console.log(`OK ${out} (${(fs.statSync(out).size / 1024).toFixed(0)} KB)`);
    await send('Target.closeTarget', { targetId });
  }
  ws.close();
}

main().then(() => process.exit(0)).catch((e) => { console.error('ERR', e.message); process.exit(1); });
