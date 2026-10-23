/* ================================================================
   SyncSpace — timeline motion & overview (presentation only)

   app.js stays the single owner of the timeline: it renders the rows
   into #timeline. This file only WATCHES #timeline (MutationObserver)
   and decorates what app.js rendered:

     • data-state on every row (free / mine / booked / pending / past /
       blackout) so CSS can colour it,
     • data-hour-start to group rows by hour, data-now + --now-pct for
       the red "now" line,
     • a day overview strip above the rows (click a segment to jump),
     • animations: rows cascade in when you change resource or date;
       a row whose state changes during a live refresh flashes; your
       own new booking "stamps" in after the drawer closes,
     • clicking anywhere on a free row presses its Book button.

   It never changes ids, classes or texts that app.js or the tests use,
   and never adds .slot elements, so the app works the same without it.
   ================================================================ */
(function () {
  "use strict";

  const timeline = document.getElementById("timeline");
  if (!timeline) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const DEFAULT_SLOT_MS = 30 * 60 * 1000;
  const STATE_LABELS = {
    free: "free",
    mine: "yours",
    pending: "waiting for approval",
    booked: "booked",
    blackout: "unavailable",
  };
  const LEGEND_ORDER = ["free", "mine", "pending", "booked", "blackout"];

  let lastViewKey = null;
  let lastSignatures = new Map(); // data-start -> signature of the row
  let pendingStamps = [];         // rows to stamp once the drawer closes
  let scheduled = false;

  /* ── Overview strip, inserted once just above #timeline ── */
  const overview = document.createElement("div");
  overview.className = "tl-overview";
  overview.hidden = true;
  overview.innerHTML =
    '<div class="tl-bar" aria-hidden="true"></div>' +
    '<div class="tl-axis" aria-hidden="true"><span></span><span></span></div>' +
    '<ul class="tl-legend" aria-label="Day summary"></ul>';
  timeline.parentNode.insertBefore(overview, timeline);
  const bar = overview.querySelector(".tl-bar");
  const axisStart = overview.querySelector(".tl-axis span:first-child");
  const axisEnd = overview.querySelector(".tl-axis span:last-child");
  const legend = overview.querySelector(".tl-legend");

  function viewKey() {
    const resource = document.getElementById("resource-select");
    const date = document.getElementById("date-picker");
    return `${resource ? resource.value : ""}|${date ? date.value : ""}`;
  }

  function hhmm(date) {
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  // Reads the state from what app.js rendered (classes + texts).
  function classify(row) {
    const text = row.textContent || "";
    if (/Unavailable:/.test(text) || row.querySelector(".badge-past")?.textContent === "Blackout") {
      return "blackout";
    }
    if (row.classList.contains("admin-slot")) {
      if (row.classList.contains("slot-pending-approval")) return "pending";
      if (row.classList.contains("slot-confirmed-booked")) return "booked";
      if (row.classList.contains("slot-past")) return "past";
      return "free";
    }
    if (row.classList.contains("my-booked")) return "mine";
    if (row.classList.contains("past")) return "past";
    if (row.classList.contains("free")) return "free";
    const label = row.querySelector(".booked-label");
    if (label && /^You\b/.test(label.textContent)) return "mine";
    return "booked";
  }

  function signature(row) {
    return `${row.className}|${row.textContent}`;
  }

  function flash(row, cls) {
    row.classList.remove("tl-changed", "tl-stamp", "tl-focus");
    void row.offsetWidth; // restart the animation if it is already running
    row.classList.add(cls);
    row.addEventListener("animationend", () => row.classList.remove(cls), { once: true });
  }

  function drawerOpen() {
    const drawer = document.getElementById("booking-panel");
    return Boolean(drawer && !drawer.hidden);
  }

  function slotRows() {
    return Array.from(timeline.querySelectorAll(":scope > .slot[data-start]"));
  }

  /* ── The "now" line, in the overview and on the current row ── */
  function markNow(rows) {
    const now = Date.now();
    let first = null;
    let last = null;
    rows.forEach((row, i) => {
      const start = Date.parse(row.dataset.start);
      const next = rows[i + 1] ? Date.parse(rows[i + 1].dataset.start) : NaN;
      const end = next > start ? next : start + DEFAULT_SLOT_MS;
      if (first === null) first = start;
      last = end;
      if (now >= start && now < end) {
        row.dataset.now = "";
        row.style.setProperty("--now-pct", `${((now - start) / (end - start)) * 100}%`);
      } else if ("now" in row.dataset) {
        delete row.dataset.now;
        row.style.removeProperty("--now-pct");
      }
    });

    let line = bar.querySelector(".tl-now");
    if (first !== null && now >= first && now < last) {
      if (!line) {
        line = document.createElement("span");
        line.className = "tl-now";
        bar.appendChild(line);
      }
      line.style.left = `${((now - first) / (last - first)) * 100}%`;
    } else if (line) {
      line.remove();
    }
  }

  function renderOverview(rows, states, animate) {
    bar.textContent = "";
    const counts = {};
    rows.forEach((row, i) => {
      const state = states[i];
      counts[state] = (counts[state] || 0) + 1;
      const seg = document.createElement("span");
      seg.className = "tl-seg";
      seg.dataset.state = state;
      seg.style.setProperty("--i", String(i));
      const start = new Date(row.dataset.start);
      seg.title = `${hhmm(start)} ${STATE_LABELS[state] || state}`;
      seg.addEventListener("click", () => {
        row.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "center" });
        flash(row, "tl-focus");
      });
      bar.appendChild(seg);
    });

    const firstStart = new Date(rows[0].dataset.start);
    const lastStart = Date.parse(rows[rows.length - 1].dataset.start);
    const step = rows.length > 1 ? Date.parse(rows[1].dataset.start) - Date.parse(rows[0].dataset.start) : DEFAULT_SLOT_MS;
    axisStart.textContent = hhmm(firstStart);
    axisEnd.textContent = hhmm(new Date(lastStart + (step > 0 ? step : DEFAULT_SLOT_MS)));

    legend.textContent = "";
    LEGEND_ORDER.forEach((state) => {
      if (!counts[state]) return;
      const li = document.createElement("li");
      const swatch = document.createElement("i");
      swatch.dataset.state = state;
      swatch.setAttribute("aria-hidden", "true");
      const n = document.createElement("b");
      n.textContent = String(counts[state]);
      li.append(swatch, n, ` ${STATE_LABELS[state]}`);
      legend.appendChild(li);
    });

    overview.hidden = false;
    if (animate) {
      overview.classList.add("tl-enter");
      setTimeout(() => overview.classList.remove("tl-enter"), 1400);
    }
  }

  /* ── Main pass, after each app.js render ── */
  function decorate() {
    scheduled = false;
    const rows = slotRows();
    if (rows.length === 0) {
      // A message instead of rows ("Closed on this day.", an error) hides
      // the strip; an empty #timeline is just a load in progress, so the
      // strip stays put to avoid a flicker.
      if (timeline.textContent.trim()) overview.hidden = true;
      return;
    }

    const key = viewKey();
    const freshView = key !== lastViewKey;
    const animate = freshView && !reduceMotion.matches;
    const states = rows.map(classify);

    rows.forEach((row, i) => {
      row.dataset.state = states[i];
      const start = new Date(row.dataset.start);
      if (i > 0 && start.getMinutes() === 0) row.dataset.hourStart = "";
      if (start.getMinutes() !== 0) row.dataset.half = "";

      if (animate) {
        row.style.setProperty("--i", String(Math.min(i, 24)));
      } else if (!freshView) {
        const before = lastSignatures.get(row.dataset.start);
        if (before !== undefined && before !== signature(row)) {
          if (states[i] === "mine" && drawerOpen()) {
            pendingStamps.push(row.dataset.start); // wait until the sheet is gone
          } else {
            flash(row, states[i] === "mine" ? "tl-stamp" : "tl-changed");
          }
        }
      }
    });

    if (animate) {
      timeline.classList.add("tl-enter");
      setTimeout(() => timeline.classList.remove("tl-enter"), 1400);
    }

    lastViewKey = key;
    lastSignatures = new Map(rows.map((row) => [row.dataset.start, signature(row)]));
    renderOverview(rows, states, animate);
    markNow(rows);
  }

  // app.js may clear and refill #timeline several times in one load;
  // decorate once per frame, after it has settled.
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(decorate);
  }).observe(timeline, { childList: true });

  // Stamp your new booking once the drawer has slid away.
  const drawer = document.getElementById("booking-panel");
  if (drawer) {
    new MutationObserver(() => {
      if (drawer.hidden && pendingStamps.length) {
        const starts = pendingStamps;
        pendingStamps = [];
        setTimeout(() => {
          starts.forEach((start) => {
            const row = timeline.querySelector(`:scope > .slot[data-start="${CSS.escape(start)}"]`);
            if (row) flash(row, "tl-stamp");
          });
        }, 180);
      }
    }).observe(drawer, { attributes: true, attributeFilter: ["hidden"] });
  }

  // Click anywhere on a free row = press its Book button.
  timeline.addEventListener("click", (event) => {
    if (event.target.closest("button, input, select, a, label")) return;
    const row = event.target.closest(".slot.free");
    if (!row || row.parentNode !== timeline) return;
    const button = row.querySelector("button:not(:disabled)");
    if (button) button.click();
  });

  // Keep the "now" line moving.
  setInterval(() => {
    const rows = slotRows();
    if (rows.length) markNow(rows);
  }, 30 * 1000);
})();
