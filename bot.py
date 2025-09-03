import asyncio
import os
from collections import defaultdict

from aiohttp import web
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, MessageHandler, ContextTypes, filters

# ====== ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC_RAW = os.getenv("SOURCE_CHANNEL", "").strip()
DST_RAW = os.getenv("TARGET_CHANNEL", "").strip()
if not BOT_TOKEN or not SRC_RAW or not DST_RAW:
    raise SystemExit("❌ Set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Variables.")

# ====== Keepalive (start once, web mode) ======
async def _ok(_): return web.Response(text="ok")
async def start_keepalive_once():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", _ok)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Keepalive on :{port}")

# ====== Helpers ======
def _normalize_handle(x: str) -> str:
    x = x.strip()
    if x.startswith("https://t.me/"): x = x.split("https://t.me/")[-1]
    if x.startswith("@"): x = x[1:]
    return x

async def resolve_chat_id(bot, raw: str) -> int:
    """Return numeric chat_id. Accepts -100..., @handle, or t.me link."""
    raw = raw.strip()
    if raw.startswith("-100") or raw.lstrip("-").isdigit():
        return int(raw)
    handle = _normalize_handle(raw)
    # This will fail if bot tiada akses/admin di channel itu.
    chat = await bot.get_chat(handle)
    return int(chat.id)

# ====== Album buffer ======
album = defaultdict(list)
ALBUM_DELAY = 0.8

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
    try:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat or chat.id != SOURCE_ID:
            return

        if msg.media_group_id:
            album[msg.media_group_id].append(msg)
            context.job_queue.run_once(
                lambda c: context.application.create_task(
                    flush_album(context, msg.media_group_id, TARGET_ID)
                ),
                when=ALBUM_DELAY,
                name=f"flush_{msg.media_group_id}"
            )
            return

        await context.bot.copy_message(
            chat_id=TARGET_ID,
            from_chat_id=SOURCE_ID,
            message_id=msg.message_id,
        )
    except (BadRequest, Forbidden) as e:
        print(f"❌ Copy error: {e}")
    except Exception as e:
        print(f"❌ Handler error: {e!r}")

async def build_and_run():
    global SOURCE_ID, TARGET_ID
    app = Application.builder().token(BOT_TOKEN).build()

    # Resolve dengan diagnostics yang jelas
    try:
        SOURCE_ID = await resolve_chat_id(app.bot, SRC_RAW)
    except Forbidden as e:
        raise SystemExit(f"❌ Bot tiada akses ke SOURCE ({SRC_RAW}). Pastikan bot Admin. Details: {e}")
    except BadRequest as e:
        raise SystemExit(f"❌ SOURCE invalid ({SRC_RAW}). Guna @handle yang betul atau -100ID. Details: {e}")

    try:
        TARGET_ID = await resolve_chat_id(app.bot, DST_RAW)
    except Forbidden as e:
        raise SystemExit(f"❌ Bot tiada akses ke TARGET ({DST_RAW}). Pastikan bot Admin. Details: {e}")
    except BadRequest as e:
        raise SystemExit(f"❌ TARGET invalid ({DST_RAW}). Guna @handle yang betul atau -100ID. Details: {e}")

    print(f"✅ Resolved SOURCE_ID={SOURCE_ID}, TARGET_ID={TARGET_ID}")

    # Listen only to channel posts
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel))

    print("✅ Bot is running.")
    await app.run_polling(drop_pending_updates=True, allowed_updates=["channel_post"])

async def main():
    await start_keepalive_once()  # start once
    while True:
        try:
            await build_and_run()
        except TelegramError as e:
            print(f"⚠️ TelegramError: {e} → retry in 3s")
        except SystemExit as e:
            # Misconfig yang kita dah explain → jangan loop laju, bagi masa baca log
            print(str(e))
            await asyncio.sleep(20)
        except Exception as e:
            print(f"⚠️ Crash: {e!r} → retry in 3s")
            await asyncio.sleep(3)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
