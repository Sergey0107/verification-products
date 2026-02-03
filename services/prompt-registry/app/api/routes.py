from fastapi import APIRouter, HTTPException

from app.services.prompt_store import list_prompt_summaries, resolve_prompt

router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True}


@router.get("/prompts")
async def list_prompts():
    return {"items": list_prompt_summaries()}


@router.get("/prompts/{file_type}")
async def get_prompt(file_type: str):
    try:
        return resolve_prompt(file_type)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown file type")
