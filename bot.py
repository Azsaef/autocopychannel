import asyncio
import os
from collections import defaultdict

from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.ext import (
    Application, AIORateLimiter,
    ChannelPostHandler, EditedChannelPostHandler,
    ContextTypes
)

# =====================
# Config via ENV VARS
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()

if not BOT_TOKEN or not SOURCE_CHANNEL or not TARGET_CHANNEL:
    raise SystemExit("❌ Please set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in Railway Variables.")

# Buffer untuk media album
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


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return

    # Pastikan betul channel source
    if str(msg.chat.username).lower() != str(SOURCE_CHANNEL).replace("@", "").lower():
        if str(msg.chat.id) != SOURCE_CHANNEL:
            return

    # Handle album
    if msg.media_group_id:
        album_buffer[msg.media_group_id].append(msg)
        context.job_queue.run_once(
            lambda c: asyncio.create_task(flush_album(context, msg.media_group_id)),
            when=ALBUM_DELAY_SEC,
            name=f"flush_{msg.media_group_id}"
        )
        return

    # Copy biasa
    try:
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except Exception as e:
        print("❌ Copy failed:", e)


async def on_edited_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_channel_post
    if not msg:
        return

    try:
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except Exception as e:
        print("❌ Edited copy failed:", e)


def main():
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()

    app.add_handler(ChannelPostHandler(on_channel_post))
    app.add_handler(EditedChannelPostHandler(on_edited_channel_post))

    print("✅ Bot is running (polling).")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
