import logging
import traceback
import sys
import subprocess
import os
import configparser
import unicodedata
from functools import wraps
from typing import Callable
from tortoise.utils import audio
import string
from os import makedirs


MAX_CHARS_NUM = 300
CONFIG_FILE_NAME = "config"
SCRIPT_PATH = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../"))
DATA_PATH = os.path.realpath(os.path.join(SCRIPT_PATH, "../bot_data"))
RESULTS_PATH = os.path.join(DATA_PATH, "outputs")
MODELS_PATH = os.path.join(DATA_PATH, "models")
VOICES_PATH = os.path.join(DATA_PATH, "user_voices")
QUERY_PATTERN_RETRY = "c_re"
SOURCE_WEB_LINK = "https://github.com/Helther/voice-pick-tbot"
FOLDER_CHAR_LIMIT = 0


# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("Voice Bot")
logger.setLevel(logging.DEBUG)


class Config(object):
    def __init__(self) -> None:
        self.token = "7164789309:AAGXZK2Czhu14O9cuFBNrVv5MVm3tyOdeeI"
        self.user_id_set: set = set()
        self.keep_cache = False
        self.high_vram = True
        self.batch_size = None
        self.device = 0
        self.default_voices = []
        makedirs(RESULTS_PATH, exist_ok=True)
        makedirs(MODELS_PATH, exist_ok=True)
        makedirs(VOICES_PATH, exist_ok=True)

    def is_user_specified(self) -> bool:
        return len(self.user_id_set) != 0

    def load_config(self, filepath: str) -> None:
        config = configparser.ConfigParser()
        with open(filepath, 'r') as config_file:
            config.read_file(config_file)
            config_section_name = "Main"
            self.token = config[config_section_name]["TOKEN"]
            user_id_str = config[config_section_name].get("USER_ID", None)
            if user_id_str:
                user_id_str = user_id_str.replace(" ", "")
                user_ids = user_id_str.split(",")
                for id in user_ids:
                    self.user_id_set.add(int(id))  # if config invalid then terminate

            config_section_name = "Tortoise"
            self.keep_cache = config.getboolean(config_section_name, "KEEP_CACHE")
            self.high_vram = config.getboolean(config_section_name, "HIGH_VRAM")
            self.batch_size = config.getint(config_section_name, "BATCH_SIZE", fallback=None)
            self.device = config.getint(config_section_name, "DEVICE", fallback=0)

        with os.scandir(audio.BUILTIN_VOICES_DIR) as it:
            for entry in it:
                if not entry.name.startswith('.') and entry.is_dir():
                    self.default_voices.append(entry.name)


config = Config()


def validate_text(user, text: str) -> tuple:
    """
    check if there is a text and look for invalid emotion brakets in text
    returns validation result and failure reason
    """
    is_text_there = len(text) > 0
    empty_text_err_msg = get_text_locale(user, get_cis_locale_dict("В сообщении нет текста"), "There is no text")
    if '[' not in text:
        return is_text_there, empty_text_err_msg
    splitted = text.split('[')
    for spl in splitted[1:]:
        if ']' not in spl:
            return False, get_text_locale(user, get_cis_locale_dict("Обнаружена незакрытая скобка ']'"), "Detected unpaired bracket symbol ']'")

    return is_text_there, empty_text_err_msg


def log_cmd(user, name: str) -> None:
    logger.info(f"user: {user.full_name} with id: {user.id} called: {name}")


def convert_to_voice(filename: str) -> str:
    result_file = filename.replace('wav', 'ogg')
    convert_to_voice_cmd = f"ffmpeg -i {filename} -c:a libopus {result_file}"
    try:
        subprocess.run(f"{convert_to_voice_cmd}", shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        traceback.print_exc(file=sys.stdout)
        remove_temp_file(result_file)  # may not produce the result
        result_file = None

    return result_file


def convert_to_wav(filename: str) -> str:
    result_file = filename.replace('ogg', 'wav')
    convert_to_voice_cmd = f"ffmpeg -i {filename} -acodec pcm_s16le {result_file}"
    try:
        subprocess.run(f"{convert_to_voice_cmd}", shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        remove_temp_file(result_file)
        raise Exception from e
    finally:
        remove_temp_file(filename)

    return result_file


def clear_dir(dir_name: str) -> None:
    for filename in os.listdir(dir_name):
        file_path = os.path.join(dir_name, filename)
        if os.path.isfile(file_path) or os.path.islink(file_path):
            os.unlink(file_path)


def user_restricted(func: Callable):
    """Restrict usage of func to allowed users only and replies if necessary"""
    @wraps(func)
    async def inner(update, *args, **kwargs):
        user = update.effective_user
        user_id = user.id
        if config.is_user_specified() and user_id not in config.user_id_set:
            logger.debug(f"Unauthorized call of {func.__name__} by user: {user.full_name}, with id: {user_id}")
            if update.effective_message:
                reply = get_text_locale(user, get_cis_locale_dict(f"{user.mention_html()}, в доступе отказано, к сожалению это частный бот"),
                                        f"Sorry, {user.mention_html()}, it's a private bot, access denied")
                await update.effective_message.reply_html(reply)
            return  # quit function

        log_cmd(user, func.__name__)
        return await func(update, *args, **kwargs)
    return inner


def get_emot_string(emot: str) -> str:
    return f"[I am really {emot},]"


def get_user_voice_dir(user_id: int) -> str:
    voices_dir = os.path.normpath(os.path.join(VOICES_PATH, str(user_id)))
    if not os.path.exists(voices_dir):
        os.makedirs(voices_dir)
    return voices_dir


def sanitize_filename(filename: str) -> str:
    # replace spaces
    filename.replace(' ', '_')

    # keep only valid ascii chars
    cleaned_filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode()

    # keep only whitelisted chars
    whitelist = "-_.() %s%s" % (string.ascii_letters, string.digits)
    cleaned_filename = ''.join(c for c in cleaned_filename if c in whitelist)
    return cleaned_filename[:FOLDER_CHAR_LIMIT]


async def answer_query(query) -> None:
    await query.answer()


def get_text_locale(user, locales: dict, default: str) -> str:
    """
    returns localized text based upon user language_code
    locales - dict of language_code: string
    default - fallback string if code is not set or absent
    """
    if user is not None:
        for k, v in locales.items():
            if k in user.language_code:
                return v
    return default


def get_cis_locale_dict(text: str) -> dict:
    # returns locales dict for CIS countries that may use ru lang
    return {"ab": text, "be": text, "kk": text, "ky": text, "ru": text}


def remove_temp_file(file_path: str) -> None:
    """if maybe doesn't exist"""
    try:
        os.remove(file_path)
    except Exception:
        pass
