import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

const LEGACY_HEAD_ATTR = "data-character-manager-legacy-head";
const LEGACY_SCRIPT_ATTR = "data-character-manager-legacy-script";

function extractCharacterId(characterSlug, legacyId) {
  const directId = String(legacyId || "").trim();
  if (directId) return directId;
  const slug = String(characterSlug || "").trim();
  if (!slug) return "";
  const slugId = slug.includes("_") ? slug.slice(0, slug.indexOf("_")) : slug;
  if (!slugId) return "";
  try {
    return decodeURIComponent(slugId);
  } catch (_) {
    return slugId;
  }
}

function CharacterEditPage() {
  const { id: legacyId, characterSlug } = useParams();
  const id = extractCharacterId(characterSlug, legacyId);
  const hostRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id || !hostRef.current) return undefined;
    let cancelled = false;
    const appendedHead = [];
    const appendedScripts = [];

    const loadLegacy = async () => {
      setLoading(true);
      setError("");
      try {
        const targetUrl = `/character_edit_0_3_5.html?id=${encodeURIComponent(id)}`;
        const response = await fetch(targetUrl, { credentials: "include" });
        if (!response.ok) {
          throw new Error(`Unable to load 0.3.5 sheet (HTTP ${response.status})`);
        }
        const html = await response.text();
        if (cancelled) return;

        const parser = new DOMParser();
        const legacyDoc = parser.parseFromString(html, "text/html");

        document.querySelectorAll(`[${LEGACY_HEAD_ATTR}]`).forEach((node) => node.remove());
        document.querySelectorAll(`[${LEGACY_SCRIPT_ATTR}]`).forEach((node) => node.remove());

        const headNodes = legacyDoc.querySelectorAll("head style, head link[rel='stylesheet']");
        headNodes.forEach((node) => {
          if (node.tagName.toLowerCase() === "link") {
            const href = node.getAttribute("href");
            if (!href) return;
            const exists = Array.from(document.querySelectorAll("link[rel='stylesheet']")).some(
              (ln) => ln.getAttribute("href") === href
            );
            if (exists) return;
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = href;
            link.setAttribute(LEGACY_HEAD_ATTR, "1");
            document.head.appendChild(link);
            appendedHead.push(link);
            return;
          }
          const style = document.createElement("style");
          style.textContent = node.textContent || "";
          style.setAttribute(LEGACY_HEAD_ATTR, "1");
          document.head.appendChild(style);
          appendedHead.push(style);
        });

        const bodyClone = legacyDoc.body.cloneNode(true);
        const scriptNodes = Array.from(bodyClone.querySelectorAll("script"));
        scriptNodes.forEach((script) => script.remove());

        hostRef.current.innerHTML = "";
        while (bodyClone.firstChild) {
          hostRef.current.appendChild(bodyClone.firstChild);
        }

        for (const scriptNode of scriptNodes) {
          if (cancelled) return;
          const script = document.createElement("script");
          script.setAttribute(LEGACY_SCRIPT_ATTR, "1");
          const src = scriptNode.getAttribute("src");
          if (src) {
            script.src = src;
            if (scriptNode.getAttribute("defer") !== null) script.defer = true;
            if (scriptNode.getAttribute("type")) script.type = scriptNode.getAttribute("type");
          } else {
            script.text = scriptNode.textContent || "";
          }
          hostRef.current.appendChild(script);
          appendedScripts.push(script);
          if (src) {
            await new Promise((resolve, reject) => {
              script.addEventListener("load", resolve, { once: true });
              script.addEventListener("error", () => reject(new Error(`Failed to load script: ${src}`)), {
                once: true,
              });
            });
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to initialize 0.3.5 character sheet.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void loadLegacy();

    return () => {
      cancelled = true;
      appendedScripts.forEach((node) => node.remove());
      appendedHead.forEach((node) => node.remove());
      if (hostRef.current) {
        hostRef.current.innerHTML = "";
      }
    };
  }, [id]);

  if (!id) {
    return (
      <div className="cm-page">
        <div className="cm-wrap">
          <div className="cm-topbar">
            <h1>Character Sheet</h1>
            <Link className="cm-btn" to="/">
              Back to New Character Manager
            </Link>
          </div>
          <div className="cm-error">Missing character id.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="cm-page">
      <div className="cm-wrap cm-sheet-wrap">
        <div className="cm-topbar">
          <h1>Character Sheet</h1>
          <Link className="cm-btn" to="/">
            Back to New Character Manager
          </Link>
          <a className="cm-btn" href={`/character_edit_0_3_5.html?id=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">
            Open 0.3.5 Sheet Directly
          </a>
        </div>
        {loading && <div className="cm-muted">Loading NoE 0.3.5 sheet...</div>}
        {error && <div className="cm-error">{error}</div>}
        <div ref={hostRef} />
      </div>
    </div>
  );
}

export default CharacterEditPage;
