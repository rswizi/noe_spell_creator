import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { createItemWeapon, fetchItemWeapons, fetchMe, importItemWeapons } from "../api";

const POSITIVE_TRAITS = [
  "Accurate",
  "Defensive",
  "Concealable",
  "Reach",
  "Chain/Cord",
  "Free Hand",
  "Heavy",
  "Shooting (X)",
  "Melee Shot",
  "Dual-Damage",
  "Versatile",
  "Throwable",
];

const NEGATIVE_TRAITS = ["Ammo", "Reload (X)", "Solo-Damage"];

const TRAIT_SCORE = Object.fromEntries([
  ...POSITIVE_TRAITS.map((trait) => [trait, 1]),
  ...NEGATIVE_TRAITS.map((trait) => [trait, -1]),
]);

const DEFAULT_FORM = {
  name: "",
  hands: 1,
  preferred_damage_type: "Rending",
  characteristic: "AGI",
  skill_used: "Technicity",
  bonus_damage_from_trait_sacrifice: false,
  traits: [],
  shooting_x: 1,
  reload_x: 1,
  examples: "",
};

const DEFAULT_SKILL_BY_CHARACTERISTIC = {
  AGI: "Technicity",
  BOD: "Brutality",
  DEX: "Accuracy",
};

function normalizeRole(role) {
  return String(role || "").toLowerCase();
}

function isPrivilegedRole(role) {
  return ["admin", "moderator", "mod"].includes(normalizeRole(role));
}

function requiredTraitNet(hands, bonusDamageFromTraitSacrifice) {
  const base = Number(hands) === 2 ? 3 : 2;
  return bonusDamageFromTraitSacrifice ? base - 1 : base;
}

function computeTraitNet(traits) {
  return (traits || []).reduce((total, trait) => {
    const key = String(trait || "").trim().toLowerCase();
    if (key.startsWith("shooting")) return total + 1;
    if (key.startsWith("reload")) return total - 1;
    return total + (TRAIT_SCORE[trait] || 0);
  }, 0);
}

function toPlainText(html) {
  if (!html) return "";
  const holder = document.createElement("div");
  holder.innerHTML = String(html);
  return String(holder.textContent || holder.innerText || "").trim();
}

function normalizeTraitFromParser(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return null;
  if (raw.startsWith("shooting")) {
    const m = raw.match(/\(\s*(\d+)\s*\)/);
    return m ? `Shooting (${m[1]})` : "Shooting (X)";
  }
  if (raw.startsWith("reload")) {
    const m = raw.match(/\(\s*(\d+)\s*\)/);
    return m ? `Reload (${m[1]})` : "Reload (X)";
  }
  if (raw === "solo damage" || raw === "solo-damage") return "Solo-Damage";
  if (raw === "chain" || raw === "chain cord" || raw === "chain/cord") return "Chain/Cord";
  if (raw === "freehand" || raw === "free hand") return "Free Hand";
  const allTraits = [...POSITIVE_TRAITS, ...NEGATIVE_TRAITS];
  return allTraits.find((trait) => trait.toLowerCase() === raw) || null;
}

function splitHeaderLine(value) {
  const line = String(value || "").trim();
  const match = line.match(/^(.+?)\s*\((1|2)\s*Hand(?:s)?\s*\/\s*([^)]+)\)\s*$/i);
  if (!match) return null;
  return {
    name: String(match[1] || "").trim(),
    hands: Number(match[2]),
    preferred_damage_type: String(match[3] || "").trim() || "Rending",
  };
}

function parseWeaponsFromRichText(html) {
  const root = document.createElement("div");
  root.innerHTML = String(html || "");

  const blocks = [];
  root.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = String(node.textContent || "").trim();
      if (text) {
        blocks.push({
          text,
          html: `<p>${text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]))}</p>`,
        });
      }
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const text = String(node.textContent || "").trim();
      if (!text) return;
      blocks.push({ text, html: node.outerHTML });
    }
  });

  const sections = [];
  let current = null;
  blocks.forEach((block) => {
    const header = splitHeaderLine(block.text);
    if (header) {
      if (current) sections.push(current);
      current = { header, lines: [] };
      return;
    }
    if (current) {
      current.lines.push(block);
    }
  });
  if (current) sections.push(current);

  const weapons = [];
  const errors = [];

  sections.forEach((section, idx) => {
    const labels = section.lines.map((line) => String(line.text || ""));
    const traitIdx = labels.findIndex((line) => /^traits\s*:/i.test(line));
    const damageIdx = labels.findIndex((line) => /^damage\s*:/i.test(line));
    const examplesIdx = labels.findIndex((line) => /^examples?\s*:/i.test(line));
    const firstMetaIdx = [traitIdx, damageIdx, examplesIdx].filter((index) => index >= 0).sort((a, b) => a - b)[0];
    const descriptionBlocks = firstMetaIdx === undefined ? section.lines : section.lines.slice(0, firstMetaIdx);

    const traitsLine = traitIdx >= 0 ? labels[traitIdx].replace(/^traits\s*:/i, "").trim() : "";
    const damageLine = damageIdx >= 0 ? labels[damageIdx].replace(/^damage\s*:/i, "").trim() : "";
    const examplesLine = examplesIdx >= 0 ? labels[examplesIdx].replace(/^examples?\s*:/i, "").trim() : "";

    const parsedTraits = traitsLine
      .split(",")
      .map((entry) => normalizeTraitFromParser(entry))
      .filter(Boolean);
    const uniqueTraits = Array.from(new Set(parsedTraits));
    const characteristicMatch = damageLine.match(/\b(AGI|BOD|DEX)\b/i);
    const characteristic = characteristicMatch ? characteristicMatch[1].toUpperCase() : "AGI";
    const skill_used = DEFAULT_SKILL_BY_CHARACTERISTIC[characteristic] || "Technicity";
    const examples = examplesLine
      .split(",")
      .map((entry) => String(entry || "").trim())
      .filter(Boolean);

    const weapon = {
      name: section.header.name,
      hands: section.header.hands,
      preferred_damage_type: section.header.preferred_damage_type,
      characteristic,
      skill_used,
      traits: uniqueTraits,
      bonus_damage_from_trait_sacrifice: false,
      description_html: descriptionBlocks.map((line) => line.html).join(""),
      examples,
    };

    const expected = requiredTraitNet(weapon.hands, false);
    const net = computeTraitNet(weapon.traits);
    if (!weapon.name) {
      errors.push(`Weapon #${idx + 1}: missing name.`);
      return;
    }
    if (!weapon.traits.length) {
      errors.push(`Weapon #${idx + 1} (${weapon.name}): no traits parsed from "Traits:".`);
      return;
    }
    if (weapon.traits.some((trait) => trait === "Shooting (X)")) {
      errors.push(`Weapon #${idx + 1} (${weapon.name}): Shooting trait must include a numeric value, e.g. Shooting (7).`);
      return;
    }
    if (weapon.traits.some((trait) => trait === "Reload (X)")) {
      errors.push(`Weapon #${idx + 1} (${weapon.name}): Reload trait must include a numeric value, e.g. Reload (3).`);
      return;
    }
    if (net !== expected) {
      errors.push(
        `Weapon #${idx + 1} (${weapon.name}): trait net is ${net}, expected ${expected} for ${weapon.hands}-hand weapon.`
      );
      return;
    }
    weapons.push(weapon);
  });

  if (!sections.length) {
    errors.push("No weapon blocks found. Expected lines like: Name (1 Hand/Rending).");
  }

  return { weapons, errors };
}

function ManagerTopbar({ title, meLabel }) {
  return (
    <div className="cm-topbar">
      <h1>{title}</h1>
      <div className="cm-right cm-row">
        <a className="cm-btn" href="/character-manager">
          Character Manager
        </a>
        <a className="cm-btn" href="/economy-manager">
          Economy Manager
        </a>
        <span className="cm-muted">{meLabel}</span>
      </div>
    </div>
  );
}

function ItemManagerHome({ meLabel }) {
  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <ManagerTopbar title="Item Manager (0.3.5)" meLabel={meLabel} />
        <div className="cm-grid">
          <Link className="cm-card" to="/weapon-manager">
            <div className="cm-meta">
              <strong>Weapon Manager</strong>
              <span className="cm-muted">Create, browse, and import 0.3.5 weapons.</span>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}

function WeaponManagerHome({ meLabel }) {
  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <ManagerTopbar title="Weapon Manager (0.3.5)" meLabel={meLabel} />
        <div className="cm-row" style={{ marginBottom: 14 }}>
          <Link className="cm-btn" to="/">
            Back to Item Manager
          </Link>
        </div>
        <div className="cm-grid">
          <Link className="cm-card" to="/weapon-manager/create-weapon">
            <div className="cm-meta">
              <strong>Create Weapon</strong>
              <span className="cm-muted">Create custom weapons with 0.3.5 trait balancing rules.</span>
            </div>
          </Link>
          <Link className="cm-card" to="/weapon-manager/browse-weapon">
            <div className="cm-meta">
              <strong>Browse Weapons</strong>
              <span className="cm-muted">Browse general weapons and your own created weapons.</span>
            </div>
          </Link>
          <Link className="cm-card" to="/weapon-manager/import-weapon">
            <div className="cm-meta">
              <strong>Import Weapon</strong>
              <span className="cm-muted">Paste rich text blocks and import multiple weapons to general database.</span>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}

function CreateWeaponPage({ meLabel }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [descriptionHtml, setDescriptionHtml] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const descRef = useRef(null);

  const net = computeTraitNet(form.traits);
  const expected = requiredTraitNet(form.hands, form.bonus_damage_from_trait_sacrifice);
  const balanceOk = net === expected;
  const damagePreview = `2d6 + Lvl + ${form.characteristic}${form.bonus_damage_from_trait_sacrifice ? " + 2" : ""}`;

  function updateCharacteristic(nextCharacteristic) {
    const characteristic = String(nextCharacteristic || "AGI").toUpperCase();
    setForm((prev) => ({
      ...prev,
      characteristic,
      skill_used: DEFAULT_SKILL_BY_CHARACTERISTIC[characteristic] || prev.skill_used,
    }));
  }

  function toggleTrait(trait) {
    setForm((prev) => {
      const exists = prev.traits.includes(trait);
      return {
        ...prev,
        traits: exists ? prev.traits.filter((entry) => entry !== trait) : [...prev.traits, trait],
      };
    });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setMessage("");

    if (!form.name.trim()) {
      setError("Weapon name is required.");
      return;
    }
    if (!balanceOk) {
      setError(`Trait net must be exactly ${expected}. Current net: ${net}.`);
      return;
    }
    if (!form.traits.length) {
      setError("Select at least one trait.");
      return;
    }
    if (form.traits.includes("Shooting (X)") && (!Number.isFinite(Number(form.shooting_x)) || Number(form.shooting_x) <= 0)) {
      setError("Shooting (X) requires X > 0.");
      return;
    }
    if (form.traits.includes("Reload (X)") && (!Number.isFinite(Number(form.reload_x)) || Number(form.reload_x) <= 0)) {
      setError("Reload (X) requires X > 0.");
      return;
    }

    const payloadTraits = form.traits.map((trait) => {
      if (trait === "Shooting (X)") return `Shooting (${Math.max(1, Math.floor(Number(form.shooting_x) || 1))})`;
      if (trait === "Reload (X)") return `Reload (${Math.max(1, Math.floor(Number(form.reload_x) || 1))})`;
      return trait;
    });

    setBusy(true);
    try {
      await createItemWeapon({
        ...form,
        traits: payloadTraits,
        shooting_range: form.traits.includes("Shooting (X)") ? Math.max(1, Math.floor(Number(form.shooting_x) || 1)) : 0,
        magazine_size: form.traits.includes("Reload (X)") ? Math.max(1, Math.floor(Number(form.reload_x) || 1)) : 0,
        description_html: descriptionHtml,
        examples: form.examples
          .split(",")
          .map((entry) => String(entry || "").trim())
          .filter(Boolean),
      });
      setMessage("Weapon created.");
      setForm(DEFAULT_FORM);
      setDescriptionHtml("");
      if (descRef.current) descRef.current.innerHTML = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create weapon.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <ManagerTopbar title="Create Weapon (0.3.5)" meLabel={meLabel} />
        <div className="cm-row" style={{ marginBottom: 14 }}>
          <Link className="cm-btn" to="/weapon-manager">
            Back to Weapon Manager
          </Link>
          <span className="cm-badge">Damage: {damagePreview}</span>
          <span className={`cm-badge ${balanceOk ? "" : "cm-danger"}`}>
            Trait net: {net} / required {expected}
          </span>
        </div>

        <form className="cm-grid-2" onSubmit={submit}>
          <div className="cm-panel">
            <h2>Core</h2>
            <label>
              Weapon Name
              <input value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} />
            </label>
            <label>
              Hands
              <select
                value={form.hands}
                onChange={(event) => setForm((prev) => ({ ...prev, hands: Number(event.target.value) || 1 }))}
              >
                <option value={1}>1 Hand</option>
                <option value={2}>2 Hands</option>
              </select>
            </label>
            <label>
              Preferred Damage Type
              <input
                value={form.preferred_damage_type}
                onChange={(event) => setForm((prev) => ({ ...prev, preferred_damage_type: event.target.value }))}
              />
            </label>
            <label>
              Characteristic
              <select value={form.characteristic} onChange={(event) => updateCharacteristic(event.target.value)}>
                <option value="AGI">AGI</option>
                <option value="BOD">BOD</option>
                <option value="DEX">DEX</option>
              </select>
            </label>
            <label>
              Skill Used
              <select
                value={form.skill_used}
                onChange={(event) => setForm((prev) => ({ ...prev, skill_used: event.target.value }))}
              >
                <option value="Technicity">Technicity</option>
                <option value="Brutality">Brutality</option>
                <option value="Accuracy">Accuracy</option>
              </select>
            </label>
            <label className="cm-checkline">
              <input
                type="checkbox"
                checked={form.bonus_damage_from_trait_sacrifice}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, bonus_damage_from_trait_sacrifice: event.target.checked }))
                }
              />
              Sacrifice 1 trait slot to add +2 damage
            </label>
            <label>
              Examples (comma-separated)
              <input
                value={form.examples}
                onChange={(event) => setForm((prev) => ({ ...prev, examples: event.target.value }))}
                placeholder="Rapier, Chokuto"
              />
            </label>
          </div>

          <div className="cm-panel">
            <h2>Traits (+/-)</h2>
            <div className="cm-stack">
              <strong>Positive (+1 each)</strong>
              <div className="cm-row">
                {POSITIVE_TRAITS.map((trait) => (
                  <label key={trait} className="cm-checkline">
                    <input type="checkbox" checked={form.traits.includes(trait)} onChange={() => toggleTrait(trait)} />
                    {trait}
                  </label>
                ))}
              </div>
              {form.traits.includes("Shooting (X)") && (
                <label>
                  Shooting Range (X)
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={form.shooting_x}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, shooting_x: Number(event.target.value) || 1 }))
                    }
                  />
                </label>
              )}
            </div>
            <div className="cm-stack">
              <strong>Negative (-1 each)</strong>
              <div className="cm-row">
                {NEGATIVE_TRAITS.map((trait) => (
                  <label key={trait} className="cm-checkline">
                    <input type="checkbox" checked={form.traits.includes(trait)} onChange={() => toggleTrait(trait)} />
                    {trait}
                  </label>
                ))}
              </div>
              {form.traits.includes("Reload (X)") && (
                <label>
                  Reload Capacity (X)
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={form.reload_x}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, reload_x: Number(event.target.value) || 1 }))
                    }
                  />
                </label>
              )}
            </div>
          </div>

          <div className="cm-panel cm-panel-wide">
            <h2>Description (Rich Text)</h2>
            <div
              ref={descRef}
              className="cm-rich-editor"
              contentEditable
              suppressContentEditableWarning
              onInput={(event) => setDescriptionHtml(event.currentTarget.innerHTML)}
              data-placeholder="Write weapon description..."
            />
          </div>

          <div className="cm-panel cm-panel-wide">
            <div className="cm-row">
              <button className="cm-btn cm-primary" type="submit" disabled={busy}>
                {busy ? "Creating..." : "Create Weapon"}
              </button>
              {message && <span className="cm-muted">{message}</span>}
              {error && <span className="cm-error">{error}</span>}
            </div>
            <div className="cm-muted">
              Rule check: one-handed net trait score must be 2, two-handed must be 3. If bonus damage is enabled, required
              net is reduced by 1.
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

function BrowseWeaponPage({ meLabel }) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState([]);

  useEffect(() => {
    let active = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      setError("");
      try {
        const res = await fetchItemWeapons({ q: query, scope, limit: 300 });
        if (!active) return;
        setRows(res.weapons || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load weapons.");
      } finally {
        if (active) setBusy(false);
      }
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, scope]);

  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <ManagerTopbar title="Browse Weapons (0.3.5)" meLabel={meLabel} />
        <div className="cm-row" style={{ marginBottom: 14 }}>
          <Link className="cm-btn" to="/weapon-manager">
            Back to Weapon Manager
          </Link>
          <label className="cm-inline">
            Name
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter by name" />
          </label>
          <label className="cm-inline">
            Scope
            <select value={scope} onChange={(event) => setScope(event.target.value)}>
              <option value="all">General + My weapons</option>
              <option value="mine">My weapons only</option>
            </select>
          </label>
        </div>
        {error && <div className="cm-error">{error}</div>}
        {busy ? (
          <div className="cm-muted">Loading weapons...</div>
        ) : (
          <div className="cm-list">
            {!rows.length && <div className="cm-muted">No weapons found.</div>}
            {rows.map((row) => (
              <div key={row.id} className="cm-list-item cm-list-row">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="cm-inline">
                    <strong>{row.name}</strong>
                    <span className="cm-badge">{row.hands}H</span>
                    <span className="cm-badge">{row.preferred_damage_type}</span>
                    <span className="cm-badge">{row.skill_used}</span>
                    <span className="cm-badge">{row.damage_formula}</span>
                    {!!Number(row.range) && <span className="cm-badge">Range {Number(row.range)}</span>}
                    {!!Number(row.magazine_size) && <span className="cm-badge">Magazine {Number(row.magazine_size)}</span>}
                    <span className="cm-badge">{row.visibility === "general" ? "General DB" : "My Weapon"}</span>
                  </div>
                  <div className="cm-muted" style={{ marginTop: 4 }}>
                    Traits: {(row.traits || []).join(", ")}
                  </div>
                  {!!(row.examples || []).length && (
                    <div className="cm-muted" style={{ marginTop: 4 }}>
                      Examples: {(row.examples || []).join(", ")}
                    </div>
                  )}
                  {!!row.description_html && (
                    <div className="cm-rich-preview" dangerouslySetInnerHTML={{ __html: row.description_html }} />
                  )}
                  {!row.description_html && row.description_text && (
                    <div className="cm-muted" style={{ marginTop: 4 }}>
                      {toPlainText(row.description_text)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ImportWeaponPage({ meLabel, isPrivileged }) {
  const editorRef = useRef(null);
  const [editorHtml, setEditorHtml] = useState("");
  const [replaceDuplicates, setReplaceDuplicates] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [lastResult, setLastResult] = useState(null);

  const parsed = useMemo(() => parseWeaponsFromRichText(editorHtml), [editorHtml]);

  async function onImport(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLastResult(null);

    if (!isPrivileged) {
      setError("Only moderators/admins can import into the general database.");
      return;
    }
    if (parsed.errors.length) {
      setError("Fix parser errors before importing.");
      return;
    }
    if (!parsed.weapons.length) {
      setError("No weapons parsed.");
      return;
    }

    setBusy(true);
    try {
      const res = await importItemWeapons({
        weapons: parsed.weapons,
        replace_duplicates: replaceDuplicates,
      });
      setLastResult(res);
      setMessage(`Imported ${res.created?.length || 0} weapon(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <ManagerTopbar title="Import Weapon Parser (0.3.5)" meLabel={meLabel} />
        <div className="cm-row" style={{ marginBottom: 14 }}>
          <Link className="cm-btn" to="/weapon-manager">
            Back to Weapon Manager
          </Link>
          <label className="cm-checkline">
            <input
              type="checkbox"
              checked={replaceDuplicates}
              onChange={(event) => setReplaceDuplicates(event.target.checked)}
            />
            Replace duplicate names in general database
          </label>
        </div>

        <div className="cm-grid-2">
          <div className="cm-panel">
            <h2>Rich Text Parser Input</h2>
            <div
              ref={editorRef}
              className="cm-rich-editor cm-rich-editor-lg"
              contentEditable
              suppressContentEditableWarning
              onInput={(event) => setEditorHtml(event.currentTarget.innerHTML)}
              data-placeholder={`Paste one or more blocks:\n\nDuel Blade (1 Hand/Rending)\nDescription...\nTraits: Accurate, Defensive\nDamage: [2d6 + Lvl + AGI]\nExamples: Rapier, Chokuto`}
            />
            <div className="cm-row">
              <button className="cm-btn cm-primary" onClick={onImport} type="button" disabled={busy}>
                {busy ? "Importing..." : "Import to General Database"}
              </button>
              {message && <span className="cm-muted">{message}</span>}
              {error && <span className="cm-error">{error}</span>}
            </div>
            {!isPrivileged && (
              <div className="cm-error">Current account is not moderator/admin. Import is blocked for this role.</div>
            )}
          </div>

          <div className="cm-panel">
            <h2>Parser Preview</h2>
            {!!parsed.errors.length && (
              <div className="cm-error">
                {parsed.errors.map((entry) => (
                  <div key={entry}>{entry}</div>
                ))}
              </div>
            )}
            {!parsed.errors.length && !parsed.weapons.length && <div className="cm-muted">No parsed weapons yet.</div>}
            <div className="cm-list">
              {parsed.weapons.map((weapon, index) => (
                <div key={`${weapon.name}-${index}`} className="cm-list-item cm-list-row">
                  <div>
                    <strong>{weapon.name}</strong>
                    <div className="cm-muted">
                      {weapon.hands}H | {weapon.preferred_damage_type} | {weapon.skill_used} | 2d6 + Lvl + {weapon.characteristic}
                    </div>
                    <div className="cm-muted">
                      Auto range/mag from traits:{" "}
                      {(weapon.traits || []).some((entry) => String(entry).toLowerCase().startsWith("shooting"))
                        ? (weapon.traits || []).find((entry) => String(entry).toLowerCase().startsWith("shooting"))
                        : "No shooting trait"}{" "}
                      |{" "}
                      {(weapon.traits || []).some((entry) => String(entry).toLowerCase().startsWith("reload"))
                        ? (weapon.traits || []).find((entry) => String(entry).toLowerCase().startsWith("reload"))
                        : "No reload trait"}
                    </div>
                    <div className="cm-muted">Traits: {(weapon.traits || []).join(", ")}</div>
                    {!!weapon.examples?.length && <div className="cm-muted">Examples: {weapon.examples.join(", ")}</div>}
                  </div>
                </div>
              ))}
            </div>
            {!!lastResult && (
              <div className="cm-stack">
                <strong>Last Import Result</strong>
                <div className="cm-muted">Created: {lastResult.created?.length || 0}</div>
                <div className="cm-muted">Skipped: {lastResult.skipped?.length || 0}</div>
                <div className="cm-muted">Errors: {lastResult.errors?.length || 0}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ItemManagerPage() {
  const [me, setMe] = useState({
    label: "Checking login...",
    role: "",
    isPrivileged: false,
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const meData = await fetchMe();
        if (!active) return;
        const role = meData.role || "";
        setMe({
          label: `${meData.username || "Unknown"} (${role || "user"})`,
          role,
          isPrivileged: isPrivilegedRole(role),
        });
      } catch (_) {
        if (!active) return;
        setMe({
          label: "Not authenticated",
          role: "",
          isPrivileged: false,
        });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <Routes>
      <Route path="/" element={<ItemManagerHome meLabel={me.label} />} />
      <Route path="/weapon-manager" element={<WeaponManagerHome meLabel={me.label} />} />
      <Route path="/weapon-manager/create-weapon" element={<CreateWeaponPage meLabel={me.label} />} />
      <Route path="/weapon-manager/browse-weapon" element={<BrowseWeaponPage meLabel={me.label} />} />
      <Route
        path="/weapon-manager/import-weapon"
        element={<ImportWeaponPage meLabel={me.label} isPrivileged={me.isPrivileged} />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default ItemManagerPage;
