from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from router.server.lifespan import lifespan

app = FastAPI(title="free-claw-router", lifespan=lifespan)

@app.get("/health")
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "catalog_version": request.app.state.catalog_version,
    })

@app.post("/v1/chat/completions")
async def chat_completions(payload: dict) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "error": {
                "code": "not_implemented",
                "message": "chat.completions not wired yet",
            }
        },
    )
