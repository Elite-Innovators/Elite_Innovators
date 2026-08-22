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


  /* ════════════ 4b. LOCATION SEARCH (GEOCODING) ════════════ */
  const searchInput     = document.getElementById('searchInput');
  const searchResults   = document.getElementById('searchResults');
  const searchLoading   = document.getElementById('searchLoading');
  const latInput        = document.getElementById('inputLat');
  const lonInput        = document.getElementById('inputLon');
  const clockMeta       = document.getElementById('clockMeta');

  let searchTimeout = null;
  let activeResultIdx = -1;
  let currentResults = [];

  // Debounced geocoding search
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim();
    clearTimeout(searchTimeout);
    activeResultIdx = -1;

    if (q.length < 2) {
      searchResults.classList.remove('open');
      searchResults.innerHTML = '';
      searchLoading.classList.remove('active');
      return;
    }

    searchLoading.classList.add('active');

    searchTimeout = setTimeout(async () => {
      try {
        const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        currentResults = Array.isArray(data) ? data : [];
        renderSearchResults(currentResults);
      } catch (err) {
        searchResults.innerHTML = '<div class="search-result-item"><span class="result-text"><span class="result-name" style="color:var(--flag)">Search failed — check connection</span></span></div>';
        searchResults.classList.add('open');
      } finally {
        searchLoading.classList.remove('active');
      }
    }, 300);
  });

  // Render search results dropdown
  function renderSearchResults(results) {
    searchResults.innerHTML = '';
    if (!results.length) {
      searchResults.innerHTML = '<div class="search-result-item"><span class="result-text"><span class="result-name" style="color:var(--paper-dim)">No locations found</span></span></div>';
      searchResults.classList.add('open');
      return;
    }

    results.forEach((r, i) => {
      const item = document.createElement('div');
      item.className = 'search-result-item';
      item.dataset.index = i;

      // Split display_name for primary/secondary parts
      const parts = r.display_name.split(', ');
      const primary = parts.slice(0, 2).join(', ');
      const secondary = parts.slice(2).join(', ');

      item.innerHTML = `
        <span class="result-pin">📍</span>
        <span class="result-text">
          <span class="result-name">${primary}</span>
          <span class="result-detail">${secondary || r.display_name}</span>
        </span>
        ${r.type ? `<span class="result-type">${r.type}</span>` : ''}
      `;

      item.addEventListener('click', () => selectResult(i));
      item.addEventListener('mouseenter', () => {
        activeResultIdx = i;
        highlightResult();
      });
      searchResults.appendChild(item);
    });
    searchResults.classList.add('open');
  }

  // Select a geocoding result
  function selectResult(index) {
    const r = currentResults[index];
    if (!r) return;

    latInput.value = r.lat.toFixed(6);
    lonInput.value = r.lon.toFixed(6);
    searchInput.value = r.display_name;
    searchResults.classList.remove('open');

    // Update header meta with selected location coordinates
    if (clockMeta) {
      clockMeta.textContent = `${r.lat.toFixed(4)}°${r.lat >= 0 ? 'N' : 'S'}, ${Math.abs(r.lon).toFixed(4)}°${r.lon >= 0 ? 'E' : 'W'}`;
    }

    // Flash the lat/lon fields to show they were populated
    [latInput, lonInput].forEach(inp => {
      inp.style.borderColor = 'var(--good)';
      inp.style.boxShadow = '0 0 0 3px rgba(79,180,119,0.2)';
      setTimeout(() => {
        inp.style.borderColor = '';
        inp.style.boxShadow = '';
      }, 1200);
    });
  }

  // Keyboard navigation for search results
  function highlightResult() {
    const items = searchResults.querySelectorAll('.search-result-item');
    items.forEach((item, i) => {
      item.classList.toggle('active', i === activeResultIdx);
    });
    // Scroll active item into view
    if (items[activeResultIdx]) {
      items[activeResultIdx].scrollIntoView({ block: 'nearest' });
    }
  }

  searchInput.addEventListener('keydown', (e) => {
    const items = searchResults.querySelectorAll('.search-result-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeResultIdx = Math.min(activeResultIdx + 1, items.length - 1);
      highlightResult();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeResultIdx = Math.max(activeResultIdx - 1, 0);
      highlightResult();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeResultIdx >= 0) {
        selectResult(activeResultIdx);
      }
    } else if (e.key === 'Escape') {
      searchResults.classList.remove('open');
    }
  });

  // Close search results when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrapper')) {
      searchResults.classList.remove('open');
    }
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
    const lat = parseFloat(document.getElementById('inputLat').value);
    const lon = parseFloat(document.getElementById('inputLon').value);

    if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      scanStatus.textContent = '✗ Enter valid coordinates (lat: -90..90, lon: -180..180)';
      scanStatus.className = 'scan-status error';
      return;
    }

    // reset UI
    imageryFrame.classList.remove('show');
    imageryFrame.classList.remove('draw-mode');
    scale = 1; panX = 0; panY = 0; updateZoom();
    calcGrid.classList.remove('show');
    calcGrid.innerHTML = '';
    overlaySvg.innerHTML = '';
    scanStatus.className = 'scan-status';
    scanStatus.innerHTML = '<span class="spinner"></span>Fetching aerial tile…';
    runScanBtn.disabled = true;
    resetDrawingState();

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
      lastScanData = data;

      // ── show imagery ──
      scanImg.src = data.image_url;
      scanImg.onload = () => {
        imageryFrame.classList.add('show');
        imageryCaption.textContent =
          `${data.width}×${data.height} px · ${data.mpp} m/px · zoom ${data.zoom} · ` +
          `${data.lat.toFixed(5)}°N, ${data.lon.toFixed(5)}°E`;

        // Setup the overlay SVG viewBox
        overlaySvg.setAttribute('viewBox', `0 0 ${data.width} ${data.height}`);
        currentImgW = data.width;
        currentImgH = data.height;
        currentMpp = data.mpp;

        // ── show calculations ──
        setTimeout(() => showCalcResults(data), 600);
      };

      scanStatus.textContent = '✓ Tile fetched — use ✏️ Draw or 🤖 AI Detect to trace the roof';
      scanStatus.className = 'scan-status ok';

    } catch (err) {
      scanStatus.textContent = '✗ ' + err.message;
      scanStatus.className = 'scan-status error';
    } finally {
      runScanBtn.disabled = false;
    }
  });


  /* ════════════ 5. POLYGON DRAWING ENGINE ════════════ */

  let drawingMode = false;
  let vertices = [];          // [{x, y}] in SVG/image coordinates
  let polygonClosed = false;
  let draggingVertex = -1;
  let lastScanData = null;
  let currentImgW = 0, currentImgH = 0, currentMpp = 0.3;

  const drawModeBtn    = document.getElementById('drawModeBtn');
  const aiDetectBtn    = document.getElementById('aiDetectBtn');
  const undoVertexBtn  = document.getElementById('undoVertexBtn');
  const clearDrawBtn   = document.getElementById('clearDrawBtn');
  const completePolyBtn = document.getElementById('completePolyBtn');
  const areaBadge      = document.getElementById('areaBadge');
  const zoomHint       = document.getElementById('zoomHint');

  function resetDrawingState() {
    vertices = [];
    polygonClosed = false;
    drawingMode = false;
    draggingVertex = -1;
    drawModeBtn.classList.remove('active');
    imageryFrame.classList.remove('draw-mode');
    undoVertexBtn.disabled = true;
    clearDrawBtn.disabled = true;
    completePolyBtn.disabled = true;
    areaBadge.classList.remove('show');
    areaBadge.textContent = '';
  }

  // Toggle draw mode
  drawModeBtn.addEventListener('click', () => {
    if (polygonClosed) {
      // If polygon is already closed, clear it to start fresh
      clearPolygon();
    }
    drawingMode = !drawingMode;
    drawModeBtn.classList.toggle('active', drawingMode);
    imageryFrame.classList.toggle('draw-mode', drawingMode);
    if (drawingMode && zoomHint) {
      zoomHint.textContent = 'Click to place vertices · Click first vertex to close';
    } else if (zoomHint) {
      zoomHint.textContent = 'Scroll to zoom · Click & drag to pan';
    }
  });

  // Get mouse position in SVG coordinates
  function getSvgPoint(e) {
    const rect = scanImg.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * currentImgW;
    const y = ((e.clientY - rect.top) / rect.height) * currentImgH;
    return { x, y };
  }

  // Click on image to place vertex
  zoomLayer.addEventListener('click', (e) => {
    if (!drawingMode || polygonClosed) return;
    if (e.target.closest('.draw-vertex')) return; // handled separately
    e.stopPropagation();

    const pt = getSvgPoint(e);

    // Check if clicking near first vertex to close
    if (vertices.length >= 3) {
      const first = vertices[0];
      const dist = Math.sqrt((pt.x - first.x) ** 2 + (pt.y - first.y) ** 2);
      const threshold = currentImgW * 0.015;
      if (dist < threshold) {
        closePolygon();
        return;
      }
    }

    vertices.push(pt);
    renderDrawing();
    updateToolbarState();
  });

  // Mouse move for guide line
  zoomLayer.addEventListener('mousemove', (e) => {
    if (!drawingMode || polygonClosed || vertices.length === 0) return;

    if (draggingVertex >= 0) {
      // Dragging a vertex
      const pt = getSvgPoint(e);
      vertices[draggingVertex] = pt;
      renderDrawing();
      return;
    }

    const pt = getSvgPoint(e);
    const guideLine = overlaySvg.querySelector('.draw-guide-line');
    if (guideLine) {
      const last = vertices[vertices.length - 1];
      guideLine.setAttribute('x1', last.x);
      guideLine.setAttribute('y1', last.y);
      guideLine.setAttribute('x2', pt.x);
      guideLine.setAttribute('y2', pt.y);
    }

    // Check proximity to first vertex for close hint
    if (vertices.length >= 3) {
      const first = vertices[0];
      const dist = Math.sqrt((pt.x - first.x) ** 2 + (pt.y - first.y) ** 2);
      const threshold = currentImgW * 0.015;
      const firstCircle = overlaySvg.querySelector('.first-vertex');
      if (firstCircle) {
        if (dist < threshold) {
          firstCircle.setAttribute('r', '10');
        } else {
          firstCircle.setAttribute('r', '6');
        }
      }
    }
  });

  // Render the current drawing state
  function renderDrawing() {
    overlaySvg.innerHTML = '';
    if (vertices.length === 0) {
      areaBadge.classList.remove('show');
      return;
    }

    // Draw polygon/polyline
    if (polygonClosed && vertices.length >= 3) {
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      poly.setAttribute('points', vertices.map(v => `${v.x},${v.y}`).join(' '));
      poly.setAttribute('class', 'draw-polygon-fill completed');
      overlaySvg.appendChild(poly);
    } else if (vertices.length >= 2) {
      const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      polyline.setAttribute('points', vertices.map(v => `${v.x},${v.y}`).join(' '));
      polyline.setAttribute('class', 'draw-polygon-line');
      overlaySvg.appendChild(polyline);
    }

    // Guide line (for active drawing)
    if (!polygonClosed && vertices.length > 0) {
      const guide = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      const last = vertices[vertices.length - 1];
      guide.setAttribute('x1', last.x);
      guide.setAttribute('y1', last.y);
      guide.setAttribute('x2', last.x);
      guide.setAttribute('y2', last.y);
      guide.setAttribute('class', 'draw-guide-line');
      overlaySvg.appendChild(guide);
    }

    // Vertex circles
    vertices.forEach((v, i) => {
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', v.x);
      circle.setAttribute('cy', v.y);
      circle.setAttribute('r', i === 0 && !polygonClosed && vertices.length >= 3 ? '8' : '6');
      circle.setAttribute('class', `draw-vertex${i === 0 && !polygonClosed && vertices.length >= 3 ? ' first-vertex' : ''}`);
      circle.dataset.vertexIndex = i;

      // Vertex dragging
      circle.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        draggingVertex = i;
      });

      // Click first vertex to close
      if (i === 0 && !polygonClosed && vertices.length >= 3) {
        circle.addEventListener('click', (e) => {
          e.stopPropagation();
          closePolygon();
        });
      }

      overlaySvg.appendChild(circle);
    });

    // Update area
    if (vertices.length >= 3) {
      const area = calculateArea();
      areaBadge.textContent = `${area.toFixed(1)} m²`;
      areaBadge.classList.add('show');
    } else {
      areaBadge.classList.remove('show');
    }
  }

  // Mouse up to stop dragging
  window.addEventListener('mouseup', () => {
    if (draggingVertex >= 0) {
      draggingVertex = -1;
      renderDrawing();
    }
  });

  // Close the polygon
  function closePolygon() {
    if (vertices.length < 3) return;
    polygonClosed = true;
    drawingMode = false;
    drawModeBtn.classList.remove('active');
    imageryFrame.classList.remove('draw-mode');
    renderDrawing();
    updateToolbarState();

    // Update scan status with area
    const area = calculateArea();
    scanStatus.textContent = `✓ Roof outlined — ${area.toFixed(1)} m² usable area (${vertices.length} vertices)`;
    scanStatus.className = 'scan-status ok';

    if (zoomHint) zoomHint.textContent = 'Scroll to zoom · Click & drag to pan';
  }

  // Calculate area using Shoelace formula (in m²)
  function calculateArea() {
    if (vertices.length < 3) return 0;
    let sum = 0;
    for (let i = 0; i < vertices.length; i++) {
      const j = (i + 1) % vertices.length;
      sum += vertices[i].x * vertices[j].y;
      sum -= vertices[j].x * vertices[i].y;
    }
    const pixelArea = Math.abs(sum) / 2;
    return pixelArea * (currentMpp * currentMpp);
  }

  function updateToolbarState() {
    undoVertexBtn.disabled = vertices.length === 0 || polygonClosed;
    clearDrawBtn.disabled = vertices.length === 0;
    completePolyBtn.disabled = vertices.length < 3 || polygonClosed;
  }

  // Undo last vertex
  undoVertexBtn.addEventListener('click', () => {
    if (vertices.length > 0 && !polygonClosed) {
      vertices.pop();
      renderDrawing();
      updateToolbarState();
    }
  });

  // Clear all
  function clearPolygon() {
    vertices = [];
    polygonClosed = false;
    overlaySvg.innerHTML = '';
    areaBadge.classList.remove('show');
    updateToolbarState();
  }
  clearDrawBtn.addEventListener('click', clearPolygon);

  // Complete polygon
  completePolyBtn.addEventListener('click', closePolygon);

  // Keyboard shortcuts while in draw mode
  document.addEventListener('keydown', (e) => {
    if (!imageryFrame.classList.contains('show')) return;
    if (e.target.tagName === 'INPUT') return;

    if (e.key === 'z' && (e.ctrlKey || e.metaKey) && !polygonClosed) {
      e.preventDefault();
      if (vertices.length > 0) {
        vertices.pop();
        renderDrawing();
        updateToolbarState();
      }
    } else if (e.key === 'Enter' && drawingMode && !polygonClosed && vertices.length >= 3) {
      e.preventDefault();
      closePolygon();
    }
  });


  /* ════════════ 6. AI ROOF DETECTION ════════════ */

  aiDetectBtn.addEventListener('click', async () => {
    if (!lastScanData || !lastScanData.image_url) {
      scanStatus.textContent = '✗ Run a scan first to get a satellite tile';
      scanStatus.className = 'scan-status error';
      return;
    }

    let maskPolygon = null;
    if (vertices.length >= 3) {
      maskPolygon = vertices.map(v => [v.x, v.y]);
    }

    // Clear existing drawing
    clearPolygon();

    aiDetectBtn.classList.add('loading');
    scanStatus.innerHTML = '<span class="spinner"></span>AI detecting roof outline…';
    scanStatus.className = 'scan-status';

    try {
      const payload = {
        image_b64: lastScanData.image_url,
        mpp: lastScanData.mpp,
      };
      if (maskPolygon) {
        payload.mask_polygon = maskPolygon;
      }

      const res = await fetch('/api/detect-roof', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Server error ${res.status}`);
      }

      const data = await res.json();

      if (!data.polygon || data.polygon.length < 3) {
        scanStatus.textContent = `✗ AI could not detect a clear roof outline (${data.contour_count || 0} contours found). Try ✏️ Draw to trace manually.`;
        scanStatus.className = 'scan-status error';
        return;
      }

      // Render AI-detected polygon
      renderAIPolygon(data.polygon, data.area_m2);

      scanStatus.textContent = `✓ AI detected roof — ${data.area_m2} m² (${data.vertex_count} vertices, ${data.contour_count} candidates)`;
      scanStatus.className = 'scan-status ok';

    } catch (err) {
      scanStatus.textContent = '✗ AI detection failed: ' + err.message;
      scanStatus.className = 'scan-status error';
    } finally {
      aiDetectBtn.classList.remove('loading');
    }
  });

  function renderAIPolygon(polygon, areaM2) {
    overlaySvg.innerHTML = '';

    // Draw polygon
    const pointsStr = polygon.map(p => `${p[0]},${p[1]}`).join(' ');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', pointsStr);
    poly.setAttribute('class', 'ai-polygon');
    overlaySvg.appendChild(poly);

    // Vertex dots (staggered animation)
    polygon.forEach((p, i) => {
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', p[0]);
      circle.setAttribute('cy', p[1]);
      circle.setAttribute('r', Math.max(4, currentImgW * 0.004));
      circle.setAttribute('class', 'ai-vertex');
      circle.style.animationDelay = `${0.5 + i * 0.08}s`;
      overlaySvg.appendChild(circle);
    });

    // Set vertices so user can edit
    vertices = polygon.map(p => ({ x: p[0], y: p[1] }));
    polygonClosed = true;
    updateToolbarState();

    // Area badge
    areaBadge.textContent = `${areaM2} m²`;
    areaBadge.classList.add('show');
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
