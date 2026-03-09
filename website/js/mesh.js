/**
 * REFInet Mesh Network Canvas Animation
 * Animated node/mesh network for the hero section
 */
(function () {
  const canvas = document.getElementById('mesh-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const NODE_COUNT = 42;
  const CONNECT_DIST = 150;
  const PULSE_INTERVAL = 3000;

  let width, height;
  let mouseX = -1000, mouseY = -1000;
  let nodes = [];
  let animId;

  function resize() {
    width = canvas.width = canvas.parentElement.offsetWidth;
    height = canvas.height = canvas.parentElement.offsetHeight;
  }

  function createNodes() {
    nodes = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      nodes.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        radius: 2 + Math.random() * 2,
        pulseRadius: 0,
        pulseAlpha: 0,
        nextPulse: Date.now() + Math.random() * PULSE_INTERVAL * 3
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);

    // Update and draw connections
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < CONNECT_DIST) {
          const alpha = (1 - dist / CONNECT_DIST) * 0.35;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.strokeStyle = `rgba(0, 240, 255, ${alpha})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }
      }
    }

    const now = Date.now();
    for (const n of nodes) {
      // Mouse attraction
      const mdx = mouseX - n.x;
      const mdy = mouseY - n.y;
      const mDist = Math.sqrt(mdx * mdx + mdy * mdy);
      if (mDist < 200 && mDist > 1) {
        n.vx += (mdx / mDist) * 0.02;
        n.vy += (mdy / mDist) * 0.02;
      }

      // Move
      n.x += n.vx;
      n.y += n.vy;

      // Dampen
      n.vx *= 0.999;
      n.vy *= 0.999;

      // Bounce
      if (n.x < 0 || n.x > width) n.vx *= -1;
      if (n.y < 0 || n.y > height) n.vy *= -1;
      n.x = Math.max(0, Math.min(width, n.x));
      n.y = Math.max(0, Math.min(height, n.y));

      // Pulse
      if (now > n.nextPulse) {
        n.pulseRadius = 0;
        n.pulseAlpha = 0.6;
        n.nextPulse = now + PULSE_INTERVAL + Math.random() * PULSE_INTERVAL * 2;
      }
      if (n.pulseAlpha > 0) {
        n.pulseRadius += 1.2;
        n.pulseAlpha -= 0.008;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.pulseRadius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(0, 240, 255, ${Math.max(0, n.pulseAlpha)})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw node
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 240, 255, 0.5)';
      ctx.fill();
    }

    animId = requestAnimationFrame(draw);
  }

  // Pause when tab hidden
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      cancelAnimationFrame(animId);
    } else {
      animId = requestAnimationFrame(draw);
    }
  });

  canvas.addEventListener('mousemove', function (e) {
    const rect = canvas.getBoundingClientRect();
    mouseX = e.clientX - rect.left;
    mouseY = e.clientY - rect.top;
  });
  canvas.addEventListener('mouseleave', function () {
    mouseX = -1000;
    mouseY = -1000;
  });

  window.addEventListener('resize', function () {
    resize();
  });

  resize();
  createNodes();
  draw();
})();
