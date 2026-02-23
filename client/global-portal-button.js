(() => {
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const PORTAL_URL = "/portal.html";
  const VIDEO_SRC = "/assets/logo/logo_animated.mp4";
  const POSTER_SRC = "/assets/logo/logo.png";
  const BUTTON_ID = "global-portal-replay-btn";
  const STYLE_ID = "global-portal-replay-style";
  const OVERLAY_ID = "global-portal-replay-overlay";

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
      #${OVERLAY_ID} {
        position: fixed;
        inset: 0;
        z-index: 9998;
        background: #000;
        opacity: 1;
        transition: opacity .55s ease;
        display: grid;
        place-items: center;
      }
      #${OVERLAY_ID}.fade {
        opacity: 0;
      }
      #${OVERLAY_ID} video {
        width: min(96vw, 960px);
        max-height: 96vh;
        object-fit: contain;
        background: #000;
      }
    `;
    document.head.appendChild(style);
  }

  function removeOverlay() {
    const old = document.getElementById(OVERLAY_ID);
    if (old) old.remove();
  }

  function redirectToPortal() {
    window.location.assign(PORTAL_URL);
  }

  function playIntroThenGoPortal() {
    ensureStyles();
    removeOverlay();

    const overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.setAttribute("aria-hidden", "true");

    const video = document.createElement("video");
    video.setAttribute("autoplay", "");
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "");
    video.setAttribute("preload", "auto");
    video.setAttribute("poster", POSTER_SRC);
    video.setAttribute("aria-hidden", "true");

    const source = document.createElement("source");
    source.src = VIDEO_SRC;
    source.type = "video/mp4";
    video.appendChild(source);
    overlay.appendChild(video);
    document.body.appendChild(overlay);

    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      overlay.classList.add("fade");
      setTimeout(() => {
        overlay.remove();
        redirectToPortal();
      }, 600);
    };

    const timeoutId = setTimeout(done, 10000);
    const clearAndDone = () => {
      clearTimeout(timeoutId);
      done();
    };

    video.addEventListener("ended", clearAndDone, { once: true });
    video.addEventListener("error", clearAndDone, { once: true });
    video.play().catch(clearAndDone);
  }

  function bindExistingPortalButton(button) {
    if (!button || button.dataset.portalReplayBound === "1") return;
    button.dataset.portalReplayBound = "1";
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        playIntroThenGoPortal();
      },
      true
    );
  }

  function createFloatingButton() {
    if (document.getElementById(BUTTON_ID)) return;
    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.setAttribute("aria-label", "Play intro and return to portal");
    button.title = "Play intro and return to portal";
    button.innerHTML = '<img src="/assets/logo/logo.svg" alt="Portal" />';
    button.addEventListener("click", (event) => {
      event.preventDefault();
      playIntroThenGoPortal();
    });
    document.body.appendChild(button);
  }

  function init() {
    ensureStyles();
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
