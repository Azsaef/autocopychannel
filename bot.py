import asyncio
import os
from collections import defaultdict

from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC_RAW = os.getenv("SOURCE_CHANNEL", "").strip()
DST_RAW = os.getenv("TARGET_CHANNEL", "").strip()
if not BOT_TOKEN or not SRC_RAW or not DST_RAW:
    raise SystemExit("❌ Set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Variables.")

# ---------- helpers ----------
def is_numeric_id(x: str) -> bool:
    x = x.strip()
    return x.startswith("-100") or x.lstrip("-").isdigit()

def norm_handle(x: str) -> str:
    x = x.strip()
    if x.startswith("https://t.me/"): x = x.split("https://t.me/")[-1]
    if x.startswith("@"): x = x[1:]
    return x

async def resolve_id(bot, raw: str) -> int:
    """Return numeric chat_id. Accepts -100..., @handle, or t.me link."""
    raw = raw.strip()
    if is_numeric_id(raw):
        return int(raw)
    chat = await bot.get_chat(norm_handle(raw))
    return int(chat.id)

album = defaultdict(list)
ALBUM_DELAY = 0.8

SOURCE_ID = None
TARGET_ID = None

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

async def run_once():
    global SOURCE_ID, TARGET_ID
    app = Application.builder().token(BOT_TOKEN).build()

    # Resolve SOURCE
    try:
        SOURCE_ID = await resolve_id(app.bot, SRC_RAW)
    except Forbidden as e:
        print(f"❌ Bot has no access to SOURCE ({SRC_RAW}). Make the bot Admin. Detail: {e}")
        await asyncio.sleep(10);  return
    except BadRequest as e:
        print(f"❌ SOURCE invalid ({SRC_RAW}). Use correct @handle or -100ID. Detail: {e}")
        await asyncio.sleep(10);  return

    # Resolve TARGET
    try:
        TARGET_ID = await resolve_id(app.bot, DST_RAW)
    except Forbidden as e:
        print(f"❌ Bot has no access to TARGET ({DST_RAW}). Make the bot Admin. Detail: {e}")
        await asyncio.sleep(10);  return
    except BadRequest as e:
        print(f"❌ TARGET invalid ({DST_RAW}). Use correct @handle or -100ID. Detail: {e}")
        await asyncio.sleep(10);  return

    print(f"✅ Resolved SOURCE_ID={SOURCE_ID}, TARGET_ID={TARGET_ID}")
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel))
    print("✅ Bot is running.")
    await app.run_polling(drop_pending_updates=True, allowed_updates=["channel_post"])

async def main():
    while True:
        try:
            await run_once()
        except TelegramError as e:
            print(f"⚠️ TelegramError: {e} → retry in 3s")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"⚠️ Crash: {e!r} → retry in 3s")
            await asyncio.sleep(3)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
