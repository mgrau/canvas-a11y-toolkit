// yuja_launch.mjs <url> <outdir> [wait] [action] [wait2]: open a URL in headless Chrome,
// keep every JSON response it fetches, and save the page's text and a
// screenshot. For reading YuJa Panorama through a Canvas sessionless launch.
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const [url, outdir, wait = '25', action = '', wait2 = '15'] = process.argv.slice(2);
fs.mkdirSync(outdir, {recursive: true});
// Chrome or Chromium: $CHROME, else the usual install places.
const CHROME = process.env.CHROME || [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].find(p => fs.existsSync(p));
if (!CHROME) { console.error('no Chrome found: set CHROME=/path/to/chrome'); process.exit(1); }
// Panorama is only ever read. A Reprocess or any other change is the
// instructor's to make in the browser, so refuse an action that names it.
if (/reprocess|deleteDocuments|refreshCourse/i.test(action)) {
  console.error('refusing: this script only reads Panorama'); process.exit(1);
}
const profile = fs.mkdtempSync(path.join(outdir, '.chrome-profile-'));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, '--no-first-run', '--window-size=1400,1000', 'about:blank'], {stdio: 'ignore'});
const sleep = ms => new Promise(r => setTimeout(r, ms));

try {
  let targets;
  for (let i = 0; i < 50 && !targets; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { await sleep(200); }
  }
  const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0;
  const pending = new Map(), responses = new Map();
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const n = ++id;
    pending.set(n, m => m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result));
    ws.send(JSON.stringify({id: n, method, params}));
  });
  const log = [], requests = [];
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    if (m.method === 'Network.requestWillBeSent' && /\/api\//.test(m.params.request.url)) {
      const q = m.params.request;
      log.push(`REQUEST ${q.method} ${q.url.slice(0, 200)} ${(q.postData || '').slice(0, 400)}`);
      requests.push({url: q.url, method: q.method, headers: q.headers, postData: q.postData});
    }
    if (m.method === 'Network.responseReceived') {
      const r = m.params.response;
      log.push(`${r.status} ${r.mimeType} ${r.url.slice(0, 200)}`);
      if (/json/.test(r.mimeType)) responses.set(m.params.requestId, r.url);
    }
  });
  await send('Network.enable');
  await send('Page.enable');
  await send('Page.navigate', {url});
  await sleep(Number(wait) * 1000);
  // An optional action once the app has loaded, such as clicking a tab.
  if (action) {
    const r = await send('Runtime.evaluate', {expression: action, returnByValue: true, awaitPromise: true});
    const value = r.result.value ?? r.exceptionDetails?.text ?? null;
    fs.writeFileSync(path.join(outdir, 'action.json'), JSON.stringify(value, null, 1));
    console.log('action:', JSON.stringify(value).slice(0, 300));
    await sleep(Number(wait2) * 1000);
  }
  let k = 0;
  for (const [rid, u] of responses) {
    try {
      const {body, base64Encoded} = await send('Network.getResponseBody', {requestId: rid});
      fs.writeFileSync(path.join(outdir, `json-${String(++k).padStart(3, '0')}.json`),
        JSON.stringify({url: u, body: base64Encoded ? Buffer.from(body, 'base64').toString() : body}));
    } catch {}
  }
  fs.writeFileSync(path.join(outdir, 'network.log'), log.join('\n'));
  // Full API requests, so a caller can replay one (yuja.sh issues).
  fs.writeFileSync(path.join(outdir, 'requests.json'), JSON.stringify(requests));
  // A page still loading after an action's navigation may have no body yet.
  const text = (await send('Runtime.evaluate', {expression: 'location.href + "\\n\\n" + (document.body?.innerText ?? "")', returnByValue: true})).result.value ?? '';
  fs.writeFileSync(path.join(outdir, 'page.txt'), text);
  const shot = await send('Page.captureScreenshot', {format: 'png'});
  fs.writeFileSync(path.join(outdir, 'page.png'), Buffer.from(shot.data, 'base64'));
  console.log(`${log.length} responses, ${k} JSON saved; landed on ${text.split('\n')[0].slice(0, 120)}`);
  ws.close();
} finally {
  chrome.kill();
  await sleep(500);
  fs.rmSync(profile, {recursive: true, force: true});
}
