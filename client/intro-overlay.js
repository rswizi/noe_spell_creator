(() => {
  if (typeof window === "undefined") return;
  const STORAGE_KEY = "noeIntroPlayed";
  const VIDEO_SRC = "/assets/logo/logo_animated.mp4";
  const POSTER_SRC = "/assets/logo/logo.png";
  const FALLBACK_TIMEOUT = 10000;
  const FADE_CLASS = "intro-overlay--fade";
  const OVERLAY_ID = "intro-overlay";

  function safeSessionStorage() {
    try {
      return window.sessionStorage;
    } catch {
      return null;
    }
  }

  function shouldShowIntro(storage) {
    if (!storage) return false;
    return storage.getItem(STORAGE_KEY) !== "1";
  }

  function markIntroSeen(storage) {
    if (!storage) return;
    try {
      storage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore write failures (private mode, quota, etc.)
    }
  }

  function buildVideoElement() {
    const video = document.createElement("video");
    video.className = "intro-overlay__video";
    video.setAttribute("autoplay", "");
    video.setAttribute("playsinline", "");
    video.setAttribute("muted", "");
    video.setAttribute("preload", "auto");
    video.setAttribute("poster", POSTER_SRC);
    video.setAttribute("aria-hidden", "true");

    const source = document.createElement("source");
    source.src = VIDEO_SRC;
    source.type = "video/mp4";
    video.appendChild(source);
    video.appendChild(document.createTextNode("Loading logo animation…"));
    return video;
  }

  function removeExistingOverlay() {
    const existing = document.getElementById(OVERLAY_ID);
    if (existing) {
      existing.remove();
    }
  }

  function attachOverlay() {
    if (!document.body) return;
    removeExistingOverlay();
    const overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.className = "intro-overlay";
    overlay.setAttribute("aria-hidden", "true");

    const video = buildVideoElement();
    overlay.appendChild(video);
    document.body.appendChild(overlay);

    let hidden = false;
    const hide = () => {
      if (hidden) return;
      hidden = true;
      overlay.classList.add(FADE_CLASS);
      overlay.addEventListener("transitionend", () => overlay.remove(), { once: true });
      setTimeout(() => overlay.remove(), 1200);
    };

    const safeHide = () => {
      requestAnimationFrame(hide);
    };

    const fallbackTimer = setTimeout(() => {
      safeHide();
    }, FALLBACK_TIMEOUT);

    const cancelFallback = () => clearTimeout(fallbackTimer);

    video.addEventListener("ended", () => {
      cancelFallback();
      safeHide();
    });
    video.addEventListener("error", () => {
      cancelFallback();
      safeHide();
    });
    video.addEventListener("playing", cancelFallback);
    overlay.addEventListener("transitionend", cancelFallback);

    video.play().catch(() => {
      cancelFallback();
      safeHide();
    });
  }

  function runIntro(force = false) {
    const storage = safeSessionStorage();
    if (!force && !shouldShowIntro(storage)) {
      return false;
    }
    markIntroSeen(storage);
    attachOverlay();
    return true;
  }

  window.replayIntroOverlay = () => runIntro(true);

  if (typeof document === "undefined") {
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", runIntro);
  } else {
    runIntro();
  }
})();
