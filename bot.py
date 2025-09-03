import os
from collections import defaultdict

from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, MessageHandler, ContextTypes, filters

# ==== ENV (must be numeric -100... ids) ====
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC = os.getenv("SOURCE_CHANNEL", "").strip()
DST = os.getenv("TARGET_CHANNEL", "").strip()
if not BOT_TOKEN or not SRC or not DST:
    raise SystemExit("❌ Set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Variables.")

try:
    SOURCE_ID = int(SRC)
    TARGET_ID = int(DST)
except ValueError:
    raise SystemExit("❌ Use numeric channel IDs (e.g., -1001234567890), not @handles/URLs.")

album = defaultdict(list)
ALBUM_DELAY = 0.8  # seconds

async def flush_album(context: ContextTypes.DEFAULT_TYPE, mgid: str):
    msgs = album.pop(mgid, [])
    if not msgs:
        return
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
        await context.bot.send_media_group(chat_id=TARGET_ID, media=media)

async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Accept channel_post + edited_channel_post (we'll copy only new posts)
    msg = update.channel_post or update.edited_channel_post
    if not msg or msg.chat.id != SOURCE_ID:
        return

    try:
        if msg.media_group_id:
            album[msg.media_group_id].append(msg)
            context.job_queue.run_once(
                lambda c: context.application.create_task(flush_album(context, msg.media_group_id)),
                when=ALBUM_DELAY,
                name=f"flush_{msg.media_group_id}"
            )
            return

        # Copy (no "Forwarded from" label)
        await context.bot.copy_message(
            chat_id=TARGET_ID,
            from_chat_id=SOURCE_ID,
            message_id=msg.message_id,
        )
    except (BadRequest, Forbidden) as e:
        print(f"❌ Copy error: {e}")
    except Exception as e:
        print(f"❌ Handler error: {e!r}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    # Listen to ALL updates; we filter inside the handler
    app.add_handler(MessageHandler(filters.ALL, handler))
    print(f"✅ Bot is running. SOURCE_ID={SOURCE_ID} TARGET_ID={TARGET_ID}")
    # Synchronous/blocking; PTB manages the event loop — no asyncio.run(), no retries needed
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["channel_post", "edited_channel_post", "message", "edited_message"],
        close_loop=False,  # don't try to close host loop (defensive)
    )

if __name__ == "__main__":
    main()
