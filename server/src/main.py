import os
import json
import uvicorn
import sys
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.objects.effects import load_effect
from src.objects.spells import Spell

# Create app instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Absolute path to /data/effects regardless of run location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EFFECTS_DIR = os.path.join(BASE_DIR, "..", "data", "effects")
SPELLS_DIR = os.path.join(BASE_DIR, "..", "data", "spells")
os.makedirs(SPELLS_DIR, exist_ok=True)

def get_next_spell_id() -> str:
    """Find the highest numeric ID in /data/spells and return next one as zero-padded string."""
    existing_ids = []
    for fname in os.listdir(SPELLS_DIR):
        if fname.endswith(".json"):
            try:
                existing_ids.append(int(os.path.splitext(fname)[0]))
            except ValueError:
                continue
    next_id = (max(existing_ids) + 1) if existing_ids else 0
    return f"{next_id:04d}"

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/effects")
def get_effects():
    effects = []
    for filename in os.listdir(EFFECTS_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(EFFECTS_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    effect = json.load(f)
                    effects.append(effect)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
    return {"effects": effects}

@app.post("/costs")
async def get_costs(request: Request):
    try:
        body = await request.json()
        range_val = body.get("range")
        aoe_val = body.get("aoe")
        duration_val = body.get("duration")
        activation_val = body.get("activation")
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]

        effects = [load_effect(eid) for eid in effect_ids]

        # Build a temp spell so it uses set_* methods and your cost_utils correctly
        temp = Spell(
            id="__preview__",
            name="__preview__",
            activation=activation_val,
            range=range_val,
            aoe=aoe_val,
            duration=duration_val,
            effects=effects
        )
        # Make sure update + category run (post_init usually does, but be explicit)
        temp.update_cost()
        temp.set_spell_category()

        return {
            "mp_cost": temp.mp_cost,
            "en_cost": temp.en_cost,
            "category": temp.category
        }
    except Exception as e:
        # Keep 200 for now, but return an error key so the UI can show it
        return {"error": str(e)}


@app.post("/submit_spell")
async def submit_spell(request: Request):
    try:
        body = await request.json()
        name = body.get("name") or "Unnamed Spell"
        activation = body.get("activation")
        range_val = body.get("range")
        aoe_val = body.get("aoe")
        duration_val = body.get("duration")
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]

        effects = [load_effect(eid) for eid in effect_ids]

        # Auto-generate numeric ID
        spell_id = get_next_spell_id()

        spell = Spell(
            id=spell_id,
            name=name,
            activation=activation,
            range=range_val,
            aoe=aoe_val,
            duration=duration_val,
            effects=effects,
        )
        spell.update_cost()
        spell.set_spell_category()
        spell.save()

        return {"status": "success", "id": spell.id, "saved": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)