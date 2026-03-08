(() => {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__NOE_GLOBAL_AUTH_READY__) return;
  window.__NOE_GLOBAL_AUTH_READY__ = true;

  const API_BASE = "";
  const STYLE_ID = "gauth-style";
  const HOST_ID = "gauth-host";
  const BACKDROP_ID = "gauth-backdrop";
  const MODAL_ID = "gauth-modal";
  const EXISTING_DOCK_CLASS = "gauth-existing-dock";
  const AUTH_KEY_TOKEN = "auth_token";
  const AUTH_KEY_USERNAME = "auth_username";
  const AUTH_KEY_ROLE = "auth_role";

  function authChanged(detail) {
    window.dispatchEvent(new CustomEvent("noe-auth-changed", { detail }));
  }

  function clearAuthStorage() {
    try {
      window.localStorage.removeItem(AUTH_KEY_TOKEN);
      window.localStorage.removeItem(AUTH_KEY_USERNAME);
      window.localStorage.removeItem(AUTH_KEY_ROLE);
    } catch {
      // ignore storage restrictions
    }
  }

  function setAuthStorage(username, role, token) {
    try {
      if (token) window.localStorage.setItem(AUTH_KEY_TOKEN, token);
      if (username) window.localStorage.setItem(AUTH_KEY_USERNAME, username);
      if (role) window.localStorage.setItem(AUTH_KEY_ROLE, role);
    } catch {
      // ignore storage restrictions
    }
  }

  function authToken() {
    try {
      return window.localStorage.getItem(AUTH_KEY_TOKEN) || "";
    } catch {
      return "";
    }
  }

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .${EXISTING_DOCK_CLASS} {
        position: fixed !important;
        top: 12px;
        right: 12px;
        z-index: 10040;
        display: flex !important;
        gap: 8px;
        align-items: center;
      }
      #${HOST_ID} {
        position: fixed;
        top: 12px;
        right: 12px;
        z-index: 10040;
        display: flex;
        gap: 8px;
        align-items: center;
      }
      #${HOST_ID} .gauth-btn,
      #${HOST_ID} .gauth-link,
      #${HOST_ID} .gauth-chip-btn {
        border: 1px solid #c02d2d;
        border-radius: 8px;
        background: #141414;
        color: #fff;
        font-size: 0.9rem;
        padding: 7px 11px;
        line-height: 1.2;
        text-decoration: none;
        cursor: pointer;
      }
      #${HOST_ID} .gauth-link {
        display: inline-block;
      }
      #${HOST_ID} .gauth-btn:hover,
      #${HOST_ID} .gauth-link:hover,
      #${HOST_ID} .gauth-chip-btn:hover {
        border-color: #ff5555;
      }
      #${HOST_ID} .gauth-chip {
        display: none;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border: 1px solid #c02d2d;
        border-radius: 999px;
        background: #191919;
        color: #fff;
        max-width: min(70vw, 380px);
      }
      #${HOST_ID} .gauth-chip-name {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 0.9rem;
        opacity: 0.95;
      }
      #${BACKDROP_ID} {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.65);
        display: none;
        z-index: 10045;
      }
      #${MODAL_ID} {
        position: fixed;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        z-index: 10046;
      }
      #${MODAL_ID}.open,
      #${BACKDROP_ID}.open {
        display: flex;
      }
      #${MODAL_ID} .gauth-card {
        width: 420px;
        max-width: calc(100% - 28px);
        border: 1px solid #c02d2d;
        border-radius: 12px;
        background: #1a1a1a;
        color: #fff;
        padding: 18px;
        box-shadow: 0 0 16px rgba(192, 45, 45, 0.3);
      }
      #${MODAL_ID} .gauth-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
      }
      #${MODAL_ID} .gauth-title {
        color: #ff5b5b;
        font-size: 1.15rem;
      }
      #${MODAL_ID} .gauth-close {
        border: 1px solid #c02d2d;
        border-radius: 8px;
        background: transparent;
        color: #fff;
        cursor: pointer;
        padding: 4px 8px;
      }
      #${MODAL_ID} label {
        display: block;
        margin-top: 8px;
        font-size: 0.92rem;
        opacity: 0.95;
      }
      #${MODAL_ID} input {
        width: 100%;
        margin-top: 6px;
        border: 1px solid #303030;
        border-radius: 8px;
        background: #101010;
        color: #fff;
        padding: 10px 11px;
      }
      #${MODAL_ID} .gauth-status {
        min-height: 18px;
        margin-top: 10px;
        font-size: 0.9rem;
        color: #f0c4c4;
      }
      #${MODAL_ID} .gauth-forgot {
        border: 0;
        background: none;
        color: #ff8b8b;
        padding: 0;
        cursor: pointer;
        margin-top: 4px;
        font-size: 0.88rem;
      }
      #${MODAL_ID} .gauth-actions {
        margin-top: 14px;
        display: flex;
        justify-content: flex-end;
        gap: 8px;
      }
      #${MODAL_ID} .gauth-actions button {
        border: 1px solid #c02d2d;
        border-radius: 8px;
        color: #fff;
        background: #141414;
        cursor: pointer;
        padding: 8px 12px;
      }
      @media (max-width: 720px) {
        #${HOST_ID} {
          top: 10px;
          right: 10px;
          gap: 6px;
        }
        #${HOST_ID} .gauth-btn,
        #${HOST_ID} .gauth-link,
        #${HOST_ID} .gauth-chip-btn {
          font-size: 0.82rem;
          padding: 6px 9px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function dockExistingPortalAuth() {
    const openLogin = document.getElementById("open-login");
    const logout = document.getElementById("chip-logout");
    const userChip = document.getElementById("user-chip");
    if (!openLogin || !logout || !userChip) return false;

    const container =
      openLogin.closest(".auth-inline") ||
      userChip.closest(".auth-inline") ||
      openLogin.parentElement;
    if (!container) return false;
    if (container.dataset.gauthDocked === "1") return true;

    container.dataset.gauthDocked = "1";
    container.classList.add(EXISTING_DOCK_CLASS);
    if (container.parentElement !== document.body) {
      document.body.appendChild(container);
    }
    return true;
  }

  function ensureInjectedAuthUi() {
    if (document.getElementById(HOST_ID)) return;

    const host = document.createElement("div");
    host.id = HOST_ID;
    host.innerHTML = `
      <div class="gauth-chip" id="gauth-user-chip">
        <span class="gauth-chip-name" id="gauth-chip-name"></span>
        <button type="button" class="gauth-chip-btn" id="gauth-logout">Log Out</button>
      </div>
      <button type="button" class="gauth-btn" id="gauth-open-login">Log In</button>
      <a class="gauth-link" id="gauth-open-signup" href="/signup.html">Sign Up</a>
    `;
    document.body.appendChild(host);

    const backdrop = document.createElement("div");
    backdrop.id = BACKDROP_ID;
    backdrop.setAttribute("aria-hidden", "true");
    document.body.appendChild(backdrop);

    const modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="gauth-card">
        <div class="gauth-header">
          <div class="gauth-title">Log In</div>
          <button type="button" class="gauth-close" id="gauth-close-login" aria-label="Close">x</button>
        </div>
        <label for="gauth-username">Username</label>
        <input id="gauth-username" type="text" placeholder="Enter username" />
        <label for="gauth-password">Password</label>
        <input id="gauth-password" type="password" placeholder="Enter password" />
        <div class="gauth-status" id="gauth-status"></div>
        <button type="button" class="gauth-forgot" id="gauth-forgot-pass">Forgot password?</button>
        <div class="gauth-actions">
          <button type="button" id="gauth-cancel-login">Cancel</button>
          <button type="button" id="gauth-login-btn">Log In</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setLoggedInUi(username, role) {
    const chip = byId("gauth-user-chip");
    const chipName = byId("gauth-chip-name");
    const openLogin = byId("gauth-open-login");
    const openSignup = byId("gauth-open-signup");
    if (!chip || !chipName || !openLogin || !openSignup) return;

    chipName.textContent = `${username} (${role || "user"})`;
    chip.style.display = "flex";
    openLogin.style.display = "none";
    openSignup.style.display = "none";
  }

  function setLoggedOutUi() {
    const chip = byId("gauth-user-chip");
    const openLogin = byId("gauth-open-login");
    const openSignup = byId("gauth-open-signup");
    if (!chip || !openLogin || !openSignup) return;

    chip.style.display = "none";
    openLogin.style.display = "inline-block";
    openSignup.style.display = "inline-block";
  }

  function openLoginModal() {
    const modal = byId(MODAL_ID);
    const backdrop = byId(BACKDROP_ID);
    if (!modal || !backdrop) return;
    modal.classList.add("open");
    backdrop.classList.add("open");
    const username = byId("gauth-username");
    if (username) username.focus();
  }

  function closeLoginModal() {
    const modal = byId(MODAL_ID);
    const backdrop = byId(BACKDROP_ID);
    const status = byId("gauth-status");
    if (modal) modal.classList.remove("open");
    if (backdrop) backdrop.classList.remove("open");
    if (status) status.textContent = "";
  }

  async function safeJson(res) {
    try {
      return await res.json();
    } catch {
      return {};
    }
  }

  async function handlePasswordReset(username, currentPassword) {
    const status = byId("gauth-status");
    const nextPassword = window.prompt("Password reset required. Enter a new password:");
    if (!nextPassword) {
      if (status) status.textContent = "Password reset required.";
      return false;
    }
    if (nextPassword.length < 6) {
      if (status) status.textContent = "Password must be at least 6 characters.";
      return false;
    }

    const res = await fetch(`${API_BASE}/auth/reset-required`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        current_password: currentPassword,
        new_password: nextPassword,
      }),
    });
    const data = await safeJson(res);
    if (data.status !== "success") {
      if (status) status.textContent = data.message || "Reset failed.";
      return false;
    }
    if (status) status.textContent = "Password updated. Please log in again.";
    return true;
  }

  async function login() {
    const status = byId("gauth-status");
    const usernameInput = byId("gauth-username");
    const passwordInput = byId("gauth-password");
    if (!usernameInput || !passwordInput) return;

    const username = String(usernameInput.value || "").trim();
    const password = String(passwordInput.value || "");
    if (status) status.textContent = "";

    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await safeJson(res);

    if (data.status === "success") {
      setAuthStorage(data.username, data.role, data.token);
      setLoggedInUi(data.username, data.role);
      closeLoginModal();
      authChanged({
        status: "logged_in",
        username: data.username,
        role: data.role,
      });
      return;
    }
    if (data.status === "reset_required") {
      await handlePasswordReset(username, password);
      return;
    }
    if (status) status.textContent = data.message || "Login failed.";
  }

  async function logout() {
    const token = authToken();
    if (token) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        // ignore connectivity failure, local logout still applies
      }
    }
    clearAuthStorage();
    setLoggedOutUi();
    closeLoginModal();
    authChanged({ status: "logged_out" });
  }

  async function checkMe() {
    const token = authToken();
    if (!token) {
      setLoggedOutUi();
      return false;
    }

    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await safeJson(res);
      if (data.status === "success") {
        setAuthStorage(data.username, data.role, token);
        setLoggedInUi(data.username, data.role);
        return true;
      }
    } catch {
      // handled by logged-out fallback below
    }

    clearAuthStorage();
    setLoggedOutUi();
    return false;
  }

  function bindInjectedEvents() {
    const openLogin = byId("gauth-open-login");
    const closeLogin = byId("gauth-close-login");
    const cancelLogin = byId("gauth-cancel-login");
    const loginButton = byId("gauth-login-btn");
    const logoutButton = byId("gauth-logout");
    const backdrop = byId(BACKDROP_ID);
    const forgotPass = byId("gauth-forgot-pass");

    if (openLogin) {
      openLogin.addEventListener("click", (event) => {
        event.preventDefault();
        openLoginModal();
      });
    }
    if (closeLogin) {
      closeLogin.addEventListener("click", (event) => {
        event.preventDefault();
        closeLoginModal();
      });
    }
    if (cancelLogin) {
      cancelLogin.addEventListener("click", (event) => {
        event.preventDefault();
        closeLoginModal();
      });
    }
    if (backdrop) {
      backdrop.addEventListener("click", closeLoginModal);
    }
    if (loginButton) {
      loginButton.addEventListener("click", (event) => {
        event.preventDefault();
        login();
      });
    }
    if (logoutButton) {
      logoutButton.addEventListener("click", (event) => {
        event.preventDefault();
        logout();
      });
    }
    if (forgotPass) {
      forgotPass.addEventListener("click", async (event) => {
        event.preventDefault();
        const status = byId("gauth-status");
        const ident = window.prompt("Enter your email or username to receive a reset code:");
        if (!ident) return;
        try {
          if (status) status.textContent = "Requesting reset...";
          await fetch(`${API_BASE}/auth/forgot`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: ident, username: ident }),
          });
          window.alert("If the account exists, a reset code was generated.");
          const code = window.prompt("Enter reset code:");
          if (!code) return;
          const username = window.prompt("Confirm username:");
          const newPassword = window.prompt("Enter new password:");
          if (!username || !newPassword) return;
          const res = await fetch(`${API_BASE}/auth/reset`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, code, password: newPassword }),
          });
          const payload = await safeJson(res);
          if (payload.status === "success") {
            window.alert("Password updated.");
            if (status) status.textContent = "";
          } else {
            window.alert(payload.message || "Reset failed.");
          }
        } catch {
          window.alert("Reset failed.");
        } finally {
          if (status) status.textContent = "";
        }
      });
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeLoginModal();
    });
    window.addEventListener("storage", (event) => {
      if (
        event.key === AUTH_KEY_TOKEN ||
        event.key === AUTH_KEY_USERNAME ||
        event.key === AUTH_KEY_ROLE
      ) {
        checkMe();
      }
    });
  }

  function init() {
    ensureStyles();
    if (dockExistingPortalAuth()) {
      return;
    }
    ensureInjectedAuthUi();
    bindInjectedEvents();
    checkMe();

    window.noeGlobalAuth = {
      openLogin: openLoginModal,
      closeLogin: closeLoginModal,
      login,
      logout,
      checkMe,
      token: authToken,
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
