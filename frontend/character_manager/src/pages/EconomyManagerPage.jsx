import React, { useEffect, useMemo, useState } from "react";
import { fetchMe } from "../api";

const ECONOMY_TYPES = ["Manpower (hourly)", "Primary Resource", "Manufactured Resource", "Item"];
const AVAILABILITIES = [
  "Very Common",
  "Common",
  "Uncommon",
  "Rare",
  "Very Rare",
  "Legendary",
  "Unique",
];
const MARKUP_BY_AVAILABILITY = {
  "Very Common": 5,
  Common: 10,
  Uncommon: 30,
  Rare: 75,
  "Very Rare": 150,
  Legendary: 300,
  Unique: 1000,
};
const DEFAULT_AVAILABILITY = "Common";

function normalizeRole(role) {
  return String(role || "").toLowerCase();
}

function isPrivilegedRole(role) {
  return ["admin", "mod", "moderator"].includes(normalizeRole(role));
}

function createId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function availabilityRank(value) {
  const idx = AVAILABILITIES.indexOf(value);
  return idx === -1 ? 0 : idx;
}

function getRarestAvailability(requirements, entitiesById) {
  let rarest = "";
  let rank = -1;
  for (const entry of requirements) {
    const entity = entitiesById[entry.entityId];
    if (!entity?.availability) continue;
    const currentRank = availabilityRank(entity.availability);
    if (currentRank > rank) {
      rank = currentRank;
      rarest = entity.availability;
    }
  }
  return rarest || DEFAULT_AVAILABILITY;
}

function EconomyManagerPage() {
  const [me, setMe] = useState({
    label: "Checking login...",
    role: "",
    isAdmin: false,
    isPrivileged: false,
  });
  const [tab, setTab] = useState("configure");
  const [entities, setEntities] = useState([]);
  const [entityForm, setEntityForm] = useState({
    id: "",
    name: "",
    type: ECONOMY_TYPES[0],
    valuePerUnit: "",
    availability: AVAILABILITIES[0],
  });
  const [entityError, setEntityError] = useState("");
  const [services, setServices] = useState([]);
  const [serviceFormOpen, setServiceFormOpen] = useState(false);
  const [serviceForm, setServiceForm] = useState({ name: "", fixedPrice: "" });
  const [dynamicMeta, setDynamicMeta] = useState({});
  const [selectedDynamicId, setSelectedDynamicId] = useState("");
  const [dynamicSearch, setDynamicSearch] = useState("");
  const [dynamicFilter, setDynamicFilter] = useState("all");
  const [requirementDraft, setRequirementDraft] = useState({ entityId: "", quantity: 1 });

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((meData) => {
        if (!active) return;
        const role = meData.role || "";
        const isAdmin = normalizeRole(role) === "admin";
        setMe({
          label: `${meData.username || "Unknown"} (${role || "user"})`,
          role,
          isAdmin,
          isPrivileged: isPrivilegedRole(role),
        });
      })
      .catch(() => {
        if (!active) return;
        setMe({ label: "Not logged in", role: "", isAdmin: false, isPrivileged: false });
      });
    return () => {
      active = false;
    };
  }, []);

  const entitiesById = useMemo(() => {
    const map = {};
    entities.forEach((entity) => {
      map[entity.id] = entity;
    });
    return map;
  }, [entities]);

  const catalogItems = useMemo(() => {
    return entities
      .filter((entity) => entity.type === "Item")
      .map((entity) => ({
        id: entity.id,
        name: entity.name,
        type: "Item",
        fixedPrice: Number(entity.valuePerUnit) || 0,
      }));
  }, [entities]);

  const dynamicEntries = useMemo(() => {
    return [
      ...catalogItems,
      ...services.map((service) => ({
        id: service.id,
        name: service.name,
        type: "Service",
        fixedPrice: Number(service.fixedPrice) || 0,
      })),
    ];
  }, [catalogItems, services]);

  const filteredDynamicEntries = useMemo(() => {
    const query = String(dynamicSearch || "").toLowerCase();
    return dynamicEntries.filter((entry) => {
      if (dynamicFilter !== "all" && entry.type !== dynamicFilter) return false;
      if (!query) return true;
      return String(entry.name || "").toLowerCase().includes(query);
    });
  }, [dynamicEntries, dynamicFilter, dynamicSearch]);

  const selectedEntry = dynamicEntries.find((entry) => entry.id === selectedDynamicId) || null;
  const selectedMeta = selectedEntry ? dynamicMeta[selectedEntry.id] || null : null;

  useEffect(() => {
    if (!selectedEntry) return;
    setDynamicMeta((prev) => {
      if (prev[selectedEntry.id]) return prev;
      return {
        ...prev,
        [selectedEntry.id]: {
          requirements: [],
          availability: "",
          markupPct: "",
        },
      };
    });
  }, [selectedEntry]);

  const requirementOptions = useMemo(() => {
    return entities
      .filter((entity) => ECONOMY_TYPES.includes(entity.type))
      .map((entity) => ({
        id: entity.id,
        label: `${entity.name} (${entity.type})`,
        availability: entity.availability,
        valuePerUnit: Number(entity.valuePerUnit) || 0,
      }));
  }, [entities]);

  const requirementMap = useMemo(() => {
    const map = {};
    requirementOptions.forEach((entry) => {
      map[entry.id] = entry;
    });
    return map;
  }, [requirementOptions]);

  const defaultAvailability = useMemo(() => {
    if (!selectedMeta) return DEFAULT_AVAILABILITY;
    return getRarestAvailability(selectedMeta.requirements || [], entitiesById);
  }, [entitiesById, selectedMeta]);

  const effectiveAvailability = selectedMeta?.availability || defaultAvailability;
  const defaultMarkupPct = MARKUP_BY_AVAILABILITY[effectiveAvailability] ?? 0;
  const effectiveMarkupPct =
    selectedMeta?.markupPct === "" || selectedMeta?.markupPct === undefined || selectedMeta?.markupPct === null
      ? defaultMarkupPct
      : Number(selectedMeta?.markupPct) || 0;

  const requirementCost = useMemo(() => {
    if (!selectedMeta) return 0;
    return (selectedMeta.requirements || []).reduce((sum, entry) => {
      const source = entitiesById[entry.entityId];
      if (!source) return sum;
      const unit = Number(source.valuePerUnit) || 0;
      const qty = Number(entry.quantity) || 0;
      return sum + unit * qty;
    }, 0);
  }, [entitiesById, selectedMeta]);

  const markupValue = requirementCost * (effectiveMarkupPct / 100);
  const dynamicPrice = Math.round(requirementCost + markupValue);

  function resetEntityForm() {
    setEntityForm({
      id: "",
      name: "",
      type: ECONOMY_TYPES[0],
      valuePerUnit: "",
      availability: AVAILABILITIES[0],
    });
  }

  function handleEntitySubmit(event) {
    event.preventDefault();
    setEntityError("");
    const name = String(entityForm.name || "").trim();
    if (!name) {
      setEntityError("Name is required.");
      return;
    }
    const value = Number(entityForm.valuePerUnit);
    if (Number.isNaN(value)) {
      setEntityError("Value per unit must be a number.");
      return;
    }
    if (entityForm.id) {
      setEntities((prev) =>
        prev.map((entity) =>
          entity.id === entityForm.id
            ? { ...entity, name, type: entityForm.type, valuePerUnit: value, availability: entityForm.availability }
            : entity
        )
      );
    } else {
      const newEntity = {
        id: createId(),
        name,
        type: entityForm.type,
        valuePerUnit: value,
        availability: entityForm.availability,
      };
      setEntities((prev) => [...prev, newEntity]);
    }
    resetEntityForm();
  }

  function handleEntityEdit(entity) {
    setEntityForm({
      id: entity.id,
      name: entity.name,
      type: entity.type,
      valuePerUnit: entity.valuePerUnit,
      availability: entity.availability,
    });
  }

  function handleEntityDelete(entityId) {
    setEntities((prev) => prev.filter((entity) => entity.id !== entityId));
    setDynamicMeta((prev) => {
      if (!prev[entityId]) return prev;
      const next = { ...prev };
      delete next[entityId];
      return next;
    });
    if (selectedDynamicId === entityId) {
      setSelectedDynamicId("");
    }
  }

  function updateSelectedMeta(patch) {
    if (!selectedEntry) return;
    setDynamicMeta((prev) => ({
      ...prev,
      [selectedEntry.id]: { ...prev[selectedEntry.id], ...patch },
    }));
  }

  function handleRequirementAdd(event) {
    event.preventDefault();
    if (!selectedMeta || !selectedEntry) return;
    const entityId = requirementDraft.entityId;
    const qty = Number(requirementDraft.quantity);
    if (!entityId || Number.isNaN(qty) || qty <= 0) {
      return;
    }
    if (selectedMeta.requirements.some((entry) => entry.entityId === entityId)) {
      return;
    }
    updateSelectedMeta({
      requirements: [...selectedMeta.requirements, { entityId, quantity: qty }],
    });
    setRequirementDraft({ entityId: "", quantity: 1 });
  }

  function handleRequirementRemove(entityId) {
    if (!selectedMeta) return;
    updateSelectedMeta({
      requirements: selectedMeta.requirements.filter((entry) => entry.entityId !== entityId),
    });
  }

  function handleFixedPriceChange(value) {
    const nextValue = Number(value);
    if (!selectedEntry) return;
    if (selectedEntry.type === "Item") {
      setEntities((prev) =>
        prev.map((entity) =>
          entity.id === selectedEntry.id ? { ...entity, valuePerUnit: Number.isNaN(nextValue) ? 0 : nextValue } : entity
        )
      );
    } else {
      setServices((prev) =>
        prev.map((service) =>
          service.id === selectedEntry.id ? { ...service, fixedPrice: Number.isNaN(nextValue) ? 0 : nextValue } : service
        )
      );
    }
  }

  function handleCreateService(event) {
    event.preventDefault();
    const name = String(serviceForm.name || "").trim();
    const fixedPrice = Number(serviceForm.fixedPrice);
    if (!name || Number.isNaN(fixedPrice)) {
      return;
    }
    const newService = { id: createId(), name, fixedPrice };
    setServices((prev) => [...prev, newService]);
    setServiceForm({ name: "", fixedPrice: "" });
    setServiceFormOpen(false);
    setSelectedDynamicId(newService.id);
  }

  if (!me.isPrivileged) {
    return (
      <div className="cm-page">
        <div className="cm-wrap">
          <div className="cm-topbar">
            <h1>Economy Manager</h1>
            <a className="cm-btn" href="/character-manager">
              Back to Manager
            </a>
            <span className="cm-muted cm-right">{me.label}</span>
          </div>
          <p>Admin or moderator access required.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="cm-page">
      <div className="cm-wrap">
        <div className="cm-topbar">
          <h1>Economy Manager</h1>
          <a className="cm-btn" href="/character-manager">
            Back to Manager
          </a>
          <span className="cm-muted cm-right">{me.label}</span>
        </div>

        <div className="cm-tabs">
          <button className={`cm-tab ${tab === "configure" ? "active" : ""}`} onClick={() => setTab("configure")}>
            Configure Economy
          </button>
          <button className={`cm-tab ${tab === "dynamic" ? "active" : ""}`} onClick={() => setTab("dynamic")}>
            Dynamic Item Price
          </button>
        </div>

        {tab === "configure" && (
          <div className="cm-economy-layout">
            <div className="cm-panel">
              <h2>{entityForm.id ? "Update Entity" : "Create Entity"}</h2>
              <form className="cm-field-grid" onSubmit={handleEntitySubmit}>
                <label>
                  Name
                  <input
                    type="text"
                    value={entityForm.name}
                    onChange={(event) => setEntityForm((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="Entity name"
                  />
                </label>
                <label>
                  Type
                  <select
                    value={entityForm.type}
                    onChange={(event) => setEntityForm((prev) => ({ ...prev, type: event.target.value }))}
                  >
                    {ECONOMY_TYPES.map((entry) => (
                      <option key={entry} value={entry}>
                        {entry}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Value per Unit (Jelly)
                  <input
                    type="number"
                    value={entityForm.valuePerUnit}
                    onChange={(event) => setEntityForm((prev) => ({ ...prev, valuePerUnit: event.target.value }))}
                    placeholder="0"
                  />
                </label>
                <label>
                  Availability
                  <select
                    value={entityForm.availability}
                    onChange={(event) => setEntityForm((prev) => ({ ...prev, availability: event.target.value }))}
                  >
                    {AVAILABILITIES.map((entry) => (
                      <option key={entry} value={entry}>
                        {entry}
                      </option>
                    ))}
                  </select>
                </label>
                {entityError && <div className="cm-error">{entityError}</div>}
                <div className="cm-row">
                  <button className="cm-btn cm-primary" type="submit">
                    {entityForm.id ? "Update Entity" : "Create Entity"}
                  </button>
                  {entityForm.id && (
                    <button className="cm-btn" type="button" onClick={resetEntityForm}>
                      Cancel
                    </button>
                  )}
                </div>
              </form>
            </div>

            <div className="cm-panel">
              <h2>Existing Entities</h2>
              {!entities.length && <p className="cm-muted">No entities yet.</p>}
              {!!entities.length && (
                <table className="cm-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Value</th>
                      <th>Availability</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.map((entity) => (
                      <tr key={entity.id}>
                        <td>{entity.name}</td>
                        <td>{entity.type}</td>
                        <td>{entity.valuePerUnit}</td>
                        <td>{entity.availability}</td>
                        <td className="cm-table-actions">
                          <button type="button" className="cm-btn" onClick={() => handleEntityEdit(entity)}>
                            Edit
                          </button>
                          <button type="button" className="cm-btn" onClick={() => handleEntityDelete(entity.id)}>
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {tab === "dynamic" && (
          <div className="cm-economy-layout">
            <div className="cm-panel">
              <h2>Items & Services</h2>
              <div className="cm-field-grid">
                <label>
                  Search
                  <input
                    type="text"
                    value={dynamicSearch}
                    onChange={(event) => setDynamicSearch(event.target.value)}
                    placeholder="Search by name"
                  />
                </label>
                <label>
                  Type
                  <select value={dynamicFilter} onChange={(event) => setDynamicFilter(event.target.value)}>
                    <option value="all">All</option>
                    <option value="Item">Items</option>
                    <option value="Service">Services</option>
                  </select>
                </label>
                <button type="button" className="cm-btn cm-primary" onClick={() => setServiceFormOpen((v) => !v)}>
                  {serviceFormOpen ? "Close Service Form" : "Create Service"}
                </button>
                {serviceFormOpen && (
                  <form className="cm-inline cm-service-form" onSubmit={handleCreateService}>
                    <input
                      type="text"
                      value={serviceForm.name}
                      placeholder="Service name"
                      onChange={(event) => setServiceForm((prev) => ({ ...prev, name: event.target.value }))}
                    />
                    <input
                      type="number"
                      value={serviceForm.fixedPrice}
                      placeholder="Fixed price"
                      onChange={(event) => setServiceForm((prev) => ({ ...prev, fixedPrice: event.target.value }))}
                    />
                    <button className="cm-btn cm-primary" type="submit">
                      Add
                    </button>
                  </form>
                )}
              </div>

              <div className="cm-list">
                {!filteredDynamicEntries.length && <p className="cm-muted">No matching items yet.</p>}
                {filteredDynamicEntries.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`cm-list-item ${selectedDynamicId === entry.id ? "active" : ""}`}
                    onClick={() => setSelectedDynamicId(entry.id)}
                  >
                    <div>
                      <strong>{entry.name}</strong>
                      <div className="cm-muted">{entry.type}</div>
                    </div>
                    <span className="cm-pill">{entry.fixedPrice} Jelly</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="cm-panel">
              <h2>Dynamic Pricing</h2>
              {!selectedEntry && <p className="cm-muted">Select an item or service to configure.</p>}
              {selectedEntry && selectedMeta && (
                <div className="cm-field-grid">
                  <div className="cm-inline cm-inline-space">
                    <div>
                      <strong>{selectedEntry.name}</strong>
                      <div className="cm-muted">{selectedEntry.type}</div>
                    </div>
                    <span className="cm-badge">Dynamic price: {dynamicPrice} Jelly</span>
                  </div>

                  <label>
                    Fixed Price (Jelly)
                    <input
                      type="number"
                      value={selectedEntry.fixedPrice}
                      onChange={(event) => handleFixedPriceChange(event.target.value)}
                    />
                  </label>

                  <label>
                    Availability
                    <select
                      value={effectiveAvailability}
                      onChange={(event) => updateSelectedMeta({ availability: event.target.value })}
                    >
                      {AVAILABILITIES.map((entry) => (
                        <option key={entry} value={entry}>
                          {entry}
                        </option>
                      ))}
                    </select>
                    <div className="cm-muted cm-subtle">
                      Suggested availability: {defaultAvailability} (from prerequisites)
                    </div>
                    {selectedMeta.availability && (
                      <button
                        type="button"
                        className="cm-btn"
                        onClick={() => updateSelectedMeta({ availability: "" })}
                      >
                        Use Suggested
                      </button>
                    )}
                  </label>

                  <label>
                    Markup (%)
                    <input
                      type="number"
                      value={effectiveMarkupPct}
                      onChange={(event) => updateSelectedMeta({ markupPct: event.target.value })}
                    />
                    <div className="cm-muted cm-subtle">Suggested markup: {defaultMarkupPct}%</div>
                    {selectedMeta.markupPct !== "" && (
                      <button
                        type="button"
                        className="cm-btn"
                        onClick={() => updateSelectedMeta({ markupPct: "" })}
                      >
                        Use Suggested
                      </button>
                    )}
                  </label>

                  <div className="cm-panel cm-panel-lite">
                    <div className="cm-inline cm-inline-space">
                      <strong>Requirements</strong>
                      <span className="cm-muted">Base cost: {requirementCost} Jelly</span>
                    </div>

                    <form className="cm-inline" onSubmit={handleRequirementAdd}>
                      <select
                        value={requirementDraft.entityId}
                        onChange={(event) =>
                          setRequirementDraft((prev) => ({ ...prev, entityId: event.target.value }))
                        }
                      >
                        <option value="">-- Select requirement --</option>
                        {requirementOptions.map((entry) => (
                          <option key={entry.id} value={entry.id}>
                            {entry.label}
                          </option>
                        ))}
                      </select>
                      <input
                        type="number"
                        min={1}
                        value={requirementDraft.quantity}
                        onChange={(event) =>
                          setRequirementDraft((prev) => ({ ...prev, quantity: event.target.value }))
                        }
                      />
                      <button className="cm-btn cm-primary" type="submit">
                        Add
                      </button>
                    </form>

                    {!selectedMeta.requirements.length && <p className="cm-muted">No requirements yet.</p>}
                    {!!selectedMeta.requirements.length && (
                      <div className="cm-list">
                        {selectedMeta.requirements.map((entry) => {
                          const info = requirementMap[entry.entityId];
                          return (
                            <div key={entry.entityId} className="cm-list-item cm-list-row">
                              <div>
                                <strong>{info?.label || "Unknown"}</strong>
                                <div className="cm-muted">
                                  {info?.valuePerUnit || 0} Jelly per unit · {info?.availability || "n/a"}
                                </div>
                              </div>
                              <div className="cm-inline">
                                <span className="cm-pill">x {entry.quantity}</span>
                                <button
                                  type="button"
                                  className="cm-btn"
                                  onClick={() => handleRequirementRemove(entry.entityId)}
                                >
                                  Remove
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div className="cm-panel cm-panel-lite">
                    <div className="cm-inline cm-inline-space">
                      <strong>Dynamic Price Breakdown</strong>
                      <span className="cm-badge">{dynamicPrice} Jelly</span>
                    </div>
                    <div className="cm-stack">
                      <div className="cm-inline cm-inline-space">
                        <span>Requirements cost</span>
                        <span>{requirementCost} Jelly</span>
                      </div>
                      <div className="cm-inline cm-inline-space">
                        <span>Markup ({effectiveMarkupPct}%)</span>
                        <span>{Math.round(markupValue)} Jelly</span>
                      </div>
                      <div className="cm-inline cm-inline-space">
                        <strong>Total</strong>
                        <strong>{dynamicPrice} Jelly</strong>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default EconomyManagerPage;
