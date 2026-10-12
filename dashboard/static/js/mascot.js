// "Surveyor": a 24x24 pixel field robot drawn to a canvas at an integer scale.
// State comes from the agent_state event; "offline" is derived from the socket.
// With prefers-reduced-motion it shows one static frame.
import { SIZE, SPRITES, FRAME_MS } from './mascot-sprites.js';

const SCALE = 2;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

export function createMascot(canvas) {
  canvas.width = SIZE * SCALE;
  canvas.height = SIZE * SCALE;
  const ctx = canvas.getContext('2d');
  let state = 'offline';
  let frame = 0;
  let timer = null;
  let foundTimer = null;

  function palette() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim() || '#888';
    const p = {
      k: v('--ink'), b: v('--rule'), d: v('--muted'), l: v('--surface'),
      a: v('--accent'), x: v('--ink'),
    };
    if (state === 'error') p.a = v('--muted');
    return p;
  }

  function draw() {
    const frames = SPRITES[state] || SPRITES.idle;
    const rows = frames[frame % frames.length];
    const colors = palette();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.globalAlpha = state === 'offline' ? 0.45 : 1;
    for (let y = 0; y < SIZE; y++) {
      for (let x = 0; x < SIZE; x++) {
        const c = colors[rows[y][x]];
        if (!c) continue;
        ctx.fillStyle = c;
        ctx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
      }
    }
    ctx.globalAlpha = 1;
  }

  function restart() {
    clearInterval(timer);
    frame = 0;
    draw();
    const frames = SPRITES[state] || [];
    if (!reduced.matches && frames.length > 1) {
      timer = setInterval(() => { frame += 1; draw(); }, FRAME_MS[state] || 500);
    }
  }

  reduced.addEventListener('change', restart);
  new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);

  return {
    get state() { return state; },
    set(next) {
      if (next === state) return;
      state = SPRITES[next] ? next : 'idle';
      clearTimeout(foundTimer);
      restart();
      if (state === 'found') foundTimer = setTimeout(() => this.set('idle'), 8000);
    },
    redraw: draw,
  };
}
