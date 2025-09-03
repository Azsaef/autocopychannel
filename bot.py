import os
from collections import defaultdict
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SRC = os.getenv("SOURCE_CHANNEL", "").strip()   # use -100... (numeric)
DST = os.getenv("TARGET_CHANNEL", "").strip()   # use -100... (numeric)
if not BOT_TOKEN or not SRC or not DST:
    raise SystemExit("❌ Set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Variables.")

SOURCE_ID = int(SRC)
TARGET_ID = int(DST)

album = defaultdict(list)
ALBUM_DELAY = 0.8

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
        print(f"📤 Sending media group ({len(media)} items) → {TARGET_ID}")
        await context.bot.send_media_group(chat_id=TARGET_ID, media=media)

async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Log what we receive so we know if the handler is firing
    if update.channel_post:
        msg = update.channel_post
        print(f"📥 Received channel_post id={msg.message_id} chat_id={msg.chat.id}")
    elif update.edited_channel_post:
        msg = update.edited_channel_post
        print(f"✏️ Received edited_channel_post id={msg.message_id} chat_id={msg.chat.id}")
    else:
        # ignore non-channel updates
        return

    msg = update.channel_post or update.edited_channel_post
    if msg.chat.id != SOURCE_ID:
        # not from our source channel; ignore
        return

    try:
        if msg.media_group_id:
            album[msg.media_group_id].append(msg)
            # schedule flush once the group completes
            context.job_queue.run_once(
                lambda c: context.application.create_task(flush_album(context, msg.media_group_id)),
                when=ALBUM_DELAY,
                name=f"flush_{msg.media_group_id}"
            )
            return

        print(f"➡️ Copying message {msg.message_id} from {SOURCE_ID} → {TARGET_ID}")
        await context.bot.copy_message(
            chat_id=TARGET_ID,
            from_chat_id=SOURCE_ID,
            message_id=msg.message_id,
        )
        print("✅ Copied.")
    except (BadRequest, Forbidden) as e:
        print(f"❌ Copy error: {e}")
    except Exception as e:
        print(f"❌ Handler error: {e!r}")

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    # Listen to ALL updates and filter manually in handler
    app.add_handler(MessageHandler(filters.ALL, handler))
    print(f"✅ Bot is running. Listening to all updates. SOURCE_ID={SOURCE_ID} TARGET_ID={TARGET_ID}")
    await app.run_polling(drop_pending_updates=True, allowed_updates=["channel_post", "edited_channel_post", "message", "edited_message"])

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
