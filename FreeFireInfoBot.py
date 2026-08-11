import os
import asyncio
import logging
import re
import io
from datetime import datetime, date
from PIL import Image
from aiogram import Bot, Dispatcher, types, BaseMiddleware
from aiogram.filters import Command, BaseFilter
from aiogram.types import (
    BufferedInputFile,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    InputMediaPhoto,
)
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
import aiohttp
from aiohttp import web
from supabase import create_client, Client

TOKEN = "8925245187:AAHhXQpOq8xiH-WBJMWyjen8CjtttxkiMU4"
OWNER_ID = 8659710238  # Bot egasining ID si

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

BOT_USERNAME = "FreeFire2026Chat"

# ==========================================
# 🗄️ SUPABASE ULANISHI
# ==========================================
# users jadvali: id (auto), chat_id (unique), lang
# majburiy jadvali: id (auto), channel_id (unique), title, username
# like_usage jadvali: user_id, usage_date, count  -> /like kunlik limiti uchun
# settings jadvali: key (unique), value           -> /likelimit qiymati uchun
#
# Supabase SQL Editor'da bir marta bajarilishi kerak bo'lgan buyruqlar:
#
#   ALTER TABLE users ADD CONSTRAINT users_chat_id_key UNIQUE (chat_id);
#   ALTER TABLE majburiy ADD CONSTRAINT majburiy_channel_id_key UNIQUE (channel_id);
#   ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'uz';
#
#   CREATE TABLE IF NOT EXISTS like_usage (
#       id BIGSERIAL PRIMARY KEY,
#       user_id BIGINT NOT NULL,
#       usage_date DATE NOT NULL,
#       count INT NOT NULL DEFAULT 0,
#       UNIQUE (user_id, usage_date)
#   );
#
#   CREATE TABLE IF NOT EXISTS settings (
#       id BIGSERIAL PRIMARY KEY,
#       key TEXT NOT NULL UNIQUE,
#       value TEXT
#   );

SUPABASE_URL = "https://ybyjpcmvmgrbwupyordo.supabase.co"
SUPABASE_KEY = "sb_publishable_CG7mnSkSh-qxriZQgh5RdQ_-ds70rCP"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SELF_URL = os.environ.get("RENDER_EXTERNAL_URL")

# ==========================================
# 🧩 "/" SIZ HAM, "/" BILAN HAM ISHLAYDIGAN KOMANDA FILTRI
# ==========================================

KNOWN_COMMANDS = {
    "start", "help", "info", "bancheck", "banner",
    "region", "token", "rek", "majburiy", "remover", "royxat", "setlang",
    "like", "likelimit"
}

def extract_command(text: str):
    if not text:
        return None
    match = re.match(r'^/?([A-Za-z_]+)(?:@\w+)?(?:\s|$)', text.strip())
    if not match:
        return None
    return match.group(1).lower()

class Cmd(BaseFilter):
    def __init__(self, *commands: str):
        self.commands = {c.lower() for c in commands}

    async def __call__(self, message: types.Message):
        cmd = extract_command(message.text)
        return cmd is not None and cmd in self.commands

# ==========================================
# 🌐 KO'P TILLI TIZIM (uz / en)
# ==========================================

DEFAULT_LANG = "uz"
SUPPORTED_LANGS = ("uz", "en")

BOT_INFO_TEXT_UZ = (
    "👋 **Assalomu alaykum! Botga xush kelibsiz.**\n\n"
    "🤖 **Bot haqida**\n"
    "Bu bot Free Fire o'yinchilari haqida ma'lumot olish uchun mo'ljallangan: "
    "profil ma'lumotlari, ban holati, banner/outfit rasmlari, region va JWT token.\n\n"
    "📜 **Foydalanuvchi buyruqlari:**\n"
    "├─ /info <uid> — o'yinchining to'liq profil ma'lumotlari (banner va outfit rasmi bilan)\n"
    "│   Masalan: `/info 8530477563`\n"
    "├─ /bancheck <uid> — akkauntning ban holatini tekshirish\n"
    "│   Masalan: `/bancheck 8530477563`\n"
    "├─ /banner <uid> — avatar-banner va live outfit rasmlarini olish\n"
    "│   Masalan: `/banner 8530477563`\n"
    "├─ /region <uid> — akkaunt region va umumiy ma'lumotlari\n"
    "│   Masalan: `/region 8530477563`\n"
    "├─ /token <uid> <parol> — JWT token olish\n"
    "│   Masalan: `/token 15088864083 sizning_parolingiz`\n"
    "├─ /like <region> <uid> — o'yinchiga layk (like) yuborish\n"
    "│   Masalan: `/like RU 8530477563`\n"
    "├─ /setlang — bot tilini tanlash (🇺🇿 / 🇬🇧)\n"
    "└─ /help — ushbu yordam xabari\n\n"
    "ℹ️ Barcha buyruqlarni `/` bilan ham (`/info 123`), `/`siz ham (`info 123`) yuborishingiz mumkin.\n"
    "ℹ️ Botni inline rejimda ham ishlatishingiz mumkin: istalgan chatda "
    f"`@{BOT_USERNAME} info 123` deb yozing.\n"
    "ℹ️ Barcha buyruqlardan foydalanish uchun avval botga majburiy obuna kanallariga "
    "a'zo bo'lishingiz kerak bo'lishi mumkin."
)

BOT_INFO_TEXT_EN = (
    "👋 **Hello! Welcome to the bot.**\n\n"
    "🤖 **About the bot**\n"
    "This bot provides information about Free Fire players: profile info, "
    "ban status, banner/outfit images, region and JWT token.\n\n"
    "📜 **User commands:**\n"
    "├─ /info <uid> — full player profile (with banner and outfit image)\n"
    "│   Example: `/info 8530477563`\n"
    "├─ /bancheck <uid> — check the account's ban status\n"
    "│   Example: `/bancheck 8530477563`\n"
    "├─ /banner <uid> — get avatar-banner and live outfit images\n"
    "│   Example: `/banner 8530477563`\n"
    "├─ /region <uid> — account region and general info\n"
    "│   Example: `/region 8530477563`\n"
    "├─ /token <uid> <password> — get a JWT token\n"
    "│   Example: `/token 15088864083 your_password`\n"
    "├─ /like <region> <uid> — send a like to a player\n"
    "│   Example: `/like RU 8530477563`\n"
    "├─ /setlang — choose the bot's language (🇺🇿 / 🇬🇧)\n"
    "└─ /help — this help message\n\n"
    "ℹ️ You can send commands with `/` (`/info 123`) or without it (`info 123`).\n"
    "ℹ️ You can also use the bot in inline mode: type "
    f"`@{BOT_USERNAME} info 123` in any chat.\n"
    "ℹ️ You may need to subscribe to required channels before using the bot's commands."
)

TR = {
    "uz": {
        "start_help": BOT_INFO_TEXT_UZ,
        "uid_missing": "❌ Xato! UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `{example}`",
        "uid_invalid": "❌ UID faqat raqamlardan iborat bo'lishi kerak!",
        "not_found": "❌ Bu UID bo'yicha ma'lumot topilmadi.",
        "loading_info": "🔍 Ma'lumotlar yuklanmoqda...",
        "loading_ban": "🔍 Ban holati tekshirilmoqda...",
        "loading_photos": "🔍 Rasmlar yuklanmoqda...",
        "loading_region": "🔍 Region ma'lumotlari yuklanmoqda...",
        "loading_token": "🔑 JWT Token olinmoqda...",
        "token_missing": (
            "❌ Xato! UID va parolni kiritishni unutdingiz.\n"
            "To'g'ri ishlatish: `/token 15088864083 sizning_parolingiz`"
        ),
        "token_failed": "❌ Token olib bo'lmadi! UID yoki parol xato.",
        "photos_failed": "❌ Rasmlarni yuklab bo'lmadi.",
        "setlang_prompt": "🌐 Tilni tanlang:",
        "setlang_set": "✅ Til o'zbekcha qilib o'rnatildi.",
        "need_sub_inline": "⚠️ Avval botga shaxsiy chatda a'zo bo'ling",
        "gender_male": "Erkak ♂️",
        "gender_female": "Ayol ♀️",
        "gender_secret": "Maxfiy 🔒",
        "bp_free": "Bepul 🆓",
        "bp_premium": "Premium ⭐",
        "ban_clean": "🟢 Toza (Ayblov yo'q)",
        "ban_temp": "⏳ Umrbod bloklangan",
        "ban_perm": "🚫 Doimiy (Cheksiz) bloklangan",
        "ban_other": "🔴 Bloklangan",
        "banned_yes": "🔴 Ha (Bloklangan)",
        "banned_no": "🟢 Yo'q (Toza)",
        "ban_type_temp": "Umrbod",
        "ban_type_perm": "Doimiy",
        "ban_type_none": "Mavjud emas",
        "unknown": "Noma'lum",
        "info_caption": "🖼 **Avatar & Banner hamda Live Outfits**",
        "banner_caption1": "🖼 Avatar va Banner",
        "banner_caption2": "👕 O'yinchining kiyimlari (Live Outfits)",
        "banner_caption_combined": "🖼 Avatar, Banner va Live Outfits",
        "inline_help_title": "ℹ️ Yordam / barcha buyruqlar",
        "inline_help_desc": "Bot haqida to'liq ma'lumot",
        "inline_info_title": "🎮 /info <uid> — to'liq profil",
        "inline_info_desc": "Masalan: info 8530477563",
        "inline_bancheck_title": "🚫 /bancheck <uid> — ban tekshirish",
        "inline_bancheck_desc": "Masalan: bancheck 8530477563",
        "inline_banner_title": "🖼 /banner <uid> — rasm(lar)",
        "inline_banner_desc": "Masalan: banner 8530477563",
        "inline_region_title": "🌍 /region <uid> — region ma'lumoti",
        "inline_region_desc": "Masalan: region 8530477563",
        "inline_token_title": "🔑 /token <uid> <parol> — JWT token",
        "inline_token_desc": "Masalan: token 15088864083 parol",
        "inline_uid_invalid_title": "❌ UID noto'g'ri",
        "inline_uid_invalid_desc": "UID faqat raqamlardan iborat bo'lishi kerak",
        "inline_not_found_title": "❌ Ma'lumot topilmadi",
        "inline_not_found_desc": "Bu UID bo'yicha hech narsa topilmadi",
        "inline_loading_title": "⏳ Yuklanmoqda...",
        "inline_loading_desc": "Tanlansangiz rasm biriktiriladi",
        "inline_token_missing_desc": "token <uid> <parol> shaklida yozing",
        "inline_tap_title": "👉 Bosing — natija shu yerda ko'rinadi",
        "inline_tap_desc": "Tanlansangiz ma'lumot shu xabarga yuklanadi",
        "info_template": (
            "🎮 **FREE FIRE PLAYER INFO**\n\n"
            "┌ 👤 **Asosiy Ma'lumotlar**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Daraja: `{level}` (Keyingi darajaga: `{exp_needed}`)\n"
            "├─ ✨ Tajriba (Exp): `{exp}` (Progress: `{progress}`)\n"
            "├─ ⏳ Akkaunt yoshi: `{acc_age}`\n"
            "├─ 📅 Yaratilgan vaqti: `{created_at}`\n"
            "├─ 🚪 Oxirgi kirish: `{last_login}`\n"
            "├─ ❤️ Layklar: `{liked}`\n"
            "├─ 🏅 Rank: `{rank}` | Max: `{max_rank}`\n"
            "├─ 📊 Reyting ballari: `{ranking_points}`\n"
            "├─ ⚔️ CS Rank: `{cs_rank}` | CS Max: `{cs_max_rank}`\n"
            "├─ 🎟 Booyah Pass: `{booyah_pass}`\n"
            "├─ 🎖 Unvon: `{title_name}`\n"
            "├─ 🖼 Avatar: `{avatar_name}`\n"
            "├─ 🚩 Banner: `{banner_name}`\n"
            "└─ 📌 Pin: `{pin_name}`\n\n"
            "┌ 👕 **Profil Jihozlari**\n"
            "├─ 🎨 Teri rangi: `{skin_color}`\n"
            "├─ 👗 Kiyimlar ID: `{clothes}`\n"
            "├─ ⚡ Qobiliyatlar ID: `{equipped_skills}`\n"
            "└─ 🔓 Qulfdan chiqish vaqti: `{unlock_time}`\n\n"
            "┌ 🛡 **Klan (Guild) Ma'lumotlari**\n"
            "├─ 🏰 Nomi: `{clan_name}` (ID: `{clan_id}`)\n"
            "├─ 👑 Lider: `{captain_nickname}` (UID: `{captain_id}`)\n"
            "├─ 📊 Klan darajasi: `{clan_level}`\n"
            "└─ 👥 A'zolar: `{member_num} / {capacity}`\n\n"
            "┌ 💯 **Kredit Reyting**\n"
            "├─ 📈 Ball: `{credit_score}`\n"
            "└─ 🎁 Mukofot holati: `{reward_state}`\n\n"
            "┌ 🐾 **Uy Hayvoni (Pet)**\n"
            "├─ 🐕 Nomi: `{pet_name}`\n"
            "└─ 📈 Darajasi: `{pet_level}` (Exp: `{pet_exp}`)\n\n"
            "┌ 💬 **Ijtimoiy Ma'lumotlar**\n"
            "├─ 🌐 Til: `{language}`\n"
            "├─ 🌙 Faollik vaqti: `{time_active}`\n"
            "├─ ✍️ Status (Imzo): `{signature}`\n"
            "└─ 👤 Jinsi: `{gender}`\n\n"
            "┌ 🚫 **Ban Holati**\n"
            "├─ 🔒 Ban Holati: `{ban_status}`\n"
            "├─ 🚫 Bloklanganmi?: `{is_banned}`\n"
            "├─ ⚠️ Ban turi: `{ban_type}`\n"
            "└─ ⏳ Ban bo'lgan oy: `{ban_period}`"
        ),
        "bancheck_clean_template": (
            "┌ 🚫 **Ban Tekshiruvi (Bancheck Info)**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Daraja: `{level}`\n"
            "├─ ❤️ Layklar: `{liked}`\n"
            "└─ 🔒 Holati: Toza (Bloklanmagan) 🟢"
        ),
        "bancheck_banned_template": (
            "┌ 🚫 **Ban Tekshiruvi (Bancheck Info)**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Daraja: `{level}`\n"
            "├─ ❤️ Layklar: `{liked}`\n"
            "├─ 🔒 Holati: Bloklangan 🔴\n"
            "└─ ⏳ Ban muddati: `{ban_desc}`"
        ),
        "ban_desc_perm": "Doimiy (Cheksiz ban)",
        "ban_desc_temp": "Umrbod Ban",
        "region_template": (
            "┌ 🌐 **Region Ma'lumotlari (Region Information)**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Daraja: `{level}`\n"
            "├─ ❤️ Layklar: `{liked}`\n"
            "├─ 📅 Yaratilgan: `{created_at}`\n"
            "└─ 🚪 Oxirgi kirish: `{last_login}`"
        ),
        "token_template": (
            "┌ 🔑 **JWT Token Ma'lumotlari (JWT Information)**\n"
            "├─ 🆔 Akkaunt ID: `{account_id}`\n"
            "├─ 🌐 IP Region: `{ip_region}`\n"
            "├─ 🔒 Qulflangan Region: `{lock_region}`\n"
            "├─ 🔔 Bildirishnoma Region: `{noti_region}`\n"
            "├─ 🎮 Agora Muhiti: `{agora_env}`\n"
            "├─ 🖥️ Server Havolasi: `{server_url}`\n"
            "├─ 🗝️ OpenID: `{openid}`\n"
            "├─ ⏱️ Amal qilish vaqti (TTL): `{ttl}`\n"
            "├─ 🎫 Access Token: `{access_token}`\n"
            "└─ 🔐 Token (JWT): `{token}`"
        ),
        "sub_prompt": (
            "⚠️ **Botdan foydalanish uchun quyidagi kanal/guruhlarga obuna bo'lishingiz shart!**\n\n"
            "Obuna bo'lgach, pastdagi \"✅ Obuna bo'ldim, tekshirish\" tugmasini bosing."
        ),
        "sub_check_button": "✅ Obuna bo'ldim, tekshirish",
        "sub_not_yet": "❌ Siz hali barcha kanal/guruhlarga obuna bo'lmagansiz!",
        "sub_confirmed": "✅ Obuna tasdiqlandi! Endi botdan to'liq foydalanishingiz mumkin.",
        "like_usage_msg": "❌ Xato! Region va UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `/like RU 8530477563`",
        "like_region_invalid": "❌ Region nomi noto'g'ri! Faqat harflardan iborat bo'lishi kerak (masalan: RU, ID, BD, PK, VN).",
        "like_loading": "❤️ Layk yuborilmoqda...",
        "like_limit_reached": "⛔ Siz bugungi layk limitiga yetdingiz (kuniga `{limit}` ta). Ertaga qayta urinib ko'ring.",
        "likelimit_usage": "❌ To'g'ri ishlatish: `/likelimit 1` yoki `/likelimit 2`",
        "likelimit_set": "✅ Kunlik layk limiti endi: `{limit}` ta/foydalanuvchi.",
        "like_status_success": "✅ Muvaffaqiyatli",
        "like_status_fail": "❌ Muvaffaqiyatsiz (bugungi limit tugagan yoki UID xato)",
        "like_success_template": (
            "✅ **Layk Muvaffaqiyatli Yuborildi!**\n\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🆔 UID: `{uid}`\n"
            "├─ ⭐ Daraja: `{level}`\n"
            "├─ ❤️ Oldingi layk soni: `{likes_before}`\n"
            "├─ ❤️ Hozirgi layk soni: `{likes_after}`\n"
            "├─ 🎉 Yuborilgan layklar: `{likes_given}`\n"
            "└─ 📌 Holat: `{status}`"
        ),
        "like_fail_template": (
            "❌ **Layk Yuborilmadi**\n\n"
            "├─ 🏷 Nik: `{nickname}`\n"
            "├─ 🆔 UID: `{uid}`\n"
            "├─ ⭐ Daraja: `{level}`\n"
            "├─ ❤️ Oldingi layk soni: `{likes_before}`\n"
            "├─ ❤️ Hozirgi layk soni: `{likes_after}`\n"
            "├─ 🎉 Yuborilgan layklar: `{likes_given}`\n"
            "└─ 📌 Holat: `{status}`"
        ),
        "inline_like_title": "❤️ /like <region> <uid> — layk yuborish",
        "inline_like_desc": "Masalan: like RU 8530477563",
        "inline_like_missing_desc": "like <region> <uid> shaklida yozing, masalan: like RU 8530477563",
    },
    "en": {
        "start_help": BOT_INFO_TEXT_EN,
        "uid_missing": "❌ Error! You forgot to enter a UID.\nCorrect usage: `{example}`",
        "uid_invalid": "❌ UID must contain digits only!",
        "not_found": "❌ No data found for this UID.",
        "loading_info": "🔍 Loading data...",
        "loading_ban": "🔍 Checking ban status...",
        "loading_photos": "🔍 Loading images...",
        "loading_region": "🔍 Loading region info...",
        "loading_token": "🔑 Getting JWT token...",
        "token_missing": (
            "❌ Error! You forgot to enter the UID and password.\n"
            "Correct usage: `/token 15088864083 your_password`"
        ),
        "token_failed": "❌ Could not get the token! Wrong UID or password.",
        "photos_failed": "❌ Could not load the images.",
        "setlang_prompt": "🌐 Choose your language:",
        "setlang_set": "✅ Language set to English.",
        "need_sub_inline": "⚠️ Please subscribe first via the bot's private chat",
        "gender_male": "Male ♂️",
        "gender_female": "Female ♀️",
        "gender_secret": "Hidden 🔒",
        "bp_free": "Free 🆓",
        "bp_premium": "Premium ⭐",
        "ban_clean": "🟢 Clean (No violations)",
        "ban_temp": "⏳ Temporarily banned",
        "ban_perm": "🚫 Permanently banned",
        "ban_other": "🔴 Banned",
        "banned_yes": "🔴 Yes (Banned)",
        "banned_no": "🟢 No (Clean)",
        "ban_type_temp": "Temporary",
        "ban_type_perm": "Permanent",
        "ban_type_none": "None",
        "unknown": "Unknown",
        "info_caption": "🖼 **Avatar & Banner and Live Outfits**",
        "banner_caption1": "🖼 Avatar and Banner",
        "banner_caption2": "👕 Player's Live Outfits",
        "banner_caption_combined": "🖼 Avatar, Banner and Live Outfits",
        "inline_help_title": "ℹ️ Help / all commands",
        "inline_help_desc": "Full information about the bot",
        "inline_info_title": "🎮 /info <uid> — full profile",
        "inline_info_desc": "Example: info 8530477563",
        "inline_bancheck_title": "🚫 /bancheck <uid> — check ban",
        "inline_bancheck_desc": "Example: bancheck 8530477563",
        "inline_banner_title": "🖼 /banner <uid> — image(s)",
        "inline_banner_desc": "Example: banner 8530477563",
        "inline_region_title": "🌍 /region <uid> — region info",
        "inline_region_desc": "Example: region 8530477563",
        "inline_token_title": "🔑 /token <uid> <password> — JWT token",
        "inline_token_desc": "Example: token 15088864083 password",
        "inline_uid_invalid_title": "❌ Invalid UID",
        "inline_uid_invalid_desc": "UID must contain digits only",
        "inline_not_found_title": "❌ Not found",
        "inline_not_found_desc": "Nothing found for this UID",
        "inline_loading_title": "⏳ Loading...",
        "inline_loading_desc": "Image will be attached once selected",
        "inline_token_missing_desc": "Type it as: token <uid> <password>",
        "inline_tap_title": "👉 Tap — the result will appear here",
        "inline_tap_desc": "Once selected, the data will load into this message",
        "info_template": (
            "🎮 **FREE FIRE PLAYER INFO**\n\n"
            "┌ 👤 **Main Info**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Level: `{level}` (Exp needed for next level: `{exp_needed}`)\n"
            "├─ ✨ Exp: `{exp}` (Progress: `{progress}`)\n"
            "├─ ⏳ Account age: `{acc_age}`\n"
            "├─ 📅 Created at: `{created_at}`\n"
            "├─ 🚪 Last login: `{last_login}`\n"
            "├─ ❤️ Likes: `{liked}`\n"
            "├─ 🏅 Rank: `{rank}` | Max: `{max_rank}`\n"
            "├─ 📊 Ranking points: `{ranking_points}`\n"
            "├─ ⚔️ CS Rank: `{cs_rank}` | CS Max: `{cs_max_rank}`\n"
            "├─ 🎟 Booyah Pass: `{booyah_pass}`\n"
            "├─ 🎖 Title: `{title_name}`\n"
            "├─ 🖼 Avatar: `{avatar_name}`\n"
            "├─ 🚩 Banner: `{banner_name}`\n"
            "└─ 📌 Pin: `{pin_name}`\n\n"
            "┌ 👕 **Profile Gear**\n"
            "├─ 🎨 Skin color: `{skin_color}`\n"
            "├─ 👗 Clothes ID: `{clothes}`\n"
            "├─ ⚡ Skills ID: `{equipped_skills}`\n"
            "└─ 🔓 Unlock time: `{unlock_time}`\n\n"
            "┌ 🛡 **Guild Info**\n"
            "├─ 🏰 Name: `{clan_name}` (ID: `{clan_id}`)\n"
            "├─ 👑 Leader: `{captain_nickname}` (UID: `{captain_id}`)\n"
            "├─ 📊 Guild level: `{clan_level}`\n"
            "└─ 👥 Members: `{member_num} / {capacity}`\n\n"
            "┌ 💯 **Credit Score**\n"
            "├─ 📈 Score: `{credit_score}`\n"
            "└─ 🎁 Reward state: `{reward_state}`\n\n"
            "┌ 🐾 **Pet**\n"
            "├─ 🐕 Name: `{pet_name}`\n"
            "└─ 📈 Level: `{pet_level}` (Exp: `{pet_exp}`)\n\n"
            "┌ 💬 **Social Info**\n"
            "├─ 🌐 Language: `{language}`\n"
            "├─ 🌙 Active time: `{time_active}`\n"
            "├─ ✍️ Signature: `{signature}`\n"
            "└─ 👤 Gender: `{gender}`\n\n"
            "┌ 🚫 **Ban Status**\n"
            "├─ 🔒 Ban status: `{ban_status}`\n"
            "├─ 🚫 Banned?: `{is_banned}`\n"
            "├─ ⚠️ Ban type: `{ban_type}`\n"
            "└─ ⏳ Ban period: `{ban_period}`"
        ),
        "bancheck_clean_template": (
            "┌ 🚫 **Bancheck Info**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Level: `{level}`\n"
            "├─ ❤️ Likes: `{liked}`\n"
            "└─ 🔒 Status: Clean (Not banned) 🟢"
        ),
        "bancheck_banned_template": (
            "┌ 🚫 **Bancheck Info**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Level: `{level}`\n"
            "├─ ❤️ Likes: `{liked}`\n"
            "├─ 🔒 Status: Banned 🔴\n"
            "└─ ⏳ Ban duration: `{ban_desc}`"
        ),
        "ban_desc_perm": "Permanent (unlimited ban)",
        "ban_desc_temp": "Temporary ban",
        "region_template": (
            "┌ 🌐 **Region Information**\n"
            "├─ 🆔 UID: `{account_id}`\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🌍 Region: `{region}`\n"
            "├─ ⭐ Level: `{level}`\n"
            "├─ ❤️ Likes: `{liked}`\n"
            "├─ 📅 Created: `{created_at}`\n"
            "└─ 🚪 Last login: `{last_login}`"
        ),
        "token_template": (
            "┌ 🔑 **JWT Token Information**\n"
            "├─ 🆔 Account ID: `{account_id}`\n"
            "├─ 🌐 IP Region: `{ip_region}`\n"
            "├─ 🔒 Locked Region: `{lock_region}`\n"
            "├─ 🔔 Notification Region: `{noti_region}`\n"
            "├─ 🎮 Agora Environment: `{agora_env}`\n"
            "├─ 🖥️ Server URL: `{server_url}`\n"
            "├─ 🗝️ OpenID: `{openid}`\n"
            "├─ ⏱️ TTL: `{ttl}`\n"
            "├─ 🎫 Access Token: `{access_token}`\n"
            "└─ 🔐 Token (JWT): `{token}`"
        ),
        "sub_prompt": (
            "⚠️ **You must subscribe to the following channel(s)/group(s) to use the bot!**\n\n"
            "Once subscribed, tap the \"✅ I subscribed, check\" button below."
        ),
        "sub_check_button": "✅ I subscribed, check",
        "sub_not_yet": "❌ You haven't subscribed to all the required channels/groups yet!",
        "sub_confirmed": "✅ Subscription confirmed! You can now fully use the bot.",
        "like_usage_msg": "❌ Error! You forgot to enter the region and UID.\nCorrect usage: `/like RU 8530477563`",
        "like_region_invalid": "❌ Invalid region! It must contain letters only (e.g. RU, ID, BD, PK, VN).",
        "like_loading": "❤️ Sending like...",
        "like_limit_reached": "⛔ You've reached today's like limit (`{limit}` per day). Please try again tomorrow.",
        "likelimit_usage": "❌ Correct usage: `/likelimit 1` or `/likelimit 2`",
        "likelimit_set": "✅ Daily like limit is now: `{limit}` per user.",
        "like_status_success": "✅ Success",
        "like_status_fail": "❌ Failed (daily limit reached or invalid UID)",
        "like_success_template": (
            "✅ **Like Sent Successfully!**\n\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🆔 UID: `{uid}`\n"
            "├─ ⭐ Level: `{level}`\n"
            "├─ ❤️ Likes before: `{likes_before}`\n"
            "├─ ❤️ Likes now: `{likes_after}`\n"
            "├─ 🎉 Likes sent: `{likes_given}`\n"
            "└─ 📌 Status: `{status}`"
        ),
        "like_fail_template": (
            "❌ **Like Not Sent**\n\n"
            "├─ 🏷 Nickname: `{nickname}`\n"
            "├─ 🆔 UID: `{uid}`\n"
            "├─ ⭐ Level: `{level}`\n"
            "├─ ❤️ Likes before: `{likes_before}`\n"
            "├─ ❤️ Likes now: `{likes_after}`\n"
            "├─ 🎉 Likes sent: `{likes_given}`\n"
            "└─ 📌 Status: `{status}`"
        ),
        "inline_like_title": "❤️ /like <region> <uid> — send a like",
        "inline_like_desc": "Example: like RU 8530477563",
        "inline_like_missing_desc": "Type it as: like <region> <uid>, e.g. like RU 8530477563",
    },
}

def t(key: str, lang: str, **kwargs) -> str:
    lang = lang if lang in TR else DEFAULT_LANG
    template = TR.get(lang, {}).get(key)
    if template is None:
        template = TR.get("en", {}).get(key, key)
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError):
        return template

# --- FOYDALANUVCHI TILI: SAQLASH VA O'QISH ---

_LANG_CACHE: dict[int, str] = {}

def _get_user_lang_sync(user_id: int):
    try:
        resp = supabase.table("users").select("lang").eq("chat_id", user_id).limit(1).execute()
        if resp.data:
            return resp.data[0].get("lang")
    except Exception as e:
        logging.error(f"Til o'qish xatosi ({user_id}): {e}")
    return None

def _set_user_lang_sync(user_id: int, lang: str) -> bool:
    try:
        supabase.table("users").upsert(
            {"chat_id": user_id, "lang": lang}, on_conflict="chat_id"
        ).execute()
        return True
    except Exception as e:
        logging.error(f"Til yozish xatosi ({user_id}): {e}")
        return False

async def get_user_lang(user_id: int, chat_type: str = "private") -> str:
    if user_id in _LANG_CACHE:
        return _LANG_CACHE[user_id]

    lang = await asyncio.to_thread(_get_user_lang_sync, user_id)
    if lang in SUPPORTED_LANGS:
        _LANG_CACHE[user_id] = lang
        return lang

    return "en" if chat_type != "private" else DEFAULT_LANG

async def set_user_lang(user_id: int, lang: str) -> bool:
    if lang not in SUPPORTED_LANGS:
        return False
    _LANG_CACHE[user_id] = lang
    ok = await asyncio.to_thread(_set_user_lang_sync, user_id, lang)
    if not ok:
        logging.warning(f"Til Supabase'ga saqlanmadi (user_id={user_id})")
    return ok

# ==========================================
# 💾 FOYDALANUVCHILAR BAZASI
# ==========================================

def _db_add_id_sync(chat_id: int) -> bool:
    try:
        supabase.table("users").upsert(
            {"chat_id": chat_id}, on_conflict="chat_id"
        ).execute()
        return True
    except Exception as e:
        logging.error(f"DB Add xatosi ({chat_id}): {e}")
        return False

def _db_get_ids_sync():
    try:
        resp = supabase.table("users").select("chat_id").execute()
        return [row["chat_id"] for row in (resp.data or [])]
    except Exception as e:
        logging.error(f"DB Get IDs xatosi: {e}")
        return []

def _db_remove_id_sync(chat_id) -> bool:
    try:
        supabase.table("users").delete().eq("chat_id", int(chat_id)).execute()
        return True
    except Exception as e:
        logging.error(f"DB Remove xatosi ({chat_id}): {e}")
        return False

async def db_add_id(session: aiohttp.ClientSession, chat_id: int):
    return await asyncio.to_thread(_db_add_id_sync, chat_id)

async def db_get_ids(session: aiohttp.ClientSession):
    return await asyncio.to_thread(_db_get_ids_sync)

async def db_remove_id(session: aiohttp.ClientSession, chat_id):
    return await asyncio.to_thread(_db_remove_id_sync, chat_id)

# ==========================================
# 🔔 MAJBURIY A'ZOLIK BAZASI
# ==========================================

def _majburiy_add_id_sync(chat_id, title="", username="") -> bool:
    try:
        supabase.table("majburiy").upsert(
            {"channel_id": int(chat_id), "title": title or "", "username": username or ""},
            on_conflict="channel_id",
        ).execute()
        return True
    except Exception as e:
        logging.error(f"Majburiy Add xatosi ({chat_id}): {e}")
        return False

def _majburiy_get_ids_sync():
    try:
        resp = supabase.table("majburiy").select("channel_id").execute()
        return [row["channel_id"] for row in (resp.data or [])]
    except Exception as e:
        logging.error(f"Majburiy Get IDs xatosi: {e}")
        return []

def _majburiy_remove_id_sync(chat_id) -> bool:
    try:
        supabase.table("majburiy").delete().eq("channel_id", int(chat_id)).execute()
        return True
    except Exception as e:
        logging.error(f"Majburiy Remove xatosi ({chat_id}): {e}")
        return False

async def majburiy_add_id(session: aiohttp.ClientSession, chat_id, title="", username=""):
    return await asyncio.to_thread(_majburiy_add_id_sync, chat_id, title, username)

async def majburiy_get_ids(session: aiohttp.ClientSession):
    return await asyncio.to_thread(_majburiy_get_ids_sync)

async def majburiy_remove_id(session: aiohttp.ClientSession, chat_id):
    return await asyncio.to_thread(_majburiy_remove_id_sync, chat_id)

# ==========================================
# ❤️ /like KUNLIK LIMIT VA SOZLAMALAR (Supabase: like_usage, settings)
# ==========================================

DEFAULT_LIKE_LIMIT = 1

def _get_like_limit_sync() -> int:
    try:
        resp = supabase.table("settings").select("value").eq("key", "like_daily_limit").limit(1).execute()
        if resp.data:
            return int(resp.data[0].get("value") or DEFAULT_LIKE_LIMIT)
    except Exception as e:
        logging.error(f"Like limit o'qish xatosi: {e}")
    return DEFAULT_LIKE_LIMIT

def _set_like_limit_sync(limit: int) -> bool:
    try:
        supabase.table("settings").upsert(
            {"key": "like_daily_limit", "value": str(limit)}, on_conflict="key"
        ).execute()
        return True
    except Exception as e:
        logging.error(f"Like limit yozish xatosi: {e}")
        return False

def _get_like_usage_sync(user_id: int) -> int:
    today = date.today().isoformat()
    try:
        resp = (
            supabase.table("like_usage")
            .select("count")
            .eq("user_id", user_id)
            .eq("usage_date", today)
            .limit(1)
            .execute()
        )
        if resp.data:
            return int(resp.data[0].get("count") or 0)
    except Exception as e:
        logging.error(f"Like usage o'qish xatosi ({user_id}): {e}")
    return 0

def _increment_like_usage_sync(user_id: int) -> int:
    today = date.today().isoformat()
    try:
        resp = (
            supabase.table("like_usage")
            .select("count")
            .eq("user_id", user_id)
            .eq("usage_date", today)
            .limit(1)
            .execute()
        )
        current = int(resp.data[0]["count"]) if resp.data else 0
        new_count = current + 1
        supabase.table("like_usage").upsert(
            {"user_id": user_id, "usage_date": today, "count": new_count},
            on_conflict="user_id,usage_date",
        ).execute()
        return new_count
    except Exception as e:
        logging.error(f"Like usage yozish xatosi ({user_id}): {e}")
        return 0

async def get_like_limit() -> int:
    return await asyncio.to_thread(_get_like_limit_sync)

async def set_like_limit(limit: int) -> bool:
    return await asyncio.to_thread(_set_like_limit_sync, limit)

async def get_like_usage(user_id: int) -> int:
    return await asyncio.to_thread(_get_like_usage_sync, user_id)

async def increment_like_usage(user_id: int) -> int:
    return await asyncio.to_thread(_increment_like_usage_sync, user_id)

# --- BAZAGA AVTOMATIK QO'SHISH MIDDLEWARE ---

class AutoRegisterMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.chat:
            chat_id = event.chat.id
            asyncio.create_task(db_add_id(data["session"], chat_id))
        return await handler(event, data)

# ==========================================
# 🔒 MAJBURIY OBUNA TEKSHIRUVI (FORCE SUBSCRIBE)
# ==========================================

EXEMPT_COMMANDS = ("start", "help", "setlang")

async def check_user_subscription(user_id: int, session: aiohttp.ClientSession):
    channel_ids = await majburiy_get_ids(session)

    async def _check(cid):
        try:
            member = await bot.get_chat_member(int(cid), user_id)
            if member.status in ("left", "kicked"):
                return cid
        except Exception:
            return cid
        return None

    results = await asyncio.gather(*[_check(cid) for cid in channel_ids])
    not_subscribed = [cid for cid in results if cid is not None]
    return not_subscribed

async def build_subscription_keyboard(not_subbed_ids, lang: str = DEFAULT_LANG):
    rows = []
    idx = 1
    for cid in not_subbed_ids:
        try:
            chat = await bot.get_chat(int(cid))
        except Exception:
            continue
        title = chat.title or (f"@{chat.username}" if chat.username else str(cid))
        link = None
        if chat.username:
            link = f"https://t.me/{chat.username}"
        else:
            try:
                link = await bot.export_chat_invite_link(int(cid))
            except Exception:
                link = None
        if link:
            rows.append([types.InlineKeyboardButton(text=f"{idx}- {title}", url=link)])
            idx += 1
    rows.append([types.InlineKeyboardButton(text=t("sub_check_button", lang), callback_data="check_sub")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

async def send_subscription_prompt(message: types.Message, not_subbed_ids, lang: str = DEFAULT_LANG):
    keyboard = await build_subscription_keyboard(not_subbed_ids, lang)
    await message.answer(
        t("sub_prompt", lang),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

class ForceSubscribeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.from_user and event.text:
            if event.from_user.id == OWNER_ID:
                return await handler(event, data)

            cmd = extract_command(event.text)

            if cmd in EXEMPT_COMMANDS:
                return await handler(event, data)

            if cmd in KNOWN_COMMANDS:
                session = data.get("session")
                not_subbed = await check_user_subscription(event.from_user.id, session)
                if not_subbed:
                    lang = await get_user_lang(event.from_user.id, event.chat.type)
                    await send_subscription_prompt(event, not_subbed, lang)
                    return
        return await handler(event, data)

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, session: aiohttp.ClientSession):
    lang = await get_user_lang(callback.from_user.id, callback.message.chat.type if callback.message else "private")
    not_subbed = await check_user_subscription(callback.from_user.id, session)
    if not_subbed:
        keyboard = await build_subscription_keyboard(not_subbed, lang)
        await callback.answer(t("sub_not_yet", lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
    else:
        await callback.answer(t("sub_confirmed", lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass

@dp.message(Cmd("start"))
async def start_command_handler(message: types.Message):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    await message.answer(t("start_help", lang), parse_mode="Markdown")

@dp.message(Cmd("help"))
async def help_command_handler(message: types.Message):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    await message.answer(t("start_help", lang), parse_mode="Markdown")

# ==========================================
# 🌐 /setlang — TIL TANLASH BUYRUG'I
# ==========================================

@dp.message(Cmd("setlang"))
async def setlang_command_handler(message: types.Message):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="setlang_uz"),
        types.InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en"),
    ]])
    await message.answer(t("setlang_prompt", lang), reply_markup=keyboard)

@dp.callback_query(lambda c: c.data in ("setlang_uz", "setlang_en"))
async def setlang_callback_handler(callback: types.CallbackQuery):
    lang = "uz" if callback.data == "setlang_uz" else "en"
    await set_user_lang(callback.from_user.id, lang)
    try:
        await callback.message.edit_text(t("setlang_set", lang))
    except Exception:
        pass
    await callback.answer()

# ==========================================
# 🔔 MAJBURIY A'ZOLIK BOSHQARUV BUYRUQLARI (FAQAT OWNER, FAQAT LICHKA)
# ==========================================

async def resolve_chat_id(username_or_id: str):
    try:
        chat = await bot.get_chat(username_or_id)
        return chat
    except Exception as e:
        logging.error(f"Resolve xatosi ({username_or_id}): {e}")
        return None

@dp.message(Cmd("majburiy"))
async def majburiy_command_handler(message: types.Message, session: aiohttp.ClientSession):
    if message.from_user.id != OWNER_ID or message.chat.type != "private":
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Xato! Kanal yoki guruh username'ini kiritishni unutdingiz.\n"
            "To'g'ri ishlatish: `/majburiy @kanalguruh`",
            parse_mode="Markdown"
        )
        return

    username = parts[1].strip()
    chat = await resolve_chat_id(username)
    if not chat:
        await message.answer(
            "❌ Bu username bo'yicha kanal/guruh topilmadi.\n"
            "Botning o'sha kanal/guruhga *administrator* qilib qo'shilganini tekshiring.",
            parse_mode="Markdown"
        )
        return

    ok = await majburiy_add_id(session, chat.id, chat.title or "", chat.username or "")

    if ok:
        await message.answer(
            f"✅ Majburiy azolik ro'yxatiga qo'shildi:\n"
            f"🆔 ID: `{chat.id}`\n"
            f"🏷 Nomi: {chat.title or chat.username}",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "⚠️ Yozishda xatolik yuz berdi, qaytadan urinib ko'ring.",
            parse_mode="Markdown"
        )

@dp.message(Cmd("remover"))
async def remover_command_handler(message: types.Message, session: aiohttp.ClientSession):
    if message.from_user.id != OWNER_ID or message.chat.type != "private":
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Xato! Kanal yoki guruh username'ini kiritishni unutdingiz.\n"
            "To'g'ri ishlatish: `/remover @kanalguruh`",
            parse_mode="Markdown"
        )
        return

    username = parts[1].strip()
    chat = await resolve_chat_id(username)
    if not chat:
        await message.answer("❌ Bu username bo'yicha kanal/guruh topilmadi.")
        return

    ok = await majburiy_remove_id(session, chat.id)

    if ok:
        await message.answer(
            f"✅ Majburiy azolik ro'yxatidan o'chirildi:\n"
            f"🆔 ID: `{chat.id}`\n"
            f"🏷 Nomi: {chat.title or chat.username}",
            parse_mode="Markdown"
        )
    else:
        await message.answer("⚠️ O'chirishda xatolik yuz berdi.")

@dp.message(Cmd("royxat"))
async def royxat_command_handler(message: types.Message, session: aiohttp.ClientSession):
    if message.from_user.id != OWNER_ID or message.chat.type != "private":
        return

    ids_list = await majburiy_get_ids(session)

    if not ids_list:
        await message.answer("❌ Majburiy azolik ro'yxati bo'sh.")
        return

    text_lines = ["📋 **Majburiy Azolik Kanallari Ro'yxati:**\n"]
    keyboard_rows = []
    idx = 1

    for cid in ids_list:
        try:
            chat = await bot.get_chat(int(cid))
        except Exception:
            continue

        title = chat.title or (f"@{chat.username}" if chat.username else str(cid))
        link = None
        if chat.username:
            link = f"https://t.me/{chat.username}"
        else:
            try:
                link = await bot.export_chat_invite_link(int(cid))
            except Exception:
                link = None

        text_lines.append(f"{idx}- {title}")
        if link:
            keyboard_rows.append([types.InlineKeyboardButton(text=f"{idx}- {title}", url=link)])
        idx += 1

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None
    await message.answer("\n".join(text_lines), reply_markup=keyboard, parse_mode="Markdown")

# --- TARJIMA VA FORMATLASH FUNKSIYALARI ---

def clean_text(text):
    if not text or not isinstance(text, str):
        return text or "Noma'lum"
    text = re.sub(r'\(Br Rank -:\s*https?://\S+\)', '', text)
    text = re.sub(r'https?://\S+', '', text)
    return text.strip()

def format_unix_date(timestamp):
    if timestamp in (None, "", 0, "0"):
        return None
    try:
        ts = int(float(timestamp))
        if ts <= 0:
            return None
        if ts > 10_000_000_000:
            ts //= 1000
        dt = datetime.utcfromtimestamp(ts)
        return dt.strftime("%d.%m.%Y")
    except (ValueError, TypeError, OSError, OverflowError):
        return None

def translate_uzbek_datetime(text):
    if not text or not isinstance(text, str):
        return None

    months = {
        'January': 'Yanvar', 'February': 'Fevral', 'March': 'Mart', 'April': 'Aprel',
        'May': 'May', 'June': 'Iyun', 'July': 'Iyul', 'August': 'Avgust',
        'September': 'Sentabr', 'October': 'Oktabr', 'November': 'Noyabr', 'December': 'Dekabr'
    }
    units = {
        'years': 'yil', 'year': 'yil',
        'months': 'oy', 'month': 'oy',
        'days': 'kun', 'day': 'kun',
        'hours': 'soat', 'hour': 'soat',
        'minutes': 'daqiqa', 'minute': 'daqiqa',
        'seconds': 'soniya', 'second': 'soniya',
        'ago': 'oldin', 'at': 'soat'
    }

    res = str(text)
    for eng, uz in months.items():
        res = re.sub(r'\b' + eng + r'\b', uz, res, flags=re.IGNORECASE)
    for eng, uz in units.items():
        res = re.sub(r'\b' + eng + r'\b', uz, res, flags=re.IGNORECASE)
    return res.strip()

def localize_raw_datetime(text, lang: str):
    if lang == "uz":
        result = translate_uzbek_datetime(text)
    else:
        result = str(text).strip() if text else None
    return result if result else t("unknown", lang)

def localize_date(timestamp, lang: str):
    formatted = format_unix_date(timestamp)
    return formatted if formatted else t("unknown", lang)

def translate_gender(gender_str, lang: str):
    val = str(gender_str).lower().strip()
    if 'male' in val and 'female' not in val:
        return t("gender_male", lang)
    elif 'female' in val:
        return t("gender_female", lang)
    return t("gender_secret", lang)

def translate_ban_info(ban, lang: str):
    status_raw = str(ban.get('ban_status', '')).lower()
    if 'not banned' in status_raw or 'clean' in status_raw or 'normal' in status_raw or status_raw in ['none', '', '0']:
        ban_status = t("ban_clean", lang)
    elif 'temporary' in status_raw:
        ban_status = t("ban_temp", lang)
    elif 'permanent' in status_raw:
        ban_status = t("ban_perm", lang)
    else:
        ban_status = t("ban_other", lang)

    is_banned_raw = str(ban.get('is_banned', '')).lower()
    is_banned = is_banned_raw in ['true', '1', 'yes']

    type_raw = str(ban.get('ban_type', '')).lower()
    if 'temporary' in type_raw:
        ban_type = t("ban_type_temp", lang)
    elif 'permanent' in type_raw:
        ban_type = t("ban_type_perm", lang)
    elif type_raw in ['not banned', 'none', 'null', '', '0']:
        ban_type = t("ban_type_none", lang)
    else:
        ban_type = ban.get('ban_type') or t("ban_type_none", lang)

    period_raw = ban.get('ban_period') or ban.get('since') or ban.get('period')
    ban_period = localize_raw_datetime(period_raw, lang)

    is_banned_str = t("banned_yes", lang) if is_banned else t("banned_no", lang)

    return ban_status, is_banned_str, ban_type, ban_period, is_banned

def translate_booyah_pass(bp_str, lang: str):
    val = str(bp_str).lower()
    if 'free' in val:
        return t("bp_free", lang)
    elif 'premium' in val:
        return t("bp_premium", lang)
    return bp_str or t("unknown", lang)

def combine_banner_and_outfit(banner_bytes, outfit_bytes):
    try:
        banner_img = Image.open(io.BytesIO(banner_bytes)).convert("RGB")
        outfit_img = Image.open(io.BytesIO(outfit_bytes)).convert("RGB")

        target_w = outfit_img.width
        b_ratio = target_w / float(banner_img.width)
        b_h = int(float(banner_img.height) * b_ratio)
        banner_resized = banner_img.resize((target_w, b_h), Image.Resampling.LANCZOS)

        gap = 8
        total_h = b_h + gap + outfit_img.height

        canvas = Image.new("RGB", (target_w, total_h), (15, 15, 18))
        canvas.paste(banner_resized, (0, 0))
        canvas.paste(outfit_img, (0, b_h + gap))

        out_buffer = io.BytesIO()
        canvas.save(out_buffer, format="JPEG", quality=90)
        return out_buffer.getvalue()
    except Exception as e:
        logging.error(f"Rasm birlashtirish xatosi: {e}")
        return banner_bytes or outfit_bytes

async def combine_banner_and_outfit_async(banner_bytes, outfit_bytes):
    return await asyncio.to_thread(combine_banner_and_outfit, banner_bytes, outfit_bytes)

# --- API SO'ROVLARI ---

FF_API_BASE = "https://solanki-info-free-fire-player-statu.vercel.app"
LIKE_API_BASE = "https://ff-like-444.vercel.app"

API_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=API_TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logging.warning(f"fetch_json xatosi ({url}): {e}")
    return None

async def fetch_bytes(session, url):
    try:
        async with session.get(url, timeout=API_TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception as e:
        logging.warning(f"fetch_bytes xatosi ({url}): {e}")
    return None

def build_info_text(data: dict, lang: str) -> str:
    acc = data.get("AccountInfo", {})
    prof = data.get("AccountProfileInfo", {})
    guild = data.get("GuildInfo", {})
    cap = data.get("CaptainInfo", {})
    credit = data.get("CreditScoreInfo", {})
    pet = data.get("PetInfo", {})
    soc = data.get("SocialInfo", {})
    ban = data.get("BanStatus", {})

    ban_status, is_banned_str, ban_type, ban_period, _ = translate_ban_info(ban, lang)
    gender_text = translate_gender(soc.get('genderLabel'), lang)
    booyah_pass_text = translate_booyah_pass(acc.get('booyahPass'), lang)
    clean_ranking_points = clean_text(acc.get('rankingPoints')) or t("unknown", lang)

    acc_age = localize_raw_datetime(acc.get('accountAge'), lang)
    created_at = localize_date(acc.get('createAt'), lang)
    last_login = localize_date(acc.get('lastLoginAt'), lang)
    unk = t("unknown", lang)

    return t(
        "info_template", lang,
        account_id=acc.get('accountId', unk),
        nickname=acc.get('nickname', unk),
        region=acc.get('region', unk),
        level=acc.get('level', unk),
        exp_needed=acc.get('ExpNeededForNextLevel', unk),
        exp=acc.get('exp', unk),
        progress=acc.get('Progress', unk),
        acc_age=acc_age,
        created_at=created_at,
        last_login=last_login,
        liked=acc.get('liked', unk),
        rank=acc.get('rank', unk),
        max_rank=acc.get('maxRank', unk),
        ranking_points=clean_ranking_points,
        cs_rank=acc.get('csRank', unk),
        cs_max_rank=acc.get('csMaxRank', unk),
        booyah_pass=booyah_pass_text,
        title_name=acc.get('titleName', unk),
        avatar_name=acc.get('avatarName', unk),
        banner_name=acc.get('bannerName', unk),
        pin_name=acc.get('pinName', unk),
        skin_color=prof.get('skinColor', unk),
        clothes=prof.get('clothes', unk),
        equipped_skills=prof.get('equipedSkills', unk),
        unlock_time=prof.get('unlockTime', unk),
        clan_name=guild.get('clanName', unk),
        clan_id=guild.get('clanId', unk),
        captain_nickname=cap.get('nickname', unk),
        captain_id=cap.get('accountId', unk),
        clan_level=guild.get('clanLevel', unk),
        member_num=guild.get('memberNum', unk),
        capacity=guild.get('capacity', unk),
        credit_score=credit.get('creditScore', unk),
        reward_state=credit.get('rewardState', unk),
        pet_name=pet.get('displayName', unk),
        pet_level=pet.get('level', unk),
        pet_exp=pet.get('exp', unk),
        language=soc.get('languageLabel', unk),
        time_active=soc.get('timeActiveLabel', unk),
        signature=soc.get('signature', unk),
        gender=gender_text,
        ban_status=ban_status,
        is_banned=is_banned_str,
        ban_type=ban_type,
        ban_period=ban_period,
    )

def build_bancheck_text(data: dict, lang: str) -> str:
    acc = data.get("AccountInfo", {})
    ban = data.get("BanStatus", {})
    unk = t("unknown", lang)

    ban_status, is_banned_str, ban_type, ban_period, is_banned = translate_ban_info(ban, lang)

    nickname = acc.get('nickname', unk)
    region = acc.get('region', unk)
    level = acc.get('level', unk)
    liked = acc.get('liked', "0")
    account_id = acc.get('accountId', unk)

    if not is_banned:
        return t(
            "bancheck_clean_template", lang,
            account_id=account_id, nickname=nickname, region=region, level=level, liked=liked
        )

    if ban_type == t("ban_type_perm", lang):
        ban_desc = t("ban_desc_perm", lang)
    else:
        ban_desc = t("ban_desc_temp", lang)

    return t(
        "bancheck_banned_template", lang,
        account_id=account_id, nickname=nickname, region=region, level=level,
        liked=liked, ban_desc=ban_desc
    )

def build_region_text(data: dict, lang: str) -> str:
    acc = data.get("AccountInfo", {})
    unk = t("unknown", lang)

    account_id = acc.get('accountId', unk)
    nickname = acc.get('nickname', unk)
    region = acc.get('region', unk)
    level = acc.get('level', unk)
    liked = acc.get('liked', "0")
    created_at = localize_date(acc.get('createAt'), lang)
    last_login = localize_date(acc.get('lastLoginAt'), lang)

    return t(
        "region_template", lang,
        account_id=account_id, nickname=nickname, region=region, level=level,
        liked=liked, created_at=created_at, last_login=last_login
    )

def build_token_text(data: dict, lang: str) -> str:
    unk = t("unknown", lang)
    return t(
        "token_template", lang,
        account_id=data.get("accountId", unk),
        ip_region=data.get("ipRegion", unk),
        lock_region=data.get("lockRegion", unk),
        noti_region=data.get("notiRegion", unk),
        agora_env=data.get("agoraEnvironment", unk),
        server_url=data.get("serverUrl", unk),
        openid=data.get("openid", unk),
        ttl=data.get("ttl", unk),
        access_token=data.get("access_token", unk),
        token=data.get("token", unk),
    )

def build_like_text(like_data: dict, level, lang: str) -> str:
    """/like API javobidan hisobot matnini yasaydi. like_data - LIKE_API_BASE
    dan qaytgan xom JSON (LikesGivenByAPI, LikesafterCommand, LikesbeforeCommand,
    PlayerNickname, UID, status). `level` - alohida /player-info dan olingan
    daraja (like API'sida daraja bo'lmagani uchun)."""
    unk = t("unknown", lang)
    status_val = like_data.get("status")
    success = str(status_val) in ("1", "True", "true")

    nickname = like_data.get("PlayerNickname", unk)
    uid = like_data.get("UID", unk)
    likes_before = like_data.get("LikesbeforeCommand", unk)
    likes_after = like_data.get("LikesafterCommand", unk)
    likes_given = like_data.get("LikesGivenByAPI", 0)
    status_text = t("like_status_success", lang) if success else t("like_status_fail", lang)

    template_key = "like_success_template" if success else "like_fail_template"
    return t(
        template_key, lang,
        nickname=nickname, uid=uid, level=(level if level not in (None, "") else unk),
        likes_before=likes_before, likes_after=likes_after,
        likes_given=likes_given, status=status_text,
    ), success

async def fetch_player_level(session, uid: str, lang: str):
    """Faqat darajani olish uchun /player-info'ga murojaat qiladi (like API
    javobida daraja bo'lmagani uchun hisobotda ko'rsatish uchun kerak)."""
    info_url = f"{FF_API_BASE}/player-info?uid={uid}"
    data = await fetch_json(session, info_url)
    if not data:
        return None
    return data.get("AccountInfo", {}).get("level")

async def perform_like(session, region: str, uid: str, lang: str):
    """Info API'dan darajani, keyin LIKE_API_BASE'dan layk natijasini oladi va
    tayyor hisobot matnini qaytaradi. Qaytadi: (text, success: bool)."""
    level, like_data = await asyncio.gather(
        fetch_player_level(session, uid, lang),
        fetch_json(session, f"{LIKE_API_BASE}/like?uid={uid}&server_name={region}"),
    )
    if not like_data or not isinstance(like_data, dict):
        unk = t("unknown", lang)
        text = t(
            "like_fail_template", lang,
            nickname=unk, uid=uid, level=(level if level not in (None, "") else unk),
            likes_before=unk, likes_after=unk, likes_given=0,
            status=t("like_status_fail", lang),
        )
        return text, False
    return build_like_text(like_data, level, lang)

# ==========================================
# 📢 REKLAMA YUBORISH KOMANDASI (rek)
# ==========================================

@dp.message(Cmd("rek"))
async def rek_command_handler(message: types.Message, session: aiohttp.ClientSession):
    if message.from_user.id != OWNER_ID:
        return

    if not message.reply_to_message:
        await message.answer("❌ **Xatolik!** `/rek` buyrug'ini yubormoqchi bo'lgan postingizga **reply** (javob) qilib yozing!")
        return

    target_post = message.reply_to_message
    ids_list = await db_get_ids(session)

    if not ids_list:
        await message.answer("❌ Bazada hech qanday foydalanuvchi yoki guruh ID'si topilmadi.")
        return

    status_msg = await message.answer(f"🚀 **Reklama yuborish boshlandi...**\n🎯 Jami mo'ljal: `{len(ids_list)}` ta chat.")

    success_count = 0
    failed_count = 0

    for raw_id in ids_list:
        try:
            chat_id = int(str(raw_id).strip())
        except ValueError:
            continue

        errors_count = 0
        sent = False

        for attempt in range(5):
            try:
                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=message.chat.id,
                    message_id=target_post.message_id
                )
                success_count += 1
                sent = True
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest):
                errors_count = 5
                break
            except Exception:
                errors_count += 1
                await asyncio.sleep(1)

        if not sent and errors_count >= 5:
            failed_count += 1
            await db_remove_id(session, chat_id)

        await asyncio.sleep(0.05)

    report_text = f"""✅ **Reklama yuborish yakunlandi!**

📊 **Natijalar:**
├─ 🟢 Muvaffaqiyatli: `{success_count}` ta
├─ 🔴 Yetib bormadi (O'chirildi): `{failed_count}` ta
└─ 👥 Baza hajmi: `{len(ids_list)}` ta
"""
    await status_msg.edit_text(report_text, parse_mode="Markdown")

# ==========================================
# 🎮 FREE FIRE BUYRUQLARI
# ==========================================

@dp.message(Cmd("info"))
async def info_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer(t("uid_missing", lang, example="/info 8530477563"), parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    waiting_msg = await message.answer(t("loading_info", lang))

    info_url = f"{FF_API_BASE}/player-info?uid={uid}"
    banner_url = f"{FF_API_BASE}/avatar-banner?uid={uid}"
    outfit_url = f"{FF_API_BASE}/player-live-outfits?uid={uid}"

    data, banner_bytes, outfit_bytes = await asyncio.gather(
        fetch_json(session, info_url),
        fetch_bytes(session, banner_url),
        fetch_bytes(session, outfit_url)
    )

    if not data:
        await waiting_msg.edit_text(t("not_found", lang))
        return

    result_text = build_info_text(data, lang)

    await waiting_msg.delete()
    sent_msg = await message.answer(result_text, parse_mode="Markdown")

    if banner_bytes and outfit_bytes:
        final_image = await combine_banner_and_outfit_async(banner_bytes, outfit_bytes)
        photo_file = BufferedInputFile(final_image, filename="player_info.jpg")
        await message.answer_photo(
            photo=photo_file,
            caption=t("info_caption", lang),
            parse_mode="Markdown",
            reply_to_message_id=sent_msg.message_id
        )

@dp.message(Cmd("bancheck"))
async def bancheck_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer(t("uid_missing", lang, example="/bancheck 7429653776"), parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    waiting_msg = await message.answer(t("loading_ban", lang))

    info_url = f"{FF_API_BASE}/player-info?uid={uid}"
    data = await fetch_json(session, info_url)

    if not data:
        await waiting_msg.edit_text(t("not_found", lang))
        return

    result_text = build_bancheck_text(data, lang)
    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("banner"))
async def banner_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer(t("uid_missing", lang, example="/banner 7429653776"), parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    waiting_msg = await message.answer(t("loading_photos", lang))

    banner_url = f"{FF_API_BASE}/avatar-banner?uid={uid}"
    outfit_url = f"{FF_API_BASE}/player-live-outfits?uid={uid}"

    banner_bytes, outfit_bytes = await asyncio.gather(
        fetch_bytes(session, banner_url),
        fetch_bytes(session, outfit_url)
    )

    await waiting_msg.delete()

    if not banner_bytes and not outfit_bytes:
        await message.answer(t("photos_failed", lang))
        return

    if banner_bytes:
        file1 = BufferedInputFile(banner_bytes, filename="banner.jpg")
        await message.answer_photo(
            photo=file1,
            caption=t("banner_caption1", lang),
            reply_to_message_id=message.message_id
        )

    if outfit_bytes:
        file2 = BufferedInputFile(outfit_bytes, filename="outfit.jpg")
        await message.answer_photo(
            photo=file2,
            caption=t("banner_caption2", lang),
            reply_to_message_id=message.message_id
        )

@dp.message(Cmd("region"))
async def region_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer(t("uid_missing", lang, example="/region 8530477563"), parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    waiting_msg = await message.answer(t("loading_region", lang))

    info_url = f"{FF_API_BASE}/player-info?uid={uid}"
    data = await fetch_json(session, info_url)

    if not data:
        await waiting_msg.edit_text(t("not_found", lang))
        return

    result_text = build_region_text(data, lang)
    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("token"))
async def token_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=2)
    if len(command_parts) < 3:
        await message.answer(t("token_missing", lang), parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    password = command_parts[2].strip()

    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    waiting_msg = await message.answer(t("loading_token", lang))

    jwt_url = f"{FF_API_BASE}/token?uid={uid}&password={password}"
    data = await fetch_json(session, jwt_url)

    if not data or not isinstance(data, dict):
        await waiting_msg.edit_text(t("token_failed", lang))
        return

    result_text = build_token_text(data, lang)
    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("like"))
async def like_command_handler(message: types.Message, session: aiohttp.ClientSession):
    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=2)
    if len(command_parts) < 3:
        await message.answer(t("like_usage_msg", lang), parse_mode="Markdown")
        return

    region = command_parts[1].strip()
    uid = command_parts[2].strip()

    if not region.isalpha():
        await message.answer(t("like_region_invalid", lang))
        return
    if not uid.isdigit():
        await message.answer(t("uid_invalid", lang))
        return

    limit = await get_like_limit()
    used = await get_like_usage(message.from_user.id)
    if used >= limit:
        await message.answer(t("like_limit_reached", lang, limit=limit))
        return

    waiting_msg = await message.answer(t("like_loading", lang))

    result_text, success = await perform_like(session, region.upper(), uid, lang)

    if success:
        await increment_like_usage(message.from_user.id)

    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("likelimit"))
async def likelimit_command_handler(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return

    lang = await get_user_lang(message.from_user.id, message.chat.type)
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip().isdigit():
        await message.answer(t("likelimit_usage", lang), parse_mode="Markdown")
        return

    limit = int(command_parts[1].strip())
    if limit <= 0:
        await message.answer(t("likelimit_usage", lang), parse_mode="Markdown")
        return

    ok = await set_like_limit(limit)
    if ok:
        await message.answer(t("likelimit_set", lang, limit=limit), parse_mode="Markdown")
    else:
        await message.answer("⚠️ Saqlashda xatolik yuz berdi, qaytadan urinib ko'ring.")

# ==========================================
# 🔎 INLINE REJIM (@FreeFire2026Chat ...)
# ==========================================
# Ishlashi uchun @BotFather'da botingizga inline rejimni yoqishni unutmang:
#   BotFather -> /mybots -> botingiz -> Bot Settings -> Inline Mode -> Turn on
#
# ESLATMA (yangi xatti-harakat): og'ir/sekin API so'rovlari endi inline_query
# javobi ICHIDA emas, foydalanuvchi natijani TANLAGANDAN keyin
# (chosen_inline_result) bajariladi. Shu sabab inline ro'yxatda hech qanday
# "yuklanmoqda" matni ko'rinmaydi - foydalanuvchi darhol "bosing" turidagi
# natijani ko'radi, so'rov faqat u BOSGANDA (tanlaganda) fonda ishga tushadi
# va tayyor bo'lgach xabar avtomatik hisobotga almashtiriladi (edit_message_text
# / edit_message_media orqali). Bu /banner uchun eskidan shunday ishlagan,
# endi /info, /bancheck, /region, /token, /like uchun ham xuddi shunday.

def _inline_command_articles(lang: str):
    items = [
        ("help", t("inline_help_title", lang), t("inline_help_desc", lang)),
        ("info", t("inline_info_title", lang), t("inline_info_desc", lang)),
        ("bancheck", t("inline_bancheck_title", lang), t("inline_bancheck_desc", lang)),
        ("banner", t("inline_banner_title", lang), t("inline_banner_desc", lang)),
        ("region", t("inline_region_title", lang), t("inline_region_desc", lang)),
        ("token", t("inline_token_title", lang), t("inline_token_desc", lang)),
        ("like", t("inline_like_title", lang), t("inline_like_desc", lang)),
    ]
    results = []
    for key, title, desc in items:
        if key == "help":
            content = InputTextMessageContent(message_text=t("start_help", lang), parse_mode="Markdown")
        else:
            content = InputTextMessageContent(message_text=f"/{key} ")
        results.append(
            InlineQueryResultArticle(
                id=f"cmd_{key}",
                title=title,
                description=desc,
                input_message_content=content,
            )
        )
    return results

def _error_article(result_id: str, title: str, description: str, text: str):
    return InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text=text),
    )

def _pending_article(result_id: str, title: str, desc: str, placeholder_text: str):
    """Og'ir ish (API so'rovi) bajarilmasdan turib DARHOL qaytariladigan
    natija - foydalanuvchi buni tanlaganda chosen_inline_result orqali
    haqiqiy hisobotga almashtiriladi."""
    return InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=desc,
        input_message_content=InputTextMessageContent(message_text=placeholder_text),
    )

@dp.inline_query()
async def inline_query_handler(inline_query: InlineQuery, session: aiohttp.ClientSession):
    user_id = inline_query.from_user.id
    lang = await get_user_lang(user_id, "private")
    query_text = (inline_query.query or "").strip()

    if user_id != OWNER_ID:
        not_subbed = await check_user_subscription(user_id, session)
        if not_subbed:
            await inline_query.answer(
                [],
                cache_time=5,
                is_personal=True,
                switch_pm_text=t("need_sub_inline", lang),
                switch_pm_parameter="sub",
            )
            return

    if not query_text:
        await inline_query.answer(_inline_command_articles(lang), cache_time=30, is_personal=True)
        return

    cmd = extract_command(query_text)
    parts = query_text.split(maxsplit=2)

    if cmd not in ("info", "bancheck", "banner", "region", "token", "like", "help"):
        await inline_query.answer(_inline_command_articles(lang), cache_time=10, is_personal=True)
        return

    if cmd == "help":
        await inline_query.answer(
            [InlineQueryResultArticle(
                id="cmd_help",
                title=t("inline_help_title", lang),
                description=t("inline_help_desc", lang),
                input_message_content=InputTextMessageContent(message_text=t("start_help", lang), parse_mode="Markdown"),
            )],
            cache_time=30, is_personal=True,
        )
        return

    if cmd == "token":
        if len(parts) < 3:
            await inline_query.answer(
                [_error_article("token_missing", t("inline_token_title", lang), t("inline_token_missing_desc", lang), t("token_missing", lang))],
                cache_time=5, is_personal=True,
            )
            return
        uid, password = parts[1].strip(), parts[2].strip()
        if not uid.isdigit():
            await inline_query.answer(
                [_error_article("token_invalid", t("inline_uid_invalid_title", lang), t("inline_uid_invalid_desc", lang), t("uid_invalid", lang))],
                cache_time=5, is_personal=True,
            )
            return
        # Og'ir ish (API so'rovi) endi bu yerda emas - chosen_inline_result'da.
        await inline_query.answer(
            [_pending_article(
                f"token:{uid}:{password}",
                f"🔑 UID {uid}",
                t("inline_tap_desc", lang),
                t("inline_loading_title", lang),
            )],
            cache_time=0, is_personal=True,
        )
        return

    if cmd == "like":
        if len(parts) < 3:
            await inline_query.answer(
                [_error_article("like_missing", t("inline_like_title", lang), t("inline_like_missing_desc", lang), t("like_usage_msg", lang))],
                cache_time=5, is_personal=True,
            )
            return
        region, uid = parts[1].strip(), parts[2].strip()
        if not region.isalpha():
            await inline_query.answer(
                [_error_article("like_region_invalid", t("inline_like_title", lang), t("inline_like_missing_desc", lang), t("like_region_invalid", lang))],
                cache_time=5, is_personal=True,
            )
            return
        if not uid.isdigit():
            await inline_query.answer(
                [_error_article("like_uid_invalid", t("inline_uid_invalid_title", lang), t("inline_uid_invalid_desc", lang), t("uid_invalid", lang))],
                cache_time=5, is_personal=True,
            )
            return
        await inline_query.answer(
            [_pending_article(
                f"like:{region.upper()}:{uid}",
                f"❤️ {region.upper()} — {uid}",
                t("inline_tap_desc", lang),
                t("inline_loading_title", lang),
            )],
            cache_time=0, is_personal=True,
        )
        return

    # info / bancheck / region / banner -> faqat UID kerak
    if len(parts) < 2 or not parts[1].strip().isdigit():
        title_key = f"inline_{cmd}_title"
        desc_key = f"inline_{cmd}_desc"
        await inline_query.answer(
            [_error_article(f"{cmd}_invalid", t(title_key, lang), t(desc_key, lang), t("uid_invalid", lang))],
            cache_time=5, is_personal=True,
        )
        return

    uid = parts[1].strip()

    # info / bancheck / region / banner - hammasi DARHOL "bosing" natijasini
    # qaytaradi, og'ir ish faqat tanlangandan keyin (chosen_inline_result)
    # bajariladi.
    title_key = f"inline_{cmd}_title"
    await inline_query.answer(
        [_pending_article(
            f"{cmd}:{uid}",
            f"{t(title_key, lang)} — {uid}",
            t("inline_tap_desc", lang),
            t("inline_loading_title", lang),
        )],
        cache_time=0, is_personal=True,
    )

@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen: ChosenInlineResult, session: aiohttp.ClientSession):
    """Foydalanuvchi inline natijani TANLAGANDAN keyin ishga tushadi - barcha
    og'ir/sekin API so'rovlari shu yerda, fonda bajariladi, keyin xabar
    tayyor hisobot/rasm bilan almashtiriladi."""
    if not chosen.inline_message_id:
        return

    result_id = chosen.result_id or ""
    if ":" not in result_id:
        return

    parts = result_id.split(":")
    cmd = parts[0]
    lang = await get_user_lang(chosen.from_user.id, "private")

    if cmd == "banner":
        uid = parts[1] if len(parts) > 1 else ""
        if not uid.isdigit():
            return
        banner_url = f"{FF_API_BASE}/avatar-banner?uid={uid}"
        outfit_url = f"{FF_API_BASE}/player-live-outfits?uid={uid}"
        banner_bytes, outfit_bytes = await asyncio.gather(
            fetch_bytes(session, banner_url),
            fetch_bytes(session, outfit_url),
        )

        if not banner_bytes and not outfit_bytes:
            try:
                await bot.edit_message_text(
                    inline_message_id=chosen.inline_message_id,
                    text=t("photos_failed", lang),
                )
            except Exception as e:
                logging.warning(f"Inline banner matn yangilashda xato: {e}")
            return

        if banner_bytes and outfit_bytes:
            final_bytes = await combine_banner_and_outfit_async(banner_bytes, outfit_bytes)
            caption = t("banner_caption_combined", lang)
        elif banner_bytes:
            final_bytes = banner_bytes
            caption = t("banner_caption1", lang)
        else:
            final_bytes = outfit_bytes
            caption = t("banner_caption2", lang)

        photo_file = BufferedInputFile(final_bytes, filename="banner.jpg")

        try:
            await bot.edit_message_media(
                inline_message_id=chosen.inline_message_id,
                media=InputMediaPhoto(media=photo_file, caption=caption, parse_mode="Markdown"),
            )
        except Exception as e:
            logging.warning(f"Inline rasm biriktirishda xato: {e}")
            try:
                await bot.edit_message_text(
                    inline_message_id=chosen.inline_message_id,
                    text=t("photos_failed", lang),
                )
            except Exception:
                pass
        return

    if cmd in ("info", "bancheck", "region"):
        uid = parts[1] if len(parts) > 1 else ""
        if not uid.isdigit():
            return
        info_url = f"{FF_API_BASE}/player-info?uid={uid}"
        data = await fetch_json(session, info_url)
        if not data:
            try:
                await bot.edit_message_text(inline_message_id=chosen.inline_message_id, text=t("not_found", lang))
            except Exception as e:
                logging.warning(f"Inline {cmd} matn yangilashda xato: {e}")
            return

        if cmd == "info":
            result_text = build_info_text(data, lang)
        elif cmd == "bancheck":
            result_text = build_bancheck_text(data, lang)
        else:
            result_text = build_region_text(data, lang)

        try:
            await bot.edit_message_text(
                inline_message_id=chosen.inline_message_id,
                text=result_text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Inline {cmd} matn yangilashda xato: {e}")
        return

    if cmd == "token":
        # id shakli: token:<uid>:<password>
        if len(parts) < 3:
            return
        uid, password = parts[1], ":".join(parts[2:])
        jwt_url = f"{FF_API_BASE}/token?uid={uid}&password={password}"
        data = await fetch_json(session, jwt_url)
        if not data or not isinstance(data, dict):
            try:
                await bot.edit_message_text(inline_message_id=chosen.inline_message_id, text=t("token_failed", lang))
            except Exception as e:
                logging.warning(f"Inline token matn yangilashda xato: {e}")
            return
        result_text = build_token_text(data, lang)
        try:
            await bot.edit_message_text(
                inline_message_id=chosen.inline_message_id,
                text=result_text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Inline token matn yangilashda xato: {e}")
        return

    if cmd == "like":
        # id shakli: like:<REGION>:<uid>
        if len(parts) < 3:
            return
        region, uid = parts[1], parts[2]
        user_id = chosen.from_user.id

        limit = await get_like_limit()
        used = await get_like_usage(user_id)
        if used >= limit:
            try:
                await bot.edit_message_text(
                    inline_message_id=chosen.inline_message_id,
                    text=t("like_limit_reached", lang, limit=limit),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logging.warning(f"Inline like limit xabarini yangilashda xato: {e}")
            return

        result_text, success = await perform_like(session, region, uid, lang)
        if success:
            await increment_like_usage(user_id)

        try:
            await bot.edit_message_text(
                inline_message_id=chosen.inline_message_id,
                text=result_text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Inline like hisobotini yangilashda xato: {e}")
        return

# ==========================================
# 🌐 RENDER UCHUN KEEP-ALIVE (WEB SERVER + SELF-PING)
# ==========================================

async def handle_ping(request):
    return web.Response(text="Bot ishlayapti ✅")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server {port}-portda ishga tushdi (Render uchun).")

async def self_ping_loop(session: aiohttp.ClientSession):
    port = int(os.environ.get("PORT", 8080))
    target_url = SELF_URL or f"http://127.0.0.1:{port}/"

    if not SELF_URL:
        logging.warning(
            "RENDER_EXTERNAL_URL topilmadi, shuning uchun lokal manzilga ping qilinmoqda."
        )

    while True:
        await asyncio.sleep(300)
        try:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                logging.info(f"Self-ping yuborildi ({target_url}), status: {resp.status}")
        except Exception as e:
            logging.warning(f"Self-ping xatosi: {e}")

# --- MAIN RUNNER ---

async def main():
    global BOT_USERNAME
    try:
        me = await bot.get_me()
        if me.username:
            BOT_USERNAME = me.username
            logging.info(f"Bot @{BOT_USERNAME} nomi bilan ishga tushdi.")
    except Exception as e:
        logging.warning(f"get_me() xatosi: {e}")

    connector = aiohttp.TCPConnector(limit=100, limit_per_host=50, ttl_dns_cache=300)
    session_timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(connector=connector, timeout=session_timeout) as session:
        dp.message.outer_middleware(AutoRegisterMiddleware())
        dp.message.outer_middleware(ForceSubscribeMiddleware())

        @dp.update.outer_middleware
        async def session_middleware(handler, event, data):
            data["session"] = session
            return await handler(event, data)

        await start_webserver()
        asyncio.create_task(self_ping_loop(session))

        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
