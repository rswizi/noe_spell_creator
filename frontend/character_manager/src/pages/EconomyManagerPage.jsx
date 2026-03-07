import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
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

const PRIMARY_RESOURCE_TYPE = "Primary Resource";

const FILTER_TYPES = [
  { value: "all", label: "All" },
  { value: "object", label: "Object" },
  { value: "equipment", label: "Equipment" },
  { value: "weapon", label: "Weapon" },
  { value: "tool", label: "Tool" },
  { value: "service", label: "Service" },
  { value: "primary_resource", label: "Primary Ressource" },
];

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

function sourceKindLabel(kind, item) {
  const value = String(kind || "").toLowerCase();
  if (value === "object") return "Object";
  if (value === "equipment") return "Equipment";
  if (value === "weapon") return "Weapon";
  if (value === "tool") return "Tool";
  if (value === "service") return "Service";
  if (value === "entity") return item?.entity_type || PRIMARY_RESOURCE_TYPE;
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

function Icon({ name, label }) {
  return (
    <>
      <i className={`fa-solid ${name}`} aria-hidden="true" />
      <span className="cm-sr-only">{label}</span>
    </>
  );
}

function EconomyManagerPage() {
  const [me, setMe] = useState({
    label: "Checking login...",
    role: "",
    isPrivileged: false,
  });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const [entities, setEntities] = useState([]);
  const [services, setServices] = useState([]);
  const [availabilities, setAvailabilities] = useState(DEFAULT_AVAILABILITIES);
  const [markupByAvailability, setMarkupByAvailability] = useState(DEFAULT_MARKUP_BY_AVAILABILITY);

  const [serviceSearch, setServiceSearch] = useState("");
  const [serviceForm, setServiceForm] = useState({ name: "", fixed_price: "" });
  const [serviceBusy, setServiceBusy] = useState(false);
  const [serviceError, setServiceError] = useState("");

  const [primarySearch, setPrimarySearch] = useState("");
  const [primaryForm, setPrimaryForm] = useState({
    id: "",
    name: "",
    value_per_unit: "",
    availability: DEFAULT_AVAILABILITIES[0],
  });
  const [primaryBusy, setPrimaryBusy] = useState(false);
  const [primaryError, setPrimaryError] = useState("");

  const [dynamicSearch, setDynamicSearch] = useState("");
  const [dynamicType, setDynamicType] = useState("all");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogItems, setCatalogItems] = useState([]);
  const [allCatalogItems, setAllCatalogItems] = useState([]);
  const [selectedKey, setSelectedKey] = useState("");

  const [editorMeta, setEditorMeta] = useState({
    requirements: [],
    availability_override: "",
    markup_pct_override: "",
  });
  const [priceDraft, setPriceDraft] = useState("");
  const [requirementDraft, setRequirementDraft] = useState({ key: "", quantity: 1 });

  const [dynamicSaveBusy, setDynamicSaveBusy] = useState(false);
  const [dynamicSaveError, setDynamicSaveError] = useState("");
  const [dynamicSaveMessage, setDynamicSaveMessage] = useState("");

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
      setServices([]);
      return false;
    }
    const bootstrap = await fetchEconomyBootstrap();
    setEntities(bootstrap.entities || []);
    setServices(bootstrap.services || []);
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
      const result = await fetchEconomyCatalog({
        q: searchValue || "",
        itemType: typeValue || "all",
        limit: 300,
      });
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

  const selectedItem = useMemo(() => {
    const key = selectedKey;
    if (!key) return null;
    return (
      allCatalogItems.find((entry) => economySourceKey(entry.source_kind, entry.source_id) === key) ||
      catalogItems.find((entry) => economySourceKey(entry.source_kind, entry.source_id) === key) ||
      null
    );
  }, [allCatalogItems, catalogItems, selectedKey]);

  useEffect(() => {
    if (!selectedItem) return;
    const meta = selectedItem.meta || {};
    setEditorMeta({
      requirements: Array.isArray(meta.requirements) ? meta.requirements : [],
      availability_override: meta.availability_override || "",
      markup_pct_override:
        meta.markup_pct_override === undefined || meta.markup_pct_override === null
          ? ""
          : String(meta.markup_pct_override),
    });
    setPriceDraft(String(selectedItem.fixed_price ?? ""));
    setRequirementDraft({ key: "", quantity: 1 });
    setDynamicSaveError("");
    setDynamicSaveMessage("");
  }, [selectedItem]);

  const primaryResources = useMemo(
    () => (entities || []).filter((entry) => String(entry.type || "").toLowerCase() === PRIMARY_RESOURCE_TYPE.toLowerCase()),
    [entities]
  );

  const filteredServices = useMemo(() => {
    const q = String(serviceSearch || "").trim().toLowerCase();
    if (!q) return services;
    return services.filter((service) => String(service.name || "").toLowerCase().includes(q));
  }, [serviceSearch, services]);

  const filteredPrimaryResources = useMemo(() => {
    const q = String(primarySearch || "").trim().toLowerCase();
    if (!q) return primaryResources;
    return primaryResources.filter((entry) => String(entry.name || "").toLowerCase().includes(q));
  }, [primaryResources, primarySearch]);

  const requirementOptions = useMemo(() => {
    const merged = (allCatalogItems || []).map((entry) => ({
      key: economySourceKey(entry.source_kind, entry.source_id),
      source_kind: entry.source_kind,
      source_id: entry.source_id,
      label: `${entry.name} (${sourceKindLabel(entry.source_kind, entry)})`,
      fixed_price: Number(entry.fixed_price) || 0,
      availability: entry.meta?.availability_override || entry.entity_availability || "Common",
    }));
    const selectedSource = selectedItem ? economySourceKey(selectedItem.source_kind, selectedItem.source_id) : "";
    return merged
      .filter((entry) => entry.key !== selectedSource)
      .sort((a, b) => String(a.label).localeCompare(String(b.label)));
  }, [allCatalogItems, selectedItem]);

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

  const markupMultiplier = 1 + effectiveMarkupPct / 100;
  const dynamicPriceRaw = requirementCost * markupMultiplier;
  const dynamicPrice = Number.isFinite(dynamicPriceRaw) ? Math.round(dynamicPriceRaw) : 0;

  function goBack(fallback = "/character-manager") {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.location.assign(fallback);
  }

  async function onCreateService(event) {
    event.preventDefault();
    const name = String(serviceForm.name || "").trim();
    const fixedPrice = Number(serviceForm.fixed_price);
    if (!name || Number.isNaN(fixedPrice) || fixedPrice < 0) {
      setServiceError("Service name and valid fixed price are required.");
      return;
    }
    setServiceBusy(true);
    setServiceError("");
    try {
      const created = await createEconomyService({ name, fixed_price: fixedPrice });
      setServiceForm({ name: "", fixed_price: "" });
      await reloadEconomyData();
      const serviceId = created.service?.id || "";
      if (serviceId) {
        setSelectedKey(economySourceKey("service", serviceId));
      }
    } catch (err) {
      setServiceError(err instanceof Error ? err.message : "Unable to create service.");
    } finally {
      setServiceBusy(false);
    }
  }

  async function onDeleteService(serviceId) {
    if (!window.confirm("Delete this service?")) return;
    setServiceError("");
    try {
      await deleteEconomyService(serviceId);
      if (selectedKey === economySourceKey("service", serviceId)) {
        setSelectedKey("");
      }
      await reloadEconomyData();
    } catch (err) {
      setServiceError(err instanceof Error ? err.message : "Unable to delete service.");
    }
  }

  async function onSubmitPrimaryResource(event) {
    event.preventDefault();
    const name = String(primaryForm.name || "").trim();
    const price = Number(primaryForm.value_per_unit);
    if (!name) {
      setPrimaryError("Primary ressource name is required.");
      return;
    }
    if (Number.isNaN(price) || price < 0) {
      setPrimaryError("Price must be a number >= 0.");
      return;
    }

    const payload = {
      name,
      type: PRIMARY_RESOURCE_TYPE,
      value_per_unit: price,
      availability: primaryForm.availability || availabilities[0] || "Common",
    };

    setPrimaryBusy(true);
    setPrimaryError("");
    try {
      if (primaryForm.id) {
        await updateEconomyEntity(primaryForm.id, payload);
      } else {
        const created = await createEconomyEntity(payload);
        const newId = created.entity?.id || "";
        if (newId) {
          setSelectedKey(economySourceKey("entity", newId));
        }
      }
      setPrimaryForm({
        id: "",
        name: "",
        value_per_unit: "",
        availability: availabilities[0] || "Common",
      });
      await reloadEconomyData();
    } catch (err) {
      setPrimaryError(err instanceof Error ? err.message : "Unable to save primary ressource.");
    } finally {
      setPrimaryBusy(false);
    }
  }

  async function onDeletePrimaryResource(entityId) {
    if (!window.confirm("Delete this primary ressource?")) return;
    setPrimaryError("");
    try {
      await deleteEconomyEntity(entityId);
      if (selectedKey === economySourceKey("entity", entityId)) {
        setSelectedKey("");
      }
      if (primaryForm.id === entityId) {
        setPrimaryForm({
          id: "",
          name: "",
          value_per_unit: "",
          availability: availabilities[0] || "Common",
        });
      }
      await reloadEconomyData();
    } catch (err) {
      setPrimaryError(err instanceof Error ? err.message : "Unable to delete primary ressource.");
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
        const nextPrice = Number(priceDraft);
        if (Number.isNaN(nextPrice) || nextPrice < 0) {
          throw new Error("Service fixed price must be a number >= 0.");
        }
        await updateEconomyService(selectedItem.source_id, {
          name: selectedItem.name,
          fixed_price: nextPrice,
        });
      }

      if (selectedItem.source_kind === "entity") {
        const nextPrice = Number(priceDraft);
        if (Number.isNaN(nextPrice) || nextPrice < 0) {
          throw new Error("Primary ressource price must be a number >= 0.");
        }
        const entityDoc = (entities || []).find((entry) => String(entry.id) === String(selectedItem.source_id));
        if (!entityDoc) {
          throw new Error("Primary ressource not found.");
        }
        await updateEconomyEntity(selectedItem.source_id, {
          name: entityDoc.name,
          type: entityDoc.type,
          value_per_unit: nextPrice,
          availability: entityDoc.availability || "Common",
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

  const portalPath = "/";
  const servicesPath = "services";
  const primaryResourcesPath = "primary-ressources";

  if (busy) {
    return (
      <div className="cm-page">
        <div className="cm-wrap">
          <div className="cm-topbar">
            <h1>Economy Manager</h1>
            <button
              className="cm-btn cm-icon-btn"
              type="button"
              onClick={() => goBack("/character-manager")}
              title="Back"
              aria-label="Back"
            >
              <Icon name="fa-arrow-left" label="Back" />
            </button>
          </div>
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
            <button
              className="cm-btn cm-icon-btn"
              type="button"
              onClick={() => goBack("/character-manager")}
              title="Back"
              aria-label="Back"
            >
              <Icon name="fa-arrow-left" label="Back" />
            </button>
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
            <button
              className="cm-btn cm-icon-btn"
              type="button"
              onClick={() => goBack("/character-manager")}
              title="Back"
              aria-label="Back"
            >
              <Icon name="fa-arrow-left" label="Back" />
            </button>
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
          <button
            className="cm-btn cm-icon-btn"
            type="button"
            onClick={() => goBack("/character-manager")}
            title="Back"
            aria-label="Back"
          >
            <Icon name="fa-arrow-left" label="Back" />
          </button>
          <span className="cm-muted cm-right">{me.label}</span>
        </div>

        <Routes>
          <Route
            path={portalPath}
            element={
              <div className="cm-field-grid">
                <div className="cm-panel">
                  <h2>Managers</h2>
                  <p className="cm-muted">Manage services and primary ressources.</p>
                  <div className="cm-row">
                    <Link className="cm-btn cm-icon-btn" to={servicesPath} title="Manage Services" aria-label="Manage Services">
                      <Icon name="fa-screwdriver-wrench" label="Manage Services" />
                    </Link>
                    <Link
                      className="cm-btn cm-icon-btn"
                      to={primaryResourcesPath}
                      title="Manage Primary Ressources"
                      aria-label="Manage Primary Ressources"
                    >
                      <Icon name="fa-seedling" label="Manage Primary Ressources" />
                    </Link>
                  </div>
                </div>

                <div className="cm-economy-layout">
                  <div className="cm-panel">
                    <h2>Browse Entities</h2>
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
                          {FILTER_TYPES.map((entry) => (
                            <option key={entry.value} value={entry.value}>
                              {entry.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    {catalogBusy && <p className="cm-muted">Loading catalog...</p>}
                    {catalogError && <p className="cm-error">{catalogError}</p>}

                    <div className="cm-list">
                      {!catalogBusy && !catalogItems.length && <p className="cm-muted">No matching entities found.</p>}
                      {catalogItems.map((entry) => {
                        const key = economySourceKey(entry.source_kind, entry.source_id);
                        const onSelect = () => setSelectedKey(key);
                        const onKeyDown = (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onSelect();
                          }
                        };
                        return (
                          <div
                            key={key}
                            className={`cm-list-item cm-list-main-btn ${selectedKey === key ? "active" : ""}`}
                            role="button"
                            tabIndex={0}
                            onClick={onSelect}
                            onKeyDown={onKeyDown}
                            aria-label={`Select ${entry.name}`}
                          >
                            <div>
                              <strong>{entry.name}</strong>
                              <div className="cm-muted">{sourceKindLabel(entry.source_kind, entry)}</div>
                            </div>
                            <span className="cm-pill">{Number(entry.fixed_price || 0).toFixed(2)} Jelly</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className="cm-panel">
                    <h2>Dynamic Pricing</h2>
                    {!selectedItem && <p className="cm-muted">Select an entity to configure.</p>}
                    {selectedItem && (
                      <div className="cm-field-grid">
                        <div className="cm-inline cm-inline-space">
                          <div>
                            <strong>{selectedItem.name}</strong>
                            <div className="cm-muted">{sourceKindLabel(selectedItem.source_kind, selectedItem)}</div>
                          </div>
                          <span className="cm-badge">Dynamic price: {dynamicPrice} Jelly</span>
                        </div>

                        {selectedItem.source_kind === "service" || selectedItem.source_kind === "entity" ? (
                          <label>
                            Base Price (Jelly)
                            <input type="number" value={priceDraft} onChange={(event) => setPriceDraft(event.target.value)} />
                          </label>
                        ) : (
                          <label>
                            Base Price (Jelly)
                            <input type="number" value={Number(selectedItem.fixed_price || 0)} disabled />
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
                          <div className="cm-muted cm-subtle">Suggested availability: {defaultAvailability}</div>
                          {editorMeta.availability_override && (
                            <button
                              type="button"
                              className="cm-btn cm-icon-btn"
                              onClick={() => setEditorMeta((prev) => ({ ...prev, availability_override: "" }))}
                              title="Use Suggested Availability"
                              aria-label="Use Suggested Availability"
                            >
                              <Icon name="fa-rotate-left" label="Use Suggested Availability" />
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
                              className="cm-btn cm-icon-btn"
                              onClick={() => setEditorMeta((prev) => ({ ...prev, markup_pct_override: "" }))}
                              title="Use Suggested Markup"
                              aria-label="Use Suggested Markup"
                            >
                              <Icon name="fa-rotate-left" label="Use Suggested Markup" />
                            </button>
                          )}
                        </label>

                        <div className="cm-panel cm-panel-lite">
                          <div className="cm-inline cm-inline-space">
                            <strong>Requirements</strong>
                            <span className="cm-muted">Base sum: {requirementCost.toFixed(2)} Jelly</span>
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
                            <button
                              className="cm-btn cm-primary cm-icon-btn"
                              type="submit"
                              title="Add Requirement"
                              aria-label="Add Requirement"
                            >
                              <Icon name="fa-plus" label="Add Requirement" />
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
                                        className="cm-btn cm-danger cm-icon-btn"
                                        onClick={() => onRemoveRequirement(entry.source_kind, entry.source_id)}
                                        title="Remove Requirement"
                                        aria-label="Remove Requirement"
                                      >
                                        <Icon name="fa-trash" label="Remove Requirement" />
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
                              <span>Sum(price x qty)</span>
                              <span>{requirementCost.toFixed(2)} Jelly</span>
                            </div>
                            <div className="cm-inline cm-inline-space">
                              <span>Markup multiplier</span>
                              <span>x {markupMultiplier.toFixed(2)}</span>
                            </div>
                            <div className="cm-inline cm-inline-space">
                              <span>Markup ({effectiveMarkupPct}%)</span>
                              <span>{(dynamicPriceRaw - requirementCost).toFixed(2)} Jelly</span>
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
                          <button
                            className="cm-btn cm-primary cm-icon-btn"
                            type="button"
                            onClick={saveDynamicConfiguration}
                            disabled={dynamicSaveBusy}
                            title="Save Dynamic Pricing"
                            aria-label="Save Dynamic Pricing"
                          >
                            <Icon name={dynamicSaveBusy ? "fa-spinner" : "fa-floppy-disk"} label="Save Dynamic Pricing" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            }
          />

          <Route
            path={servicesPath}
            element={
              <div className="cm-field-grid">
                <div className="cm-row">
                  <Link className="cm-btn cm-icon-btn" to={portalPath} title="Back to Portal" aria-label="Back to Portal">
                    <Icon name="fa-house" label="Back to Portal" />
                  </Link>
                </div>

                <div className="cm-economy-layout">
                  <div className="cm-panel">
                    <h2>Create Service</h2>
                    <form className="cm-field-grid" onSubmit={onCreateService}>
                      <label>
                        Name
                        <input
                          type="text"
                          value={serviceForm.name}
                          onChange={(event) => setServiceForm((prev) => ({ ...prev, name: event.target.value }))}
                          placeholder="Service name"
                        />
                      </label>
                      <label>
                        Fixed Price (Jelly)
                        <input
                          type="number"
                          value={serviceForm.fixed_price}
                          onChange={(event) => setServiceForm((prev) => ({ ...prev, fixed_price: event.target.value }))}
                          placeholder="0"
                        />
                      </label>
                      {serviceError && <div className="cm-error">{serviceError}</div>}
                      <div className="cm-row">
                        <button
                          className="cm-btn cm-primary cm-icon-btn"
                          type="submit"
                          disabled={serviceBusy}
                          title="Create Service"
                          aria-label="Create Service"
                        >
                          <Icon name={serviceBusy ? "fa-spinner" : "fa-plus"} label="Create Service" />
                        </button>
                      </div>
                    </form>
                  </div>

                  <div className="cm-panel">
                    <h2>Services</h2>
                    <label>
                      Search
                      <input
                        type="text"
                        value={serviceSearch}
                        onChange={(event) => setServiceSearch(event.target.value)}
                        placeholder="Search services"
                      />
                    </label>
                    {!filteredServices.length && <p className="cm-muted">No services found.</p>}
                    {!!filteredServices.length && (
                      <table className="cm-table">
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>Price</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredServices.map((service) => (
                            <tr key={service.id}>
                              <td>{service.name}</td>
                              <td>{Number(service.fixed_price || 0).toFixed(2)}</td>
                              <td className="cm-table-actions">
                                <button
                                  type="button"
                                  className="cm-btn cm-danger cm-icon-btn"
                                  onClick={() => onDeleteService(service.id)}
                                  title="Delete Service"
                                  aria-label="Delete Service"
                                >
                                  <Icon name="fa-trash" label="Delete Service" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              </div>
            }
          />

          <Route
            path={primaryResourcesPath}
            element={
              <div className="cm-field-grid">
                <div className="cm-row">
                  <Link className="cm-btn cm-icon-btn" to={portalPath} title="Back to Portal" aria-label="Back to Portal">
                    <Icon name="fa-house" label="Back to Portal" />
                  </Link>
                </div>

                <div className="cm-economy-layout">
                  <div className="cm-panel">
                    <h2>{primaryForm.id ? "Update Primary Ressource" : "Create Primary Ressource"}</h2>
                    <form className="cm-field-grid" onSubmit={onSubmitPrimaryResource}>
                      <label>
                        Name
                        <input
                          type="text"
                          value={primaryForm.name}
                          onChange={(event) => setPrimaryForm((prev) => ({ ...prev, name: event.target.value }))}
                          placeholder="Primary ressource name"
                        />
                      </label>
                      <label>
                        Price (Jelly)
                        <input
                          type="number"
                          value={primaryForm.value_per_unit}
                          onChange={(event) => setPrimaryForm((prev) => ({ ...prev, value_per_unit: event.target.value }))}
                          placeholder="0"
                        />
                      </label>
                      <label>
                        Availability
                        <select
                          value={primaryForm.availability}
                          onChange={(event) => setPrimaryForm((prev) => ({ ...prev, availability: event.target.value }))}
                        >
                          {availabilities.map((entry) => (
                            <option key={entry} value={entry}>
                              {entry}
                            </option>
                          ))}
                        </select>
                      </label>
                      {primaryError && <div className="cm-error">{primaryError}</div>}
                      <div className="cm-row">
                        <button
                          className="cm-btn cm-primary cm-icon-btn"
                          type="submit"
                          disabled={primaryBusy}
                          title={primaryForm.id ? "Save Primary Ressource" : "Create Primary Ressource"}
                          aria-label={primaryForm.id ? "Save Primary Ressource" : "Create Primary Ressource"}
                        >
                          <Icon name={primaryBusy ? "fa-spinner" : primaryForm.id ? "fa-floppy-disk" : "fa-plus"} label="Save" />
                        </button>
                        {primaryForm.id && (
                          <button
                            className="cm-btn cm-icon-btn"
                            type="button"
                            onClick={() =>
                              setPrimaryForm({
                                id: "",
                                name: "",
                                value_per_unit: "",
                                availability: availabilities[0] || "Common",
                              })
                            }
                            title="Cancel Edit"
                            aria-label="Cancel Edit"
                          >
                            <Icon name="fa-xmark" label="Cancel Edit" />
                          </button>
                        )}
                      </div>
                    </form>
                  </div>

                  <div className="cm-panel">
                    <h2>Primary Ressources</h2>
                    <label>
                      Search
                      <input
                        type="text"
                        value={primarySearch}
                        onChange={(event) => setPrimarySearch(event.target.value)}
                        placeholder="Search primary ressources"
                      />
                    </label>
                    {!filteredPrimaryResources.length && <p className="cm-muted">No primary ressources found.</p>}
                    {!!filteredPrimaryResources.length && (
                      <table className="cm-table">
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>Price</th>
                            <th>Availability</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredPrimaryResources.map((entry) => (
                            <tr key={entry.id}>
                              <td>{entry.name}</td>
                              <td>{Number(entry.value_per_unit || 0).toFixed(2)}</td>
                              <td>{entry.availability || "Common"}</td>
                              <td className="cm-table-actions">
                                <button
                                  type="button"
                                  className="cm-btn cm-icon-btn"
                                  onClick={() =>
                                    setPrimaryForm({
                                      id: entry.id,
                                      name: entry.name,
                                      value_per_unit: String(entry.value_per_unit ?? ""),
                                      availability: entry.availability || availabilities[0] || "Common",
                                    })
                                  }
                                  title="Edit Primary Ressource"
                                  aria-label="Edit Primary Ressource"
                                >
                                  <Icon name="fa-pen" label="Edit Primary Ressource" />
                                </button>
                                <button
                                  type="button"
                                  className="cm-btn cm-danger cm-icon-btn"
                                  onClick={() => onDeletePrimaryResource(entry.id)}
                                  title="Delete Primary Ressource"
                                  aria-label="Delete Primary Ressource"
                                >
                                  <Icon name="fa-trash" label="Delete Primary Ressource" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              </div>
            }
          />

          <Route path="primary-resources" element={<Navigate to={primaryResourcesPath} replace />} />
          <Route path="economy-tab" element={<Navigate to={portalPath} replace />} />
          <Route path="dynamic-pricing" element={<Navigate to={portalPath} replace />} />
          <Route path="dynamic-price" element={<Navigate to={portalPath} replace />} />
          <Route path="configure-economy" element={<Navigate to={primaryResourcesPath} replace />} />
          <Route path="*" element={<Navigate to={portalPath} replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default EconomyManagerPage;
