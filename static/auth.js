async function authRequest(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

function showAuthMessage(el, text, kind) {
  el.textContent = text;
  el.className = "auth-message" + (kind ? " " + kind : "");
}

// UI polish: spinner on the submit button while a request is in flight,
// and a short shake of the form when it fails. Presentation only.
function setFormBusy(form, busy) {
  const btn = form.querySelector(".auth-submit");
  if (btn) btn.setAttribute("aria-busy", busy ? "true" : "false");
}

function shakeForm(form) {
  form.classList.remove("is-shaking");
  void form.offsetWidth; // restart the animation
  form.classList.add("is-shaking");
}

async function redirectIfLoggedIn() {
  try {
    const res = await fetch("/auth/me", { credentials: "include" });
    if (res.ok) {
      window.location.href = "/";
    }
  } catch (e) {
    // ignore — stay on the auth page
  }
}

const VERIFICATION_POLL_MS = 3000;

const CHECK_ICON_SVG =
  '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';

// Once the user clicks the link in their email (usually in a different tab),
// this makes the original "check your email" tab notice on its own and log
// the user straight in — we already have their password in memory from the
// signup form, so there's no reason to send them back to type it again.
function pollForVerification(statusToken, email, password) {
  const checkEmailSection = document.getElementById("signup-check-email");
  const heading = checkEmailSection.querySelector("h1");
  const subtitle = checkEmailSection.querySelector(".auth-subtitle");

  const poll = setInterval(async () => {
    try {
      const res = await fetch(`/auth/verification-status?token=${encodeURIComponent(statusToken)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.verified) return;

      clearInterval(poll);
      if (heading) heading.textContent = "Email verified!";
      if (subtitle) subtitle.textContent = "Logging you in...";
      const icon = document.getElementById("signup-check-email-icon");
      if (icon) {
        icon.classList.add("is-success");
        icon.innerHTML = CHECK_ICON_SVG;
      }
      const waiting = document.getElementById("signup-waiting");
      if (waiting) waiting.classList.add("is-done");
      const waitingText = document.getElementById("signup-waiting-text");
      if (waitingText) waitingText.textContent = "Verified";

      const loginResp = await authRequest("/auth/login", { email, password });
      if (loginResp.ok) {
        window.location.href = "/";
      } else {
        // Fell out of sync somehow (e.g. password changed elsewhere) —
        // fall back to the normal login form instead of getting stuck.
        if (subtitle) subtitle.textContent = "Taking you to log in...";
        setTimeout(() => (window.location.href = "/login.html"), 1200);
      }
    } catch (e) {
      // ignore transient network errors — keep polling
    }
  }, VERIFICATION_POLL_MS);
}

function wireSignupForm() {
  const form = document.getElementById("signup-form");
  if (!form) return;
  const messageEl = document.getElementById("signup-message");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("signup-name").value.trim();
    const email = document.getElementById("signup-email").value.trim();
    const password = document.getElementById("signup-password").value;
    const retype = document.getElementById("signup-retype").value;

    if (password !== retype) {
      showAuthMessage(messageEl, "Passwords do not match.", "error");
      return;
    }

    setFormBusy(form, true);
    let resp;
    try {
      resp = await authRequest("/auth/signup", { name, email, password });
    } finally {
      setFormBusy(form, false);
    }
    const { ok, data } = resp;
    if (ok) {
      const formSection = document.getElementById("signup-form-section");
      const checkEmailSection = document.getElementById("signup-check-email");
      if (formSection && checkEmailSection) {
        document.getElementById("signup-check-email-address").textContent = email;
        formSection.hidden = true;
        checkEmailSection.hidden = false;
        // Keep the password in memory (not persisted anywhere) only long
        // enough to auto-login once verification is detected; the form
        // itself is cleared so it isn't left sitting in the DOM/autofill.
        pollForVerification(data.status_token, email, password);
        form.reset();
      } else {
        form.reset();
        showAuthMessage(messageEl, data.message, "success");
      }
    } else {
      showAuthMessage(messageEl, (data && data.detail) || "Sign up failed.", "error");
      shakeForm(form);
    }
  });
}

function wireLoginForm() {
  const form = document.getElementById("login-form");
  if (!form) return;
  const messageEl = document.getElementById("login-message");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;

    setFormBusy(form, true);
    let resp;
    try {
      resp = await authRequest("/auth/login", { email, password });
    } catch (e) {
      setFormBusy(form, false);
      throw e;
    }
    const { ok, data } = resp;
    if (ok) {
      window.location.href = "/"; // keep the spinner until the app loads
    } else {
      setFormBusy(form, false);
      showAuthMessage(messageEl, (data && data.detail) || "Login failed.", "error");
      shakeForm(form);
    }
  });
}

function wireForgotPasswordForm() {
  const form = document.getElementById("forgot-password-form");
  if (!form) return;
  const messageEl = document.getElementById("forgot-password-message");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("forgot-password-email").value.trim();
    const { ok, data } = await authRequest("/auth/forgot-password", { email });
    showAuthMessage(messageEl, (data && data.message) || (ok ? "Check your email." : "Something went wrong."), ok ? "success" : "error");
  });
}

function wireResetPasswordForm() {
  const form = document.getElementById("reset-password-form");
  if (!form) return;
  const messageEl = document.getElementById("reset-password-message");
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || "";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = document.getElementById("reset-password-password").value;
    const retype = document.getElementById("reset-password-retype").value;

    if (password !== retype) {
      showAuthMessage(messageEl, "Passwords do not match.", "error");
      return;
    }
    if (!token) {
      showAuthMessage(messageEl, "This reset link is missing its token.", "error");
      return;
    }

    const { ok, data } = await authRequest("/auth/reset-password", { token, password });
    if (ok) {
      showAuthMessage(messageEl, `${data.message} Redirecting to login...`, "success");
      setTimeout(() => (window.location.href = "/login.html"), 1500);
    } else {
      showAuthMessage(messageEl, (data && data.detail) || "Reset failed.", "error");
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  redirectIfLoggedIn();
  wireSignupForm();
  wireLoginForm();
  wireForgotPasswordForm();
  wireResetPasswordForm();
});
