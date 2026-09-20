"""
Syncronix REST API.

Auth and user endpoints are now real: Postgres-backed via SQLAlchemy,
hashed passwords, JWT access/refresh tokens with Redis-backed revocation.
See security.py, routers/auth.py, routers/users.py.

Document endpoints are still the Phase 0 in-memory stub below - they don't
survive a restart and have no permission checks yet. That's next: replace
`_documents` with the `Document`/`DocumentPermission` models from
docs/requirements.md and add the require_role() checks described in the
README "Permissions & access control" section.
"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import init_models
from routers import auth, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1 shortcut: create tables straight from the models instead of
    # running migrations - see database.py for why this isn't the long-term
    # answer.
    await init_models()
    yield


app = FastAPI(title="Syncronix API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Documents (still an in-memory stub) ------------------------------------

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
