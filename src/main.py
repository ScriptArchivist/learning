# src/main.py
from fastapi import FastAPI
from web.explorer import router


app = FastAPI()
app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "FastAPI Learning App"}