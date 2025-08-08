import os
import json
import uvicorn
import sys
from fastapi import FastAPI, Request

from src.objects.effects import load_effect
from src.objects.spells import Spell

# Create app instance
app = FastAPI()

# Absolute path to /data/effects regardless of run location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EFFECTS_DIR = os.path.join(BASE_DIR, "..", "data", "effects")

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
        effect_ids = body.get("effects", [])
        effects = [load_effect(eid) for eid in effect_ids]

        mp_cost, en_cost = Spell.compute_cost(
            range_val=range_val,
            aoe_val=aoe_val,
            duration_val=duration_val,
            activation_val=activation_val,
            effects=effects
        )
        return {"mp_cost": mp_cost, "en_cost": en_cost}

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # Run this file directly → dynamically use this file's app
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)