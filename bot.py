import os
from collections import defaultdict
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC = os.getenv("SOURCE_CHANNEL", "").strip()
DST = os.getenv("TARGET_CHANNEL", "").strip()
if not BOT_TOKEN or not SRC or not DST:
    raise SystemExit("Set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Variables.")

# Accept @handle, t.me link, or -100... id
def norm(x: str) -> str:
    x = x.strip()
    if x.startswith("https://t.me/"): x = x.split("https://t.me/")[-1]
    if x.startswith("@"): x = x[1:]
    return x

async def resolve_id(bot, raw: str) -> int:
    raw = raw.strip()
    if raw.startswith("-100") or raw.lstrip("-").isdigit():
        return int(raw)
    chat = await bot.get_chat(norm(raw))
    return int(chat.id)

album = defaultdict(list)
ALBUM_DELAY = 0.8  # seconds

async def flush_album(context: ContextTypes.DEFAULT_TYPE, mgid: str, target_id: int):
    msgs = album.pop(mgid, [])
    if not msgs: return
    media = []
    for m in msgs:
        cap = m.caption if not media else None
        if m.photo:
            media.append(InputMediaPhoto(m.photo[-1].file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.video:
            media.append(InputMediaVideo(m.video.file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.document:
            media.append(InputMediaDocument(m.document.file_id, caption=cap, parse_mode=ParseMode.HTML))
    if media:
        await context.bot.send_media_group(chat_id=target_id, media=media)

SOURCE_ID = None
TARGET_ID = None

async def on_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SOURCE_ID, TARGET_ID
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.id != SOURCE_ID:
        return

    if msg.media_group_id:
        album[msg.media_group_id].append(msg)
        context.job_queue.run_once(
            lambda c: context.application.create_task(flush_album(context, msg.media_group_id, TARGET_ID)),
            when=ALBUM_DELAY,
            name=f"flush_{msg.media_group_id}"
        )
        return

    await context.bot.copy_message(
        chat_id=TARGET_ID,
        from_chat_id=SOURCE_ID,
        message_id=msg.message_id,
    )

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    global SOURCE_ID, TARGET_ID
    SOURCE_ID = await resolve_id(app.bot, SRC)
    TARGET_ID = await resolve_id(app.bot, DST)
    print(f"Resolved SOURCE_ID={SOURCE_ID}, TARGET_ID={TARGET_ID}")
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel))
    print("Bot is running.")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
