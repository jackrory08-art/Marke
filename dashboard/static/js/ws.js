// WebSocket with reconnect/backoff and a tiny event bus.
import { goToLogin } from './api.js';

const listeners = new Map();   // type -> Set<fn>
let socket = null;
let attempts = 0;
let timer = null;
export let status = 'connecting';   // connecting | open | closed

function setStatus(next) {
  status = next;
  emit('_status', { status });
}

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}

function emit(type, data) {
  for (const fn of listeners.get(type) || []) {
    try { fn(data); } catch (e) { console.error(e); }
  }
}

export function connect() {
  clearTimeout(timer);
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${proto}//${window.location.host}/ws`);
  setStatus('connecting');

  socket.addEventListener('open', () => {
    attempts = 0;
    setStatus('open');
  });
  socket.addEventListener('message', (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === 'session_expired') { goToLogin(); return; }
    emit(msg.type, msg.data);
    emit('*', msg);
  });
  socket.addEventListener('close', (ev) => {
    setStatus('closed');
    if (ev.code === 4401 || ev.code === 4403) { goToLogin(); return; }
    const delay = Math.min(30000, 1000 * 2 ** attempts) * (0.75 + Math.random() * 0.5);
    attempts += 1;
    timer = setTimeout(connect, delay);
  });
  socket.addEventListener('error', () => { /* close follows */ });
}

export function send(obj) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(obj));
}

setInterval(() => send({ type: 'ping' }), 25000);
