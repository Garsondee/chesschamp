import { Chessground } from './vendor/chessground.min.js';

// ---- elements ----
const el = (id) => document.getElementById(id);
const chatEl = el('chat'),
  movesEl = el('moves'),
  statusEl = el('status');
const evalFill = el('evalFill'),
  evalNum = el('evalNum');
const promoEl = el('promo');

let latestFen = null;
let userColor = 'white';
let flipOverride = null; // null = follow userColor
let ground = null;
let lastCp = 0; // most recent eval, for redraws on flip
let myTurn = false;
let lastProposal = null; // dedupe repeated right-drag arrows
let prevMoveCount = 0;
let prevGameOver = false;
let soundOn = true;
let audioCtx = null;

// ---- board ----
ground = Chessground(el('board'), {
  fen: 'start',
  orientation: 'white',
  movable: { free: false, color: undefined, dests: new Map(), showDests: true },
  animation: { enabled: true, duration: 220 },
  highlight: { lastMove: true, check: true },
  drawable: { enabled: true, onChange: onDraw }, // right-drag = propose a move
  events: { move: onUserMove },
});

// A second, view-only board for practice-board demonstrations (Phase 5) — it never touches
// the real game state, it just plays back a precomputed line on top of it. Constructed
// LAZILY (only once the overlay is actually visible): Chessground measures its container's
// pixel size at construction time, and #lessonOverlay starts `display:none` — building it
// eagerly at page load baked in a 0-width board that never recovered once shown.
let lessonGround = null;
function ensureLessonGround() {
  if (!lessonGround) {
    lessonGround = Chessground(el('lessonBoard'), {
      fen: 'start',
      viewOnly: true,
      animation: { enabled: true, duration: 280 },
      highlight: { lastMove: true, check: true },
    });
  }
  return lessonGround;
}

function toDests(obj) {
  const m = new Map();
  for (const k in obj) m.set(k, obj[k]);
  return m;
}

function pieceAt(fen, sq) {
  const rows = fen.split(' ')[0].split('/'); // rows[0] = rank 8
  const file = sq.charCodeAt(0) - 97;
  const rank = parseInt(sq[1], 10);
  let f = 0;
  for (const ch of rows[8 - rank]) {
    if (/\d/.test(ch)) f += parseInt(ch, 10);
    else {
      if (f === file) return ch;
      f++;
    }
  }
  return null;
}

function onUserMove(orig, dest) {
  ensureAudio();
  const piece = pieceAt(latestFen, orig);
  const isPawn = piece && piece.toLowerCase() === 'p';
  const lastRank = dest[1] === '8' || dest[1] === '1';
  // lock the board until the server confirms and it's our turn again
  ground.set({ movable: { color: undefined } });
  if (isPawn && lastRank) showPromo(orig, dest);
  else send({ type: 'move', from: orig, to: dest, promotion: null });
}

// ---- promotion ----
function showPromo(orig, dest) {
  const glyphs =
    userColor === 'white' ? { q: '♕', r: '♖', b: '♗', n: '♘' } : { q: '♛', r: '♜', b: '♝', n: '♞' };
  promoEl.innerHTML = '';
  for (const p of ['q', 'r', 'b', 'n']) {
    const btn = document.createElement('button');
    btn.textContent = glyphs[p];
    btn.onclick = () => {
      promoEl.classList.add('hidden');
      send({ type: 'move', from: orig, to: dest, promotion: p });
    };
    promoEl.appendChild(btn);
  }
  // place near the destination file, top of board
  const fileIdx = dest.charCodeAt(0) - 97;
  const leftPct = (flipOverride || userColor) === 'white' ? fileIdx : 7 - fileIdx;
  promoEl.style.left = `calc(26px + ${leftPct} * (min(70vh,560px) / 8))`;
  promoEl.style.top = '2px';
  promoEl.classList.remove('hidden');
}

// ---- websocket ----
let ws;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    setStatus('· reconnecting…');
    setTimeout(connect, 1000);
  };
  ws.onopen = () => setStatus('');
}
function send(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

// ---- sound (Web Audio, synthesized — no files, fully offline) ----
function ensureAudio() {
  if (!audioCtx) {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    } catch {
      // No Web Audio support — sound is a nice-to-have, so just stay silent rather than break the app.
    }
  }
  if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
}
function tone(freq, dur, type, vol, when) {
  if (!soundOn || !audioCtx) return;
  const t = audioCtx.currentTime + (when || 0);
  const o = audioCtx.createOscillator(),
    g = audioCtx.createGain();
  o.type = type || 'sine';
  o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(vol, t + 0.008);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(audioCtx.destination);
  o.start(t);
  o.stop(t + dur + 0.03);
}
function sfx(name) {
  ensureAudio();
  if (!soundOn || !audioCtx) return;
  if (name === 'move') tone(300, 0.09, 'triangle', 0.12);
  else if (name === 'coach') tone(220, 0.11, 'sine', 0.13);
  else if (name === 'capture') {
    tone(170, 0.13, 'sawtooth', 0.14);
    tone(110, 0.15, 'square', 0.05, 0.02);
  } else if (name === 'check') {
    tone(680, 0.09, 'square', 0.11);
    tone(680, 0.09, 'square', 0.11, 0.13);
  } else if (name === 'propose') tone(540, 0.07, 'sine', 0.08);
  else if (name === 'demo') tone(460, 0.07, 'triangle', 0.09);
  else if (name === 'win') {
    tone(523, 0.12, 'triangle', 0.13);
    tone(659, 0.12, 'triangle', 0.13, 0.12);
    tone(784, 0.2, 'triangle', 0.13, 0.24);
  } else if (name === 'lose') {
    tone(392, 0.14, 'sine', 0.12);
    tone(311, 0.24, 'sine', 0.12, 0.14);
  }
}
function moveSound(san, by) {
  if (!san || san.includes('#')) return; // checkmate → game-end sound instead
  if (san.includes('+')) sfx('check');
  else if (san.includes('x')) sfx('capture');
  else sfx(by === 'coach' ? 'coach' : 'move');
}

// ---- propose a move (right-drag draws an arrow; we send it for evaluation) ----
function onDraw(shapes) {
  if (!myTurn || !shapes || !shapes.length) return;
  const arrow = [...shapes].reverse().find((sh) => sh.dest && sh.orig !== sh.dest);
  if (!arrow) return;
  const key = arrow.orig + arrow.dest;
  if (key === lastProposal) return; // don't re-ask the same arrow
  lastProposal = key;
  sfx('propose');
  send({ type: 'propose', from: arrow.orig, to: arrow.dest });
}
function addProposal(m) {
  const div = document.createElement('div');
  div.className = 'msg propose';
  if (m.san) {
    const b = document.createElement('b');
    b.textContent = m.san + '? ';
    div.appendChild(b);
  }
  div.appendChild(document.createTextNode(m.chat || ''));
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function handle(m) {
  if (m.type === 'state') applyState(m);
  else if (m.type === 'coach') {
    if (m.text) addMsg('coach', m.text, 'Coach');
  } else if (m.type === 'feedback') addFeedback(m);
  else if (m.type === 'info') addMsg('info', m.message);
  else if (m.type === 'hint') addMsg('hint', `Engine likes ${m.best || '—'}`);
  else if (m.type === 'rating') addRating(m);
  else if (m.type === 'proposal') addProposal(m);
  else if (m.type === 'lesson_offer') showLessonOffer(m);
  else if (m.type === 'lesson_start') startLessonPlayback(m);
  else if (m.type === 'error') addMsg('info', m.message);
}

// ---- rendering ----
function applyState(s) {
  latestFen = s.fen;
  userColor = s.userColor;
  const orient = flipOverride || s.userColor;
  myTurn = s.turn === s.userColor && !s.gameOver;
  ground.set({
    fen: s.fen,
    orientation: orient,
    turnColor: s.turn,
    check: s.check,
    lastMove: s.lastMove || undefined,
    movable: {
      free: false,
      color: myTurn ? s.userColor : undefined,
      dests: toDests(s.dests || {}),
      showDests: true,
    },
  });
  renderEval(s.evalWhite);
  renderCaptured(s.captured, s.materialDiff, orient);
  renderMoves(s.moveLog);
  el('spend').textContent = `$${(s.spend ?? 0).toFixed(4)}`;
  el('today').textContent = `$${(s.spentToday ?? 0).toFixed(4)}`;
  el('tb').textContent = s.takebacks ?? 0;
  el('elo').textContent = `~${s.opponentElo}`;
  el('model').textContent = s.model || '';
  el('yourElo').textContent = s.yourElo ? `~${s.yourElo}` : 'no read yet';
  el('calib').textContent = s.yourElo ? (s.calibrating ? ' · calibrating' : ' · dialed in') : '';
  el('games').textContent = s.gamesPlayed ?? 0;
  setStatus(s.thinking ? '· coach is thinking…' : '');

  // sounds for newly-played moves, and the game-end jingle
  const mc = (s.moveLog || []).length;
  if (mc > prevMoveCount) {
    const last = s.moveLog[mc - 1];
    if (last) moveSound(last.san, last.by);
  }
  if (mc !== prevMoveCount) lastProposal = null; // a move (or takeback) clears the arrow dedupe
  prevMoveCount = mc;
  if (s.gameOver && !prevGameOver) {
    const won =
      (s.result === '1-0' && s.userColor === 'white') ||
      (s.result === '0-1' && s.userColor === 'black');
    const lost =
      (s.result === '1-0' && s.userColor === 'black') ||
      (s.result === '0-1' && s.userColor === 'white');
    sfx(won ? 'win' : lost ? 'lose' : 'coach');
  }
  prevGameOver = s.gameOver;

  if (s.gameOver) showBanner(s.result);
}

function fmtEval(cp) {
  if (cp == null) return '—';
  if (Math.abs(cp) >= 90000) return cp > 0 ? 'M+' : 'M−';
  return (cp / 100).toFixed(1);
}
function renderEval(cp) {
  lastCp = cp;
  let adv;
  if (cp == null) adv = 0.5;
  else if (Math.abs(cp) >= 90000) adv = cp > 0 ? 1 : 0;
  else adv = 1 / (1 + Math.exp(-cp / 350));
  // fill grows from the bottom for whichever side the board is oriented to
  const whiteBottom = (flipOverride || userColor) === 'white';
  evalFill.style.height = `${(whiteBottom ? adv : 1 - adv) * 100}%`;
  evalNum.textContent = fmtEval(cp);
}

const GLYPH = {
  white: { q: '♕', r: '♖', b: '♗', n: '♘', p: '♙' },
  black: { q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' },
};

function renderCaptured(captured, materialDiff, orient) {
  if (!captured) return;
  const bottom = orient,
    top = orient === 'white' ? 'black' : 'white';
  const diffFor = (side) => (side === 'white' ? materialDiff : -materialDiff);
  const fill = (el, side) => {
    el.innerHTML = '';
    // pieces THIS side captured are drawn in the OPPONENT's glyph colour (what was taken)
    const glyphSet = GLYPH[side === 'white' ? 'black' : 'white'];
    for (const letter of captured[side] || []) {
      const span = document.createElement('span');
      span.className = 'cap-piece';
      span.textContent = glyphSet[letter] || '';
      el.appendChild(span);
    }
    const d = diffFor(side);
    if (d > 0) {
      const badge = document.createElement('span');
      badge.className = 'diff';
      badge.textContent = `+${d}`;
      el.appendChild(badge);
    }
  };
  fill(el('capTop'), top);
  fill(el('capBottom'), bottom);
}

function renderMoves(log) {
  movesEl.innerHTML = '';
  log.forEach((mv, i) => {
    if (i % 2 === 0) {
      const num = document.createElement('span');
      num.className = 'num';
      num.textContent = `${Math.floor(i / 2) + 1}.`;
      movesEl.appendChild(num);
    }
    const span = document.createElement('span');
    span.className = `mv ${mv.by === 'you' ? 'you' : 'coach'} ${mv.cls ? 'g-' + mv.cls : ''}`;
    span.textContent = mv.san;
    movesEl.appendChild(span);
  });
  movesEl.scrollTop = movesEl.scrollHeight;
}

function addMsg(kind, text, who) {
  const div = document.createElement('div');
  div.className = `msg ${kind}`;
  if (who) {
    const b = document.createElement('b');
    b.textContent = who + ': ';
    div.appendChild(b);
  }
  div.appendChild(document.createTextNode(text));
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addFeedback(m) {
  const div = document.createElement('div');
  div.className = 'msg you';
  const worse = ['inaccuracy', 'mistake', 'blunder'].includes(m.cls);
  const tail = worse ? ` (−${m.cpLoss}cp)` : '';
  div.innerHTML = `You: ${m.san} — <span class="grade g-${m.cls}">${m.cls}</span>${tail}`;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addRating(m) {
  const dir = m.estimate > m.prev ? '▲' : m.estimate < m.prev ? '▼' : '=';
  const status = m.calibrating ? `calibrating · game ${m.gamesRated}` : 'dialed in';
  addMsg('rating', `📊 New read on you: ~${m.estimate} ${dir} (was ~${m.prev}) — ${status}`);
}

function showBanner(result) {
  const div = document.createElement('div');
  div.className = 'banner';
  const label = { '1-0': 'White wins', '0-1': 'Black wins', '1/2-1/2': 'Draw' }[result] || result;
  div.textContent = `Game over — ${label}`;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function setStatus(t) {
  statusEl.textContent = t;
}

// ---- practice-board demonstrations ("diversions") ----
let pendingLessonId = null;
let activeLesson = null; // the lesson_start payload while playback is running
let lessonStepIdx = -1;
let lessonTimer = null;

function turnFromFen(fen) {
  return fen.split(' ')[1] === 'w' ? 'white' : 'black';
}

function showLessonOffer(m) {
  pendingLessonId = m.lessonId;
  el('lessonTeaser').textContent = m.teaser;
  document.querySelector('#lessonOfferModal .modal-actions').classList.remove('hidden');
  el('lessonOfferModal').classList.remove('hidden');
}

function startLessonPlayback(m) {
  el('lessonOfferModal').classList.add('hidden');
  activeLesson = m;
  lessonStepIdx = -1;
  document.getElementById('app').classList.add('diverting');
  el('lessonOverlay').classList.remove('hidden'); // must be visible BEFORE Chessground measures it
  const lg = ensureLessonGround();
  lg.set({
    fen: m.startFen,
    orientation: m.orientation,
    turnColor: turnFromFen(m.startFen),
    lastMove: undefined,
    check: undefined,
  });
  el('lessonNarration').textContent = m.intro || 'Let’s take a look…';
  el('lessonProgress').textContent = `0 / ${m.steps.length}`;
  el('lessonContinue').classList.add('hidden');
  scheduleLessonStep(1300);
}

function scheduleLessonStep(delay) {
  clearTimeout(lessonTimer);
  lessonTimer = setTimeout(advanceLesson, delay);
}

function advanceLesson() {
  if (!activeLesson) return;
  const steps = activeLesson.steps;
  lessonStepIdx++;
  if (lessonStepIdx >= steps.length) {
    el('lessonNarration').textContent = activeLesson.outro || 'Back to the game.';
    el('lessonProgress').textContent = `${steps.length} / ${steps.length}`;
    el('lessonContinue').classList.remove('hidden');
    return;
  }
  const step = steps[lessonStepIdx];
  lessonGround.set({
    fen: step.fen,
    turnColor: turnFromFen(step.fen),
    lastMove: step.lastMove,
    check: !!step.check,
  });
  if (step.san && step.san.includes('+')) sfx('check');
  else if (step.capture) sfx('capture');
  else sfx('demo');
  el('lessonNarration').textContent = step.narration || step.san;
  el('lessonProgress').textContent = `${lessonStepIdx + 1} / ${steps.length}`;
  scheduleLessonStep(1500);
}

function skipLesson() {
  clearTimeout(lessonTimer);
  if (!activeLesson) return;
  const steps = activeLesson.steps;
  lessonStepIdx = steps.length - 1;
  const last = steps[steps.length - 1];
  if (last)
    lessonGround.set({
      fen: last.fen,
      turnColor: turnFromFen(last.fen),
      lastMove: last.lastMove,
      check: !!last.check,
    });
  el('lessonNarration').textContent = activeLesson.outro || (last ? last.narration : '');
  el('lessonProgress').textContent = `${steps.length} / ${steps.length}`;
  el('lessonContinue').classList.remove('hidden');
}

function endLesson() {
  clearTimeout(lessonTimer);
  document.getElementById('app').classList.remove('diverting');
  el('lessonOverlay').classList.add('hidden');
  const id = activeLesson ? activeLesson.lessonId : null;
  activeLesson = null;
  if (id != null) send({ type: 'lesson_done', lessonId: id });
}

el('lessonYes').onclick = () => {
  ensureAudio();
  document.querySelector('#lessonOfferModal .modal-actions').classList.add('hidden');
  el('lessonTeaser').textContent = 'One moment…';
  send({ type: 'lesson_respond', lessonId: pendingLessonId, accept: true });
};
el('lessonNo').onclick = () => {
  el('lessonOfferModal').classList.add('hidden');
  send({ type: 'lesson_respond', lessonId: pendingLessonId, accept: false });
};
el('lessonContinue').onclick = endLesson;
el('lessonExit').onclick = endLesson;
el('lessonSkip').onclick = skipLesson;

// ---- controls ----
document.querySelectorAll('.newgame [data-color]').forEach((b) => {
  b.onclick = () => {
    ensureAudio();
    chatEl.innerHTML = '';
    send({ type: 'new_game', color: b.dataset.color });
  };
});
el('takeback').onclick = () => send({ type: 'takeback' });
el('hint').onclick = () => send({ type: 'hint' });
el('resign').onclick = () => send({ type: 'resign' });
el('sound').onclick = () => {
  soundOn = !soundOn;
  el('sound').textContent = soundOn ? '🔊' : '🔇';
  el('sound').title = soundOn ? 'Sound on' : 'Sound off';
  if (soundOn) sfx('move');
};
el('flip').onclick = () => {
  const cur = flipOverride || userColor;
  flipOverride = cur === 'white' ? 'black' : 'white';
  ground.set({ orientation: flipOverride });
  renderEval(lastCp);
};

connect();

// Dev convenience: drive the client from the console (local, personal tool).
window.cc = {
  ground,
  get lessonGround() {
    return lessonGround;
  }, // live accessor — it's built lazily, on first use
  move: (o, d, p) => send({ type: 'move', from: o, to: d, promotion: p || null }),
  propose: (o, d) => send({ type: 'propose', from: o, to: d }),
  newGame: (c) => {
    chatEl.innerHTML = '';
    send({ type: 'new_game', color: c });
  },
  lessonRespond: (accept) => send({ type: 'lesson_respond', lessonId: pendingLessonId, accept }),
  getLessonState: () => ({ pendingLessonId, activeLesson, lessonStepIdx }),
};
