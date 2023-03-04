from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, User, Message
from telegram.ext import CallbackContext
import time
import traceback
import sys
from os import path
from typing import Callable
import bot_utils
from bot_utils import validate_text, convert_to_voice, clear_results_dir, user_restricted, MAX_CHARS_NUM, RESULTS_PATH
from tortoise_api import tts_audio_from_text


@user_restricted
async def start_cmd(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    bot_utils.logger.debug(f"started by user: {user.full_name} with id: {user.id}")
    await update.message.reply_html(f"Hi, {user.mention_html()}!")


@user_restricted
async def gen_audio_cmd(update: Update, context: CallbackContext) -> None:
    """Send voice audio file generated by inference"""
    user = update.effective_user
    bot_utils.logger.info(f"Audio generation called by {user.full_name}, with id: {user.id}, with query: {update.message.text}")
    reply_id = update.message.message_id
    if not context.args:
        await update.message.reply_text("Error: invalid arguments provided)", reply_to_message_id=reply_id)
        return

    try:
        text = ' '.join(context.args[1:])
        voice = context.args[0]
        if not validate_text(text):
            await update.message.reply_text("Error: Invalid text detected",
                                      reply_to_message_id=reply_id)
            return

        await gen_audio_impl(text, user, update.message, tts_audio_from_text, voice)
    except BaseException as e:
        bot_utils.logger.error(msg="Exception while gen audio:", exc_info=e)
        await update.message.reply_html("Server Internal Error", reply_to_message_id=reply_id)


async def gen_audio_impl(text: str, user: User, message: Message, syntesize: Callable, speaker_id: str = "freeman") -> None:
    filename_result = path.abspath(path.join(RESULTS_PATH, '{}_{}.wav'.format(user.id, int(time.time()))))
    try:
        syntesize(filename_result, text, speaker_id)
    except BaseException:
        bot_utils.logger.info(f"Audio generation FAILED: called by {user.full_name} with query: {text}")
        traceback.print_exc(file=sys.stdout)
    else:
        voice_file = convert_to_voice(filename_result)
        try:
            with open(voice_file, 'rb') as audio:
                keyboard = [[InlineKeyboardButton("Regenerate", callback_data=speaker_id)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if len(text) > MAX_CHARS_NUM:
                    text = f"{text[:MAX_CHARS_NUM]}..."
                await message.reply_voice(voice=audio, caption=text, reply_to_message_id=message.message_id, reply_markup=reply_markup)
        except BaseException:
            bot_utils.logger.info(f"Audio generation FAILED SEND FILE: called by {user.full_name} with query: {text}")
            traceback.print_exc(file=sys.stdout)
            await message.reply_html("Server Internal Error", reply_to_message_id=message.message_id)
        else:
            bot_utils.logger.info(f"Audio generation DONE: called by {user.full_name} with query: {text}")
    finally:
        clear_results_dir(RESULTS_PATH)


@user_restricted
async def retry_button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    bot_utils.logger.info(f"Retry called by {user.full_name}, with id: {user.id}, with query: {query.message.caption}")
    await gen_audio_impl(query.message.caption, user, query.message, tts_audio_from_text, query.data)


async def help_cmd(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    bot_utils.logger.debug(f"user: {user.full_name} with id: {user.id} asked for help")
    await update.message.reply_text("No help here, yet")  # TODO
