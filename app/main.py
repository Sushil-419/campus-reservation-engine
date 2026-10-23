import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Resource Reservation Engine",
    description="Multi-User Resource Reservation & Scheduling Engine — KLE Tech, Team 16",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
from app.routers import auth, resources, bookings  # noqa: E402

app.include_router(auth.router)
app.include_router(resources.router)
app.include_router(bookings.router)

@app.get("/health")
def health():
    return {"status": "ok"}

# Serve frontend static files (must be last — catches all unmatched routes)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
