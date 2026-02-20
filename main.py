from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64
import json
from typing import List, Dict, Any
import uvicorn
import os

app = FastAPI(title="AI-EDA Bridge", version="1.1")

# === CONFIGURATION SÉCURITÉ ===
API_KEY = os.getenv("API_KEY")  # À définir sur Render

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

# CORS pour ChatGPT + ton frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================== MODÈLES ======================
class Command(BaseModel):
    type: str
    payload: Dict[str, Any]

class PatchRequest(BaseModel):
    project_base64: str          # .epro encodé en base64
    commands: List[Command]

class PatchResponse(BaseModel):
    patched_project_base64: str
    log: List[str]
    success: bool

# ====================== ROUTES ======================
@app.get("/health")
async def health():
    return {"ok": True, "service": "ai_eda_bridge", "version": "1.1"}

@app.post("/schematic/patch", response_model=PatchResponse, dependencies=[Depends(verify_api_key)])
async def patch_schematic(request: PatchRequest):
    try:
        # Décodage du projet
        project_bytes = base64.b64decode(request.project_base64)
        project = json.loads(project_bytes.decode('utf-8')) if project_bytes.startswith(b'{') else project_bytes

        # Ici tu appelles ta logique existante (protocol + handlers)
        # Pour l'instant on simule (à remplacer par ton vrai moteur)
        log = ["[AI-EDA] Received patch request with {} commands".format(len(request.commands))]

        # Exemple : on renvoie le même projet pour le moment
        patched_project = project  # ← REMPLACE PAR TON VRAI update_schema

        patched_base64 = base64.b64encode(
            json.dumps(patched_project).encode('utf-8') if isinstance(patched_project, dict) else patched_project
        ).decode('utf-8')

        return PatchResponse(
            patched_project_base64=patched_base64,
            log=log,
            success=True
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/openapi.yaml")
async def get_openapi():
    return app.openapi()

# ====================== LANCEMENT ======================
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
