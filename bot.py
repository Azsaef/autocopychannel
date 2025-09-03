import asyncio
import os
from collections import defaultdict
from contextlib import suppress

from aiohttp import web
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, Forbidden
from telegram.ext import (
    Application, AIORateLimiter,
    ChannelPostHandler, EditedChannelPostHandler,
    ContextTypes
)

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC_RAW = os.getenv("SOURCE_CHANNEL", "").strip()
DST_RAW = os.getenv("TARGET_CHANNEL", "").strip()

if not BOT_TOKEN or not SRC_RAW or not DST_RAW:
    raise SystemExit("❌ Please set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Railway Variables.")

# ========= Keepalive HTTP (so Railway keeps it alive) =========
async def _ok(_):
    return web.Response(text="ok")

async def start_keepalive():
    app = web.Application()
    app.router.add_get("/", _ok)
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Keepalive server on :{port}")

# ========= Helpers =========
def _normalize_handle(x: str) -> str:
    x = x.strip()
    if x.startswith("https://t.me/"):
        x = x.split("https://t.me/")[-1]
    if x.startswith("@"):
        x = x[1:]
    return x

async def resolve_chat_id(bot, raw: str) -> int:
    """
    Accepts:
      - @handle
      - https://t.me/handle
      - -100xxxxxxxxxxxx (already numeric)
    Returns numeric chat_id (int). Raises if not resolvable / bot missing access.
    """
    raw = raw.strip()
    # already numeric id?
    if raw.startswith("-100") or raw.lstrip("-").isdigit():
        return int(raw)

    handle = _normalize_handle(raw)
    chat = await bot.get_chat(handle)  # requires bot to have access (admin/member)
    return int(chat.id)

# ========= Album buffer =========
album_buffer = defaultdict(list)
ALBUM_DELAY_SEC = 0.8

async def flush_album(context: ContextTypes.DEFAULT_TYPE, media_group_id: str, target_id: int):
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
        await context.bot.send_media_group(chat_id=target_id, media=media)

# ========= Handlers (filled later after IDs resolved) =========
SOURCE_ID: int | None = None
TARGET_ID: int | None = None

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.channel_post
        if not msg:
            return
        if msg.chat.id != SOURCE_ID:
            return

        if msg.media_group_id:
            album_buffer[msg.media_group_id].append(msg)
            context.job_queue.run_once(
                lambda c: asyncio.create_task(flush_album(context, msg.media_group_id, TARGET_ID)),
                when=ALBUM_DELAY_SEC,
                name=f"flush_{msg.media_group_id}"
            )
            return

        await context.bot.copy_message(
            chat_id=TARGET_ID,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except (BadRequest, Forbidden) as e:
        # Most common: chat not found / bot not admin
        print(f"❌ Handler BadRequest/Forbidden: {e}")
    except Exception as e:
        print(f"❌ Handler error: {e!r}")

async def on_edited_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.edited_channel_post
        if not msg or msg.chat.id != SOURCE_ID:
            return
        with suppress(Exception):
            await context.bot.copy_message(
                chat_id=TARGET_ID,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id,
            )
    except Exception as e:
        print(f"❌ Edited handler error: {e!r}")

# ========= Runner =========
async def run_bot():
    await start_keepalive()

    # Build app first to get bot instance for resolving IDs
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()

    # Resolve IDs
    global SOURCE_ID, TARGET_ID
    SOURCE_ID = await resolve_chat_id(app.bot, SRC_RAW)
    TARGET_ID = await resolve_chat_id(app.bot, DST_RAW)
    print(f"✅ Resolved SOURCE_ID={SOURCE_ID}, TARGET_ID={TARGET_ID}")

    # Register handlers
    app.add_handler(ChannelPostHandler(on_channel_post))
    app.add_handler(EditedChannelPostHandler(on_edited_channel_post))

    print("✅ Bot is running (polling).")
    await app.run_polling(
        close_loop=True,
        allowed_updates=["channel_post", "edited_channel_post"],
        drop_pending_updates=True
    )

async def main():
    # resilient loop
    while True:
        try:
            await run_bot()
        except TelegramError as e:
            print(f"⚠️ TelegramError: {e}. Retry in 3s.")
        except Exception as e:
            print(f"⚠️ Crash: {e!r}. Retry in 3s.")
        await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bye")
