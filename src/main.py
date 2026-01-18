from fastapi import FastAPI
from web import explorer

app = FastAPI()

app.include_router(explorer.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "FastAPI Learning App"}