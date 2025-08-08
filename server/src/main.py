import os
import json
from fastapi import FastAPI

app = FastAPI()

EFFECTS_DIR = os.path.join("server", "data", "effects")

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/effects")
def get_effects():
    effects = []

    # Loop through all .json files in the effects directory
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