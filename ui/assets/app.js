// ===== BACKGROUND CANVAS — Particle Network =====
const canvas = document.getElementById('bgCanvas');
const ctx = canvas.getContext('2d');
let W, H;

function resize() {
  W = canvas.width = window.innerWidth;
  H = canvas.height = window.innerHeight;
}
resize();
window.addEventListener('resize', resize);

const PARTICLES = 120;
const CONNECTION_DIST = 130;
const particles = [];

for (let i = 0; i < PARTICLES; i++) {
  particles.push({
    x: Math.random() * W,
    y: Math.random() * H,
    vx: (Math.random() - 0.5) * 0.5,
    vy: (Math.random() - 0.5) * 0.5,
    r: Math.random() * 2 + 1,
  });
}

function drawParticles() {
  ctx.clearRect(0, 0, W, H);

  for (const p of particles) {
    p.x += p.vx;
    p.y += p.vy;
    if (p.x < 0) p.x = W;
    if (p.x > W) p.x = 0;
    if (p.y < 0) p.y = H;
    if (p.y > H) p.y = 0;

    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = '#7f5af0';
    ctx.shadowBlur = 8;
    ctx.shadowColor = '#7f5af066';
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x;
      const dy = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < CONNECTION_DIST) {
        const alpha = 1 - dist / CONNECTION_DIST;
        ctx.beginPath();
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.strokeStyle = `rgba(127, 90, 240, ${alpha * 0.4})`;
        ctx.lineWidth = 0.6;
        ctx.stroke();
      }
    }
  }

  requestAnimationFrame(drawParticles);
}

drawParticles();

// ===== CONSOLE LOG =====
const consoleEl = document.getElementById('console');

function logToConsole(msg, type = 'info') {
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  const line = document.createElement('div');
  line.className = 'line';
  if (type === 'highlight') {
    line.innerHTML = `<span class="timestamp">[${ts}]</span> <span class="prompt">⟫</span> <span class="highlight">${msg}</span>`;
  } else if (type === 'error') {
    line.innerHTML = `<span class="timestamp">[${ts}]</span> <span class="prompt">⟫</span> <span class="error">${msg}</span>`;
  } else {
    line.innerHTML = `<span class="timestamp">[${ts}]</span> <span class="prompt">⟫</span> ${msg}`;
  }
  consoleEl.appendChild(line);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ===== CARD ACTIONS =====
document.querySelectorAll('.btn-pulse').forEach((btn) => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.target;

    switch (target) {
      case 'matrix': {
        const codes = ['0x7F5AF0', '0x2CB67D', '0xFFFF00', '0xFF0055', '0x00E5FF'];
        const hex = codes[Math.floor(Math.random() * codes.length)];
        const intensity = Math.floor(Math.random() * 100);
        logToConsole(`🟣 Matrix Pulse » hex=${hex} intensity=${intensity}%`, 'highlight');
        break;
      }
      case 'void': {
        const packets = Math.floor(Math.random() * 9000 + 1000);
        const lost = Math.floor(packets * Math.random() * 0.3);
        logToConsole(`⬟ Void Signal » ${packets} packets sent, ${lost} lost to the abyss`, lost > 500 ? 'error' : 'highlight');
        break;
      }
      case 'chronos': {
        const fragments = ['~ echo from 1999', '~ whisper of tomorrow', '~ ghost in the machine', '~ origin of the signal', '~ end of the loop'];
        const pick = fragments[Math.floor(Math.random() * fragments.length)];
        logToConsole(`⟁ Chronos Gate » ${pick}`, 'highlight');
        break;
      }
      case 'quantum': {
        const outcomes = ['State: COLLAPSED ✓', 'State: SUPERPOSITION ⬟', 'State: ENTANGLED ⟁', 'State: OBSERVED ◈', 'State: DECOHERED ✕'];
        const state = outcomes[Math.floor(Math.random() * outcomes.length)];
        logToConsole(`⧫ Quantum Rift » ${state}`, state.includes('✕') ? 'error' : 'highlight');
        break;
      }
      default:
        logToConsole(`Unknown command: ${target}`, 'error');
    }
  });
});

// ===== RANDOM AMBIENT LOG =====
const ambientMessages = [
  '⟳ Daemon heartbeat OK',
  '⋮ Scanning localhost…',
  '◈ Cipher cycle complete',
  '⟁ Recursive loop detected',
  '⬟ Packet from unknown origin',
];

setInterval(() => {
  if (Math.random() > 0.65) {
    const msg = ambientMessages[Math.floor(Math.random() * ambientMessages.length)];
    logToConsole(msg);
  }
}, 8000);

logToConsole('All modules loaded. Ready.', 'highlight');
