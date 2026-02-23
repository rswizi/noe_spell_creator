(() => {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const PORTAL_PATH = "/portal.html";
  const REPLAY_FLAG_KEY = "noePortalReplayPending";
  const REPLAY_QUERY_KEY = "replay_intro";
  const BUTTON_ID = "global-portal-replay-btn";
  const STYLE_ID = "global-portal-replay-style";

  function isPortalPage() {
    const path = String(window.location.pathname || "").toLowerCase();
    return path === "/portal.html" || path === "/portal";
  }

  function setReplayPending() {
    try {
      window.sessionStorage.setItem(REPLAY_FLAG_KEY, "1");
    } catch {
      // ignore storage restrictions
    }
  }

  function consumeReplayPending() {
    let pending = false;
    try {
      pending = window.sessionStorage.getItem(REPLAY_FLAG_KEY) === "1";
      if (pending) window.sessionStorage.removeItem(REPLAY_FLAG_KEY);
    } catch {
      // ignore storage restrictions
    }
    const current = new URL(window.location.href);
    if (current.searchParams.get(REPLAY_QUERY_KEY) === "1") {
      pending = true;
      current.searchParams.delete(REPLAY_QUERY_KEY);
      window.history.replaceState(window.history.state, "", current.pathname + current.search + current.hash);
    }
    return pending;
  }

  function replayIntroOnPortal() {
    const attemptReplay = () => {
      if (typeof window.replayIntroOverlay === "function") {
        window.replayIntroOverlay();
        return true;
      }
      return false;
    };
    if (attemptReplay()) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (attemptReplay() || tries > 40) {
        window.clearInterval(timer);
      }
    }, 100);
  }

  function goToPortalThenReplay() {
    if (isPortalPage()) {
      replayIntroOnPortal();
      return;
    }
    setReplayPending();
    const target = new URL(PORTAL_PATH, window.location.origin);
    target.searchParams.set(REPLAY_QUERY_KEY, "1");
    window.location.assign(target.pathname + target.search);
  }

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${BUTTON_ID} {
        position: fixed;
        top: 12px;
        left: 12px;
        width: 52px;
        height: 52px;
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.22);
        background: rgba(7, 8, 14, 0.82);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        z-index: 9990;
        padding: 6px;
        backdrop-filter: blur(4px);
      }
      #${BUTTON_ID} img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        pointer-events: none;
      }
      #${BUTTON_ID}:hover {
        border-color: rgba(255,255,255,0.5);
      }
    `;
    document.head.appendChild(style);
  }

  function bindExistingPortalButton(button) {
    if (!button || button.dataset.portalReplayBound === "1") return;
    button.dataset.portalReplayBound = "1";
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        goToPortalThenReplay();
      },
      true
    );
  }

  function createFloatingButton() {
    if (document.getElementById(BUTTON_ID)) return;
    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.setAttribute("aria-label", "Return to portal and replay intro");
    button.title = "Return to portal and replay intro";
    button.innerHTML = '<img src="/assets/logo/logo.svg" alt="Portal" />';
    button.addEventListener("click", (event) => {
      event.preventDefault();
      goToPortalThenReplay();
    });
    document.body.appendChild(button);
  }

  function init() {
    ensureStyles();

    if (isPortalPage() && consumeReplayPending()) {
      replayIntroOnPortal();
    }

    const portalHeaderButton = document.getElementById("portal-logo-btn");
    if (portalHeaderButton) {
      bindExistingPortalButton(portalHeaderButton);
      return;
    }
    createFloatingButton();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
