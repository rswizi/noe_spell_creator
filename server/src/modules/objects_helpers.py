from db_mongo import norm_key


def _modifiers_from_body(b: dict) -> list[dict]:
    mods_in = (b or {}).get("modifiers") or []
    if not isinstance(mods_in, list):
        return []
    mods: list[dict] = []
    for m in mods_in:
        if not isinstance(m, dict): continue
        target = (m.get("target") or m.get("key") or "").strip()
        if not target: continue
        mode = (m.get("mode") or "add").lower()
        if mode not in ("add","mul","set"): mode = "add"
        try: value = float(m.get("value") or 0)
        except Exception: value = 0.0
        note = (m.get("note") or "").strip()
        mods.append({"target": target, "mode": mode, "value": value, "note": note})
    return mods

def _object_from_body(b: dict) -> dict:
    name = (b.get("name") or "").strip() or "Unnamed"
    price = int(b.get("price") or 0)
    enc   = int(b.get("enc") or 0)
    desc  = (b.get("description") or "").strip()
    return {
        "name": name,
        "name_key": norm_key(name),
        "price": price,
        "enc": enc,
        "description": desc,
        "modifiers": _modifiers_from_body(b),
    }
