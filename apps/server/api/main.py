"""
Phase 0 REST API skeleton.

This intentionally stores documents in memory and uses a fake login with no
password check - it exists so the client has something to talk to while the
editor and realtime sync are wired up. Replace before Phase 1:

  - Swap the in-memory `_documents` dict for real SQLAlchemy models against
    Postgres (see docs/requirements.md for the schema).
  - Swap the login stub for real auth (FastAPI-Users or Authlib), issuing a
    verifiable JWT rather than a fake token string.
  - Add the document_permissions checks described in README "Permissions &
    access control" to every endpoint below - right now everything is wide
    open on purpose, to keep Phase 0 simple.
"""

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Syncronix API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Auth (stub) -----------------------------------------------------------

class LoginRequest(BaseModel):
    email: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    display_name: str


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    # Dev-only: no password check, deterministic fake user id from the email.
    fake_user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, payload.email))
    return LoginResponse(
        token=f"dev-token-{fake_user_id}",
        user_id=fake_user_id,
        display_name=payload.email.split("@")[0],
    )


# --- Documents (in-memory stub) ---------------------------------------------

_documents: dict[str, dict] = {}


class CreateDocumentRequest(BaseModel):
    title: str
    owner_id: str


@app.post("/documents")
def create_document(payload: CreateDocumentRequest):
    doc_id = str(uuid.uuid4())
    _documents[doc_id] = {
        "id": doc_id,
        "title": payload.title,
        "owner_id": payload.owner_id,
    }
    return _documents[doc_id]


@app.get("/documents")
def list_documents():
    return list(_documents.values())


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc
