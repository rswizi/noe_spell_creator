import React from "react";
import { Link, useParams } from "react-router-dom";

function CharacterEditPage() {
  const { id } = useParams();

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

  const src = `/character_edit.html?id=${encodeURIComponent(id)}`;
  return (
    <div className="cm-page cm-sheet-page">
      <div className="cm-wrap cm-sheet-wrap">
        <div className="cm-topbar">
          <h1>Character Sheet</h1>
          <Link className="cm-btn" to="/">
            Back to New Character Manager
          </Link>
          <a className="cm-btn" href={src} target="_blank" rel="noreferrer">
            Open Legacy Sheet
          </a>
        </div>
        <div className="cm-iframe-shell">
          <iframe title={`character-${id}`} src={src} className="cm-iframe" />
        </div>
      </div>
    </div>
  );
}

export default CharacterEditPage;
