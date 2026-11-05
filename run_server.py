import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1")
    print(f"\nServer starting at: http://127.0.0.1:{port} (or http://localhost:{port})\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)

