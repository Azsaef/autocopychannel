
import asyncio
import os
from collections import defaultdict

from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.constants import ParseMode
from telegram.ext import (
    Application, AIORateLimiter,
    ChannelPostHandler, MessageHandler,
    filters, ContextTypes
)

# =====================
# Config via ENV VARS
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# You can use either numeric chat_id (e.g. -1001234567890) or a public @username
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "").strip()  # e.g. @Azsaef
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()  # e.g. @crypto

if not BOT_TOKEN or not SOURCE_CHANNEL or not TARGET_CHANNEL:
    raise SystemExit("ERROR: Please set BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL in environment variables (or .env file).")

# Buffer for media albums
album_buffer = defaultdict(list)
ALBUM_DELAY_SEC = 0.8  # small delay to gather all items of an album


async def flush_album(context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    """Send the collected media group to TARGET_CHANNEL."""
    msgs = album_buffer.pop(media_group_id, [])
    if not msgs:
        return

    media = []
    for m in msgs:
        cap = m.caption if not media else None  # caption only on first item
        if m.photo:
            media.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.video:
            media.append(InputMediaVideo(media=m.video.file_id, caption=cap, parse_mode=ParseMode.HTML))
        elif m.document:
            media.append(InputMediaDocument(media=m.document.file_id, caption=cap, parse_mode=ParseMode.HTML))

    if media:
        await context.bot.send_media_group(chat_id=TARGET_CHANNEL, media=media)


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mirror any new post from SOURCE_CHANNEL to TARGET_CHANNEL via copy (no 'Forwarded from')."""
    msg = update.channel_post
    if not msg:
        return

    # Only mirror from the designated source channel
    if str(msg.chat.username).lower() != str(SOURCE_CHANNEL).replace("@", "").lower():
        # If you prefer to support numeric chat_id comparison:
        if str(msg.chat.id) != SOURCE_CHANNEL:
            return

    # Handle media albums
    if msg.media_group_id:
        album_buffer[msg.media_group_id].append(msg)
        # schedule a flush
        context.job_queue.run_once(
            lambda c: asyncio.create_task(flush_album(context, msg.media_group_id)),
            when=ALBUM_DELAY_SEC,
            name=f"flush_{msg.media_group_id}"
        )
        return

    # Single messages (text / single media / polls / etc.) -> copyMessage
    try:
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
            # keep original captions/formatting
        )
    except Exception as e:
        # Fallback to forward if copy fails for some rare types
        try:
            await context.bot.forward_message(
                chat_id=TARGET_CHANNEL,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception as ee:
            print("Copy & forward both failed:", e, ee)


async def on_edited_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Optional: when a post is edited in SOURCE_CHANNEL, re-copy it (simple strategy)."""
    msg = update.edited_channel_post
    if not msg:
        return

    if str(msg.chat.username).lower() != str(SOURCE_CHANNEL).replace("@", "").lower():
        if str(msg.chat.id) != SOURCE_CHANNEL:
            return

    try:
        await context.bot.copy_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except Exception as e:
        print("Edited copy failed:", e)


def main():
    application = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()

    # Listen to new/edited posts from channels
    application.add_handler(ChannelPostHandler(on_channel_post))
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_CHANNEL_POST, on_edited_channel_post))

    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
