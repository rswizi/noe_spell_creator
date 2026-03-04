import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import {
  createEconomyEntity,
  createEconomyService,
  deleteEconomyEntity,
  deleteEconomyService,
  fetchEconomyBootstrap,
  fetchEconomyCatalog,
  fetchMe,
  updateEconomyEntity,
  updateEconomyService,
  upsertEconomyItemMeta,
} from "../api";

const DEFAULT_AVAILABILITIES = [
  "Very Common",
  "Common",
  "Uncommon",
  "Rare",
  "Very Rare",
  "Legendary",
  "Unique",
];

const DEFAULT_MARKUP_BY_AVAILABILITY = {
  "Very Common": 5,
  Common: 10,
  Uncommon: 30,
  Rare: 75,
  "Very Rare": 150,
  Legendary: 300,
  Unique: 1000,
};

const ECONOMY_TYPES = ["Manpower (hourly)", "Primary Resource", "Manufactured Resource", "Item"];

function normalizeRole(role) {
  return String(role || "").toLowerCase();
}

function isPrivilegedRole(role) {
  return ["admin", "mod", "moderator"].includes(normalizeRole(role));
}

function availabilityRank(value, availabilities) {
  const idx = availabilities.indexOf(value);
  return idx === -1 ? 0 : idx;
}

function sourceKindLabel(kind) {
  const value = String(kind || "").toLowerCase();
  if (value === "object") return "Object";
  if (value === "equipment") return "Equipment";
  if (value === "weapon") return "Weapon";
  if (value === "tool") return "Tool";
  if (value === "service") return "Service";
  if (value === "entity") return "Economy Entity";
  return kind || "Unknown";
}

function splitSourceKey(key) {
  const raw = String(key || "");
  const [kind, ...rest] = raw.split(":");
  return { source_kind: kind || "", source_id: rest.join(":") || "" };
}

function economySourceKey(sourceKind, sourceId) {
  return `${String(sourceKind || "").toLowerCase()}:${String(sourceId || "").trim()}`;
}

function EconomyManagerPage() {
  const location = useLocation();
  const [me, setMe] = useState({
    label: "Checking login...",
    role: "",
    isPrivileged: false,
  });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const [entities, setEntities] = useState([]);
  const [availabilities, setAvailabilities] = useState(DEFAULT_AVAILABILITIES);
  const [markupByAvailability, setMarkupByAvailability] = useState(DEFAULT_MARKUP_BY_AVAILABILITY);

  const [entityForm, setEntityForm] = useState({
    id: "",
    name: "",
    type: ECONOMY_TYPES[0],
    value_per_unit: "",
    availability: DEFAULT_AVAILABILITIES[0],
  });
  const [entityError, setEntityError] = useState("");

  const [dynamicSearch, setDynamicSearch] = useState("");
  const [dynamicType, setDynamicType] = useState("all");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogItems, setCatalogItems] = useState([]);
  const [allCatalogItems, setAllCatalogItems] = useState([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [serviceFormOpen, setServiceFormOpen] = useState(false);
  const [serviceForm, setServiceForm] = useState({ name: "", fixed_price: "" });
  const [dynamicSaveBusy, setDynamicSaveBusy] = useState(false);
  const [dynamicSaveError, setDynamicSaveError] = useState("");
  const [dynamicSaveMessage, setDynamicSaveMessage] = useState("");

  const [editorMeta, setEditorMeta] = useState({
    requirements: [],
    availability_override: "",
    markup_pct_override: "",
  });
  const [servicePriceDraft, setServicePriceDraft] = useState("");
  const [requirementDraft, setRequirementDraft] = useState({ key: "", quantity: 1 });

  const loadBootstrap = useCallback(async () => {
    const meData = await fetchMe();
    const role = meData.role || "";
    const privileged = isPrivilegedRole(role);
    setMe({
      label: `${meData.username || "Unknown"} (${role || "user"})`,
      role,
      isPrivileged: privileged,
    });
    if (!privileged) {
      setEntities([]);
      return false;
    }
    const bootstrap = await fetchEconomyBootstrap();
    setEntities(bootstrap.entities || []);
    if (Array.isArray(bootstrap.availabilities) && bootstrap.availabilities.length) {
      setAvailabilities(bootstrap.availabilities);
    }
    if (bootstrap.markup_by_availability && typeof bootstrap.markup_by_availability === "object") {
      setMarkupByAvailability(bootstrap.markup_by_availability);
    }
    return true;
  }, []);

  const loadCatalog = useCallback(async (searchValue, typeValue) => {
    setCatalogBusy(true);
    setCatalogError("");
    try {
      const result = await fetchEconomyCatalog({ q: searchValue || "", itemType: typeValue || "all", limit: 250 });
      setCatalogItems(result.items || []);
    } catch (err) {
      setCatalogError(err instanceof Error ? err.message : "Failed to load item catalog.");
    } finally {
      setCatalogBusy(false);
    }
  }, []);

  const loadAllCatalog = useCallback(async () => {
    try {
      const result = await fetchEconomyCatalog({ q: "", itemType: "all", limit: 500 });
      setAllCatalogItems(result.items || []);
    } catch (_) {
      setAllCatalogItems([]);
    }
  }, []);

  const reloadEconomyData = useCallback(async () => {
    const privileged = await loadBootstrap();
    if (!privileged) {
      setCatalogItems([]);
      setAllCatalogItems([]);
      return;
    }
    await Promise.all([loadCatalog(dynamicSearch, dynamicType), loadAllCatalog()]);
  }, [dynamicSearch, dynamicType, loadAllCatalog, loadBootstrap, loadCatalog]);

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    reloadEconomyData()
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load economy manager data.");
      })
      .finally(() => {
        if (!active) return;
        setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [reloadEconomyData]);

  useEffect(() => {
    if (!me.isPrivileged) return;
    const timer = setTimeout(() => {
      void loadCatalog(dynamicSearch, dynamicType);
    }, 250);
    return () => clearTimeout(timer);
  }, [dynamicSearch, dynamicType, loadCatalog, me.isPrivileged]);

  const selectedItem = useMemo(
    () => catalogItems.find((entry) => economySourceKey(entry.source_kind, entry.source_id) === selectedKey) || null,
    [catalogItems, selectedKey]
  );

  useEffect(() => {
    if (!selectedItem) return;
    const meta = selectedItem.meta || {};
    setEditorMeta({
      requirements: Array.isArray(meta.requirements) ? meta.requirements : [],
      availability_override: meta.availability_override || "",
      markup_pct_override: meta.markup_pct_override === undefined || meta.markup_pct_override === null ? "" : String(meta.markup_pct_override),
    });
    setServicePriceDraft(String(selectedItem.fixed_price ?? ""));
    setRequirementDraft({ key: "", quantity: 1 });
    setDynamicSaveError("");
    setDynamicSaveMessage("");
  }, [selectedItem]);
  const requirementOptions = useMemo(() => {
    const entityOptions = (entities || []).map((entry) => ({
      key: economySourceKey("entity", entry.id),
      source_kind: "entity",
      source_id: entry.id,
      label: `${entry.name} (${entry.type})`,
      fixed_price: Number(entry.value_per_unit) || 0,
      availability: entry.availability || "Common",
      type_label: "Economy Entity",
    }));
    const itemOptions = (allCatalogItems || []).map((entry) => ({
      key: economySourceKey(entry.source_kind, entry.source_id),
      source_kind: entry.source_kind,
      source_id: entry.source_id,
      label: `${entry.name} (${sourceKindLabel(entry.source_kind)})`,
      fixed_price: Number(entry.fixed_price) || 0,
      availability: entry.meta?.availability_override || "Common",
      type_label: sourceKindLabel(entry.source_kind),
    }));

    const merged = [...entityOptions, ...itemOptions];
    const selectedSource = selectedItem ? economySourceKey(selectedItem.source_kind, selectedItem.source_id) : "";
    return merged
      .filter((entry) => entry.key !== selectedSource)
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  }, [allCatalogItems, entities, selectedItem]);

  const requirementMap = useMemo(() => {
    const map = {};
    requirementOptions.forEach((entry) => {
      map[entry.key] = entry;
    });
    return map;
  }, [requirementOptions]);

  const defaultAvailability = useMemo(() => {
    const requirements = editorMeta.requirements || [];
    if (!requirements.length) return availabilities[1] || availabilities[0] || "Common";
    let best = availabilities[1] || availabilities[0] || "Common";
    let bestRank = availabilityRank(best, availabilities);
    requirements.forEach((entry) => {
      const opt = requirementMap[economySourceKey(entry.source_kind, entry.source_id)];
      const current = opt?.availability || "Common";
      const currentRank = availabilityRank(current, availabilities);
      if (currentRank > bestRank) {
        best = current;
        bestRank = currentRank;
      }
    });
    return best;
  }, [availabilities, editorMeta.requirements, requirementMap]);

  const effectiveAvailability = editorMeta.availability_override || defaultAvailability;
  const defaultMarkupPct = Number(markupByAvailability[effectiveAvailability] ?? 0);
  const effectiveMarkupPct =
    editorMeta.markup_pct_override === "" || editorMeta.markup_pct_override === null
      ? defaultMarkupPct
      : Number(editorMeta.markup_pct_override) || 0;

  const requirementCost = useMemo(
    () =>
      (editorMeta.requirements || []).reduce((total, entry) => {
        const option = requirementMap[economySourceKey(entry.source_kind, entry.source_id)];
        const unitPrice = Number(option?.fixed_price) || 0;
        const qty = Number(entry.quantity) || 0;
        return total + unitPrice * qty;
      }, 0),
    [editorMeta.requirements, requirementMap]
  );

  const markupValue = requirementCost * (effectiveMarkupPct / 100);
  const dynamicPrice = Math.round(requirementCost + markupValue);

  async function submitEntity(event) {
    event.preventDefault();
    setEntityError("");
    const name = String(entityForm.name || "").trim();
    const value = Number(entityForm.value_per_unit);
    if (!name) {
      setEntityError("Name is required.");
      return;
    }
    if (Number.isNaN(value) || value < 0) {
      setEntityError("Value per unit must be a valid number >= 0.");
      return;
    }

    const payload = {
      name,
      type: entityForm.type,
      value_per_unit: value,
      availability: entityForm.availability,
    };

    try {
      if (entityForm.id) {
        await updateEconomyEntity(entityForm.id, payload);
      } else {
        await createEconomyEntity(payload);
      }
      setEntityForm({
        id: "",
        name: "",
        type: ECONOMY_TYPES[0],
        value_per_unit: "",
        availability: availabilities[0] || "Very Common",
      });
      await reloadEconomyData();
    } catch (err) {
      setEntityError(err instanceof Error ? err.message : "Unable to save entity.");
    }
  }

  async function onDeleteEntity(entityId) {
    if (!window.confirm("Delete this entity?")) return;
    try {
      await deleteEconomyEntity(entityId);
      if (entityForm.id === entityId) {
        setEntityForm({
          id: "",
          name: "",
          type: ECONOMY_TYPES[0],
          value_per_unit: "",
          availability: availabilities[0] || "Very Common",
        });
      }
      await reloadEconomyData();
    } catch (err) {
      setEntityError(err instanceof Error ? err.message : "Unable to delete entity.");
    }
  }

  async function onCreateService(event) {
    event.preventDefault();
    const name = String(serviceForm.name || "").trim();
    const fixedPrice = Number(serviceForm.fixed_price);
    if (!name || Number.isNaN(fixedPrice) || fixedPrice < 0) {
      setDynamicSaveError("Service name and valid fixed price are required.");
      return;
    }

    try {
      const created = await createEconomyService({ name, fixed_price: fixedPrice });
      setServiceForm({ name: "", fixed_price: "" });
      setServiceFormOpen(false);
      await reloadEconomyData();
      const serviceId = created.service?.id || "";
      if (serviceId) {
        setSelectedKey(economySourceKey("service", serviceId));
      }
    } catch (err) {
      setDynamicSaveError(err instanceof Error ? err.message : "Unable to create service.");
    }
  }

  async function onDeleteService(serviceId) {
    if (!window.confirm("Delete this service?")) return;
    try {
      await deleteEconomyService(serviceId);
      if (selectedKey === economySourceKey("service", serviceId)) {
        setSelectedKey("");
      }
      await reloadEconomyData();
    } catch (err) {
      setDynamicSaveError(err instanceof Error ? err.message : "Unable to delete service.");
    }
  }

  function onAddRequirement(event) {
    event.preventDefault();
    if (!selectedItem) return;
    const source = splitSourceKey(requirementDraft.key);
    const quantity = Number(requirementDraft.quantity);
    if (!source.source_kind || !source.source_id || Number.isNaN(quantity) || quantity <= 0) return;

    const exists = (editorMeta.requirements || []).some(
      (entry) => entry.source_kind === source.source_kind && entry.source_id === source.source_id
    );
    if (exists) return;

    setEditorMeta((prev) => ({
      ...prev,
      requirements: [...(prev.requirements || []), { ...source, quantity }],
    }));
    setRequirementDraft({ key: "", quantity: 1 });
  }

  function onRemoveRequirement(sourceKind, sourceId) {
    setEditorMeta((prev) => ({
      ...prev,
      requirements: (prev.requirements || []).filter(
        (entry) => !(entry.source_kind === sourceKind && entry.source_id === sourceId)
      ),
    }));
  }
  async function saveDynamicConfiguration() {
    if (!selectedItem) return;
    setDynamicSaveBusy(true);
    setDynamicSaveError("");
    setDynamicSaveMessage("");
    try {
      if (selectedItem.source_kind === "service") {
        const nextPrice = Number(servicePriceDraft);
        if (Number.isNaN(nextPrice) || nextPrice < 0) {
          throw new Error("Service fixed price must be a number >= 0.");
        }
        await updateEconomyService(selectedItem.source_id, {
          name: selectedItem.name,
          fixed_price: nextPrice,
        });
      }

      await upsertEconomyItemMeta(selectedItem.source_kind, selectedItem.source_id, {
        requirements: editorMeta.requirements || [],
        availability_override: editorMeta.availability_override || "",
        markup_pct_override: editorMeta.markup_pct_override === "" ? null : Number(editorMeta.markup_pct_override) || 0,
      });

      await reloadEconomyData();
      setDynamicSaveMessage("Dynamic pricing configuration saved.");
    } catch (err) {
      setDynamicSaveError(err instanceof Error ? err.message : "Unable to save dynamic pricing.");
    } finally {
      setDynamicSaveBusy(false);
    }
  }

  const configurePath = "configure-economy";
  const dynamicPath = "dynamic-price";
  const currentPath = String(location.pathname || "").toLowerCase();
  const configureActive = !currentPath.includes(dynamicPath);
  const dynamicActive = currentPath.includes(dynamicPath);

  if (busy) {
    return (
      <div className="cm-page">
        <div className="cm-wrap">
          <p className="cm-muted">Loading economy manager...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cm-page">
        <div className="cm-wrap">
          <div className="cm-topbar">
            <h1>Economy Manager</h1>
            <a className="cm-btn" href="/character-manager">
              Back to Manager
            </a>
          </div>
          <p className="cm-error">{error}</p>
        </div>
      </div>
    );
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
          <Link className={`cm-tab ${configureActive ? "active" : ""}`} to={configurePath}>
            Configure Economy
          </Link>
          <Link className={`cm-tab ${dynamicActive ? "active" : ""}`} to={dynamicPath}>
            Dynamic Item Price
          </Link>
        </div>

        <Routes>
          <Route path="/" element={<Navigate to={configurePath} replace />} />
          <Route
            path={configurePath}
            element={
              <div className="cm-economy-layout">
                <div className="cm-panel">
                  <h2>{entityForm.id ? "Update Entity" : "Create Entity"}</h2>
                  <form className="cm-field-grid" onSubmit={submitEntity}>
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
                        value={entityForm.value_per_unit}
                        onChange={(event) => setEntityForm((prev) => ({ ...prev, value_per_unit: event.target.value }))}
                        placeholder="0"
                      />
                    </label>
                    <label>
                      Availability
                      <select
                        value={entityForm.availability}
                        onChange={(event) => setEntityForm((prev) => ({ ...prev, availability: event.target.value }))}
                      >
                        {availabilities.map((entry) => (
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
                        <button
                          className="cm-btn"
                          type="button"
                          onClick={() =>
                            setEntityForm({
                              id: "",
                              name: "",
                              type: ECONOMY_TYPES[0],
                              value_per_unit: "",
                              availability: availabilities[0] || "Very Common",
                            })
                          }
                        >
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
                            <td>{entity.value_per_unit}</td>
                            <td>{entity.availability}</td>
                            <td className="cm-table-actions">
                              <button
                                type="button"
                                className="cm-btn"
                                onClick={() =>
                                  setEntityForm({
                                    id: entity.id,
                                    name: entity.name,
                                    type: entity.type,
                                    value_per_unit: String(entity.value_per_unit ?? ""),
                                    availability: entity.availability || availabilities[0] || "Very Common",
                                  })
                                }
                              >
                                Edit
                              </button>
                              <button type="button" className="cm-btn cm-danger" onClick={() => onDeleteEntity(entity.id)}>
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
            }
          />
          <Route
            path={dynamicPath}
            element={
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
                      <select value={dynamicType} onChange={(event) => setDynamicType(event.target.value)}>
                        <option value="all">All</option>
                        <option value="object">Object</option>
                        <option value="equipment">Equipment</option>
                        <option value="weapon">Weapon</option>
                        <option value="tool">Tool</option>
                        <option value="service">Service</option>
                      </select>
                    </label>
                    <button type="button" className="cm-btn cm-primary" onClick={() => setServiceFormOpen((value) => !value)}>
                      {serviceFormOpen ? "Close Service Form" : "Create Service"}
                    </button>
                    {serviceFormOpen && (
                      <form className="cm-inline cm-service-form" onSubmit={onCreateService}>
                        <input
                          type="text"
                          value={serviceForm.name}
                          placeholder="Service name"
                          onChange={(event) => setServiceForm((prev) => ({ ...prev, name: event.target.value }))}
                        />
                        <input
                          type="number"
                          value={serviceForm.fixed_price}
                          placeholder="Fixed price"
                          onChange={(event) => setServiceForm((prev) => ({ ...prev, fixed_price: event.target.value }))}
                        />
                        <button className="cm-btn cm-primary" type="submit">
                          Add
                        </button>
                      </form>
                    )}
                  </div>

                  {catalogBusy && <p className="cm-muted">Loading catalog...</p>}
                  {catalogError && <p className="cm-error">{catalogError}</p>}

                  <div className="cm-list">
                    {!catalogBusy && !catalogItems.length && <p className="cm-muted">No matching items found.</p>}
                    {catalogItems.map((entry) => {
                      const key = economySourceKey(entry.source_kind, entry.source_id);
                      return (
                        <div key={key} className={`cm-list-item ${selectedKey === key ? "active" : ""}`}>
                          <button type="button" className="cm-list-main-btn" onClick={() => setSelectedKey(key)}>
                            <div>
                              <strong>{entry.name}</strong>
                              <div className="cm-muted">{sourceKindLabel(entry.source_kind)}</div>
                            </div>
                            <span className="cm-pill">{entry.fixed_price} Jelly</span>
                          </button>
                          {entry.source_kind === "service" && (
                            <button type="button" className="cm-btn cm-danger" onClick={() => onDeleteService(entry.source_id)}>
                              Delete
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="cm-panel">
                  <h2>Dynamic Pricing</h2>
                  {!selectedItem && <p className="cm-muted">Select an item or service to configure.</p>}
                  {selectedItem && (
                    <div className="cm-field-grid">
                      <div className="cm-inline cm-inline-space">
                        <div>
                          <strong>{selectedItem.name}</strong>
                          <div className="cm-muted">{sourceKindLabel(selectedItem.source_kind)}</div>
                        </div>
                        <span className="cm-badge">Dynamic price: {dynamicPrice} Jelly</span>
                      </div>

                      {selectedItem.source_kind === "service" ? (
                        <label>
                          Fixed Price (Jelly)
                          <input type="number" value={servicePriceDraft} onChange={(event) => setServicePriceDraft(event.target.value)} />
                        </label>
                      ) : (
                        <label>
                          Fixed Price (Jelly)
                          <input type="number" value={selectedItem.fixed_price} disabled />
                        </label>
                      )}

                      <label>
                        Availability
                        <select
                          value={editorMeta.availability_override || defaultAvailability}
                          onChange={(event) => {
                            const value = event.target.value;
                            const shouldUseSuggested = value === defaultAvailability;
                            setEditorMeta((prev) => ({ ...prev, availability_override: shouldUseSuggested ? "" : value }));
                          }}
                        >
                          {availabilities.map((entry) => (
                            <option key={entry} value={entry}>
                              {entry}
                            </option>
                          ))}
                        </select>
                        <div className="cm-muted cm-subtle">Suggested availability: {defaultAvailability} (based on prerequisites)</div>
                        {editorMeta.availability_override && (
                          <button
                            type="button"
                            className="cm-btn"
                            onClick={() => setEditorMeta((prev) => ({ ...prev, availability_override: "" }))}
                          >
                            Use Suggested
                          </button>
                        )}
                      </label>

                      <label>
                        Markup (%)
                        <input
                          type="number"
                          value={editorMeta.markup_pct_override === "" ? defaultMarkupPct : editorMeta.markup_pct_override}
                          onChange={(event) => setEditorMeta((prev) => ({ ...prev, markup_pct_override: event.target.value }))}
                        />
                        <div className="cm-muted cm-subtle">Suggested markup: {defaultMarkupPct}%</div>
                        {editorMeta.markup_pct_override !== "" && (
                          <button
                            type="button"
                            className="cm-btn"
                            onClick={() => setEditorMeta((prev) => ({ ...prev, markup_pct_override: "" }))}
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
                        <form className="cm-inline" onSubmit={onAddRequirement}>
                          <select
                            value={requirementDraft.key}
                            onChange={(event) => setRequirementDraft((prev) => ({ ...prev, key: event.target.value }))}
                          >
                            <option value="">-- Select requirement --</option>
                            {requirementOptions.map((entry) => (
                              <option key={entry.key} value={entry.key}>
                                {entry.label}
                              </option>
                            ))}
                          </select>
                          <input
                            type="number"
                            min={0.01}
                            step="0.01"
                            value={requirementDraft.quantity}
                            onChange={(event) => setRequirementDraft((prev) => ({ ...prev, quantity: event.target.value }))}
                          />
                          <button className="cm-btn cm-primary" type="submit">
                            Add
                          </button>
                        </form>

                        {!editorMeta.requirements.length && <p className="cm-muted">No requirements yet.</p>}
                        {!!editorMeta.requirements.length && (
                          <div className="cm-list">
                            {editorMeta.requirements.map((entry) => {
                              const key = economySourceKey(entry.source_kind, entry.source_id);
                              const info = requirementMap[key];
                              return (
                                <div key={key} className="cm-list-item cm-list-row">
                                  <div>
                                    <strong>{info?.label || `${entry.source_kind}:${entry.source_id}`}</strong>
                                    <div className="cm-muted">
                                      {(Number(info?.fixed_price) || 0).toFixed(2)} Jelly per unit | {info?.availability || "Common"}
                                    </div>
                                  </div>
                                  <div className="cm-inline">
                                    <span className="cm-pill">x {entry.quantity}</span>
                                    <button
                                      type="button"
                                      className="cm-btn"
                                      onClick={() => onRemoveRequirement(entry.source_kind, entry.source_id)}
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
                            <span>{requirementCost.toFixed(2)} Jelly</span>
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

                      {dynamicSaveError && <div className="cm-error">{dynamicSaveError}</div>}
                      {dynamicSaveMessage && <div className="cm-muted">{dynamicSaveMessage}</div>}
                      <div className="cm-row">
                        <button className="cm-btn cm-primary" type="button" onClick={saveDynamicConfiguration} disabled={dynamicSaveBusy}>
                          {dynamicSaveBusy ? "Saving..." : "Save Dynamic Config"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            }
          />
          <Route path="*" element={<Navigate to={configurePath} replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default EconomyManagerPage;
