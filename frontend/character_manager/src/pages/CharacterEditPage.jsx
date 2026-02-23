import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  deleteCharacter,
  fetchArchetypes,
  fetchCharacter,
  fetchInventories,
  fetchMySpellLists,
  updateCharacter,
  uploadCharacterAvatar,
} from "../api";

const DEFAULT_INTENSITIES = ["Fire", "Lightning", "Water", "Earth", "Wind", "Sun", "Moon", "Ki"];

const toInt = (value, fallback = 0) => {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clone = (value) => JSON.parse(JSON.stringify(value ?? {}));

const normalizeStats = (stats) => {
  const base = clone(stats || {});
  if (!base.intensities || typeof base.intensities !== "object" || Array.isArray(base.intensities)) {
    base.intensities = {};
  }
  return base;
};

function CharacterEditPage() {
  const { id } = useParams();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [tab, setTab] = useState("overview");
  const [avatarTs, setAvatarTs] = useState(Date.now());

  const [archetypes, setArchetypes] = useState([]);
  const [inventories, setInventories] = useState([]);
  const [spellLists, setSpellLists] = useState([]);

  const [form, setForm] = useState({
    name: "",
    public: false,
    level: 1,
    xp: 0,
    archetype_id: "",
    inventory_id: "",
    spell_list_id: "",
    stats: normalizeStats({}),
  });
  const [rawStats, setRawStats] = useState("{}");
  const [skillDraftByChar, setSkillDraftByChar] = useState({});

  const missingId = !id;

  useEffect(() => {
    if (!id) return;
    let active = true;
    const run = async () => {
      setLoading(true);
      setError("");
      setStatus("");
      try {
        const [charRes, archRes, invRes, spellRes] = await Promise.all([
          fetchCharacter(id),
          fetchArchetypes().catch(() => ({ archetypes: [] })),
          fetchInventories().catch(() => ({ inventories: [] })),
          fetchMySpellLists().catch(() => ({ lists: [] })),
        ]);
        if (!active) return;

        const character = charRes.character || {};
        const level = toInt(character.level ?? character?.stats?.level, 1);
        const normalizedStats = normalizeStats(character.stats || {});

        setForm({
          name: character.name || "",
          public: Boolean(character.public),
          level,
          xp: Math.max(0, toInt(character.xp, 0)),
          archetype_id: character.archetype_id || "",
          inventory_id: character.inventory_id || "",
          spell_list_id: character.spell_list_id || "",
          stats: normalizedStats,
        });
        setRawStats(JSON.stringify(normalizedStats, null, 2));
        setArchetypes(archRes.archetypes || []);
        setInventories(invRes.inventories || []);
        setSpellLists(spellRes.lists || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Unable to load character.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [id]);

  useEffect(() => {
    setRawStats(JSON.stringify(form.stats || {}, null, 2));
  }, [form.stats]);

  const characteristicEntries = useMemo(() => {
    const entries = Object.entries(form.stats || {}).filter(([, value]) => {
      if (!value || typeof value !== "object" || Array.isArray(value)) return false;
      return Object.prototype.hasOwnProperty.call(value, "invest") || Object.prototype.hasOwnProperty.call(value, "skills");
    });
    entries.sort((a, b) => a[0].localeCompare(b[0]));
    return entries;
  }, [form.stats]);

  const setFormField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateStatInvest = (charKey, value) => {
    setForm((prev) => {
      const next = clone(prev.stats);
      if (!next[charKey] || typeof next[charKey] !== "object") next[charKey] = {};
      next[charKey].invest = toInt(value, 0);
      if (!next[charKey].skills || typeof next[charKey].skills !== "object") next[charKey].skills = {};
      return { ...prev, stats: next };
    });
  };

  const updateSkillInvest = (charKey, skillKey, value) => {
    setForm((prev) => {
      const next = clone(prev.stats);
      if (!next[charKey] || typeof next[charKey] !== "object") next[charKey] = {};
      if (!next[charKey].skills || typeof next[charKey].skills !== "object") next[charKey].skills = {};
      next[charKey].skills[skillKey] = toInt(value, 0);
      return { ...prev, stats: next };
    });
  };

  const removeSkill = (charKey, skillKey) => {
    setForm((prev) => {
      const next = clone(prev.stats);
      if (!next[charKey]?.skills || typeof next[charKey].skills !== "object") return prev;
      delete next[charKey].skills[skillKey];
      return { ...prev, stats: next };
    });
  };

  const addSkill = (charKey) => {
    const skillName = (skillDraftByChar[charKey] || "").trim();
    if (!skillName) return;
    setForm((prev) => {
      const next = clone(prev.stats);
      if (!next[charKey] || typeof next[charKey] !== "object") next[charKey] = {};
      if (!next[charKey].skills || typeof next[charKey].skills !== "object") next[charKey].skills = {};
      if (!Object.prototype.hasOwnProperty.call(next[charKey].skills, skillName)) {
        next[charKey].skills[skillName] = 0;
      }
      return { ...prev, stats: next };
    });
    setSkillDraftByChar((prev) => ({ ...prev, [charKey]: "" }));
  };

  const updateIntensity = (nature, value) => {
    setForm((prev) => {
      const next = clone(prev.stats);
      if (!next.intensities || typeof next.intensities !== "object") next.intensities = {};
      next.intensities[nature] = toInt(value, 0);
      return { ...prev, stats: next };
    });
  };

  const applyRawStats = () => {
    try {
      const parsed = JSON.parse(rawStats || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Stats JSON must be an object.");
      }
      setForm((prev) => ({ ...prev, stats: normalizeStats(parsed) }));
      setStatus("Raw stats applied.");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid JSON");
    }
  };

  const onSave = async () => {
    if (!id) return;
    setSaving(true);
    setError("");
    setStatus("");
    try {
      const payload = {
        name: (form.name || "").trim() || "New Character",
        public: Boolean(form.public),
        level: Math.max(1, toInt(form.level, 1)),
        xp: Math.max(0, toInt(form.xp, 0)),
        archetype_id: form.archetype_id || "",
        inventory_id: form.inventory_id || "",
        spell_list_id: form.spell_list_id || "",
        stats: {
          ...clone(form.stats),
          level: Math.max(1, toInt(form.level, 1)),
        },
      };
      await updateCharacter(id, payload);
      setStatus("Character saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!id) return;
    if (!window.confirm("Delete this character? This cannot be undone.")) return;
    setError("");
    setStatus("");
    try {
      await deleteCharacter(id);
      window.location.href = "/character-manager";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    }
  };

  const onAvatarPicked = async (event) => {
    if (!id) return;
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingAvatar(true);
    setError("");
    setStatus("");
    try {
      await uploadCharacterAvatar(id, file);
      setAvatarTs(Date.now());
      setStatus("Avatar updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Avatar upload failed.");
    } finally {
      setUploadingAvatar(false);
      event.target.value = "";
    }
  };

  if (missingId) {
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

  const legacyHref = `/character_edit.html?id=${encodeURIComponent(id)}`;

  return (
    <div className="cm-page">
      <div className="cm-wrap cm-sheet-wrap">
        <div className="cm-topbar">
          <h1>Character Sheet</h1>
          <Link className="cm-btn" to="/">
            Back to New Character Manager
          </Link>
          <a className="cm-btn" href={legacyHref} target="_blank" rel="noreferrer">
            Open Legacy Sheet
          </a>
          <button type="button" className="cm-btn cm-primary cm-right" onClick={onSave} disabled={saving || loading}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button type="button" className="cm-btn" onClick={onDelete} disabled={saving || loading}>
            Delete
          </button>
        </div>

        {error && <div className="cm-error">{error}</div>}
        {status && <div className="cm-muted">{status}</div>}
        {loading && <div className="cm-muted">Loading character...</div>}

        {!loading && (
          <>
            <div className="cm-tabs">
              <button className={`cm-tab ${tab === "overview" ? "active" : ""}`} onClick={() => setTab("overview")} type="button">
                Overview
              </button>
              <button className={`cm-tab ${tab === "stats" ? "active" : ""}`} onClick={() => setTab("stats")} type="button">
                Statistics
              </button>
              <button className={`cm-tab ${tab === "advanced" ? "active" : ""}`} onClick={() => setTab("advanced")} type="button">
                Advanced
              </button>
            </div>

            {tab === "overview" && (
              <div className="cm-grid-2">
                <section className="cm-panel">
                  <h2>General</h2>
                  <label>
                    Name
                    <input value={form.name} onChange={(event) => setFormField("name", event.target.value)} />
                  </label>
                  <label>
                    Level
                    <input
                      type="number"
                      min={1}
                      value={form.level}
                      onChange={(event) => setFormField("level", event.target.value)}
                    />
                  </label>
                  <label>
                    XP
                    <input
                      type="number"
                      min={0}
                      value={form.xp}
                      onChange={(event) => setFormField("xp", event.target.value)}
                    />
                  </label>
                  <label className="cm-checkline">
                    <input
                      type="checkbox"
                      checked={Boolean(form.public)}
                      onChange={(event) => setFormField("public", event.target.checked)}
                    />
                    Public
                  </label>
                </section>

                <section className="cm-panel">
                  <h2>Links</h2>
                  <label>
                    Archetype
                    <select
                      value={form.archetype_id}
                      onChange={(event) => setFormField("archetype_id", event.target.value)}
                    >
                      <option value="">-- None --</option>
                      {archetypes.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name || item.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Inventory
                    <select
                      value={form.inventory_id}
                      onChange={(event) => setFormField("inventory_id", event.target.value)}
                    >
                      <option value="">-- None --</option>
                      {inventories.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name || item.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Spell List
                    <select
                      value={form.spell_list_id}
                      onChange={(event) => setFormField("spell_list_id", event.target.value)}
                    >
                      <option value="">-- None --</option>
                      {spellLists.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name || item.id}
                        </option>
                      ))}
                    </select>
                  </label>
                </section>

                <section className="cm-panel cm-panel-wide">
                  <h2>Avatar</h2>
                  <div className="cm-avatar-row">
                    <img
                      className="cm-big-avatar"
                      src={`/characters/${encodeURIComponent(id)}/avatar?ts=${avatarTs}`}
                      alt="Character avatar"
                      onError={(event) => {
                        event.currentTarget.style.opacity = "0.4";
                      }}
                    />
                    <div className="cm-avatar-controls">
                      <input type="file" accept="image/png,image/jpeg,image/jpg" onChange={onAvatarPicked} />
                      <div className="cm-muted">{uploadingAvatar ? "Uploading..." : "PNG/JPEG up to 2MB"}</div>
                    </div>
                  </div>
                </section>
              </div>
            )}

            {tab === "stats" && (
              <div className="cm-stat-layout">
                <section className="cm-panel">
                  <h2>Intensities</h2>
                  <div className="cm-intensity-grid">
                    {DEFAULT_INTENSITIES.map((nature) => (
                      <label key={nature}>
                        {nature}
                        <input
                          type="number"
                          value={toInt(form.stats?.intensities?.[nature], 0)}
                          onChange={(event) => updateIntensity(nature, event.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                </section>

                {characteristicEntries.map(([charKey, statObj]) => {
                  const skills = Object.entries(statObj.skills || {}).sort((a, b) => a[0].localeCompare(b[0]));
                  return (
                    <section key={charKey} className="cm-panel">
                      <h2>{charKey}</h2>
                      <label>
                        Invest
                        <input
                          type="number"
                          value={toInt(statObj.invest, 0)}
                          onChange={(event) => updateStatInvest(charKey, event.target.value)}
                        />
                      </label>
                      <div className="cm-skill-list">
                        {skills.map(([skillKey, skillVal]) => (
                          <div className="cm-skill-row" key={`${charKey}-${skillKey}`}>
                            <span>{skillKey}</span>
                            <input
                              type="number"
                              value={toInt(skillVal, 0)}
                              onChange={(event) => updateSkillInvest(charKey, skillKey, event.target.value)}
                            />
                            <button type="button" className="cm-btn" onClick={() => removeSkill(charKey, skillKey)}>
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                      <div className="cm-add-skill">
                        <input
                          placeholder="New skill key"
                          value={skillDraftByChar[charKey] || ""}
                          onChange={(event) => setSkillDraftByChar((prev) => ({ ...prev, [charKey]: event.target.value }))}
                        />
                        <button type="button" className="cm-btn" onClick={() => addSkill(charKey)}>
                          Add Skill
                        </button>
                      </div>
                    </section>
                  );
                })}
              </div>
            )}

            {tab === "advanced" && (
              <section className="cm-panel">
                <h2>Raw Stats JSON</h2>
                <textarea
                  className="cm-json"
                  value={rawStats}
                  onChange={(event) => setRawStats(event.target.value)}
                  spellCheck={false}
                />
                <div className="cm-row">
                  <button type="button" className="cm-btn" onClick={applyRawStats}>
                    Apply JSON
                  </button>
                  <div className="cm-muted">Use this when a field has not yet been ported to UI controls.</div>
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default CharacterEditPage;
