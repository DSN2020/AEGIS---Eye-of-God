// The supervisor owns this server. Each remote client owns only its contexts.
const fs = require('fs');
const {chromium} = require(process.argv[2]);
const statePath = process.argv[3];
let server;
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  try { if (server) await server.close(); } finally { process.exit(0); }
}
process.stdin.resume();
process.stdin.on('end', stop);
process.stdin.on('data', stop);
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
(async () => {
  server = await chromium.launchServer({host: '127.0.0.1', port: 0,
    headless: true, ...(process.argv[4] ? {channel: process.argv[4]} : {})});
  if (stopping) { await server.close(); return; }
  server.on('close', () => process.exit(stopping ? 0 : 1));
  fs.writeFileSync(statePath + '.tmp', JSON.stringify({
    hostPid: process.pid, browserPid: server.process().pid,
    endpoint: server.wsEndpoint()
  }));
  fs.renameSync(statePath + '.tmp', statePath);
})().catch(() => { console.error('Shared Chrome host failed to start'); process.exit(1); });
