/* app.js — shared utilities for all pages */
'use strict';

// ── Toast ──────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 3800) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(110%)';
    setTimeout(() => toast.remove(), 320);
  }, duration);
}

// ── API ────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (res.status === 401) { window.location.href = 'index.html'; return null; }
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) { data = text; }
  if (!res.ok) {
    const msg = typeof data === 'object' && data?.detail
      ? (Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail)
      : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

// ── Auth ───────────────────────────────────────────────────
let _currentUser = null;

async function getCurrentUser() {
  if (_currentUser) return _currentUser;
  try {
    _currentUser = await api('/auth/me');
    return _currentUser;
  } catch (_) {
    window.location.href = 'index.html';
    return null;
  }
}

async function requireRoles(...roles) {
  const user = await getCurrentUser();
  if (!user) return null;
  if (roles.length && !roles.includes(user.role)) {
    showToast('Access denied for your role.', 'error');
    setTimeout(() => { window.location.href = 'resources.html'; }, 1200);
    return null;
  }
  return user;
}

async function logout() {
  try { await api('/auth/logout', { method: 'POST' }); } catch (_) {}
  window.location.href = 'index.html';
}

// ── Sidebar ────────────────────────────────────────────────
function buildSidebar(user, activePage) {
  const roleLabel = {
    super_admin: 'Super Admin', admin: 'Admin', hod: 'Head of Dept',
    faculty: 'Faculty', lab_instructor: 'Lab Instructor',
    cr: 'Class Representative', club_president: 'Club President', student: 'Student',
  }[user.role] || user.role;

  const initials = user.name.split(' ').map(p => p[0]).join('').substring(0,2).toUpperCase();

  const adminRoles = ['super_admin', 'admin', 'hod'];
  const bookingRoles = ['faculty', 'lab_instructor', 'hod', 'super_admin', 'admin'];
  const requestRoles = ['cr', 'club_president', 'faculty', 'lab_instructor'];

  const links = [
    { href: 'resources.html',  label: 'Resources',       page: 'resources',  always: true,
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>` },
    { href: 'bookings.html',   label: 'My Bookings',     page: 'bookings',   roles: bookingRoles,
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>` },
    { href: 'requests.html',   label: 'My Requests',     page: 'requests',   roles: requestRoles,
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>` },
    { href: 'pending.html',    label: 'Pending Reviews', page: 'pending',    roles: adminRoles,
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>` },
    { href: 'named-me.html',   label: 'Referencing Me',  page: 'named-me',   roles: ['faculty','hod','lab_instructor'],
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>` },
    { href: 'clubs.html',      label: 'Club Registration', page: 'clubs',    roles: ['student','cr','club_president'],
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0"/>` },
    { href: 'admin.html',      label: user.role === 'hod' ? 'Department Admin' : (user.role === 'super_admin' ? 'Super Admin' : 'Admin Operations'), page: 'admin', roles: adminRoles,
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>` },
  ];

  const visibleLinks = links.filter(l => l.always || (l.roles && l.roles.includes(user.role)));

  const navHtml = visibleLinks.map(l => `
    <a href="${l.href}" class="nav-link ${activePage === l.page ? 'active' : ''}">
      <svg class="nav-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">${l.icon}</svg>
      ${l.label}
    </a>
  `).join('');

  return `
    <div class="sidebar-brand">
      <div class="brand-name">Campus Reservation</div>
      <div class="brand-sub">KLE Tech — Team 16</div>
    </div>
    <div class="sidebar-user">
      <div class="user-avatar">${initials}</div>
      <div class="user-meta">
        <div class="user-name">${user.name}</div>
        <div class="user-role">${roleLabel}</div>
      </div>
    </div>
    <nav class="sidebar-nav">
      <div class="nav-section-label">Navigation</div>
      ${navHtml}
    </nav>
    <div class="sidebar-footer">
      <button class="btn-logout" id="btn-logout">
        <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
        </svg>
        Sign Out
      </button>
    </div>
  `;
}

function initSidebar(user, activePage) {
  const el = document.getElementById('sidebar');
  if (el) {
    el.innerHTML = buildSidebar(user, activePage);
    document.getElementById('btn-logout')?.addEventListener('click', logout);
  }
}

// ── Helpers ────────────────────────────────────────────────
function fmtDate(str) {
  if (!str) return '—';
  return new Date(str).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' });
}
function fmtDateTime(str) {
  if (!str) return '—';
  return new Date(str).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
}
function roleBadge(role) {
  return `<span class="badge badge-${role}">${role.replace(/_/g,' ')}</span>`;
}
function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}
function typeBadge(type) {
  return `<span class="badge-type">${type.replace(/_/g,' ')}</span>`;
}

// ── Mobile sidebar toggle ──────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('sidebar-toggle');
  const sidebar = document.getElementById('sidebar');
  if (toggle && sidebar) {
    toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    document.addEventListener('click', e => {
      if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && e.target !== toggle) {
        sidebar.classList.remove('open');
      }
    });
  }
});
