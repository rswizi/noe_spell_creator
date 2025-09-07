from db_mongo import norm_key

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
    }