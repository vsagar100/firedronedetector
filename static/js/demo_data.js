(() => {
  const activePage = document.body.dataset.page;
  if (activePage !== "batch") return;

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'\"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '\"': "&quot;"
  }[char]));

  const isFire = (event) => String(event?.status || "").includes("FIRE DETECTED");

  function eventKey(referenceName, currentName) {
    return `${referenceName || ""}|${currentName || ""}`;
  }

  function queuedRow(pair) {
    return `<div class="batch-row">
      <div class="batch-evidence">
        <img src="${pair.before.url}" data-preview="${pair.before.url}" data-caption="Non-fire reference · ${escapeHtml(pair.before.name)}">
        <img src="${pair.after.url}" data-preview="${pair.after.url}" data-caption="Current thermal frame · ${escapeHtml(pair.after.name)}">
      </div>
      <div class="batch-meta">
        <strong>${escapeHtml(pair.label)}</strong>
        <small>${escapeHtml(pair.id)} · ${escapeHtml(pair.before.name)} → ${escapeHtml(pair.after.name)}</small>
        <span class="batch-location">GPS ${pair.latitude}, ${pair.longitude} · ${pair.altitude_m} m</span>
      </div>
      <span class="status-chip">Queued</span>
      <strong>--</strong><small>--</small><small>--</small>
    </div>`;
  }

  function analyzedRow(pair, event) {
    const evidence = event.result_url || event.current_url || pair.after.url;
    const fire = isFire(event);
    return `<div class="batch-row">
      <div class="batch-evidence">
        <img src="${event.reference_url || pair.before.url}" data-preview="${event.reference_url || pair.before.url}" data-caption="Non-fire reference · ${escapeHtml(event.reference_image || pair.before.name)}">
        <img src="${evidence}" data-preview="${evidence}" data-caption="Analysis evidence · ${escapeHtml(event.event_id)}">
      </div>
      <div class="batch-meta">
        <strong>${escapeHtml(pair.label)}</strong>
        <small>${escapeHtml(pair.id)} · Event ${escapeHtml(event.event_id)} · ${escapeHtml(event.reference_image)} → ${escapeHtml(event.current_image)}</small>
        <span class="batch-location">GPS ${escapeHtml(event.latitude)}, ${escapeHtml(event.longitude)} · ${escapeHtml(event.altitude_m)} m · ${escapeHtml(event.timestamp)}</span>
      </div>
      <span class="status-chip ${fire ? "fire" : ""}">${escapeHtml(event.status)}</span>
      <strong>${escapeHtml(event.confidence)}%</strong>
      <small>${escapeHtml(event.severity)} · ${escapeHtml(event.bbox_count)} region(s) · ${escapeHtml(event.hotspot_area_percent)}%</small>
      <small>${escapeHtml(event.processing_ms)} ms</small>
    </div>`;
  }

  async function hydrateBatchFromStoredEvents() {
    try {
      const [pairsResponse, eventsResponse] = await Promise.all([
        fetch("/api/pairs"),
        fetch("/api/events?limit=500")
      ]);
      if (!pairsResponse.ok || !eventsResponse.ok) return;

      const pairsData = await pairsResponse.json();
      const eventsData = await eventsResponse.json();
      const pairs = pairsData.pairs || [];
      const events = eventsData.events || [];
      const eventMap = new Map();

      // API returns newest records first; keep the newest result for each pair.
      events.forEach((event) => {
        const key = eventKey(event.reference_image, event.current_image);
        if (!eventMap.has(key)) eventMap.set(key, event);
      });

      const stored = [];
      const rows = pairs.map((pair) => {
        const event = eventMap.get(eventKey(pair.before.name, pair.after.name));
        if (!event) return queuedRow(pair);
        stored.push(event);
        return analyzedRow(pair, event);
      });

      const processed = stored.length;
      const fires = stored.filter(isFire).length;
      const averageConfidence = processed
        ? stored.reduce((total, event) => total + Number(event.confidence || 0), 0) / processed
        : 0;

      const pairCount = document.getElementById("batchPairs");
      const processedCount = document.getElementById("batchProcessed");
      const fireCount = document.getElementById("batchFires");
      const confidence = document.getElementById("batchConfidence");
      const results = document.getElementById("batchResults");
      const progress = document.getElementById("batchProgress");

      if (pairCount) pairCount.textContent = pairs.length;
      if (processedCount) processedCount.textContent = processed;
      if (fireCount) fireCount.textContent = fires;
      if (confidence) confidence.textContent = processed ? `${averageConfidence.toFixed(1)}%` : "--";
      if (results) results.innerHTML = rows.join("");
      if (progress) progress.style.width = pairs.length ? `${Math.round(processed / pairs.length * 100)}%` : "0%";
    } catch (error) {
      console.warn("Stored batch results could not be hydrated", error);
    }
  }

  // app.js initializes asynchronously; hydrate after its initial render has completed.
  window.setTimeout(hydrateBatchFromStoredEvents, 700);
})();
