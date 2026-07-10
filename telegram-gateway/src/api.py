from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from aiogram import Bot
import os

router = APIRouter(prefix="/internal")

class SendMessageRequest(BaseModel):
    user_id: int
    text: str

@router.post("/send_message")
async def send_message(request: SendMessageRequest):
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    try:
        await bot.send_message(chat_id=request.user_id, text=request.text)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))