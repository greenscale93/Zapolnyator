import uvicorn
from fastapi import FastAPI
from src.api import router
from src.mapping_store import init_db

app = FastAPI()
app.include_router(router)

@app.on_event("startup")
async def startup():
    init_db()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)