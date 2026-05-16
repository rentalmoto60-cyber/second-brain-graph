// 2.5s splash animation on a 2D canvas. Lightweight and self-contained.
// Phases: dot (0–0.5s) → grow brain silhouette (0.5–1.5s) → lobe flashes (1.5–2.0s) → fade (2.0–2.5s).

export function runSplash(splashEl, canvas) {
  if (localStorage.getItem("skip_splash") === "true") {
    splashEl.classList.add("fade-out");
    return Promise.resolve();
  }

  const ctx = canvas.getContext("2d");
  let w, h;
  const resize = () => {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  };
  resize();
  window.addEventListener("resize", resize);

  const start = performance.now();
  const DURATION = 2500;

  return new Promise((resolve) => {
    function frame(now) {
      const elapsed = now - start;
      const t = Math.min(elapsed / DURATION, 1);
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2, cy = h / 2;

      if (t < 0.2) {
        const a = t / 0.2;
        drawDot(ctx, cx, cy, 4 + a * 6, `rgba(255,210,220,${a})`);
      } else if (t < 0.6) {
        const a = (t - 0.2) / 0.4;
        drawBrainSilhouette(ctx, cx, cy, 40 + a * 90, 0.6 + 0.4 * Math.sin(now * 0.01), a);
      } else if (t < 0.8) {
        drawBrainSilhouette(ctx, cx, cy, 130, 1.0, 1.0);
        const a = (t - 0.6) / 0.2;
        drawLobeFlashes(ctx, cx, cy, 130, a);
      } else {
        drawBrainSilhouette(ctx, cx, cy, 130, 1.0, 1.0 - (t - 0.8) / 0.2);
        splashEl.style.opacity = 1.0 - (t - 0.8) / 0.2;
      }

      if (t < 1) requestAnimationFrame(frame);
      else {
        splashEl.classList.add("fade-out");
        window.removeEventListener("resize", resize);
        setTimeout(resolve, 500);
      }
    }
    requestAnimationFrame(frame);
  });
}

function drawDot(ctx, x, y, r, color) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.shadowBlur = 24; ctx.shadowColor = color;
  ctx.fill();
  ctx.shadowBlur = 0;
}

function drawBrainSilhouette(ctx, cx, cy, size, pulse, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.translate(cx, cy);
  ctx.scale(pulse, pulse * 0.92);
  ctx.beginPath();
  // Two ellipses ≈ hemispheres
  ctx.ellipse(-size * 0.35, 0, size * 0.55, size * 0.7, 0, 0, Math.PI * 2);
  ctx.ellipse( size * 0.35, 0, size * 0.55, size * 0.7, 0, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(212,155,168,0.25)";
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(255,212,216,0.5)";
  ctx.stroke();
  ctx.restore();
}

function drawLobeFlashes(ctx, cx, cy, size, t) {
  const lobes = [
    [-size * 0.4,  size * 0.25],
    [ size * 0.4,  size * 0.25],
    [-size * 0.4, -size * 0.25],
    [ size * 0.4, -size * 0.25],
  ];
  for (let i = 0; i < lobes.length; i++) {
    const phase = t - i * 0.2;
    if (phase < 0 || phase > 0.5) continue;
    const a = Math.sin(phase / 0.5 * Math.PI);
    const [dx, dy] = lobes[i];
    ctx.beginPath();
    ctx.arc(cx + dx, cy + dy, 18 * a, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(133,183,235,${a * 0.6})`;
    ctx.shadowBlur = 30; ctx.shadowColor = `rgba(133,183,235,${a})`;
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}
