from fastapi import FastAPI

app = FastAPI(title="RA1 Backend", version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok"}