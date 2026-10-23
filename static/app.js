const SLOT_MINUTES = 30;
const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CHAT_MAX_MESSAGE_LENGTH = 1200;
const CHAT_MAX_HISTORY_MESSAGES = 6;
const CHAT_STARTERS = [
  "How do I make a reservation?",
  "How does the approval process work?",
  "What happens if two users book the same slot?",
  "How does the reservation system enforce quotas?",
];
const PENDING_USERS_POLL_MS = 45000;
const PAST_SLOTS_POLL_MS = 30000;
// The timeline, date picker and every displayed time use the browser's own
// timezone; the API still stores and returns UTC instants.
const USER_TIME_ZONE = (Intl.DateTimeFormat().resolvedOptions().timeZone) || "UTC";
// Same as ACTIVE_STATUSES in app/models/reservation.py: only these occupy a slot.
const ACTIVE_STATUSES = ["pending", "confirmed"];
let pastSlotsPollHandle = null;

let resourcesById = {};
let usersById = {};
let pendingSlot = null;
let chatHistory = [];
let chatIsWaiting = false;
let currentUser = null;
let currentTimelineReservations = [];
// Bumped on every loadTimeline() call; a call whose fetches finish after a
// newer call started must not render (it would append a second set of slots).
let timelineLoadSeq = 0;

async function requireAuth() {
  const res = await fetch("/auth/me", { credentials: "include" });
  if (!res.ok) {
    window.location.href = "/welcome.html";
    return null;
  }
  return res.json();
}

function currentUserIsAdmin() {
  return !!(currentUser && currentUser.role === "admin");
}

function wireLogout(buttonId) {
  document.getElementById(buttonId).addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
    window.location.href = "/login.html";
  });
}

function wireAccountBar(user) {
  const displayName = user.name || user.email || "";
  document.getElementById("account-name").textContent = displayName;
  document.getElementById("account-email").textContent = user.email || "";

  const avatar = document.getElementById("account-avatar");
  const dropdown = document.getElementById("account-dropdown");
  avatar.textContent = displayName.trim().charAt(0).toUpperCase() || "?";
  avatar.title = displayName;

  function setMenuOpen(open) {
    dropdown.hidden = !open;
    avatar.setAttribute("aria-expanded", String(open));
  }

  avatar.addEventListener("click", (event) => {
    event.stopPropagation();
    setMenuOpen(dropdown.hidden);
  });
  document.addEventListener("click", (event) => {
    if (!dropdown.hidden && !dropdown.contains(event.target)) setMenuOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dropdown.hidden) {
      setMenuOpen(false);
      avatar.focus();
    }
  });

  wireLogout("logout-btn");
}

// Members: "3/5 bookings" in the account dropdown, from GET /auth/me (quota).
function renderAccountQuotaSummary(user) {
  const el = document.getElementById("account-group-summary");
  if (!el) return;
  if (!user || user.role === "admin" || !user.quota) {
    el.hidden = true;
    return;
  }
  el.textContent = `${user.quota.used}/${user.quota.limit} bookings`;
  el.hidden = false;
}

async function refreshAccountQuotaSummary() {
  const { ok, data } = await apiRequest("/auth/me");
  if (!ok) return;
  currentUser = { ...currentUser, quota: data.quota };
  renderAccountQuotaSummary(currentUser);
}

// FastAPI `detail` can be a string, a list of validation errors (422), or an
// object like {message, conflicting_reservation_ids} (blackout 409).
function formatDetail(detail, status) {
  if (!detail) return `Request failed with status ${status}`;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  if (detail.message) {
    const ids = detail.conflicting_reservation_ids;
    return ids && ids.length ? `${detail.message} (reservations: ${ids.map((id) => `#${id}`).join(", ")})` : detail.message;
  }
  return JSON.stringify(detail);
}

function formatResourceHours(r) {
  const days = r.open_weekdays.length === 7 ? "every day" : r.open_weekdays.map((d) => WEEKDAY_NAMES[d - 1]).join(", ");
  return `${r.open_time.slice(0, 5)}–${r.close_time.slice(0, 5)} ${r.timezone} · ${days}`;
}

// Capacity model (same rule as is_exclusive() in app/models/resource.py):
// "whole" resources take one booking at a time and capacity = most people;
// "units" resources are a pool where each booking takes party_size units.
function isWholeResource(r) {
  return Boolean(r) && r.booking_mode === "whole";
}

function isExclusiveResource(r) {
  return Boolean(r) && (r.capacity === 1 || r.booking_mode === "whole");
}

function bookingModeLabel(r) {
  return r.booking_mode === "whole" ? "whole" : "units";
}

// "fits 8" for a whole room, "3 of 10 units free" for a pool.
function capacityLabel(r, remaining) {
  if (isWholeResource(r)) return `fits ${r.capacity}`;
  return `${remaining} of ${r.capacity} units free`;
}

async function apiRequest(url, options) {
  const res = await fetch(url, options);
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

function formatTime(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function formatLocalDate(date) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function showMessage(el, text, kind) {
  el.textContent = text;
  el.className = "message" + (kind ? " " + kind : "");
}

function todayISODate() {
  return formatLocalDate(new Date());
}

async function loadResources() {
  const { data } = await apiRequest("/resources");
  resourcesById = {};
  const select = document.getElementById("resource-select");
  const previous = select.value;
  select.innerHTML = "";
  (data || []).forEach((r) => {
    resourcesById[r.id] = r;
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = `${r.name} (${r.type}, cap ${r.capacity}, ${bookingModeLabel(r)})${r.location ? ` · ${r.location}` : ""}`;
    select.appendChild(opt);
  });
  if (previous && resourcesById[previous]) {
    select.value = previous;
  }
  updateEmptyHint();
  populateFindWhat();
}

async function loadUsers() {
  // Only used to look up other users' names for display (booker names in
  // the timeline, requester names in the reservation-approvals panel) —
  // there's no "acting as" concept any more, identity always comes from
  // the real logged-in session. Non-admins get only {id, name} per user.
  const { data } = await apiRequest("/users");
  usersById = {};
  (data || []).forEach((u) => {
    usersById[u.id] = u;
  });
}

function updateEmptyHint() {
  const hint = document.getElementById("empty-hint");
  hint.textContent = Object.keys(resourcesById).length === 0 ? "No resources yet." : "";
}

async function loadTimeline() {
  // Every booking / approval / cancel path refreshes the timeline; keep the
  // board in step when it is the visible view.
  if (boardView === "board") debounced("board", loadBoard, 150);
  const resourceId = document.getElementById("resource-select").value;
  const date = document.getElementById("date-picker").value;
  const timelineEl = document.getElementById("timeline");
  const hoursHint = document.getElementById("resource-hours-hint");
  timelineEl.innerHTML = "";
  hoursHint.textContent = "";

  if (!resourceId || !date) {
    timelineEl.textContent = "Pick a resource and a date to see the day timeline.";
    return;
  }

  // The date is interpreted in the RESOURCE's timezone; slots come back as
  // UTC instants and are shown in the viewer's local time below.
  const scheduleUrl = `/resources/${resourceId}/day-schedule?date=${date}&slot_minutes=${SLOT_MINUTES}`;
  const seq = ++timelineLoadSeq;
  const [scheduleResp, reservationsResp] = await Promise.all([
    apiRequest(scheduleUrl),
    apiRequest(`/reservations?resource_id=${resourceId}&limit=500`),
  ]);
  if (seq !== timelineLoadSeq) return; // a newer load superseded this one
  timelineEl.innerHTML = "";

  if (!scheduleResp.ok) {
    timelineEl.textContent = `Could not load the day schedule: ${formatDetail(scheduleResp.data && scheduleResp.data.detail, scheduleResp.status)}`;
    return;
  }

  const resource = resourcesById[resourceId];
  const capacity = (resource && resource.capacity) || 1;
  // A unit pool shows how many units are left; a whole resource shows how
  // many people it fits (it is either free or taken, never partly used).
  const pooled = Boolean(resource) && !isExclusiveResource(resource);
  const whole = isWholeResource(resource);
  if (resource) hoursHint.textContent = `Resource hours: ${formatResourceHours(resource)}`;

  if (!scheduleResp.data.open) {
    timelineEl.textContent = "Closed on this day.";
    return;
  }

  const activeReservations = ((reservationsResp.data && reservationsResp.data.items) || []).filter(
    (r) => ACTIVE_STATUSES.includes(r.status)
  );
  currentTimelineReservations = activeReservations;

  const slots = scheduleResp.data.slots.map((s) => ({
    startDate: new Date(s.start),
    endDate: new Date(s.end),
    startIso: s.start,
    endIso: s.end,
    state: s.state,
    remaining: s.remaining,
    capacity: s.capacity,
    blackoutReason: s.blackout_reason,
  }));
  const now = new Date();

  slots.forEach((slot) => {
    const div = document.createElement("div");
    div.dataset.start = slot.startIso;
    const label = `${formatTime(slot.startDate)} - ${formatTime(slot.endDate)}`;
    const isPast = slot.startDate <= now;
    // Same meaning the old /free-slots entry had: a slot with room left.
    const freeSlot = slot.state !== "blackout" && slot.remaining > 0 ? slot : null;

    /* ── Maintenance blackout: never bookable, show the reason ── */
    if (slot.state === "blackout") {
      const reasonText = `Unavailable: ${slot.blackoutReason || "maintenance"}`;
      if (currentUserIsAdmin()) {
        div.className = "slot admin-slot slot-past";
        const infoSpan = document.createElement("span");
        infoSpan.className = "slot-info";
        const timeSpan = document.createElement("span");
        timeSpan.className = "slot-time";
        timeSpan.textContent = label;
        infoSpan.appendChild(timeSpan);
        const detailSpan = document.createElement("span");
        detailSpan.className = "slot-detail";
        detailSpan.textContent = ` ${reasonText}`;
        infoSpan.appendChild(detailSpan);
        const badge = document.createElement("span");
        badge.className = "slot-badge badge-past";
        badge.textContent = "Blackout";
        div.appendChild(infoSpan);
        div.appendChild(badge);
      } else {
        div.className = "slot booked";
        const span = document.createElement("span");
        span.textContent = label;
        const reasonSpan = document.createElement("span");
        reasonSpan.className = "booked-label";
        reasonSpan.textContent = reasonText;
        div.appendChild(span);
        div.appendChild(reasonSpan);
      }
      timelineEl.appendChild(div);
      return;
    }

    /* ── Admin timeline view: explicitly shows Free, Waiting for approval, Booked, or Past ── */
    if (currentUserIsAdmin()) {
      div.className = "slot admin-slot";
      const slotReservations = activeReservations.filter(
        (r) => new Date(r.start_time) < slot.endDate && new Date(r.end_time) > slot.startDate
      );
      const pending = slotReservations.filter((r) => r.status === "pending");
      const confirmed = slotReservations.filter((r) => r.status === "confirmed");

      const infoSpan = document.createElement("span");
      infoSpan.className = "slot-info";

      const timeSpan = document.createElement("span");
      timeSpan.className = "slot-time";
      timeSpan.textContent = label;
      infoSpan.appendChild(timeSpan);

      if (isPast && slotReservations.length === 0) {
        // Slot has passed with no bookings: show as Past (NOT Free!)
        div.classList.add("slot-past");

        const badge = document.createElement("span");
        badge.className = "slot-badge badge-past";
        badge.textContent = "Past";

        div.appendChild(infoSpan);
        div.appendChild(badge);

      } else if (pending.length > 0) {
        // State: Waiting for approval
        div.classList.add("slot-pending-approval");
        if (isPast) div.classList.add("slot-past");

        if (pooled && freeSlot && freeSlot.remaining < capacity) {
          const detailSpan = document.createElement("span");
          detailSpan.className = "slot-detail slot-detail-pending";
          detailSpan.textContent = ` (${capacityLabel(resource, freeSlot.remaining)} · ${pending.length} pending${confirmed.length ? `, ${confirmed.length} booked` : ""})`;
          infoSpan.appendChild(detailSpan);
        } else if (pooled) {
          const detailSpan = document.createElement("span");
          detailSpan.className = "slot-detail slot-detail-pending";
          detailSpan.textContent = ` (${pending.length} pending)`;
          infoSpan.appendChild(detailSpan);
        } else if (whole) {
          const detailSpan = document.createElement("span");
          detailSpan.className = "slot-detail slot-detail-pending";
          detailSpan.textContent = ` (party of ${pending[0].party_size} · ${capacityLabel(resource)})`;
          infoSpan.appendChild(detailSpan);
        }

        const requesters = pending.map((r) => (usersById[r.user_id] && usersById[r.user_id].name) || `User #${r.user_id}`);
        const namesSpan = document.createElement("span");
        namesSpan.className = "slot-requesters";
        namesSpan.textContent = `Waiting: ${requesters.join(", ")}`;
        infoSpan.appendChild(namesSpan);

        div.appendChild(infoSpan);

        if (!isPast && pending.length === 1) {
          const resv = pending[0];
          const requesterName = (usersById[resv.user_id] && usersById[resv.user_id].name) || `User #${resv.user_id}`;
          const actionsDiv = document.createElement("div");
          actionsDiv.className = "slot-admin-actions";

          const approveBtn = document.createElement("button");
          approveBtn.className = "approve-btn";
          approveBtn.textContent = "Approve";
          approveBtn.title = `Approve request by ${requesterName}`;
          approveBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const { ok, status, data: respData } = await apiRequest(`/reservations/${resv.id}/approve`, { method: "POST" });
            if (ok) {
              await loadTimeline();
              await loadPendingApprovals();
            } else {
              alert((respData && respData.detail) || `Error (${status})`);
            }
          });

          const reasonInput = document.createElement("input");
          reasonInput.type = "text";
          reasonInput.placeholder = "Reason (optional)";
          reasonInput.maxLength = 500;
          reasonInput.setAttribute("aria-label", `Rejection reason for ${requesterName}`);
          reasonInput.addEventListener("click", (e) => e.stopPropagation());

          const rejectBtn = document.createElement("button");
          rejectBtn.className = "deny-btn";
          rejectBtn.textContent = "Reject";
          rejectBtn.title = `Reject request by ${requesterName}`;
          rejectBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!confirm(`Reject reservation request by ${requesterName}?`)) return;
            const reason = reasonInput.value.trim();
            const { ok, status, data: respData } = await apiRequest(`/reservations/${resv.id}/reject`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason || null }),
            });
            if (ok) {
              await loadTimeline();
              await loadPendingApprovals();
            } else {
              alert((respData && respData.detail) || `Error (${status})`);
            }
          });

          actionsDiv.appendChild(approveBtn);
          actionsDiv.appendChild(reasonInput);
          actionsDiv.appendChild(rejectBtn);
          div.appendChild(actionsDiv);
        } else {
          const actionBtn = document.createElement("button");
          actionBtn.className = "slot-badge-btn badge-pending";
          actionBtn.textContent = isPast
            ? `Pending (${pending.length}) · Past`
            : `Waiting for approval (${pending.length}) →`;
          actionBtn.title = "Click to review in Approvals tab";
          actionBtn.addEventListener("click", () => {
            if (window.switchTab) {
              window.switchTab("approvals");
              const panel = document.getElementById("pending-approvals-panel");
              if (panel && !panel.hidden) {
                panel.scrollIntoView({ behavior: "smooth", block: "start" });
              }
            }
          });
          div.appendChild(actionBtn);
        }

      } else if (confirmed.length > 0) {
        // State: Booked
        div.classList.add("slot-confirmed-booked");
        if (isPast) div.classList.add("slot-past");

        const detailSpan = document.createElement("span");
        detailSpan.className = "slot-detail slot-detail-booked";
        if (pooled) {
          const remaining = freeSlot ? freeSlot.remaining : 0;
          if (remaining < capacity) {
            detailSpan.textContent = ` (${confirmed.length} booked · ${capacityLabel(resource, remaining)})`;
          }
        } else if (whole) {
          detailSpan.textContent = ` (party of ${confirmed[0].party_size} · ${capacityLabel(resource)})`;
        }
        infoSpan.appendChild(detailSpan);

        const bookers = confirmed.map((r) => (usersById[r.user_id] && usersById[r.user_id].name) || `User #${r.user_id}`);
        const namesSpan = document.createElement("span");
        namesSpan.className = "slot-bookers";
        namesSpan.textContent = `Booked: ${bookers.join(", ")}`;
        infoSpan.appendChild(namesSpan);

        const badge = document.createElement("span");
        badge.className = isPast ? "slot-badge badge-past" : "slot-badge badge-booked";
        if (isPast) {
          badge.textContent = "Booked (Past)";
        } else {
          badge.textContent = pooled && (!freeSlot || freeSlot.remaining === 0) ? "Fully booked" : "Booked";
        }

        div.appendChild(infoSpan);

        const actionsDiv = document.createElement("div");
        actionsDiv.className = "slot-admin-actions";
        actionsDiv.appendChild(badge);

        if (!isPast) {
          confirmed.forEach((resv) => {
            const bookerName = (usersById[resv.user_id] && usersById[resv.user_id].name) || `User #${resv.user_id}`;
            const cancelBtn = document.createElement("button");
            cancelBtn.className = "slot-cancel-btn";
            cancelBtn.textContent = confirmed.length > 1 ? `Cancel ${bookerName}` : "Cancel booking";
            cancelBtn.title = `Cancel booked reservation for ${bookerName}`;
            cancelBtn.addEventListener("click", async (e) => {
              e.stopPropagation();
              if (!confirm(`Cancel booked reservation for ${bookerName}?`)) return;
              const { ok, status, data: respData } = await apiRequest(`/reservations/${resv.id}/cancel`, { method: "POST" });
              if (ok) {
                await loadTimeline();
                await loadPendingApprovals();
              } else {
                alert((respData && respData.detail) || `Error (${status})`);
              }
            });
            actionsDiv.appendChild(cancelBtn);
          });
        }

        div.appendChild(actionsDiv);

      } else {
        // State: Free (only future / current slots!)
        div.classList.add("slot-all-free");

        // Omit (8/8 open): clean time and Free badge
        const badge = document.createElement("span");
        badge.className = "slot-badge badge-free";
        badge.textContent = "Free";

        div.appendChild(infoSpan);
        div.appendChild(badge);
      }

      timelineEl.appendChild(div);
      return;
    }

    /* ── Member timeline view ── */
    const userReservation = currentUser
      ? activeReservations.find(
          (r) =>
            r.user_id === currentUser.id &&
            new Date(r.start_time) < slot.endDate &&
            new Date(r.end_time) > slot.startDate
        )
      : null;

    if (freeSlot) {
      div.className = "slot free";
      const span = document.createElement("span");
      span.textContent = label;
      // Whole resources: "(fits N)". Pools: "(N of C units free)", but NOT
      // when every unit is still free.
      if (whole || (pooled && freeSlot.remaining < freeSlot.capacity)) {
        const capacitySpan = document.createElement("span");
        capacitySpan.className = "capacity-label";
        capacitySpan.textContent = ` (${capacityLabel(resource, freeSlot.remaining)})`;
        span.appendChild(capacitySpan);
      }
      const btn = document.createElement("button");

      if (isPast) {
        div.classList.add("past");
        btn.textContent = "Past";
        btn.disabled = true;
      } else if (userReservation) {
        div.classList.add("my-booked");
        btn.textContent = userReservation.status === "pending" ? "Booked (pending)" : "Booked";
        btn.disabled = true;
        btn.title = `You have already booked this slot (${userReservation.status}).`;
      } else {
        btn.textContent = "Book";
        btn.addEventListener("click", () => openBookingPanel(slot));
      }

      div.appendChild(span);
      div.appendChild(btn);
    } else {
      div.className = "slot booked";
      const covering = activeReservations.find(
        (r) => new Date(r.start_time) < slot.endDate && new Date(r.end_time) > slot.startDate
      );
      const span = document.createElement("span");
      span.textContent = label;
      const bookedSpan = document.createElement("span");
      bookedSpan.className = "booked-label";
      if (covering) {
        const isMine = currentUser && covering.user_id === currentUser.id;
        const bookerName = isMine
          ? "You"
          : (usersById[covering.user_id] && usersById[covering.user_id].name) || `user #${covering.user_id}`;
        bookedSpan.textContent = `${bookerName} (${covering.status})`;
      } else {
        bookedSpan.textContent = "booked";
      }
      div.appendChild(span);
      div.appendChild(bookedSpan);
    }
    timelineEl.appendChild(div);
  });
}

function updatePastSlots() {
  const now = new Date();
  if (currentUserIsAdmin()) {
    const adminFreeSlots = document.querySelectorAll("#timeline .slot.admin-slot.slot-all-free:not(.slot-past)");
    adminFreeSlots.forEach((slotEl) => {
      const startIso = slotEl.dataset.start;
      if (!startIso) return;
      if (new Date(startIso) <= now) {
        slotEl.classList.remove("slot-all-free");
        slotEl.classList.add("slot-past");
        const badge = slotEl.querySelector(".slot-badge");
        if (badge) {
          badge.className = "slot-badge badge-past";
          badge.textContent = "Past";
        }
      }
    });
    return;
  }
  const freeSlots = document.querySelectorAll("#timeline .slot.free");
  freeSlots.forEach((slotEl) => {
    const startIso = slotEl.dataset.start;
    if (!startIso) return;
    const isPast = new Date(startIso) <= now;
    if (isPast) {
      if (!slotEl.classList.contains("past")) {
        slotEl.classList.add("past");
      }
      const btn = slotEl.querySelector("button");
      if (btn && (!btn.disabled || btn.textContent !== "Past")) {
        btn.disabled = true;
        btn.textContent = "Past";
      }
    }
  });

  if (pendingSlot && pendingSlot.startDate <= now) {
    const confirmBtn = document.getElementById("confirm-booking-btn");
    if (confirmBtn) confirmBtn.disabled = true;
    const messageEl = document.getElementById("booking-message");
    if (messageEl) {
      showMessage(messageEl, "This time slot has already passed.", "error");
    }
  }
}

function openBookingPanel(slot) {
  if (slot.startDate <= new Date()) return;
  if (currentUserIsAdmin()) return; // Admins cannot book resources

  const hasExisting = currentTimelineReservations.some(
    (r) =>
      currentUser &&
      r.user_id === currentUser.id &&
      new Date(r.start_time) < slot.endDate &&
      new Date(r.end_time) > slot.startDate
  );
  if (hasExisting) return;

  openBookingDrawer({ resourceId: document.getElementById("resource-select").value, start: slot.startDate });
}

// Opens the booking drawer for `resourceId`, prefilled with `start` (a Date)
// and optionally a duration. The start time and duration stay editable.
function openBookingDrawer({ resourceId, start, durationMinutes, partySize }) {
  if (currentUserIsAdmin()) return; // Admins cannot book resources
  const resource = resourcesById[resourceId];
  if (!resource) return;

  // People (whole) or units (pool) this booking takes: 1..capacity.
  const partyInput = document.getElementById("booking-party-size");
  document.getElementById("booking-party-size-label").textContent = isWholeResource(resource) ? "People" : "Units";
  partyInput.min = "1";
  partyInput.max = String(resource.capacity);
  partyInput.value = String(Math.min(Math.max(Number(partySize) || 1, 1), resource.capacity));

  pendingSlot = { resourceId: String(resourceId), localDate: formatLocalDate(start), startDate: start };

  const timeInput = document.getElementById("booking-start-time");
  timeInput.value = formatTime(start);

  // Durations from the resource's min to max in 30-minute steps.
  const options = [];
  for (let m = resource.min_duration_minutes; m <= resource.max_duration_minutes; m += 30) options.push(m);
  if (durationMinutes && !options.includes(durationMinutes)) {
    options.push(durationMinutes);
    options.sort((a, b) => a - b);
  }
  const wanted = durationMinutes || Math.max(60, resource.min_duration_minutes);
  const chosen = options.reduce((best, m) => (Math.abs(m - wanted) < Math.abs(best - wanted) ? m : best), options[0]);
  const select = document.getElementById("booking-duration");
  select.innerHTML = "";
  options.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m % 60 === 0 ? `${m / 60} h` : m > 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
    select.appendChild(opt);
  });
  select.value = chosen;

  resetRepeatControls(dateTimeInZone(start, resource.timezone).isoWeekday);
  document.getElementById("booking-slot-label").textContent = `${resource.name} · ${pendingSlot.localDate}`;
  const messageEl = document.getElementById("booking-message");
  showMessage(messageEl, "", "");
  renderBookingAlternatives([]);
  const confirmBtn = document.getElementById("confirm-booking-btn");
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Confirm booking";
  }
  document.getElementById("booking-panel").hidden = false;
}

// The exact range the drawer will book, from its start-time + duration inputs.
function drawerRange() {
  const timeValue = document.getElementById("booking-start-time").value;
  const minutes = Number(document.getElementById("booking-duration").value);
  const start = new Date(`${pendingSlot.localDate}T${timeValue}:00`);
  return { start, end: new Date(start.getTime() + minutes * 60000) };
}

function drawerPartySize() {
  return Number(document.getElementById("booking-party-size").value) || 1;
}

function closeBookingPanel() {
  pendingSlot = null;
  renderBookingAlternatives([]);
  document.getElementById("booking-panel").hidden = true;
}

function dateInTimeZone(date, timeZone) {
  // en-CA formats as YYYY-MM-DD
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

// Used by conflict alternatives and "Find a slot" results: switch the
// timeline to that resource/date if needed, then open the prefilled drawer.
async function openDrawerForSuggestion(s, partySize) {
  const resource = resourcesById[s.resource_id];
  if (!resource) return;
  const start = new Date(s.start);
  const select = document.getElementById("resource-select");
  const picker = document.getElementById("date-picker");
  const resourceDate = dateInTimeZone(start, resource.timezone);
  if (select.value !== String(s.resource_id) || picker.value !== resourceDate) {
    select.value = s.resource_id;
    picker.value = resourceDate;
    await loadTimeline();
  }
  openBookingDrawer({ resourceId: s.resource_id, start, durationMinutes: (new Date(s.end) - start) / 60000, partySize });
}

function suggestionLabel(s) {
  const resource = resourcesById[s.resource_id];
  const name = (resource && resource.name) || s.resource_name;
  const room = resource
    ? capacityLabel(resource, s.remaining_capacity)
    : `${s.remaining_capacity} seat${s.remaining_capacity === 1 ? "" : "s"} left`;
  return `${name} · ${formatTime(new Date(s.start))}–${formatTime(new Date(s.end))} · ${room}`;
}

function renderBookingAlternatives(alternatives) {
  document.getElementById("join-waitlist-btn").hidden = true;
  const listEl = document.getElementById("booking-alternatives");
  const title = document.getElementById("booking-alternatives-title");
  listEl.innerHTML = "";
  title.hidden = alternatives.length === 0;
  // Alternatives were found for the party size the drawer just tried.
  const partySize = alternatives.length ? drawerPartySize() : 1;
  alternatives.forEach((s) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary";
    btn.textContent = suggestionLabel(s);
    btn.addEventListener("click", () => openDrawerForSuggestion(s, partySize));
    li.appendChild(btn);
    listEl.appendChild(li);
  });
}

async function confirmBooking() {
  if (!pendingSlot) return;
  const messageEl = document.getElementById("booking-message");
  const confirmBtn = document.getElementById("confirm-booking-btn");
  const { start, end } = drawerRange();
  if (Number.isNaN(start.getTime())) {
    showMessage(messageEl, "Pick a start time.", "error");
    return;
  }
  pendingSlot.startDate = start;

  if (start <= new Date()) {
    showMessage(messageEl, "This start time has already passed.", "error");
    return;
  }

  // Only the timeline's resource has its reservations loaded client-side;
  // for any other resource the server's duplicate check still applies.
  const onTimelineResource = pendingSlot.resourceId === document.getElementById("resource-select").value;
  const hasExisting =
    onTimelineResource &&
    currentTimelineReservations.some(
      (r) => currentUser && r.user_id === currentUser.id && new Date(r.start_time) < end && new Date(r.end_time) > start
    );
  if (hasExisting) {
    showMessage(messageEl, "You already have an active reservation that overlaps this time.", "error");
    return;
  }

  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Booking...";
  }
  renderBookingAlternatives([]);

  if (document.getElementById("repeat-frequency").value) {
    await confirmSeriesBooking(messageEl, confirmBtn);
    return;
  }

  const { ok, status, data } = await apiRequest("/reservations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resource_id: Number(pendingSlot.resourceId),
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      party_size: drawerPartySize(),
    }),
  });

  if (ok) {
    showMessage(messageEl, `Booked! Status: ${data.status}.`, "success");
    pendingSlot = null;
    await Promise.all([loadTimeline(), loadMyReservations(), loadPendingApprovals()]);
    setTimeout(() => {
      closeBookingPanel();
      if (confirmBtn) {
        confirmBtn.textContent = "Confirm booking";
      }
    }, 800);
  } else {
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Confirm booking";
    }
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    if (status === 409 && data && Array.isArray(data.alternatives)) {
      renderBookingAlternatives(data.alternatives);
      // Taken (overlap / full), not a blackout: offer the waitlist.
      const detail = typeof data.detail === "string" ? data.detail : "";
      if (/overlaps|at capacity/.test(detail)) {
        const joinBtn = document.getElementById("join-waitlist-btn");
        joinBtn.hidden = false;
        joinBtn.dataset.resourceId = pendingSlot.resourceId;
        joinBtn.dataset.start = start.toISOString();
        joinBtn.dataset.end = end.toISOString();
        joinBtn.dataset.partySize = String(drawerPartySize());
      }
    }
  }
}

// --- Recurring bookings (drawer "Repeat") ---------------------------------

// Wall-clock date/time of `date` in `timeZone` (series rules are expressed in
// the RESOURCE's local time, while the drawer shows the viewer's local time).
function dateTimeInZone(date, timeZone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short",
    }).formatToParts(date).map((p) => [p.type, p.value])
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
    isoWeekday: WEEKDAY_NAMES.indexOf(parts.weekday) + 1,
  };
}

function setShown(el, shown, display = "") {
  el.style.display = shown ? display : "none";
}

function updateRepeatVisibility() {
  const frequency = document.getElementById("repeat-frequency").value;
  setShown(document.getElementById("repeat-options"), Boolean(frequency), "block");
  setShown(document.getElementById("repeat-weekdays"), frequency === "weekly", "flex");
  document.getElementById("repeat-interval-label").textContent = frequency === "daily" ? "Every N days" : "Every N weeks";
  const byDate = document.getElementById("repeat-end-kind").value === "until";
  setShown(document.getElementById("repeat-count-label"), !byDate, "flex");
  setShown(document.getElementById("repeat-until-label"), byDate, "flex");
}

function resetRepeatControls(startIsoWeekday) {
  document.getElementById("repeat-frequency").value = "";
  document.getElementById("repeat-interval").value = "1";
  document.getElementById("repeat-end-kind").value = "count";
  document.getElementById("repeat-count").value = "4";
  document.getElementById("repeat-until").value = "";
  document.getElementById("repeat-mode").value = "all_or_nothing";
  document.querySelectorAll("[data-repeat-weekday]").forEach((cb) => {
    cb.checked = Number(cb.dataset.repeatWeekday) === startIsoWeekday;
  });
  document.getElementById("repeat-preview-list").innerHTML = "";
  updateRepeatVisibility();
}

function buildSeriesRule() {
  const resource = resourcesById[pendingSlot.resourceId];
  const { start, end } = drawerRange();
  const local = dateTimeInZone(start, resource.timezone);
  const frequency = document.getElementById("repeat-frequency").value;
  const rule = {
    resource_id: Number(pendingSlot.resourceId),
    frequency,
    interval: Number(document.getElementById("repeat-interval").value),
    local_start_time: local.time,
    duration_minutes: Math.round((end - start) / 60000),
    start_date: local.date,
    party_size: drawerPartySize(),
  };
  if (frequency === "weekly") {
    rule.weekdays = Array.from(document.querySelectorAll("[data-repeat-weekday]"))
      .filter((cb) => cb.checked)
      .map((cb) => Number(cb.dataset.repeatWeekday));
  }
  if (document.getElementById("repeat-end-kind").value === "until") {
    rule.until_date = document.getElementById("repeat-until").value;
  } else {
    rule.occurrence_count = Number(document.getElementById("repeat-count").value);
  }
  return rule;
}

function renderOccurrenceList(items) {
  // items: [{start, status, reason}]
  const listEl = document.getElementById("repeat-preview-list");
  listEl.innerHTML = "";
  items.forEach((o) => {
    const li = document.createElement("li");
    const d = new Date(o.start);
    const info = document.createElement("span");
    info.textContent = `${formatLocalDate(d)} ${formatTime(d)} `;
    const tag = document.createElement("span");
    tag.className = "status-tag";
    tag.textContent = `[${o.status}]`;
    info.appendChild(tag);
    if (o.reason) {
      const reason = document.createElement("span");
      reason.className = "hint";
      reason.style.display = "block";
      reason.textContent = o.reason;
      info.appendChild(reason);
    }
    li.appendChild(info);
    listEl.appendChild(li);
  });
}

async function previewSeries() {
  const messageEl = document.getElementById("booking-message");
  if (!pendingSlot) return;
  const { ok, status, data } = await apiRequest("/reservations/series/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildSeriesRule()),
  });
  if (!ok) {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    return;
  }
  renderBookingAlternatives([]); // a successful preview clears stale 409 suggestions
  const okCount = data.filter((o) => o.status === "ok").length;
  showMessage(messageEl, `${okCount} of ${data.length} occurrences can be booked right now.`, "");
  renderOccurrenceList(data);
}

async function confirmSeriesBooking(messageEl, confirmBtn) {
  const body = { ...buildSeriesRule(), mode: document.getElementById("repeat-mode").value };
  const { ok, status, data } = await apiRequest("/reservations/series", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Confirm booking";
  }
  if (ok) {
    showMessage(
      messageEl,
      `Series booked: ${data.created.length} occurrence(s) created${data.skipped.length ? `, ${data.skipped.length} skipped` : ""}.`,
      "success"
    );
    renderOccurrenceList([
      ...data.created.map((r) => ({ start: r.start_time, status: r.status, reason: null })),
      ...data.skipped.map((sk) => ({ start: sk.start, status: "skipped", reason: sk.reason })),
    ].sort((a, b) => new Date(a.start) - new Date(b.start)));
    await Promise.all([loadTimeline(), loadMyReservations(), loadPendingApprovals()]);
  } else {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    if (data && Array.isArray(data.failures)) {
      renderOccurrenceList(data.failures.map((f) => ({ start: f.start, status: "conflict", reason: f.reason })));
    }
  }
}

function describeSeries(series, occurrences) {
  const resource = resourcesById[series.resource_id];
  const freq = series.frequency === "weekly" ? "Weekly" : "Daily";
  const every = series.interval > 1 ? ` (every ${series.interval} ${series.frequency === "weekly" ? "weeks" : "days"})` : "";
  const days = series.weekdays ? ` · ${series.weekdays.map((d) => WEEKDAY_NAMES[d - 1]).join(", ")}` : "";
  const active = occurrences.filter((o) => ACTIVE_STATUSES.includes(o.status)).length;
  const name = (resource && resource.name) || `resource #${series.resource_id}`;
  return `${name} · ${freq}${every}${days} · ${series.local_start_time.slice(0, 5)} · ${active} of ${occurrences.length} active`;
}

// --- Find a slot (member) -------------------------------------------------

// "Several resources together": every resource, as a multi-select.
function populateFindResources() {
  const select = document.getElementById("find-resources");
  if (!select) return;
  const previous = new Set(Array.from(select.selectedOptions).map((o) => o.value));
  select.innerHTML = "";
  Object.values(resourcesById).forEach((r) => {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = `${r.name} (cap ${r.capacity}, ${bookingModeLabel(r)})`;
    opt.selected = previous.has(String(r.id));
    select.appendChild(opt);
  });
}

// Approved members by name (not yourself), for the participants picker.
async function loadFindParticipants() {
  const select = document.getElementById("find-participants");
  const { ok, data } = await apiRequest("/users/directory");
  if (!ok) return;
  select.innerHTML = "";
  data.filter((u) => !currentUser || u.id !== currentUser.id).forEach((u) => {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = u.name;
    select.appendChild(opt);
  });
}

function updateFindMode() {
  const multi = document.getElementById("find-mode-multi").checked;
  document.getElementById("find-single-fields").hidden = multi;
  document.getElementById("find-multi-fields").hidden = !multi;
  document.getElementById("find-slot-results").innerHTML = "";
  showMessage(document.getElementById("find-slot-message"), "", "");
}

function populateFindWhat() {
  populateFindResources();
  const select = document.getElementById("find-what");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = "";
  const resources = Object.values(resourcesById);
  const types = [...new Set(resources.map((r) => r.type))].sort();
  const typeGroup = document.createElement("optgroup");
  typeGroup.label = "Any resource of type";
  types.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = `type:${t}`;
    opt.textContent = t;
    typeGroup.appendChild(opt);
  });
  const resourceGroup = document.createElement("optgroup");
  resourceGroup.label = "A specific resource";
  resources.forEach((r) => {
    const opt = document.createElement("option");
    opt.value = `id:${r.id}`;
    opt.textContent = `${r.name} (cap ${r.capacity}, ${bookingModeLabel(r)})${r.location ? ` · ${r.location}` : ""}`;
    resourceGroup.appendChild(opt);
  });
  select.appendChild(typeGroup);
  select.appendChild(resourceGroup);
  if (previous && select.querySelector(`option[value="${CSS.escape(previous)}"]`)) select.value = previous;
}

function reasonFromBreakdown(b, hasPreferred) {
  const parts = [];
  if (hasPreferred) parts.push(b.time_distance_min === 0 ? "at your preferred time" : `${b.time_distance_min} min from your preferred time`);
  if (b.day_offset > 0) parts.push(`${b.day_offset} day${b.day_offset === 1 ? "" : "s"} after your first date`);
  parts.push(b.capacity_waste === 0 ? "right-sized" : `${Math.round(b.capacity_waste * 100)}% of seats unused`);
  if (b.fragmentation.includes("flush")) parts.push("fits snugly next to other bookings");
  if (b.fragmentation.includes("unusable")) parts.push("leaves a short unusable gap");
  return parts.join(" · ");
}

async function handleFindSlot(event) {
  event.preventDefault();
  if (document.getElementById("find-mode-multi").checked) {
    await handleFindCommonSlots();
    return;
  }
  const messageEl = document.getElementById("find-slot-message");
  const listEl = document.getElementById("find-slot-results");
  listEl.innerHTML = "";
  const what = document.getElementById("find-what").value;
  const preferred = document.getElementById("find-time").value;
  const body = {
    attendees: Number(document.getElementById("find-attendees").value),
    duration_minutes: Number(document.getElementById("find-duration").value),
    date_from: document.getElementById("find-from").value,
    date_to: document.getElementById("find-to").value,
    preferred_time: preferred || null,
    limit: 10,
  };
  if (what.startsWith("type:")) body.resource_type = what.slice(5);
  else body.resource_id = Number(what.slice(3));

  showMessage(messageEl, "Searching…", "");
  const { ok, status, data } = await apiRequest("/schedule/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!ok) {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    return;
  }
  const summary = `Searched ${data.searched_resources} resource(s), ${data.considered_candidates} possible start times.`;
  showMessage(messageEl, data.warning ? `${summary} Note: ${data.warning}.` : summary, data.warning ? "error" : "");

  if (data.suggestions.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No free slots match. Try a longer date range, a shorter duration, or fewer attendees.";
    listEl.appendChild(li);
    return;
  }
  data.suggestions.forEach((s) => {
    const li = document.createElement("li");
    const info = document.createElement("span");
    const start = new Date(s.start);
    info.textContent = `${formatLocalDate(start)} ${suggestionLabel(s)}${s.location ? ` · ${s.location}` : ""}`;
    const reason = document.createElement("span");
    reason.className = "hint";
    reason.style.display = "block";
    reason.textContent = reasonFromBreakdown(s.breakdown, Boolean(preferred));
    info.appendChild(reason);
    li.appendChild(info);
    const btn = document.createElement("button");
    btn.textContent = "Book";
    // The Attendees value becomes the booking's party size.
    btn.addEventListener("click", () => openDrawerForSuggestion(s, body.attendees));
    li.appendChild(btn);
    listEl.appendChild(li);
  });
}

// --- Find a slot: several resources together (common slots + bundles) ----

function commonSlotLabel(slot) {
  const start = new Date(slot.start);
  const parts = slot.resources.map((x) => {
    const r = resourcesById[x.resource_id];
    return r ? `${r.name} (${capacityLabel(r, x.remaining_capacity)})` : x.resource_name;
  });
  return `${formatLocalDate(start)} ${formatTime(start)}–${formatTime(new Date(slot.end))} · ${parts.join(" + ")}`;
}

async function handleFindCommonSlots() {
  const messageEl = document.getElementById("find-slot-message");
  const listEl = document.getElementById("find-slot-results");
  listEl.innerHTML = "";
  const resourceIds = Array.from(document.getElementById("find-resources").selectedOptions).map((o) => Number(o.value));
  if (resourceIds.length < 2 || resourceIds.length > 5) {
    showMessage(messageEl, "Pick between 2 and 5 resources to book together.", "error");
    return;
  }
  const partySize = Number(document.getElementById("find-party-size").value) || 1;
  const preferred = document.getElementById("find-time").value;
  const body = {
    resource_ids: resourceIds,
    party_size: partySize,
    participant_user_ids: Array.from(document.getElementById("find-participants").selectedOptions).map((o) => Number(o.value)),
    duration_minutes: Number(document.getElementById("find-duration").value),
    date_from: document.getElementById("find-from").value,
    date_to: document.getElementById("find-to").value,
    preferred_time: preferred || null,
    limit: 10,
  };
  showMessage(messageEl, "Searching…", "");
  const { ok, status, data } = await apiRequest("/schedule/common-slots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!ok) {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    return;
  }
  showMessage(messageEl, `Checked ${data.considered_candidates} possible start times across ${data.searched_resources} resources.`, "");
  if (data.slots.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No time works for all of them. Try a longer date range, a shorter duration, or fewer resources/participants.";
    listEl.appendChild(li);
    return;
  }
  data.slots.forEach((slot) => listEl.appendChild(renderCommonSlot(slot, partySize, messageEl)));
}

// One result with "Book all" -> an in-place confirm step (like the drawer).
function renderCommonSlot(slot, partySize, messageEl) {
  const li = document.createElement("li");
  const info = document.createElement("span");
  info.textContent = commonSlotLabel(slot);
  li.appendChild(info);
  const actions = document.createElement("span");
  actions.className = "pending-user-actions";
  const bookBtn = document.createElement("button");
  bookBtn.textContent = "Book all";
  const yesBtn = document.createElement("button");
  yesBtn.textContent = `Yes, book ${slot.resources.length} together`;
  yesBtn.hidden = true;
  const noBtn = document.createElement("button");
  noBtn.className = "secondary";
  noBtn.textContent = "Cancel";
  noBtn.hidden = true;
  const toggle = (confirming) => {
    bookBtn.hidden = confirming;
    yesBtn.hidden = !confirming;
    noBtn.hidden = !confirming;
  };
  bookBtn.addEventListener("click", () => toggle(true));
  noBtn.addEventListener("click", () => toggle(false));
  yesBtn.addEventListener("click", async () => {
    yesBtn.disabled = true;
    const { ok, status, data } = await apiRequest("/reservations/bundle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: slot.resources.map((x) => ({ resource_id: x.resource_id, party_size: partySize })),
        start_time: slot.start,
        end_time: slot.end,
      }),
    });
    yesBtn.disabled = false;
    if (ok) {
      showMessage(messageEl, `Booked bundle #${data.bundle.id}: ${data.items.map((r) => r.status).join(", ")}.`, "success");
      li.remove();
      await Promise.all([loadMyReservations(), loadTimeline(), loadPendingApprovals()]);
    } else {
      toggle(false);
      showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    }
  });
  actions.appendChild(bookBtn);
  actions.appendChild(yesBtn);
  actions.appendChild(noBtn);
  li.appendChild(actions);
  return li;
}

// --- Resource board (rows = resources, x = time) ---------------------------

const BOARD_SLOT_MINUTES = 30;
const BOARD_LOAD_STRIP_PX = 16; // height of the load strip on unit-pool rows
const BOARD_LANE_PX = 22; // height of one booking sub-lane on unit-pool rows
let boardView = "timeline"; // "timeline" | "board"
let boardMode = "day"; // "day" | "week"
let boardData = null;
let boardScrolledFor = null; // day the board last auto-scrolled to (long days only)

function boardSlotPx() {
  const v = getComputedStyle(document.getElementById("board-panel")).getPropertyValue("--board-slot");
  return parseFloat(v) || 40;
}

function setView(view) {
  boardView = view;
  const board = view === "board";
  document.getElementById("timeline-panel").hidden = board;
  document.getElementById("board-panel").hidden = !board;
  [["view-day-btn", !board], ["view-board-btn", board]].forEach(([id, on]) => {
    const btn = document.getElementById(id);
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
  if (board) loadBoard();
  else loadTimeline();
}

function setBoardMode(mode) {
  boardMode = mode;
  [["board-mode-day", mode === "day"], ["board-mode-week", mode === "week"]].forEach(([id, on]) => {
    const btn = document.getElementById(id);
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
  loadBoard();
}

function shiftBoardDate(direction) {
  const picker = document.getElementById("date-picker");
  const d = new Date(`${picker.value || todayISODate()}T00:00:00`);
  d.setDate(d.getDate() + direction * (boardMode === "week" ? 7 : 1));
  picker.value = formatLocalDate(d);
  loadBoard();
}

async function loadBoard() {
  if (boardView !== "board") return;
  const date = document.getElementById("date-picker").value || todayISODate();
  const typeSelect = document.getElementById("board-type");
  const params = new URLSearchParams({ date, days: boardMode === "week" ? "7" : "1", tz: USER_TIME_ZONE });
  if (typeSelect.value) params.set("type", typeSelect.value);
  const { ok, status, data } = await apiRequest(`/schedule/board?${params}`);
  const el = document.getElementById("board");
  hideBoardPopover();
  if (!ok) {
    el.textContent = `Could not load the board: ${formatDetail(data && data.detail, status)}`;
    return;
  }
  boardData = data;
  // Type filter: every type seen so far (keep the current choice).
  const known = new Set(Array.from(typeSelect.options).map((o) => o.value));
  data.resources.forEach((r) => {
    if (!known.has(r.type)) {
      known.add(r.type);
      const opt = document.createElement("option");
      opt.value = r.type;
      opt.textContent = r.type;
      typeSelect.appendChild(opt);
    }
  });
  const first = new Date(`${date}T00:00:00`);
  const last = new Date(first.getTime() + (boardMode === "week" ? 6 : 0) * 86400000);
  document.getElementById("board-range-label").textContent =
    boardMode === "week" ? `${formatLocalDate(first)} – ${formatLocalDate(last)}` : formatLocalDate(first);
  if (boardMode === "week") renderBoardWeek(data, first);
  else renderBoardDay(data, first);
}

function overlapMs(aStart, aEnd, bStart, bEnd) {
  return Math.max(0, Math.min(aEnd, bEnd) - Math.max(aStart, bStart));
}

function renderBoardDay(data, midnight) {
  const el = document.getElementById("board");
  el.innerHTML = "";
  if (!data.resources.length) {
    el.textContent = "No resources to show.";
    return;
  }
  const nextMidnight = new Date(midnight.getTime() + 86400000);
  // Grid: earliest opening to latest closing (viewer's local time), 30-min steps.
  const opens = data.resources.flatMap((r) => r.open_windows.map((w) => [new Date(w.start), new Date(w.end)]))
    .filter(([s, e]) => s < nextMidnight && e > midnight);
  let gridStart = new Date(midnight.getTime() + 8 * 3600000);
  let gridEnd = new Date(midnight.getTime() + 20 * 3600000);
  if (opens.length) {
    gridStart = new Date(Math.max(midnight, Math.min(...opens.map(([s]) => s))));
    gridEnd = new Date(Math.min(nextMidnight, Math.max(...opens.map(([, e]) => e))));
  }
  const step = BOARD_SLOT_MINUTES * 60000;
  gridStart = new Date(Math.floor((gridStart - midnight) / step) * step + midnight.getTime());
  gridEnd = new Date(Math.ceil((gridEnd - midnight) / step) * step + midnight.getTime());
  const slotPx = boardSlotPx();
  const width = ((gridEnd - gridStart) / step) * slotPx;
  const x = (t) => ((t - gridStart) / step) * slotPx;
  const place = (node, s, e) => {
    const a = Math.max(new Date(s), gridStart);
    const b = Math.min(new Date(e), gridEnd);
    if (b <= a) return false;
    node.style.left = `${x(a)}px`;
    node.style.width = `${x(b) - x(a)}px`;
    return true;
  };
  const now = new Date();
  const grid = document.createElement("div");
  grid.className = "board-grid";

  // Header: hour labels.
  const header = document.createElement("div");
  header.className = "board-row board-header";
  const corner = document.createElement("div");
  corner.className = "board-name";
  corner.textContent = `Resource · times in ${USER_TIME_ZONE.replace(/_/g, " ")}`;
  const hours = document.createElement("div");
  hours.className = "board-track";
  hours.style.width = `${width}px`;
  for (let t = new Date(gridStart); t < gridEnd; t = new Date(t.getTime() + step)) {
    if (t.getMinutes() !== 0) continue;
    const label = document.createElement("span");
    label.className = "board-hour";
    label.style.left = `${x(t)}px`;
    label.textContent = formatTime(t);
    hours.appendChild(label);
  }
  header.appendChild(corner);
  header.appendChild(hours);
  grid.appendChild(header);

  data.resources.forEach((r) => {
    const row = document.createElement("div");
    row.className = "board-row";
    row.dataset.resourceId = r.id;
    const name = document.createElement("div");
    name.className = "board-name";
    name.textContent = r.name;
    const meta = document.createElement("small");
    meta.textContent = `${r.type} · ${r.exclusive ? `fits ${r.capacity}` : `${r.capacity} units`}${r.is_active ? "" : " · inactive"}`;
    name.appendChild(meta);
    const track = document.createElement("div");
    track.className = "board-track";
    track.style.width = `${width}px`;

    // Closed hours: everything in the grid outside this resource's open windows.
    const open = r.open_windows.map((w) => [new Date(w.start), new Date(w.end)]).sort((a, b) => a[0] - b[0]);
    let cursor = gridStart;
    open.concat([[gridEnd, gridEnd]]).forEach(([s, e]) => {
      if (s > cursor) {
        const closed = document.createElement("div");
        closed.className = "board-closed";
        closed.title = "closed";
        if (place(closed, cursor, s)) track.appendChild(closed);
      }
      if (e > cursor) cursor = e;
    });
    r.blackouts.forEach((b) => {
      const div = document.createElement("div");
      div.className = "board-blackout";
      div.title = `Unavailable: ${b.reason}`;
      if (place(div, b.start, b.end)) track.appendChild(div);
    });
    // Unit pools: a thin load strip ("7/30") along the top of the row, and
    // the individual bookings in their own sub-lanes BELOW it, so no label
    // is ever drawn over another one.
    (r.load || []).forEach((seg) => {
      const div = document.createElement("div");
      div.className = "board-load";
      div.style.background = `rgba(59, 110, 246, ${0.12 + 0.6 * Math.min(seg.load / seg.capacity, 1)})`;
      div.textContent = `${seg.load}/${seg.capacity}`;
      div.title = `${seg.load} of ${seg.capacity} units in use`;
      if (place(div, seg.start, seg.end)) track.appendChild(div);
    });
    // Sub-lane for each pool booking: the first lane free at its start.
    const lane = new Map();
    let lanes = 1;
    if (!r.exclusive) {
      const ends = [];
      r.blocks.slice().sort((a, b) => new Date(a.start) - new Date(b.start)).forEach((b) => {
        let k = ends.findIndex((end) => end <= new Date(b.start));
        if (k === -1) {
          k = ends.length;
          ends.push(null);
        }
        ends[k] = new Date(b.end);
        lane.set(b, k);
      });
      lanes = Math.max(1, ends.length);
    }
    r.blocks.forEach((b) => {
      const div = document.createElement("div");
      const kind = b.busy ? "is-busy" : b.status === "pending" ? "is-pending" : "is-confirmed";
      div.className = `board-block ${kind}${b.mine ? " is-mine" : ""}`;
      if (!r.exclusive) {
        div.classList.add("is-lane");
        div.style.top = `${BOARD_LOAD_STRIP_PX + 4 + lane.get(b) * BOARD_LANE_PX}px`;
      }
      const t = `${formatTime(new Date(b.start))}–${formatTime(new Date(b.end))}`;
      div.textContent = b.busy ? "busy" : b.user_name ? `${b.user_name} · ${b.party_size}` : `mine · ${b.status}`;
      div.title = b.busy ? `busy ${t}` : `${b.user_name || "my booking"} · ${b.status} · party ${b.party_size} · ${t}`;
      if (b.id && currentUserIsAdmin()) {
        div.addEventListener("click", (event) => {
          event.stopPropagation();
          showBoardPopover(event, r, b);
        });
      } else {
        div.addEventListener("click", (event) => event.stopPropagation());
      }
      if (place(div, b.start, b.end)) track.appendChild(div);
    });
    if (!r.exclusive) {
      // Strip + one lane per overlapping booking; never shorter than a room row.
      const needed = BOARD_LOAD_STRIP_PX + 8 + Math.max(1, lanes) * BOARD_LANE_PX;
      track.style.height = `${Math.max(48, needed)}px`;
    }
    if (now > gridStart && now < gridEnd) {
      const line = document.createElement("div");
      line.className = "board-now";
      line.style.left = `${x(now)}px`;
      track.appendChild(line);
    }
    // Members: click an empty spot to book that resource at that half hour.
    track.addEventListener("click", (event) => {
      if (currentUserIsAdmin()) return;
      const rect = track.getBoundingClientRect();
      const offset = Math.max(0, event.clientX - rect.left);
      const start = new Date(gridStart.getTime() + Math.floor(offset / slotPx) * step);
      if (start <= new Date()) return;
      const inside = open.some(([s, e]) => start >= s && start < e);
      if (!inside || !resourcesById[r.id]) return;
      openBookingDrawer({ resourceId: r.id, start });
    });
    row.appendChild(name);
    row.appendChild(track);
    grid.appendChild(row);
  });
  el.appendChild(grid);
  // Long days (e.g. a 24-hour resource): bring the current time, or the first
  // opening hour on other days, into view. Only when the day changes, so a
  // refresh of the same day keeps the user's own scroll position.
  const dayKey = `${formatLocalDate(midnight)}|${width}`;
  if (gridEnd - gridStart > 12 * 3600000 && boardScrolledFor !== dayKey) {
    const later = opens.map(([s]) => s).filter((s) => s > gridStart);
    let target = later.length ? new Date(Math.min(...later)) : new Date(midnight.getTime() + 8 * 3600000);
    if (now > gridStart && now < gridEnd) target = now;
    el.scrollLeft = Math.max(0, x(target) - 2 * slotPx);
  }
  boardScrolledFor = dayKey;
}

function renderBoardWeek(data, firstDay) {
  const el = document.getElementById("board");
  boardScrolledFor = null; // back on the day view, scroll to "now" again
  el.innerHTML = "";
  if (!data.resources.length) {
    el.textContent = "No resources to show.";
    return;
  }
  const days = Array.from({ length: 7 }, (_, i) => new Date(firstDay.getTime() + i * 86400000));
  const grid = document.createElement("div");
  grid.className = "board-grid";
  const header = document.createElement("div");
  header.className = "board-row board-header";
  const corner = document.createElement("div");
  corner.className = "board-name";
  corner.textContent = "Resource";
  header.appendChild(corner);
  days.forEach((d) => {
    const cell = document.createElement("div");
    cell.className = "board-week-cell";
    cell.style.cursor = "default";
    cell.textContent = `${WEEKDAY_NAMES[(d.getDay() + 6) % 7]} ${formatLocalDate(d).slice(5)}`;
    header.appendChild(cell);
  });
  grid.appendChild(header);

  data.resources.forEach((r) => {
    const row = document.createElement("div");
    row.className = "board-row";
    row.dataset.resourceId = r.id;
    const name = document.createElement("div");
    name.className = "board-name";
    name.textContent = r.name;
    const meta = document.createElement("small");
    meta.textContent = `${r.type} · ${r.exclusive ? `fits ${r.capacity}` : `${r.capacity} units`}`;
    name.appendChild(meta);
    row.appendChild(name);
    days.forEach((d) => {
      const dayStart = d.getTime();
      const dayEnd = dayStart + 86400000;
      const openMs = r.open_windows.reduce((a, w) => a + overlapMs(dayStart, dayEnd, new Date(w.start), new Date(w.end)), 0);
      const cell = document.createElement("div");
      cell.className = "board-week-cell";
      if (!openMs) {
        cell.classList.add("is-closed");
        cell.textContent = "closed";
        row.appendChild(cell);
        return;
      }
      let used = 0;
      let label;
      if (r.exclusive) {
        const blocks = r.blocks.filter((b) => overlapMs(dayStart, dayEnd, new Date(b.start), new Date(b.end)) > 0);
        used = blocks.reduce((a, b) => a + overlapMs(dayStart, dayEnd, new Date(b.start), new Date(b.end)), 0);
        label = `${blocks.length} booking${blocks.length === 1 ? "" : "s"}`;
      } else {
        const segs = r.load.filter((s) => overlapMs(dayStart, dayEnd, new Date(s.start), new Date(s.end)) > 0);
        used = segs.reduce((a, s) => a + s.load * overlapMs(dayStart, dayEnd, new Date(s.start), new Date(s.end)), 0) / r.capacity;
        const peak = segs.reduce((a, s) => Math.max(a, s.load), 0);
        label = `peak ${peak}/${r.capacity}`;
      }
      const pct = Math.min(100, Math.round((100 * used) / openMs));
      const text = document.createElement("div");
      text.textContent = `${pct}% · ${label}`;
      const bar = document.createElement("div");
      bar.className = "board-bar";
      const fill = document.createElement("span");
      fill.style.width = `${pct}%`;
      bar.appendChild(fill);
      cell.appendChild(bar);
      cell.appendChild(text);
      cell.title = `${r.name}, ${formatLocalDate(d)}: ${pct}% of open hours used`;
      cell.addEventListener("click", () => {
        document.getElementById("date-picker").value = formatLocalDate(d);
        setBoardMode("day");
      });
      row.appendChild(cell);
    });
    grid.appendChild(row);
  });
  el.appendChild(grid);
}

function hideBoardPopover() {
  document.getElementById("board-popover").hidden = true;
}

// Admins: who / status / party, with Approve / Reject for pending.
function showBoardPopover(event, resource, b) {
  const pop = document.getElementById("board-popover");
  const panel = document.getElementById("board-panel");
  pop.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = `${resource.name} · #${b.id}`;
  const lines = document.createElement("div");
  lines.className = "hint";
  lines.textContent = `${b.user_name} · ${b.status} · party ${b.party_size} · ` +
    `${formatTime(new Date(b.start))}–${formatTime(new Date(b.end))}` +
    `${b.series_id ? ` · series #${b.series_id}` : ""}${b.bundle_id ? ` · bundle #${b.bundle_id}` : ""}`;
  const message = document.createElement("div");
  message.className = "message";
  pop.appendChild(title);
  pop.appendChild(lines);
  const actions = document.createElement("div");
  actions.className = "pending-user-actions";
  const act = async (path, body) => {
    const { ok, status, data } = await apiRequest(`/reservations/${b.id}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (ok) {
      hideBoardPopover();
      await Promise.all([loadBoard(), loadPendingApprovals()]);
    } else {
      showMessage(message, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    }
  };
  if (b.status === "pending") {
    const approve = document.createElement("button");
    approve.className = "approve-btn";
    approve.textContent = "Approve";
    approve.addEventListener("click", () => act("approve"));
    const reject = document.createElement("button");
    reject.className = "deny-btn";
    reject.textContent = "Reject";
    reject.addEventListener("click", () => act("reject", { reason: null }));
    actions.appendChild(approve);
    actions.appendChild(reject);
  }
  const close = document.createElement("button");
  close.className = "secondary";
  close.textContent = "Close";
  close.addEventListener("click", hideBoardPopover);
  actions.appendChild(close);
  pop.appendChild(actions);
  pop.appendChild(message);
  const rect = panel.getBoundingClientRect();
  pop.style.left = `${Math.min(event.clientX - rect.left, rect.width - 260)}px`;
  pop.style.top = `${event.clientY - rect.top + 12}px`;
  pop.hidden = false;
}

async function loadMyReservations() {
  if (currentUserIsAdmin()) return;
  refreshAccountQuotaSummary(); // quota "used" changes with every booking/cancel
  const listEl = document.getElementById("my-reservations-list");
  listEl.innerHTML = "";

  const [{ data }, seriesResp, bundlesResp] = await Promise.all([
    apiRequest(`/reservations?user_id=${currentUser.id}&limit=500`),
    apiRequest("/reservations/series"),
    apiRequest("/reservations/bundles"),
  ]);
  const reservations = ((data && data.items) || []).slice().sort((a, b) => new Date(a.start_time) - new Date(b.start_time));

  if (reservations.length === 0) {
    const li = document.createElement("li");
    li.textContent = "You have no reservations yet.";
    listEl.appendChild(li);
    return;
  }

  const refresh = async () => {
    await loadMyReservations();
    await loadPendingApprovals();
    await loadTimeline();
  };

  // Series first: one heading per series, its occurrences indented under it.
  (seriesResp.data || []).forEach(({ series, occurrences }) => {
    if (occurrences.length === 0) return;
    const head = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = describeSeries(series, occurrences);
    head.appendChild(title);
    const hasFutureActive = occurrences.some((o) => ACTIVE_STATUSES.includes(o.status) && new Date(o.start_time) > new Date());
    if (series.status === "active" && hasFutureActive) {
      const btn = document.createElement("button");
      btn.textContent = "Cancel series";
      btn.addEventListener("click", async () => {
        if (!confirm("Cancel all upcoming occurrences of this series?")) return;
        const { ok, status, data: respData } = await apiRequest(`/reservations/series/${series.id}/cancel`, { method: "POST" });
        if (!ok) alert(`Could not cancel series: ${formatDetail(respData && respData.detail, status)}`);
        await refresh();
      });
      head.appendChild(btn);
    }
    listEl.appendChild(head);
    occurrences.forEach((r) => {
      const li = renderMyReservationItem(r, refresh);
      li.style.marginLeft = "var(--sp-6)";
      listEl.appendChild(li);
    });
  });

  // Bundles next: one heading per bundle (several resources, one time).
  (bundlesResp.data || []).forEach(({ bundle, items }) => {
    if (items.length === 0) return;
    const head = document.createElement("li");
    const title = document.createElement("strong");
    const start = new Date(items[0].start_time);
    const active = items.filter((r) => ACTIVE_STATUSES.includes(r.status)).length;
    title.textContent = `Bundle #${bundle.id} · ${items.length} resources · ${formatLocalDate(start)} ${formatTime(start)}–${formatTime(new Date(items[0].end_time))} · ${active} of ${items.length} active`;
    head.appendChild(title);
    const hasFutureActive = items.some((r) => ACTIVE_STATUSES.includes(r.status) && new Date(r.end_time) > new Date());
    if (bundle.status === "active" && hasFutureActive) {
      const btn = document.createElement("button");
      btn.textContent = "Cancel bundle";
      btn.addEventListener("click", async () => {
        if (!confirm(`Cancel every item of bundle #${bundle.id}?`)) return;
        const { ok, status, data: respData } = await apiRequest(`/reservations/bundle/${bundle.id}/cancel`, { method: "POST" });
        if (!ok) alert(`Could not cancel bundle: ${formatDetail(respData && respData.detail, status)}`);
        await refresh();
      });
      head.appendChild(btn);
    }
    listEl.appendChild(head);
    items.forEach((r) => {
      const li = renderMyReservationItem(r, refresh, true);
      li.style.marginLeft = "var(--sp-6)";
      listEl.appendChild(li);
    });
  });

  reservations
    .filter((r) => (r.series_id === null || r.series_id === undefined) && (r.bundle_id === null || r.bundle_id === undefined))
    .forEach((r) => {
      listEl.appendChild(renderMyReservationItem(r, refresh));
    });
}

// inBundle: bundle items are cancelled together ("Cancel bundle"), so the
// per-item Cancel button is not offered.
function renderMyReservationItem(r, refresh, inBundle = false) {
  const li = document.createElement("li");
  const resourceName = (resourcesById[r.resource_id] && resourcesById[r.resource_id].name) || `resource #${r.resource_id}`;
  const start = new Date(r.start_time);
  const end = new Date(r.end_time);

  const info = document.createElement("span");
  const startDateLabel = formatLocalDate(start);
  info.textContent = `${resourceName}: ${startDateLabel} ${formatTime(start)} - ${formatTime(end)} `;
  const statusTag = document.createElement("span");
  statusTag.className = "status-tag";
  statusTag.textContent = `[${r.status}]`;
  info.appendChild(statusTag);
  if (r.status === "rejected" && r.rejection_reason) {
    const reasonEl = document.createElement("span");
    reasonEl.className = "hint";
    reasonEl.style.display = "block";
    reasonEl.textContent = `Reason: ${r.rejection_reason}`;
    info.appendChild(reasonEl);
  }
  // Check-in (resources that require it): button inside the window.
  let checkInBtn = null;
  const res = resourcesById[r.resource_id];
  if (res && res.requires_checkin && r.status === "confirmed") {
    const note = document.createElement("span");
    note.className = "hint";
    note.style.display = "block";
    const opens = new Date(start.getTime() - 10 * 60000);
    const closes = new Date(start.getTime() + res.checkin_grace_minutes * 60000);
    const now = new Date();
    if (r.checked_in_at) {
      note.textContent = `Checked in ✓ at ${formatTime(new Date(r.checked_in_at))}`;
    } else if (now < opens) {
      note.textContent = `Check in between ${formatTime(opens)} and ${formatTime(closes)}, or the booking is released.`;
    } else if (now <= closes) {
      note.textContent = `Check in by ${formatTime(closes)} or the booking is released.`;
      checkInBtn = document.createElement("button");
      checkInBtn.className = "approve-btn";
      checkInBtn.textContent = "Check in";
      checkInBtn.addEventListener("click", async () => {
        const { ok, status, data: respData } = await apiRequest(`/reservations/${r.id}/check-in`, { method: "POST" });
        if (!ok) alert(`Could not check in: ${formatDetail(respData && respData.detail, status)}`);
        await refresh();
      });
    }
    info.appendChild(note);
  }
  if (r.status === "no_show") {
    const note = document.createElement("span");
    note.className = "hint";
    note.style.display = "block";
    note.textContent = "Released: nobody checked in within the grace period (counts as a no-show).";
    info.appendChild(note);
  }
  li.appendChild(info);
  if (checkInBtn) li.appendChild(checkInBtn);

  if (ACTIVE_STATUSES.includes(r.status)) {
    const ics = document.createElement("a");
    ics.href = `/reservations/${r.id}.ics`;
    ics.textContent = "Add to calendar";
    ics.className = "hint";
    ics.style.marginRight = "var(--sp-3)";
    ics.setAttribute("download", `reservation-${r.id}.ics`);
    li.appendChild(ics);
  }

  // Only active (pending/confirmed) reservations that haven't ended yet can be cancelled.
  if (!inBundle && ACTIVE_STATUSES.includes(r.status) && end > new Date()) {
    const btn = document.createElement("button");
    btn.textContent = "Cancel";
    btn.addEventListener("click", async () => {
      const { ok, status, data: respData } = await apiRequest(`/reservations/${r.id}/cancel`, { method: "POST" });
      if (!ok) alert(`Could not cancel: ${formatDetail(respData && respData.detail, status)}`);
      await refresh();
    });
    li.appendChild(btn);
  }

  return li;
}

async function loadPendingApprovals() {
  const panel = document.getElementById("pending-approvals-panel");
  const listEl = document.getElementById("pending-approvals-list");
  const messageEl = document.getElementById("pending-approvals-message");

  if (!currentUserIsAdmin()) {
    panel.hidden = true;
    listEl.innerHTML = "";
    showMessage(messageEl, "", "");
    return;
  }

  panel.hidden = false;
  listEl.innerHTML = "";

  const { data } = await apiRequest("/reservations?status=pending&limit=500");
  const pending = ((data && data.items) || []).slice().sort((a, b) => new Date(a.start_time) - new Date(b.start_time));

  if (pending.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No reservations awaiting approval.";
    listEl.appendChild(li);
    return;
  }

  const refresh = async () => {
    showMessage(messageEl, "", "");
    await loadPendingApprovals();
    await loadTimeline();
    await loadMyReservations();
  };

  // Pending occurrences of the same series are grouped under one heading
  // with "Approve all" / "Reject all"; single bookings render as before.
  const bySeries = new Map();
  pending.forEach((r) => {
    if (r.series_id === null || r.series_id === undefined) return;
    if (!bySeries.has(r.series_id)) bySeries.set(r.series_id, []);
    bySeries.get(r.series_id).push(r);
  });
  bySeries.forEach((items, seriesId) => {
    const first = items[0];
    const resourceName = (resourcesById[first.resource_id] && resourcesById[first.resource_id].name) || `resource #${first.resource_id}`;
    const requesterName = (usersById[first.user_id] && usersById[first.user_id].name) || `user #${first.user_id}`;
    const head = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `Recurring series #${seriesId} — ${requesterName} · ${resourceName} · ${items.length} pending`;
    head.appendChild(title);
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const approveAll = document.createElement("button");
    approveAll.className = "approve-btn";
    approveAll.textContent = "Approve all";
    approveAll.addEventListener("click", async () => {
      const { ok, status, data: respData } = await apiRequest(`/reservations/series/${seriesId}/approve`, { method: "POST" });
      if (ok) await refresh();
      else showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
    });
    const reasonInput = document.createElement("input");
    reasonInput.type = "text";
    reasonInput.placeholder = "Reason (optional)";
    reasonInput.maxLength = 500;
    reasonInput.setAttribute("aria-label", `Rejection reason for series #${seriesId}`);
    const rejectAll = document.createElement("button");
    rejectAll.className = "deny-btn";
    rejectAll.textContent = "Reject all";
    rejectAll.addEventListener("click", async () => {
      if (!confirm(`Reject all ${items.length} pending occurrences of this series?`)) return;
      const reason = reasonInput.value.trim();
      const { ok, status, data: respData } = await apiRequest(`/reservations/series/${seriesId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason || null }),
      });
      if (ok) await refresh();
      else showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
    });
    actions.appendChild(approveAll);
    actions.appendChild(reasonInput);
    actions.appendChild(rejectAll);
    head.appendChild(actions);
    listEl.appendChild(head);
    items.forEach((r) => {
      const li = renderPendingItem(r, messageEl);
      li.style.marginLeft = "var(--sp-6)";
      listEl.appendChild(li);
    });
  });

  // Pending items of the same bundle: "Approve bundle" / "Reject bundle".
  const byBundle = new Map();
  pending.forEach((r) => {
    if (r.bundle_id === null || r.bundle_id === undefined) return;
    if (!byBundle.has(r.bundle_id)) byBundle.set(r.bundle_id, []);
    byBundle.get(r.bundle_id).push(r);
  });
  byBundle.forEach((items, bundleId) => {
    const first = items[0];
    const requesterName = (usersById[first.user_id] && usersById[first.user_id].name) || `user #${first.user_id}`;
    const names = items.map((r) => (resourcesById[r.resource_id] && resourcesById[r.resource_id].name) || `resource #${r.resource_id}`);
    const head = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `Bundle #${bundleId} — ${requesterName} · ${names.join(" + ")} · ${items.length} pending`;
    head.appendChild(title);
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const approveBundle = document.createElement("button");
    approveBundle.className = "approve-btn";
    approveBundle.textContent = "Approve bundle";
    approveBundle.addEventListener("click", async () => {
      const { ok, status, data: respData } = await apiRequest(`/reservations/bundle/${bundleId}/approve`, { method: "POST" });
      if (ok) await refresh();
      else showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
    });
    const reasonInput = document.createElement("input");
    reasonInput.type = "text";
    reasonInput.placeholder = "Reason (optional)";
    reasonInput.maxLength = 500;
    reasonInput.setAttribute("aria-label", `Rejection reason for bundle #${bundleId}`);
    const rejectBundle = document.createElement("button");
    rejectBundle.className = "deny-btn";
    rejectBundle.textContent = "Reject bundle";
    rejectBundle.addEventListener("click", async () => {
      if (!confirm(`Reject bundle #${bundleId}? Its pending items are rejected and confirmed ones cancelled.`)) return;
      const reason = reasonInput.value.trim();
      const { ok, status, data: respData } = await apiRequest(`/reservations/bundle/${bundleId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason || null }),
      });
      if (ok) await refresh();
      else showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
    });
    actions.appendChild(approveBundle);
    actions.appendChild(reasonInput);
    actions.appendChild(rejectBundle);
    head.appendChild(actions);
    listEl.appendChild(head);
    items.forEach((r) => {
      const li = renderPendingItem(r, messageEl);
      // Bundle items are decided together: drop the per-item buttons.
      const itemActions = li.querySelector(".approval-actions");
      if (itemActions) itemActions.remove();
      li.style.marginLeft = "var(--sp-6)";
      listEl.appendChild(li);
    });
  });

  pending
    .filter((r) => (r.series_id === null || r.series_id === undefined) && (r.bundle_id === null || r.bundle_id === undefined))
    .forEach((r) => {
      listEl.appendChild(renderPendingItem(r, messageEl));
    });
}

function renderPendingItem(r, messageEl) {
  const li = document.createElement("li");
  const resourceName = (resourcesById[r.resource_id] && resourcesById[r.resource_id].name) || `resource #${r.resource_id}`;
  const requesterName = (usersById[r.user_id] && usersById[r.user_id].name) || `user #${r.user_id}`;
  const start = new Date(r.start_time);
  const end = new Date(r.end_time);
  const startDateLabel = formatLocalDate(start);

  const info = document.createElement("span");
  info.textContent = `${resourceName} — ${requesterName}: ${startDateLabel} ${formatTime(start)} - ${formatTime(end)}`;
  li.appendChild(info);

  const actions = document.createElement("div");
  actions.className = "approval-actions";

  const approveBtn = document.createElement("button");
  approveBtn.textContent = "Approve";
  approveBtn.className = "approve-btn";
  approveBtn.addEventListener("click", async () => {
    const { ok, status, data: respData } = await apiRequest(`/reservations/${r.id}/approve`, { method: "POST" });
    if (ok) {
      showMessage(messageEl, "", "");
      await loadPendingApprovals();
      await loadTimeline();
      await loadMyReservations();
    } else {
      const detail = (respData && respData.detail) || `Request failed with status ${status}`;
      showMessage(messageEl, `Error (${status}): ${detail}`, "error");
    }
  });

  const reasonInput = document.createElement("input");
  reasonInput.type = "text";
  reasonInput.placeholder = "Reason (optional)";
  reasonInput.maxLength = 500;
  reasonInput.setAttribute("aria-label", `Rejection reason for ${requesterName}`);

  const rejectBtn = document.createElement("button");
  rejectBtn.textContent = "Reject";
  rejectBtn.className = "deny-btn";
  rejectBtn.addEventListener("click", async () => {
    if (!confirm(`Reject reservation request by ${requesterName}?`)) return;
    const reason = reasonInput.value.trim();
    const { ok, status, data: respData } = await apiRequest(`/reservations/${r.id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || null }),
    });
    if (ok) {
      showMessage(messageEl, "", "");
      await loadPendingApprovals();
      await loadTimeline();
      await loadMyReservations();
    } else {
      const detail = (respData && respData.detail) || `Request failed with status ${status}`;
      showMessage(messageEl, `Error (${status}): ${detail}`, "error");
    }
  });

  actions.appendChild(approveBtn);
  actions.appendChild(reasonInput);
  actions.appendChild(rejectBtn);
  li.appendChild(actions);

  return li;
}

// --- Waitlist (member) ------------------------------------------------------

async function joinWaitlistFromDrawer() {
  const btn = document.getElementById("join-waitlist-btn");
  const messageEl = document.getElementById("booking-message");
  const { ok, status, data } = await apiRequest("/waitlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resource_id: Number(btn.dataset.resourceId),
      start_time: btn.dataset.start,
      end_time: btn.dataset.end,
      party_size: Number(btn.dataset.partySize) || 1,
    }),
  });
  if (ok) {
    btn.hidden = true;
    showMessage(messageEl, `You're on the waitlist (position ${data.position}). You'll get the slot automatically if it frees up.`, "success");
    await loadMyWaitlist();
  } else {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
  }
}

async function loadMyWaitlist() {
  if (currentUserIsAdmin()) return;
  const listEl = document.getElementById("my-waitlist-list");
  const { data } = await apiRequest("/waitlist");
  const entries = (data || []).filter((e) => e.status === "waiting" || e.status === "promoted");
  listEl.innerHTML = "";
  if (entries.length === 0) {
    const li = document.createElement("li");
    li.textContent = "You're not waiting for any slot.";
    listEl.appendChild(li);
    return;
  }
  entries.forEach((e) => {
    const li = document.createElement("li");
    const resource = resourcesById[e.resource_id];
    const start = new Date(e.start_time);
    const info = document.createElement("span");
    info.textContent = `${(resource && resource.name) || `resource #${e.resource_id}`}: ${formatLocalDate(start)} ${formatTime(start)} - ${formatTime(new Date(e.end_time))} `;
    const tag = document.createElement("span");
    tag.className = "status-tag";
    tag.textContent = e.status === "waiting" ? `[waiting · #${e.position}]` : "[promoted — booked]";
    info.appendChild(tag);
    li.appendChild(info);
    if (e.status === "waiting") {
      const btn = document.createElement("button");
      btn.textContent = "Cancel";
      btn.addEventListener("click", async () => {
        const { ok, status, data: respData } = await apiRequest(`/waitlist/${e.id}/cancel`, { method: "POST" });
        if (!ok) alert(`Could not leave the waitlist: ${formatDetail(respData && respData.detail, status)}`);
        await loadMyWaitlist();
      });
      li.appendChild(btn);
    }
    listEl.appendChild(li);
  });
}

// --- Real-time updates (Server-Sent Events) --------------------------------

let liveSource = null;
const liveTimers = {};
function debounced(key, fn, ms = 300) {
  clearTimeout(liveTimers[key]);
  liveTimers[key] = setTimeout(fn, ms);
}

// Optional enhancement: if EventSource is missing or the stream fails, the
// app works exactly as before (manual refreshes).
function startLiveUpdates() {
  if (!window.EventSource || liveSource) return;
  liveSource = new EventSource("/events"); // reconnects by itself if the stream drops
  liveSource.addEventListener("change", (event) => {
    let change;
    try {
      change = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (String(change.resource_id) === document.getElementById("resource-select").value) {
      debounced("timeline", loadTimeline);
    }
    if (boardView === "board") debounced("board", loadBoard, 500);
    if (currentUserIsAdmin()) {
      debounced("approvals", loadPendingApprovals);
      debounced("pendingUsers", loadPendingUserCount);
    } else {
      debounced("mine", loadMyReservations);
      debounced("waitlist", loadMyWaitlist);
    }
  });
}

// --- Calendar feed (account menu) ------------------------------------------

async function showCalendarFeed() {
  if (!confirm("Create a private calendar feed URL? Any previous feed URL stops working.")) return;
  const { ok, status, data } = await apiRequest("/auth/me/calendar-token", { method: "POST" });
  if (!ok) {
    alert(`Could not create the feed: ${formatDetail(data && data.detail, status)}`);
    return;
  }
  try {
    await navigator.clipboard.writeText(data.url);
  } catch (e) {
    // clipboard may be blocked; the prompt below still lets the user copy it
  }
  window.prompt("Subscribe to this URL in your calendar app (copied to clipboard if allowed):", data.url);
}

// --- Admin: background jobs ------------------------------------------------

async function loadJobsStatus() {
  if (!currentUserIsAdmin()) return;
  const textEl = document.getElementById("jobs-status-text");
  const { ok, status, data } = await apiRequest("/admin/jobs/status");
  if (!ok) {
    textEl.textContent = `Could not load job status (${status}).`;
    return;
  }
  const last = data.last_run_at ? formatLocalDateTime(data.last_run_at) : "never";
  const result = data.last_result
    ? Object.entries(data.last_result).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(", ")
    : "—";
  textEl.textContent =
    `${data.enabled ? "Running" : "Disabled"} · every ${data.interval} s · runs: ${data.runs_count} · last run: ${last} · last result: ${result}` +
    (data.last_error ? ` · last error: ${data.last_error}` : "");
  setAdminSummary("jobs-summary", data.enabled ? `running every ${data.interval} s` : "disabled");
}

async function runJobsNow() {
  const messageEl = document.getElementById("jobs-message");
  const { ok, status, data } = await apiRequest("/admin/jobs/run-now", { method: "POST" });
  if (ok) {
    showMessage(messageEl, data.skipped ? `Skipped: ${data.skipped}` : "Jobs ran.", "success");
    await Promise.all([loadJobsStatus(), loadPendingApprovals(), loadTimeline()]);
  } else {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
  }
}

async function handleAddResource(event) {
  event.preventDefault();
  const messageEl = document.getElementById("add-resource-message");
  const payload = {
    name: document.getElementById("new-resource-name").value,
    type: document.getElementById("new-resource-type").value,
    capacity: Number(document.getElementById("new-resource-capacity").value),
    // booking_mode comes from the data-field="booking_mode" select.
    ...readResourcePolicyFields(document.getElementById("add-resource-form")),
  };

  const { ok, status, data } = await apiRequest("/resources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (ok) {
    showMessage(messageEl, `Added resource "${data.name}".`, "success");
    document.getElementById("add-resource-form").reset();
    await loadResources();
    await loadTimeline();
    await loadManageResources();
  } else {
    showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
  }
}

// --- Admin: resource policy fields, manage resources, blackouts --------

// Reads the policy inputs (marked with data-field / data-weekday) from a
// form, shared by the "Add resource" form and the inline Edit forms.
function readResourcePolicyFields(root) {
  const get = (field) => root.querySelector(`[data-field="${field}"]`);
  const textOrNull = (field) => {
    const v = get(field).value.trim();
    return v === "" ? null : v;
  };
  const payload = {
    description: textOrNull("description"),
    location: textOrNull("location"),
    open_time: get("open_time").value,
    close_time: get("close_time").value,
    open_weekdays: Array.from(root.querySelectorAll("[data-weekday]"))
      .filter((cb) => cb.checked)
      .map((cb) => Number(cb.dataset.weekday)),
    min_duration_minutes: Number(get("min_duration_minutes").value),
    max_duration_minutes: Number(get("max_duration_minutes").value),
    auto_approve: get("auto_approve").checked,
  };
  // Empty timezone = let the server apply its default.
  const tz = textOrNull("timezone");
  if (tz) payload.timezone = tz;
  const mode = get("booking_mode");
  if (mode) payload.booking_mode = mode.value;
  const checkin = get("requires_checkin");
  if (checkin) payload.requires_checkin = checkin.checked;
  const grace = get("checkin_grace_minutes");
  if (grace) payload.checkin_grace_minutes = Number(grace.value);
  return payload;
}

function makeField(labelText, input) {
  const field = document.createElement("div");
  field.className = "field";
  const label = document.createElement("label");
  label.textContent = labelText;
  field.appendChild(label);
  field.appendChild(input);
  return field;
}

function makeInput(type, dataField, value) {
  const input = document.createElement("input");
  input.type = type;
  if (dataField) input.dataset.field = dataField;
  if (type === "checkbox") input.checked = Boolean(value);
  else if (value !== null && value !== undefined) input.value = value;
  return input;
}

function makeCheckboxLabel(input, text) {
  const label = document.createElement("label");
  label.className = "checkbox-label";
  label.appendChild(input);
  label.appendChild(document.createTextNode(` ${text}`));
  return label;
}

function buildResourceEditForm(r, onDone) {
  const form = document.createElement("form");
  form.className = "stacked-form";
  form.style.flexBasis = "100%";

  const name = makeInput("text", null, r.name);
  const type = makeInput("text", null, r.type);
  const capacity = makeInput("number", null, r.capacity);
  capacity.min = "1";
  form.appendChild(makeField("Name", name));
  form.appendChild(makeField("Type", type));
  form.appendChild(makeField("Capacity", capacity));
  const mode = document.createElement("select");
  mode.dataset.field = "booking_mode";
  [["units", "Units (shared pool)"], ["whole", "Whole resource"]].forEach(([value, text]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    mode.appendChild(opt);
  });
  mode.value = r.booking_mode || "units";
  const modeField = makeField("Booking mode", mode);
  const modeHint = document.createElement("p");
  modeHint.className = "hint";
  modeHint.textContent = "Units: a pool of identical units; each booking takes as many as it needs. " +
    "Whole: one booking takes the whole resource; capacity is the most people it fits.";
  modeField.appendChild(modeHint);
  form.appendChild(modeField);
  form.appendChild(makeField("Description", makeInput("text", "description", r.description)));
  form.appendChild(makeField("Location", makeInput("text", "location", r.location)));
  form.appendChild(makeField("Timezone", makeInput("text", "timezone", r.timezone)));
  form.appendChild(makeField("Opens at", makeInput("time", "open_time", r.open_time.slice(0, 5))));
  form.appendChild(makeField("Closes at", makeInput("time", "close_time", r.close_time.slice(0, 5))));

  const days = document.createElement("div");
  days.style.display = "flex";
  days.style.flexWrap = "wrap";
  days.style.gap = "var(--sp-3)";
  WEEKDAY_NAMES.forEach((dayName, i) => {
    const cb = makeInput("checkbox", null, r.open_weekdays.includes(i + 1));
    cb.dataset.weekday = String(i + 1);
    days.appendChild(makeCheckboxLabel(cb, dayName));
  });
  form.appendChild(makeField("Open on", days));
  form.appendChild(makeField("Min duration (minutes)", makeInput("number", "min_duration_minutes", r.min_duration_minutes)));
  form.appendChild(makeField("Max duration (minutes)", makeInput("number", "max_duration_minutes", r.max_duration_minutes)));
  form.appendChild(makeCheckboxLabel(makeInput("checkbox", "auto_approve", r.auto_approve), "Auto-approve bookings"));
  form.appendChild(makeCheckboxLabel(makeInput("checkbox", "requires_checkin", r.requires_checkin), "Requires check-in"));
  const grace = makeInput("number", "checkin_grace_minutes", r.checkin_grace_minutes);
  grace.min = "5";
  grace.max = "60";
  form.appendChild(makeField("Check-in grace (minutes)", grace));

  const saveBtn = document.createElement("button");
  saveBtn.type = "submit";
  saveBtn.textContent = "Save changes";
  form.appendChild(saveBtn);
  const messageEl = document.createElement("div");
  messageEl.className = "message";
  form.appendChild(messageEl);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      name: name.value.trim(),
      type: type.value.trim(),
      capacity: Number(capacity.value),
      ...readResourcePolicyFields(form),
    };
    const { ok, status, data } = await apiRequest(`/resources/${r.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (ok) {
      await onDone();
    } else {
      showMessage(messageEl, `Error (${status}): ${formatDetail(data && data.detail, status)}`, "error");
    }
  });
  return form;
}

function formatLocalDateTime(iso) {
  const d = new Date(iso);
  return `${formatLocalDate(d)} ${formatTime(d)}`;
}

async function buildBlackoutsSection(r) {
  const section = document.createElement("div");
  section.style.flexBasis = "100%";

  const title = document.createElement("p");
  title.className = "hint";
  title.textContent = `Upcoming blackouts (times in ${USER_TIME_ZONE.replace(/_/g, " ")})`;
  section.appendChild(title);

  const list = document.createElement("ul");
  list.style.listStyle = "none";
  list.style.padding = "0";
  section.appendChild(list);

  const messageEl = document.createElement("div");
  messageEl.className = "message";

  const nowIso = new Date().toISOString();
  const { data } = await apiRequest(`/resources/${r.id}/blackouts?from=${encodeURIComponent(nowIso)}`);
  const blackouts = data || [];
  if (blackouts.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No upcoming blackouts.";
    list.appendChild(li);
  }
  blackouts.forEach((b) => {
    const li = document.createElement("li");
    const info = document.createElement("span");
    info.textContent = `${formatLocalDateTime(b.start_time)} – ${formatLocalDateTime(b.end_time)} · ${b.reason}`;
    li.appendChild(info);
    const del = document.createElement("button");
    del.className = "deny-btn";
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      if (!confirm(`Delete blackout "${b.reason}"?`)) return;
      const { ok, status, data: respData } = await apiRequest(`/resources/${r.id}/blackouts/${b.id}`, { method: "DELETE" });
      if (ok) {
        section.replaceWith(await buildBlackoutsSection(r));
        await loadTimeline();
      } else {
        showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
      }
    });
    li.appendChild(del);
    list.appendChild(li);
  });

  const form = document.createElement("form");
  form.className = "stacked-form";
  const start = makeInput("datetime-local", null, "");
  const end = makeInput("datetime-local", null, "");
  const reason = makeInput("text", null, "");
  start.required = end.required = reason.required = true;
  reason.maxLength = 500;
  reason.placeholder = "e.g. Projector repair";
  const force = makeInput("checkbox", null, false);
  form.appendChild(makeField("Blackout start", start));
  form.appendChild(makeField("Blackout end", end));
  form.appendChild(makeField("Reason", reason));
  form.appendChild(makeCheckboxLabel(force, "Force: cancel conflicting reservations"));
  const addBtn = document.createElement("button");
  addBtn.type = "submit";
  addBtn.textContent = "Add blackout";
  form.appendChild(addBtn);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (force.checked && !confirm("Cancel every active reservation that overlaps this blackout?")) return;
    const url = `/resources/${r.id}/blackouts${force.checked ? "?force=true" : ""}`;
    const { ok, status, data: respData } = await apiRequest(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // datetime-local is the admin's local wall-clock time
        start_time: new Date(start.value).toISOString(),
        end_time: new Date(end.value).toISOString(),
        reason: reason.value.trim(),
      }),
    });
    if (ok) {
      section.replaceWith(await buildBlackoutsSection(r));
      await Promise.all([loadTimeline(), loadPendingApprovals()]);
    } else {
      showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
    }
  });

  section.appendChild(form);
  section.appendChild(messageEl);
  return section;
}

async function loadManageResources() {
  if (!currentUserIsAdmin()) return;
  const panel = document.getElementById("manage-resources-panel");
  const listEl = document.getElementById("manage-resources-list");
  const messageEl = document.getElementById("manage-resources-message");
  panel.hidden = false;
  listEl.innerHTML = "";

  const { data } = await apiRequest("/resources?include_inactive=true");
  const resources = data || [];
  setAdminSummary("manage-resources-summary", String(resources.length));
  if (resources.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No resources yet.";
    listEl.appendChild(li);
    return;
  }

  const refreshAll = async () => {
    showMessage(messageEl, "", "");
    await loadResources();
    await Promise.all([loadManageResources(), loadTimeline()]);
  };

  resources.forEach((r) => {
    const li = document.createElement("li");
    li.style.flexWrap = "wrap";

    const info = document.createElement("span");
    info.textContent = `${r.name} (${r.type}, cap ${r.capacity}, ${bookingModeLabel(r)})${r.location ? ` · ${r.location}` : ""}${r.auto_approve ? " · auto-approve" : ""}${r.requires_checkin ? ` · check-in within ${r.checkin_grace_minutes} min` : ""} `;
    const statusTag = document.createElement("span");
    statusTag.className = "status-tag";
    statusTag.textContent = r.is_active ? "[active]" : "[inactive]";
    info.appendChild(statusTag);
    const hours = document.createElement("span");
    hours.className = "hint";
    hours.style.display = "block";
    hours.textContent = formatResourceHours(r);
    info.appendChild(hours);
    li.appendChild(info);

    const actions = document.createElement("div");
    actions.className = "pending-user-actions";

    const editBtn = document.createElement("button");
    editBtn.className = "approve-btn";
    editBtn.textContent = "Edit";
    let editForm = null;
    editBtn.addEventListener("click", () => {
      if (editForm) {
        editForm.remove();
        editForm = null;
        return;
      }
      editForm = buildResourceEditForm(r, refreshAll);
      li.appendChild(editForm);
    });

    const toggleBtn = document.createElement("button");
    toggleBtn.className = "deny-btn";
    toggleBtn.textContent = r.is_active ? "Deactivate" : "Activate";
    toggleBtn.addEventListener("click", async () => {
      if (r.is_active && !confirm(`Deactivate "${r.name}"? Members won't see it or be able to book it; existing reservations are kept.`)) return;
      const { ok, status, data: respData } = await apiRequest(`/resources/${r.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !r.is_active }),
      });
      if (ok) {
        await refreshAll();
      } else {
        showMessage(messageEl, `Error (${status}): ${formatDetail(respData && respData.detail, status)}`, "error");
      }
    });

    const blackoutsBtn = document.createElement("button");
    blackoutsBtn.className = "deny-btn";
    blackoutsBtn.textContent = "Blackouts";
    let blackoutsSection = null;
    blackoutsBtn.addEventListener("click", async () => {
      if (blackoutsSection && blackoutsSection.isConnected) {
        blackoutsSection.remove();
        blackoutsSection = null;
        return;
      }
      blackoutsSection = await buildBlackoutsSection(r);
      li.appendChild(blackoutsSection);
    });

    actions.appendChild(editBtn);
    actions.appendChild(toggleBtn);
    actions.appendChild(blackoutsBtn);
    li.appendChild(actions);
    listEl.appendChild(li);
  });
}

// --- Admin: pending user approvals -----------------------------------

let pendingUsersPollHandle = null;

async function loadPendingUserCount() {
  if (!currentUserIsAdmin()) return;
  const badge = document.getElementById("pending-users-badge");
  const countEl = document.getElementById("pending-users-count");
  const { ok, data } = await apiRequest("/users/pending/count");
  if (!ok) return;
  countEl.textContent = data.pending_count;
  badge.hidden = data.pending_count === 0;
}

async function loadPendingUsersPanel() {
  if (!currentUserIsAdmin()) return;
  const panel = document.getElementById("pending-users-panel");
  const listEl = document.getElementById("pending-users-list");
  const messageEl = document.getElementById("pending-users-message");
  panel.hidden = false;
  listEl.innerHTML = "";

  const { data } = await apiRequest("/users/pending");
  const pending = data || [];
  setAdminSummary("pending-users-summary", String(pending.length));

  if (pending.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No users awaiting approval.";
    listEl.appendChild(li);
    await loadPendingUserCount();
    return;
  }

  pending.forEach((u) => {
    const li = document.createElement("li");
    const info = document.createElement("span");
    info.textContent = `${u.name} (${u.email})`;
    li.appendChild(info);

    const actions = document.createElement("span");
    actions.className = "pending-user-actions";

    const approveBtn = document.createElement("button");
    approveBtn.textContent = "Approve";
    approveBtn.className = "approve-btn";
    approveBtn.addEventListener("click", async () => {
      const { ok, status, data: respData } = await apiRequest(`/users/${u.id}/approve`, {
        method: "POST",
      });
      if (ok) {
        showMessage(messageEl, "", "");
        await loadPendingUsersPanel();
      } else {
        const detail = (respData && respData.detail) || `Request failed with status ${status}`;
        showMessage(messageEl, `Error (${status}): ${detail}`, "error");
      }
    });

    const denyBtn = document.createElement("button");
    denyBtn.textContent = "Deny";
    denyBtn.className = "deny-btn";
    denyBtn.addEventListener("click", async () => {
      const { ok, status, data: respData } = await apiRequest(`/users/${u.id}/deny`, { method: "POST" });
      if (ok) {
        showMessage(messageEl, "", "");
        await loadPendingUsersPanel();
      } else {
        const detail = (respData && respData.detail) || `Request failed with status ${status}`;
        showMessage(messageEl, `Error (${status}): ${detail}`, "error");
      }
    });

    actions.appendChild(approveBtn);
    actions.appendChild(denyBtn);
    li.appendChild(actions);
    listEl.appendChild(li);
  });

  await loadPendingUserCount();
}

// Admin sections are collapsible <details>; their <summary> shows a count.
function setAdminSummary(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ? `· ${text}` : "";
}

function wireAdminPendingUsers() {
  if (!currentUserIsAdmin()) return;

  document.getElementById("pending-users-badge").addEventListener("click", () => {
    document.getElementById("pending-users-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  });

  loadPendingUserCount();
  pendingUsersPollHandle = setInterval(loadPendingUserCount, PENDING_USERS_POLL_MS);
}

function wireEvents() {
  document.getElementById("resource-select").addEventListener("change", loadTimeline);
  document.getElementById("date-picker").addEventListener("change", loadTimeline);

  document.getElementById("confirm-booking-btn").addEventListener("click", confirmBooking);
  document.getElementById("cancel-booking-panel-btn").addEventListener("click", closeBookingPanel);

  document.getElementById("add-resource-form").addEventListener("submit", handleAddResource);
  document.getElementById("find-slot-form").addEventListener("submit", handleFindSlot);
  document.getElementById("find-mode-single").addEventListener("change", updateFindMode);
  document.getElementById("find-mode-multi").addEventListener("change", updateFindMode);
  document.getElementById("view-day-btn").addEventListener("click", () => setView("timeline"));
  document.getElementById("view-board-btn").addEventListener("click", () => setView("board"));
  document.getElementById("board-mode-day").addEventListener("click", () => setBoardMode("day"));
  document.getElementById("board-mode-week").addEventListener("click", () => setBoardMode("week"));
  document.getElementById("board-prev").addEventListener("click", () => shiftBoardDate(-1));
  document.getElementById("board-next").addEventListener("click", () => shiftBoardDate(1));
  document.getElementById("board-type").addEventListener("change", loadBoard);
  document.getElementById("date-picker").addEventListener("change", loadBoard);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideBoardPopover();
  });
  document.getElementById("repeat-frequency").addEventListener("change", updateRepeatVisibility);
  document.getElementById("repeat-end-kind").addEventListener("change", updateRepeatVisibility);
  document.getElementById("repeat-preview-btn").addEventListener("click", previewSeries);
  document.getElementById("jobs-run-now-btn").addEventListener("click", runJobsNow);
  document.getElementById("join-waitlist-btn").addEventListener("click", joinWaitlistFromDrawer);
  // Alternatives / "Join waitlist" belong to the last failed attempt: any edit
  // to what's being booked makes them stale, so clear them.
  ["booking-start-time", "booking-duration", "repeat-frequency", "repeat-interval", "repeat-end-kind",
   "repeat-count", "repeat-until", "repeat-mode"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener("input", () => renderBookingAlternatives([]));
    el.addEventListener("change", () => renderBookingAlternatives([]));
  });
  document.querySelectorAll("[data-repeat-weekday]").forEach((cb) =>
    cb.addEventListener("change", () => renderBookingAlternatives([]))
  );
  document.getElementById("calendar-feed-btn").addEventListener("click", showCalendarFeed);

  if (!pastSlotsPollHandle) {
    pastSlotsPollHandle = setInterval(updatePastSlots, PAST_SLOTS_POLL_MS);
  }
}

function wireChatbotEvents() {
  document.getElementById("chatbot-toggle").addEventListener("click", toggleChatbot);
  document.getElementById("chatbot-close").addEventListener("click", closeChatbot);
  document.getElementById("chatbot-form").addEventListener("submit", handleChatSubmit);
  document.getElementById("chatbot-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("chatbot-form").requestSubmit();
    }
  });
  renderChatStarters();
}

function toggleChatbot() {
  if (document.getElementById("chatbot-panel").hidden) {
    openChatbot();
  } else {
    closeChatbot();
  }
}

function openChatbot() {
  document.getElementById("chatbot-panel").hidden = false;
  const toggle = document.getElementById("chatbot-toggle");
  toggle.classList.add("open");
  toggle.setAttribute("aria-label", "Close Reservation Assistant");
  renderChatStarters();
  document.getElementById("chatbot-input").focus();
}

function closeChatbot() {
  document.getElementById("chatbot-panel").hidden = true;
  const toggle = document.getElementById("chatbot-toggle");
  toggle.classList.remove("open");
  toggle.setAttribute("aria-label", "Open Reservation Assistant");
}

function renderChatStarters() {
  const startersEl = document.getElementById("chatbot-starters");
  startersEl.innerHTML = "";
  startersEl.hidden = chatHistory.length > 0;
  if (chatHistory.length > 0) return;

  CHAT_STARTERS.forEach((question) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = question;
    btn.addEventListener("click", () => {
      document.getElementById("chatbot-input").value = question;
      document.getElementById("chatbot-form").requestSubmit();
    });
    startersEl.appendChild(btn);
  });
}

function appendChatMessage(role, content, isLoading) {
  const messagesEl = document.getElementById("chatbot-messages");
  const bubble = document.createElement("div");
  bubble.className = `chatbot-message ${role}` + (isLoading ? " loading" : "");
  bubble.textContent = content;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function setChatWaiting(isWaiting) {
  chatIsWaiting = isWaiting;
  document.getElementById("chatbot-send").disabled = isWaiting;
  document.getElementById("chatbot-input").disabled = isWaiting;
}

function setChatError(text) {
  document.getElementById("chatbot-error").textContent = text || "";
}

async function handleChatSubmit(event) {
  event.preventDefault();
  if (chatIsWaiting) return;

  const input = document.getElementById("chatbot-input");
  const message = input.value.trim();
  if (!message) {
    setChatError("Type a question first.");
    return;
  }
  if (message.length > CHAT_MAX_MESSAGE_LENGTH) {
    setChatError(`Messages must be ${CHAT_MAX_MESSAGE_LENGTH} characters or fewer.`);
    return;
  }

  setChatError("");
  input.value = "";
  appendChatMessage("user", message, false);
  document.getElementById("chatbot-starters").hidden = true;
  setChatWaiting(true);
  const loadingBubble = appendChatMessage("assistant", "Thinking...", true);

  const recentHistory = chatHistory.slice(-CHAT_MAX_HISTORY_MESSAGES);
  const { ok, status, data } = await apiRequest("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history: recentHistory }),
  });

  loadingBubble.remove();
  if (ok) {
    const response = data.response || "I could not create a response.";
    appendChatMessage("assistant", response, false);
    chatHistory.push({ role: "user", content: message }, { role: "assistant", content: response });
    chatHistory = chatHistory.slice(-CHAT_MAX_HISTORY_MESSAGES);
  } else {
    const detail = (data && data.detail) || "The Reservation Assistant is temporarily unavailable. Please try again later.";
    appendChatMessage("assistant", detail, false);
    if (status >= 500) {
      setChatError("The assistant is temporarily unavailable.");
    }
  }

  setChatWaiting(false);
  input.focus();
}

async function init() {
  const user = await requireAuth();
  if (!user) return;
  currentUser = user;
  wireAccountBar(user);
  renderAccountQuotaSummary(user);
  // Wired independently and unconditionally so it can never be skipped by an
  // error elsewhere in setup (e.g. admin-only wiring) or by approval status —
  // the assistant is available to every logged-in user, pending or approved.
  wireChatbotEvents();

  if (user.approval_status === "pending") {
    document.getElementById("pending-approval-screen").hidden = false;
    wireLogout("pending-screen-logout-btn");
    return;
  }

  if (user.approval_status === "rejected") {
    document.getElementById("rejected-screen").hidden = false;
    wireLogout("rejected-screen-logout-btn");
    return;
  }

  document.getElementById("app-main").hidden = false;
  document.getElementById("add-resource-panel").hidden = !currentUserIsAdmin();
  document.getElementById("manage-resources-panel").hidden = !currentUserIsAdmin();
  document.getElementById("jobs-panel").hidden = !currentUserIsAdmin();

  const tabReservations = document.getElementById("tab-reservations");
  const paneReservations = document.getElementById("pane-reservations");
  if (currentUserIsAdmin()) {
    if (tabReservations) tabReservations.hidden = true;
    if (paneReservations) paneReservations.hidden = true;
    if (window.switchTab) {
      window.switchTab("approvals");
    }
  } else {
    if (tabReservations) tabReservations.hidden = false;
    if (paneReservations) paneReservations.hidden = false;
  }

  document.getElementById("date-picker").value = todayISODate();
  document.getElementById("find-from").value = todayISODate();
  document.getElementById("find-to").value = formatLocalDate(new Date(Date.now() + 6 * 86400000));
  document.getElementById("timeline-tz").textContent = `· times in ${USER_TIME_ZONE.replace(/_/g, " ")}`;
  wireEvents();
  await Promise.all([loadResources(), loadUsers()]);
  await loadTimeline();
  if (!currentUserIsAdmin()) {
    await loadMyReservations();
    await loadMyWaitlist();
    await loadFindParticipants();
  }
  await loadPendingApprovals();
  startLiveUpdates();

  if (currentUserIsAdmin()) {
    await loadPendingUsersPanel();
    wireAdminPendingUsers();
    await loadManageResources();
    await loadJobsStatus();
  }
}

document.addEventListener("DOMContentLoaded", init);
