/* dust.js — per-mote jittering dust grid (canvas-based)
   Single grid of individually animated particles with unique sub-pixel trembling. */

(function () {
  'use strict';

  var GRID = 36;
  var DOT_R = 0.8;
  var JITTER_AMP = 2.4;
  var JITTER_SPEED = 0.0008;
  var DRIFT_SPEED = 0.0003;
  var FPS_CAP = 15;
  var FRAME_MS = 1000 / FPS_CAP;

  function parseRGBA(str) {
    var m = str.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?\s*\)/);
    if (!m) return [128, 128, 128, 0.3];
    return [+m[1], +m[2], +m[3], m[4] !== undefined ? +m[4] : 1];
  }

  function readColor() {
    return parseRGBA(getComputedStyle(document.documentElement).getPropertyValue('--dust-dot').trim());
  }

  function init() {
    var canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;';
    document.body.insertBefore(canvas, document.body.firstChild);
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var w, h, motes;

    function buildMotes() {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      motes = [];
      for (var y = 0; y < h + GRID; y += GRID) {
        for (var x = 0; x < w + GRID; x += GRID) {
          motes.push({
            bx: x, by: y,
            px: (x * 7.3 + y * 13.7) % 6.2832,
            py: (x * 11.1 + y * 5.9) % 6.2832
          });
        }
      }
    }

    buildMotes();

    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(buildMotes, 200);
    });

    var rgba = readColor();
    var observer = new MutationObserver(function () { rgba = readColor(); });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    var lastFrame = 0;
    var t0 = performance.now();

    function draw(now) {
      requestAnimationFrame(draw);
      if (now - lastFrame < FRAME_MS) return;
      lastFrame = now;

      var elapsed = now - t0;
      var driftX = (elapsed * DRIFT_SPEED) % GRID;
      var driftY = (elapsed * DRIFT_SPEED * 2) % GRID;

      ctx.clearRect(0, 0, w, h);

      for (var i = 0, n = motes.length; i < n; i++) {
        var m = motes[i];
        var jx = Math.sin(elapsed * JITTER_SPEED + m.px) * JITTER_AMP;
        var jy = Math.cos(elapsed * JITTER_SPEED * 1.3 + m.py) * JITTER_AMP;
        var x = m.bx + jx + driftX;
        var y = m.by + jy + driftY;

        x = ((x % w) + w) % w;
        y = ((y % h) + h) % h;

        var fade = 1.0 - (y / h) * 0.18;
        ctx.fillStyle = 'rgba(' + rgba[0] + ',' + rgba[1] + ',' + rgba[2] + ',' + (rgba[3] * fade).toFixed(3) + ')';
        ctx.beginPath();
        ctx.arc(x, y, DOT_R, 0, 6.2832);
        ctx.fill();
      }
    }

    requestAnimationFrame(draw);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
