(function () {
  const STORAGE_KEY = "theme";

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // ignore (private browsing / storage blocked)
    }
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  const stored = getStoredTheme();
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(stored || (prefersDark ? "dark" : "light"));

  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    setStoredTheme(next);
    updateToggleButton();
  }

  const SUN_ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/>' +
    '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2' +
    'M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
  const MOON_ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

  function updateToggleButton() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    const isDark = currentTheme() === "dark";
    btn.innerHTML = isDark ? SUN_ICON : MOON_ICON;
    btn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  }

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.addEventListener("click", toggleTheme);
    }
    updateToggleButton();
  });
})();
