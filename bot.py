import asyncio
import os
from collections import defaultdict
from contextlib import suppress

from aiohttp import web
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.ext import (
    Application, AIORateLimiter,
    ChannelPostHandler, EditedChannelPostHandler,
    ContextTypes
)

# =====================
# Config dari ENV VARS
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()

if not BOT_TOKEN or not SOURCE_CHANNEL or not TARGET_CHANNEL:
    raise SystemExit("❌ Please set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Railway Variables.")

# ---- Keepalive HTTP server (supaya Railway anggap healthy) ----
async def handle_root(request):
    return web.Response(text="ok")

async def start_keepalive_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Keepalive server listening on :{port}")

# ---- Album buffer ----
album_buffer = defaultdict(list)
ALBUM_DELAY_SEC = 0.8

async def flush_album(context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    msgs = album_buffer.pop(media_group_id, [])
    if not msgs:
        return
    media = []
    for m in msgs:
        cap = m.caption if not media else None
        if m.photo:
            media.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.video:
            media.append(InputMediaVideo(media=m.video.file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.document:
            media.append(InputMediaDocument(media=m.document.file_id, caption=cap, parse_mode=ParseMode.HTML))
    if media:
        await context.bot.send_media_group(chat_id=TARGET_CHANNEL, media=media)

def _match_source(msg_chat_username: str | None, msg_chat_id: int) -> bool:
    if SOURCE_CHANNEL.startswith("@"):
        want = SOURCE_CHANNEL.replace("@", "").lower()
        return (msg_chat_username or "").lower() == want
    else:
        return str(msg_chat_id) == SOURCE_CHANNEL

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    if not _match_source(msg.chat.username, msg.chat.id):
        return
    if msg.media_group_id:
        album_buffer[msg.media_group_id].append(msg)
        context.job_queue.run_once(
            lambda c: asyncio.create_task(flush_album(context, msg.media_group_id)),
            when=ALBUM_DELAY_SEC,
            name=f"flush_{msg.media_group_id}"
        )
        return
    try:
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except Exception as e:
        print("❌ Copy failed:", repr(e))

async def on_edited_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_channel_post
    if not msg:
        return
    if not _match_source(msg.chat.username, msg.chat.id):
        return
    with suppress(Exception):
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )

async def run_bot_forever():
    # Start keepalive HTTP server
    await start_keepalive_server()

    # Resilient polling loop
    while True:
        try:
            app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
            app.add_handler(ChannelPostHandler(on_channel_post))
            app.add_handler(EditedChannelPostHandler(on_edited_channel_post))
            print("✅ Bot is running (polling).")
            await app.run_polling(close_loop=True, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        except Exception as e:
            print("⚠️ Polling crashed:", repr(e))
            await asyncio.sleep(3)  # retry selepas 3s

def main():
    try:
        asyncio.run(run_bot_forever())
    except KeyboardInterrupt:
        print("Shutting down.")

if __name__ == "__main__":
    main()
