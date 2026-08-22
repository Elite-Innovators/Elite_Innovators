/* ═══════════════════════════════════════════════
   SolarScan — main.js
   Sun-path animation · Scroll reveal · Scan modal
   ═══════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ════════════ 1. SCROLL PROGRESS BAR ════════════ */
  const progressBar = document.getElementById('progress');
  window.addEventListener('scroll', () => {
    const h = document.documentElement;
    const pct = (h.scrollTop / (h.scrollHeight - h.clientHeight)) * 100;
    progressBar.style.width = Math.min(pct, 100) + '%';
  });


  /* ════════════ 2. SUN-PATH ANIMATION ════════════ */
  const liveSun = document.getElementById('liveSun');
  const liveShadow = document.getElementById('liveShadow');
  const rvElev = document.getElementById('rvElevation');
  const rvShaded = document.getElementById('rvShaded');
  const rvYield = document.getElementById('rvYield');
  const rvRevenue = document.getElementById('rvRevenue');
  const sunLabel = document.getElementById('sunTimeLabel');

  // Sun follows a quadratic bezier: start(20,205) control(230,10) end(440,205)
  // t goes 0→1 over a ~8 second cycle
  const SUN_ARC = {
    x0: 20, y0: 205,
    cx: 230, cy: 10,
    x1: 440, y1: 205,
  };

  function bezierPoint(t) {
    const a = SUN_ARC;
    const mt = 1 - t;
    return {
      x: mt * mt * a.x0 + 2 * mt * t * a.cx + t * t * a.x1,
      y: mt * mt * a.y0 + 2 * mt * t * a.cy + t * t * a.y1,
    };
  }

  // Shadow polygon: cast from the left obstruction (top-right corner at 75,130)
  // onto the ground and roof, scaled by sun angle
  function shadowPoints(sunX, sunY) {
    const ground = 205;
    const roofLeft = 140, roofRight = 320, roofTop = 150;

    // Determine which obstruction casts the primary shadow over the roof
    const isLeftObs = sunX < 230;

    let ox, oy, obsBaseX;
    if (isLeftObs) {
      ox = 75; oy = 130; obsBaseX = 75;
    } else {
      ox = 395; oy = 110; obsBaseX = 395;
    }

    const dx = ox - sunX;
    const dy = oy - sunY;

    // If sun is below the obstruction or on the wrong side, no visible shadow over the area
    if (dy <= 0 || (isLeftObs && dx <= 0) || (!isLeftObs && dx >= 0)) {
      return `${obsBaseX},${ground} ${obsBaseX},${ground} ${obsBaseX},${ground}`;
    }

    let pts = [`${obsBaseX},${ground}`];

    if (isLeftObs) {
      const tGround = (ground - oy) / dy;
      const xGround = ox + dx * tGround;

      if (xGround <= roofLeft) {
        pts.push(`${xGround.toFixed(1)},${ground}`);
      } else {
        pts.push(`${roofLeft},${ground}`);
        const tWall = (roofLeft - ox) / dx;
        const yWall = oy + dy * tWall;

        if (yWall >= roofTop && yWall <= ground) {
          pts.push(`${roofLeft},${yWall.toFixed(1)}`);
        } else {
          pts.push(`${roofLeft},${roofTop}`);
          const tRoof = (roofTop - oy) / dy;
          const xRoof = ox + dx * tRoof;

          if (xRoof <= roofRight) {
            pts.push(`${xRoof.toFixed(1)},${roofTop}`);
          } else {
            pts.push(`${roofRight},${roofTop}`);
            const tRightWall = (roofRight - ox) / dx;
            const yRightWall = oy + dy * tRightWall;

            if (yRightWall >= roofTop && yRightWall <= ground) {
              pts.push(`${roofRight},${yRightWall.toFixed(1)}`);
            } else {
              pts.push(`${roofRight},${ground}`);
              pts.push(`${Math.min(xGround, 460).toFixed(1)},${ground}`);
            }
          }
        }
      }
    } else {
      const tGround = (ground - oy) / dy;
      const xGround = ox + dx * tGround;

      if (xGround >= roofRight) {
        pts.push(`${xGround.toFixed(1)},${ground}`);
      } else {
        pts.push(`${roofRight},${ground}`);
        const tWall = (roofRight - ox) / dx;
        const yWall = oy + dy * tWall;

        if (yWall >= roofTop && yWall <= ground) {
          pts.push(`${roofRight},${yWall.toFixed(1)}`);
        } else {
          pts.push(`${roofRight},${roofTop}`);
          const tRoof = (roofTop - oy) / dy;
          const xRoof = ox + dx * tRoof;

          if (xRoof >= roofLeft) {
            pts.push(`${xRoof.toFixed(1)},${roofTop}`);
          } else {
            pts.push(`${roofLeft},${roofTop}`);
            const tLeftWall = (roofLeft - ox) / dx;
            const yLeftWall = oy + dy * tLeftWall;

            if (yLeftWall >= roofTop && yLeftWall <= ground) {
              pts.push(`${roofLeft},${yLeftWall.toFixed(1)}`);
            } else {
              pts.push(`${roofLeft},${ground}`);
              pts.push(`${Math.max(xGround, 0).toFixed(1)},${ground}`);
            }
          }
        }
      }
    }

    pts.push(`${ox},${oy}`);
    return pts.join(' ');
  }

  function getShadedPercentage(sunX, sunY) {
    const roofLeft = 140, roofRight = 320, roofTop = 150;
    const roofWidth = roofRight - roofLeft;
    const isLeftObs = sunX < 230;
    const ox = isLeftObs ? 75 : 395;
    const oy = isLeftObs ? 130 : 110;
    const dx = ox - sunX;
    const dy = oy - sunY;

    if (dy <= 0 || (isLeftObs && dx <= 0) || (!isLeftObs && dx >= 0)) return 0;

    const tRoof = (roofTop - oy) / dy;
    const xRoof = ox + dx * tRoof;

    let shadedWidth = 0;
    if (isLeftObs) {
      if (xRoof > roofLeft) {
        shadedWidth = Math.min(xRoof, roofRight) - roofLeft;
      }
    } else {
      if (xRoof < roofRight) {
        shadedWidth = roofRight - Math.max(xRoof, roofLeft);
      }
    }
    return Math.max(0, Math.min(100, (shadedWidth / roofWidth) * 100));
  }

  const CYCLE_DURATION = 8000; // ms for one full sun arc
  let sunStart = performance.now();

  function tickSun(now) {
    const elapsed = (now - sunStart) % CYCLE_DURATION;
    const t = elapsed / CYCLE_DURATION;

    const pos = bezierPoint(t);
    liveSun.setAttribute('cx', pos.x.toFixed(1));
    liveSun.setAttribute('cy', pos.y.toFixed(1));

    // glow effect based on elevation
    const elevation = Math.max(0, (205 - pos.y) / 195 * 90);
    const glowRadius = 4 + elevation / 90 * 8;
    liveSun.setAttribute('r', glowRadius.toFixed(1));
    liveSun.style.filter = `drop-shadow(0 0 ${glowRadius}px rgba(255,201,74,0.8))`;

    // shadow
    liveShadow.setAttribute('points', shadowPoints(pos.x, pos.y));

    // data readouts
    const elevDeg = elevation.toFixed(0);
    const exactShaded = getShadedPercentage(pos.x, pos.y);
    const shadedStr = exactShaded.toFixed(0);

    // adjust yield by sun elevation and unshaded area
    const unshadedRatio = (100 - exactShaded) / 100;
    const yieldNow = (Math.max(0, elevation / 90) * 5.2 * unshadedRatio).toFixed(1);

    const hour = Math.floor(6 + t * 12); // 6 AM to 6 PM
    const minute = Math.floor((6 + t * 12 - hour) * 60);
    const revenue = Math.round(12000 + (elevation / 90) * 38000 * unshadedRatio);

    rvElev.textContent = elevDeg + '°';
    rvShaded.textContent = shadedStr + '%';
    rvYield.textContent = yieldNow + ' kWh/hr';
    rvRevenue.textContent = '₹' + revenue.toLocaleString('en-IN') + '/yr';
    sunLabel.textContent = String(hour).padStart(2, '0') + ':' + String(minute).padStart(2, '0');

    // color classes
    rvShaded.className = 'rv' + (parseInt(shadedStr) > 30 ? '' : ' up');
    rvYield.className = 'rv' + (parseFloat(yieldNow) > 2 ? ' up' : '');

    requestAnimationFrame(tickSun);
  }
  requestAnimationFrame(tickSun);


  /* ════════════ 3. SCROLL REVEAL (How It Works) ════════════ */
  const logRows = document.querySelectorAll('.log-row[data-row]');
  if (logRows.length) {
    const revealIO = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          // also mark as "active" for step number highlight
          e.target.classList.add('active');
        }
      });
    }, { threshold: 0.15 });
    logRows.forEach(row => revealIO.observe(row));
  }


  /* ════════════ 4. SCAN MODAL ════════════ */
  const backdrop = document.getElementById('scanBackdrop');
  const openScanBtn = document.getElementById('openScanBtn');
  const closeScanBtn = document.getElementById('closeScanBtn');
  const cancelScanBtn = document.getElementById('cancelScanBtn');
  const runScanBtn = document.getElementById('runScanBtn');
  const scanStatus = document.getElementById('scanStatus');
  const imageryFrame = document.getElementById('imageryFrame');
  const zoomLayer = document.getElementById('zoomLayer');
  const scanImg = document.getElementById('scanImg');
  const overlaySvg = document.getElementById('overlaySvg');
  const imageryCaption = document.getElementById('imageryCaption');
  const calcGrid = document.getElementById('calcGrid');

  function openModal() { backdrop.classList.add('open'); }
  function closeModal() { backdrop.classList.remove('open'); }

  openScanBtn.addEventListener('click', openModal);
  closeScanBtn.addEventListener('click', closeModal);
  cancelScanBtn.addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && backdrop.classList.contains('open')) closeModal();
  });


  /* ── zoom and pan logic ── */
  let scale = 1, panX = 0, panY = 0, isDragging = false, startX, startY;

  function updateZoom() {
    zoomLayer.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
  }

  imageryFrame.addEventListener('wheel', (e) => {
    e.preventDefault();
    const zoomAmount = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = Math.max(1, Math.min(scale * zoomAmount, 5));

    const rect = imageryFrame.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    panX = mx - (mx - panX) * (newScale / scale);
    panY = my - (my - panY) * (newScale / scale);

    if (newScale === 1) { panX = 0; panY = 0; }
    scale = newScale; updateZoom();
  });

  imageryFrame.addEventListener('mousedown', (e) => {
    if (scale > 1) {
      isDragging = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
    }
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    panX = e.clientX - startX;
    panY = e.clientY - startY;
    updateZoom();
  });

  window.addEventListener('mouseup', () => isDragging = false);


  /* ── run scan ── */
  runScanBtn.addEventListener('click', async () => {
    const latInput = document.getElementById('inputLat');
    const lonInput = document.getElementById('inputLon');
    const lat = parseFloat(latInput.value);
    const lon = parseFloat(lonInput.value);

    if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      scanStatus.textContent = '✗ Enter valid coordinates (lat: -90..90, lon: -180..180)';
      scanStatus.className = 'scan-status error';
      return;
    }

    // reset UI
    imageryFrame.classList.remove('show');
    scale = 1; panX = 0; panY = 0; updateZoom();
    calcGrid.classList.remove('show');
    calcGrid.innerHTML = '';
    overlaySvg.innerHTML = '';
    scanStatus.className = 'scan-status';
    scanStatus.innerHTML = '<span class="spinner"></span>Fetching aerial tile…';
    runScanBtn.disabled = true;

    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lon }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Server error ${res.status}`);
      }

      const data = await res.json();

      // ── show imagery ──
      scanImg.src = data.image_url;
      scanImg.onload = () => {
        imageryFrame.classList.add('show');
        imageryCaption.textContent =
          `${data.width}×${data.height} px · ${data.mpp} m/px · zoom ${data.zoom} · ` +
          `${data.lat.toFixed(5)}°N, ${data.lon.toFixed(5)}°E`;

        // ── draw fake roof polygon overlay ──
        drawRoofOverlay(data.width, data.height);

        // ── show calculations ──
        setTimeout(() => showCalcResults(data), 600);
      };

      scanStatus.textContent = '✓ Tile fetched — analysing roof';
      scanStatus.className = 'scan-status ok';

    } catch (err) {
      scanStatus.textContent = '✗ ' + err.message;
      scanStatus.className = 'scan-status error';
    } finally {
      runScanBtn.disabled = false;
    }
  });


  /* ── draw roof outline overlay ── */
  function drawRoofOverlay(imgW, imgH) {
    overlaySvg.setAttribute('viewBox', `0 0 ${imgW} ${imgH}`);
    overlaySvg.innerHTML = '';

    // Generate a plausible roof polygon (center region of the tile)
    const cx = imgW / 2, cy = imgH / 2;
    const rx = imgW * 0.22, ry = imgH * 0.18;
    const points = [];
    const sides = 5 + Math.floor(Math.random() * 3); // 5–7 sided polygon
    for (let i = 0; i < sides; i++) {
      const angle = (Math.PI * 2 * i) / sides - Math.PI / 2;
      const jitterX = (Math.random() - 0.5) * rx * 0.35;
      const jitterY = (Math.random() - 0.5) * ry * 0.35;
      points.push(`${(cx + Math.cos(angle) * rx + jitterX).toFixed(0)},${(cy + Math.sin(angle) * ry + jitterY).toFixed(0)}`);
    }

    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', points.join(' '));
    poly.setAttribute('class', 'roof-outline');
    overlaySvg.appendChild(poly);

    // trigger draw animation
    requestAnimationFrame(() => poly.classList.add('draw'));

    // vertex dots (staggered)
    points.forEach((pt, i) => {
      const [px, py] = pt.split(',');
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', px);
      circle.setAttribute('cy', py);
      circle.setAttribute('r', Math.max(3, imgW * 0.005));
      circle.setAttribute('class', 'roof-vertex');
      overlaySvg.appendChild(circle);
      setTimeout(() => circle.classList.add('draw'), 400 + i * 120);
    });
  }


  /* ── show calculation results ── */
  function showCalcResults(data) {
    calcGrid.innerHTML = '';
    calcGrid.classList.add('show');

    const rows = [
      ['Usable roof area', `${data.roof_area_m2} m²`],
      ['Peak sun hours/day', `${data.peak_sun_hours} hrs`],
      ['Panel count (540W)', `${data.panel_count} panels`],
      ['System size', `${data.system_kw} kWp`],
      ['Shading loss', `${data.shading_loss_pct}%`],
      ['Estimated annual yield', `${data.annual_kwh.toLocaleString('en-IN')} kWh/yr`],
      ['Gross system cost', `₹${data.gross_cost.toLocaleString('en-IN')}`],
      ['PM Surya Ghar subsidy', `−₹${data.subsidy.toLocaleString('en-IN')}`, 'up'],
      ['Net cost (you pay)', `₹${data.net_cost.toLocaleString('en-IN')}`],
      ['Annual savings', `₹${data.annual_revenue.toLocaleString('en-IN')}/yr`, 'up'],
      ['Payback period', `${data.payback_years} years`, 'hero'],
    ];

    rows.forEach(([label, value, cls], i) => {
      const row = document.createElement('div');
      row.className = 'calc-row';
      row.style.animationDelay = (i * 0.08) + 's';
      row.innerHTML = `<span class="cl">${label}</span><span class="cv${cls ? ' ' + cls : ''}">${value}</span>`;
      calcGrid.appendChild(row);
    });
  }


})();
