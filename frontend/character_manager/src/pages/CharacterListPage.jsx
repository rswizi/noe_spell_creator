import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, createCharacter, fetchCharacters, fetchMe } from "../api";

const QUALITY_ORDER = [
  "Adequate",
  "Good",
  "Very Good",
  "Excellent",
  "Legendary",
  "Mythical",
  "Epic",
  "Divine",
  "Unreal",
];

const ARMOR_SLOTS = ["head", "accessory", "arms", "legs", "chest"];
const NATURES = ["Fire", "Lightning", "Water", "Earth", "Wind", "Sun", "Moon", "Ki"];

const FALLBACK_AVATAR =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WUZPi8AAAAASUVORK5CYII=";

function sortByName(list) {
  return [...(list || [])].sort((a, b) =>
    String(a?.name || a?.id || "").localeCompare(String(b?.name || b?.id || ""))
  );
}

function slugifyCharacterName(name) {
  const normalized = String(name || "")
    .trim()
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "");
  const slug = normalized
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
  return slug || "character";
}

function buildCharacterSheetPath(id, name) {
  const cid = String(id || "").trim();
  if (!cid) return "/";
  return `/${encodeURIComponent(cid)}_${slugifyCharacterName(name || cid)}`;
}

function CharacterListPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState({ label: "Checking login...", isAdmin: false });
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  const [quickOpen, setQuickOpen] = useState(false);
  const [quickBusy, setQuickBusy] = useState(false);
  const [quickStatus, setQuickStatus] = useState("");
  const [quickDataLoaded, setQuickDataLoaded] = useState(false);
  const [quickDataError, setQuickDataError] = useState("");
  const [quickData, setQuickData] = useState({
    archetypes: [],
    species: [],
    boons: [],
    weapons: [],
    armorBySlot: {},
  });

  const [quickForm, setQuickForm] = useState({
    name: "",
    level: 1,
    archetype: "",
    species: "",
    boon: "",
    nature: "",
    money: 0,
    armorQuality: "",
    weaponId: "",
    weaponQuality: "",
  });

  const loadCharacters = useCallback(async () => {
    const data = await fetchCharacters();
    setCharacters(data.characters || []);
  }, []);

  const init = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const meData = await fetchMe();
      setMe({
        label: `${meData.username || "Unknown"} (${meData.role || "user"})`,
        isAdmin: String(meData.role || "").toLowerCase() === "admin",
      });
    } catch (err) {
      setMe({ label: "Not logged in", isAdmin: false });
    }
    try {
      await loadCharacters();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load characters.");
    } finally {
      setLoading(false);
    }
  }, [loadCharacters]);

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (event) => {
      if (!menuRef.current?.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [menuOpen]);

  const ensureQuickData = useCallback(async () => {
    if (quickDataLoaded) return;
    setQuickDataError("");
    try {
      const [speciesRes, boonRes, archetypeRes, weaponsRes, equipmentRes] = await Promise.all([
        api("/abilities?source=Specie"),
        api("/abilities?source=Boon"),
        api("/archetypes"),
        api("/catalog/weapons?limit=200"),
        api("/catalog/equipment?limit=300"),
      ]);
      const armorBySlot = {};
      for (const item of equipmentRes.equipment || []) {
        const slot = String(item?.slot || "").trim().toLowerCase();
        if (ARMOR_SLOTS.includes(slot) && !armorBySlot[slot]) {
          armorBySlot[slot] = item;
        }
      }
      setQuickData({
        archetypes: sortByName(archetypeRes.archetypes),
        species: sortByName(speciesRes.abilities),
        boons: sortByName(boonRes.abilities),
        weapons: sortByName(weaponsRes.weapons),
        armorBySlot,
      });
      setQuickDataLoaded(true);
    } catch (err) {
      setQuickDataError(err instanceof Error ? err.message : "Failed to load quick-create data.");
    }
  }, [quickDataLoaded]);

  const openQuickModal = useCallback(async () => {
    setMenuOpen(false);
    setQuickStatus("");
    setQuickDataError("");
    await ensureQuickData();
    setQuickOpen(true);
  }, [ensureQuickData]);

  const onNewNormal = useCallback(async () => {
    setMenuOpen(false);
    const value = window.prompt("Character name?", "") || "";
    const name = value.trim() || "New Character";
    try {
      const res = await createCharacter(name);
      const cid = res.id || res.character?.id;
      if (!cid) throw new Error("Character creation failed.");
      navigate(buildCharacterSheetPath(cid, name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create character.");
    }
  }, [navigate]);

  const weaponLookup = useMemo(() => {
    const map = new Map();
    for (const weapon of quickData.weapons) {
      map.set(weapon.id, weapon);
    }
    return map;
  }, [quickData.weapons]);

  const onQuickCreate = useCallback(
    async (event) => {
      event.preventDefault();
      setQuickBusy(true);
      setQuickStatus("Preparing quick build...");
      try {
        const name = (quickForm.name || "").trim() || "New Character";
        const level = Math.max(1, Math.floor(Number(quickForm.level) || 1));
        const money = Math.max(0, Math.floor(Number(quickForm.money) || 0));
        const armorQuality = quickForm.armorQuality || "";
        const weaponId = quickForm.weaponId || "";
        const weaponQuality = quickForm.weaponQuality || armorQuality || "Adequate";
        const needsInventory = Boolean(money > 0 || armorQuality || weaponId);

        let inventoryId = "";
        if (needsInventory) {
          setQuickStatus("Creating inventory...");
          const invRes = await api("/inventories", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              name: `${name} Inventory`,
              currencies: { Jelly: money },
            }),
          });
          inventoryId = invRes.inventory?.id || "";

          if (inventoryId && armorQuality) {
            for (const slot of ARMOR_SLOTS) {
              const entry = quickData.armorBySlot[slot];
              if (!entry?.id) continue;
              setQuickStatus(`Adding ${entry.name || slot}...`);
              await api(`/inventories/${encodeURIComponent(inventoryId)}/purchase`, {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({
                  kind: "equipment",
                  ref_id: entry.id,
                  quantity: 1,
                  quality: armorQuality,
                  pricing_mode: "take",
                  equipped: true,
                }),
              });
            }
          }

          if (inventoryId && weaponId) {
            const weapon = weaponLookup.get(weaponId);
            setQuickStatus(`Adding ${weapon?.name || "weapon"}...`);
            await api(`/inventories/${encodeURIComponent(inventoryId)}/purchase`, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                kind: "weapon",
                ref_id: weaponId,
                quantity: 1,
                quality: weaponQuality,
                pricing_mode: "take",
                equipped: true,
              }),
            });
          }
        }

        setQuickStatus("Creating character...");
        const created = await api("/characters", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name }),
        });
        const cid = created.id || created.character?.id;
        if (!cid) throw new Error("Character creation failed.");

        const intensities = {};
        if (quickForm.nature) {
          intensities[quickForm.nature] = 1;
        }
        const abilities = [];
        if (quickForm.species) abilities.push(quickForm.species);
        if (quickForm.boon && !abilities.includes(quickForm.boon)) abilities.push(quickForm.boon);

        const updatePayload = {
          name,
          level,
          xp: 0,
          stats: {
            level,
            intensities,
            species_ability_id: quickForm.species || "",
            boon_ability_id: quickForm.boon || "",
          },
          abilities,
          archetype_id: quickForm.archetype || "",
          starting_money: money,
        };

        if (armorQuality || weaponId) {
          const startingGear = {};
          if (armorQuality) {
            startingGear.armor = {
              quality: armorQuality,
              slots: [...ARMOR_SLOTS],
            };
          }
          if (weaponId) {
            startingGear.weapon = {
              ref_id: weaponId,
              quality: weaponQuality,
            };
          }
          updatePayload.starting_gear = startingGear;
        }
        if (inventoryId) {
          updatePayload.inventory_id = inventoryId;
        }

        setQuickStatus("Applying quick-build settings...");
        await api(`/characters/${encodeURIComponent(cid)}`, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(updatePayload),
        });

        setQuickOpen(false);
        setQuickStatus("");
        navigate(buildCharacterSheetPath(cid, name));
      } catch (err) {
        setQuickStatus(`Quick create failed: ${err instanceof Error ? err.message : "Unknown error"}`);
      } finally {
        setQuickBusy(false);
      }
    },
    [navigate, quickData.armorBySlot, quickForm, weaponLookup]
  );

  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <div className="cm-topbar">
          <h1>New Character Manager</h1>
          <a className="cm-btn" href="/portal.html">
            Portal
          </a>
          <span className="cm-muted cm-right">{me.label}</span>
          <a className="cm-btn" href="/characters.html">
            Legacy Character Manager
          </a>
          {me.isAdmin && (
            <a className="cm-btn" href="/character_admin.html">
              All Characters
            </a>
          )}
        </div>

        <div className="cm-actions">
          <div className="cm-menu-wrap" ref={menuRef}>
            <button className="cm-btn cm-primary" onClick={() => setMenuOpen((v) => !v)}>
              + New Character
            </button>
            <div className={`cm-menu ${menuOpen ? "open" : ""}`}>
              <button type="button" onClick={onNewNormal}>
                Normal
              </button>
              <button type="button" className="cm-primary-item" onClick={openQuickModal}>
                Quick Create
              </button>
            </div>
          </div>
          <span className="cm-muted">Click a card to open the character sheet.</span>
        </div>

        {error && <div className="cm-error">{error}</div>}
        {loading && <p className="cm-muted">Loading characters...</p>}
        {!loading && !characters.length && <p className="cm-muted">No characters yet. Create one to begin.</p>}

        <div className="cm-grid">
          {characters.map((character) => (
            <button
              key={character.id}
              className="cm-card"
              onClick={() => navigate(buildCharacterSheetPath(character.id, character.name || character.id))}
              type="button"
            >
              <div className="cm-avatar">
                <img
                  src={`/characters/${encodeURIComponent(character.id)}/avatar?ts=${Date.now()}`}
                  alt={`${character.name || "character"} avatar`}
                  onError={(event) => {
                    event.currentTarget.src = FALLBACK_AVATAR;
                  }}
                />
              </div>
              <div className="cm-meta">
                <strong>{character.name || "(unnamed)"}</strong>
                <div className="cm-muted">ID: {character.id}</div>
                <div className="cm-pill">Owner: {character.owner || "self"}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className={`cm-modal ${quickOpen ? "open" : ""}`} onClick={(event) => event.target === event.currentTarget && setQuickOpen(false)}>
        <div className="cm-modal-panel">
          <h2>Quick Create</h2>
          <p className="cm-muted">Create and preconfigure a character, then jump straight into the full sheet editor.</p>

          <form className="cm-field-grid" onSubmit={onQuickCreate}>
            <label>
              Character Name
              <input
                type="text"
                value={quickForm.name}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="New Character"
              />
            </label>
            <label>
              Level
              <input
                type="number"
                min={1}
                value={quickForm.level}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, level: event.target.value }))}
              />
            </label>
            <label>
              Archetype
              <select
                value={quickForm.archetype}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, archetype: event.target.value }))}
              >
                <option value="">-- Select archetype --</option>
                {quickData.archetypes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name || item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Species
              <select
                value={quickForm.species}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, species: event.target.value }))}
              >
                <option value="">-- Select species --</option>
                {quickData.species.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name || item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Boon
              <select
                value={quickForm.boon}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, boon: event.target.value }))}
              >
                <option value="">-- Select boon --</option>
                {quickData.boons.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name || item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Starting Nature
              <select
                value={quickForm.nature}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, nature: event.target.value }))}
              >
                <option value="">-- None --</option>
                {NATURES.map((nature) => (
                  <option key={nature} value={nature}>
                    {nature}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Starting Money (Jelly)
              <input
                type="number"
                min={0}
                value={quickForm.money}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, money: event.target.value }))}
              />
            </label>
            <label>
              Full Armor Quality
              <select
                value={quickForm.armorQuality}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, armorQuality: event.target.value }))}
              >
                <option value="">None</option>
                {QUALITY_ORDER.map((quality) => (
                  <option key={quality} value={quality}>
                    {quality}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Starting Weapon
              <select
                value={quickForm.weaponId}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, weaponId: event.target.value }))}
              >
                <option value="">None</option>
                {quickData.weapons.map((weapon) => (
                  <option key={weapon.id} value={weapon.id}>
                    {weapon.name || weapon.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Weapon Quality
              <select
                value={quickForm.weaponQuality}
                onChange={(event) => setQuickForm((prev) => ({ ...prev, weaponQuality: event.target.value }))}
              >
                <option value="">Same as armor</option>
                {QUALITY_ORDER.map((quality) => (
                  <option key={quality} value={quality}>
                    {quality}
                  </option>
                ))}
              </select>
            </label>

            {quickDataError && <div className="cm-error">{quickDataError}</div>}
            {quickStatus && <div className="cm-muted">{quickStatus}</div>}

            <div className="cm-modal-actions">
              <button type="button" className="cm-btn" onClick={() => setQuickOpen(false)} disabled={quickBusy}>
                Cancel
              </button>
              <button type="submit" className="cm-btn cm-primary" disabled={quickBusy}>
                {quickBusy ? "Creating..." : "Create Character"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default CharacterListPage;
