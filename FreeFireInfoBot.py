import os
import asyncio
import logging
import re
import io
from PIL import Image
from aiogram import Bot, Dispatcher, types, BaseMiddleware
from aiogram.filters import Command, BaseFilter
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
import aiohttp
from aiohttp import web

TOKEN = "8925245187:AAHhXQpOq8xiH-WBJMWyjen8CjtttxkiMU4"
OWNER_ID = 8659710238  # Bot egasining ID si

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- LOKAL FAYL BAZALARI (endi tashqi API o'rniga shu serverning o'zidagi
# .txt fayllarga yoziladi) ---
USERS_DB_FILE = "users_db.txt"          # /rek buyrug'i uchun barcha chat ID'lar
LOCAL_BACKUP_FILE = "majburiy_backup.txt"  # majburiy a'zolik kanal/guruh ID'lari

# --- RENDER UCHUN KEEP-ALIVE SOZLAMALARI ---
SELF_URL = os.environ.get("RENDER_EXTERNAL_URL")

# ==========================================
# 🧩 "/" SIZ HAM, "/" BILAN HAM ISHLAYDIGAN KOMANDA FILTRI
# ==========================================

# Botning barcha tan oladigan komandalari (slashsiz, kichik harflarda)
KNOWN_COMMANDS = {
    "start", "help", "info", "bancheck", "banner",
    "region", "token", "rek", "majburiy", "remover", "royxat"
}

def extract_command(text: str):
    """Xabar matnidan komanda nomini ajratib oladi (masalan '/info 123'
    ham, 'info 123' ham 'info' qaytaradi). Komanda topilmasa None qaytadi."""
    if not text:
        return None
    match = re.match(r'^/?([A-Za-z_]+)(?:@\w+)?(?:\s|$)', text.strip())
    if not match:
        return None
    return match.group(1).lower()

class Cmd(BaseFilter):
    """Command() filtriga o'xshaydi, lekin '/' bo'lmasa ham ishlaydi.
    Masalan Cmd('info') 'info 8530477563' va '/info 8530477563' ikkalasiga
    ham mos keladi."""

    def __init__(self, *commands: str):
        self.commands = {c.lower() for c in commands}

    async def __call__(self, message: types.Message):
        cmd = extract_command(message.text)
        return cmd is not None and cmd in self.commands

# ==========================================
# 💾 UMUMIY FOYDALANUVCHILAR BAZASI (lokal .txt fayl)
# ==========================================
# Bu bazadan faqat /rek (reklama) buyrug'i uchun barcha chat ID'lar olinadi.

def _read_users_ids():
    ids = set()
    try:
        with open(USERS_DB_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ids.add(line)
    except FileNotFoundError:
        pass
    return ids

def _write_users_ids(ids):
    with open(USERS_DB_FILE, "w", encoding="utf-8") as f:
        for i in ids:
            f.write(i + "\n")

async def db_add_id(session: aiohttp.ClientSession, chat_id: int):
    """Yangi chat (user, guruh, kanal) ID'sini lokal faylga qo'shadi"""
    try:
        ids = _read_users_ids()
        str_id = str(chat_id)
        if str_id not in ids:
            ids.add(str_id)
            _write_users_ids(ids)
        return True
    except Exception as e:
        logging.error(f"DB Add xatosi ({chat_id}): {e}")
        return False

async def db_get_ids(session: aiohttp.ClientSession):
    """Bazadagi barcha ID'lar ro'yxatini oladi"""
    try:
        return list(_read_users_ids())
    except Exception as e:
        logging.error(f"DB Get IDs xatosi: {e}")
        return []

async def db_remove_id(session: aiohttp.ClientSession, chat_id):
    """Inaktiv yoki bloklangan ID'ni bazadan o'chiradi"""
    try:
        ids = _read_users_ids()
        ids.discard(str(chat_id))
        _write_users_ids(ids)
        return True
    except Exception as e:
        logging.error(f"DB Remove xatosi ({chat_id}): {e}")
        return False

# ==========================================
# 🔔 MAJBURIY A'ZOLIK BAZASI (lokal .txt fayl)
# ==========================================

def load_local_backup():
    """Lokal fayldan barcha ID'larni o'qiydi"""
    ids = []
    try:
        with open(LOCAL_BACKUP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ids.append(line.split("|")[0])
    except FileNotFoundError:
        pass
    return ids

def _read_backup_entries():
    entries = {}
    try:
        with open(LOCAL_BACKUP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split("|")
                    entries[parts[0]] = line
    except FileNotFoundError:
        pass
    return entries

def save_local_backup_entry(chat_id, title="", username=""):
    """Bitta ID'ni lokal faylga qo'shadi/yangilaydi"""
    entries = _read_backup_entries()
    entries[str(chat_id)] = f"{chat_id}|{title}|{username}"
    with open(LOCAL_BACKUP_FILE, "w", encoding="utf-8") as f:
        for line in entries.values():
            f.write(line + "\n")

def remove_local_backup_entry(chat_id):
    """Bitta ID'ni lokal fayldan o'chiradi"""
    entries = _read_backup_entries()
    entries.pop(str(chat_id), None)
    with open(LOCAL_BACKUP_FILE, "w", encoding="utf-8") as f:
        for line in entries.values():
            f.write(line + "\n")

async def majburiy_add_id(session: aiohttp.ClientSession, chat_id, title="", username=""):
    """Majburiy azolik kanal/guruh ID'sini lokal faylga qo'shadi"""
    try:
        save_local_backup_entry(chat_id, title, username)
        return True
    except Exception as e:
        logging.error(f"Majburiy Add xatosi ({chat_id}): {e}")
        return False

async def majburiy_get_ids(session: aiohttp.ClientSession):
    """Majburiy azolik uchun barcha kanal/guruh ID'larini oladi"""
    try:
        return load_local_backup()
    except Exception as e:
        logging.error(f"Majburiy Get IDs xatosi: {e}")
        return []

async def majburiy_remove_id(session: aiohttp.ClientSession, chat_id):
    """Majburiy azolik ro'yxatidan ID'ni o'chiradi"""
    try:
        remove_local_backup_entry(chat_id)
        return True
    except Exception as e:
        logging.error(f"Majburiy Remove xatosi ({chat_id}): {e}")
        return False

# --- BAZAGA AVTOMATIK QO'SHISH MIDDLEWARE ---

class AutoRegisterMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.chat:
            chat_id = event.chat.id
            # Har qanday xabar kelganda chat ID sini fonda bazaga yozamiz
            asyncio.create_task(db_add_id(data["session"], chat_id))
        return await handler(event, data)

# ==========================================
# 🔒 MAJBURIY OBUNA TEKSHIRUVI (FORCE SUBSCRIBE)
# ==========================================

# Bu buyruqlarni majburiy obuna tekshiruvidan chetlab o'tkazamiz (slashsiz nomlar)
EXEMPT_COMMANDS = ("start", "help")

async def check_user_subscription(user_id: int, session: aiohttp.ClientSession):
    """Foydalanuvchi hali obuna bo'lmagan kanal/guruh ID'lari ro'yxatini qaytaradi"""
    not_subscribed = []
    channel_ids = await majburiy_get_ids(session)
    for cid in channel_ids:
        try:
            member = await bot.get_chat_member(int(cid), user_id)
            if member.status in ("left", "kicked"):
                not_subscribed.append(cid)
        except Exception:
            # Bot kanalga admin sifatida qo'shilmagan yoki kanal topilmasa ham xatolik chiqmasin
            not_subscribed.append(cid)
    return not_subscribed

async def build_subscription_keyboard(not_subbed_ids):
    """Obuna bo'linmagan kanallar uchun tugmalar ro'yxatini yasaydi"""
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
    rows.append([types.InlineKeyboardButton(text="✅ Obuna bo'ldim, tekshirish", callback_data="check_sub")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)

async def send_subscription_prompt(message: types.Message, not_subbed_ids):
    keyboard = await build_subscription_keyboard(not_subbed_ids)
    await message.answer(
        "⚠️ **Botdan foydalanish uchun quyidagi kanal/guruhlarga obuna bo'lishingiz shart!**\n\n"
        "Obuna bo'lgach, pastdagi \"✅ Obuna bo'ldim, tekshirish\" tugmasini bosing.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

class ForceSubscribeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message) and event.from_user and event.text:
            # Bot egasi tekshiruvdan ozod
            if event.from_user.id == OWNER_ID:
                return await handler(event, data)

            cmd = extract_command(event.text)

            # /start, start kabi ozod buyruqlar
            if cmd in EXEMPT_COMMANDS:
                return await handler(event, data)

            # Faqat bot tan oladigan buyruqlarni tekshiramiz (slash bilan yoki slashsiz)
            if cmd in KNOWN_COMMANDS:
                session = data.get("session")
                not_subbed = await check_user_subscription(event.from_user.id, session)
                if not_subbed:
                    await send_subscription_prompt(event, not_subbed)
                    return
        return await handler(event, data)

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery, session: aiohttp.ClientSession):
    not_subbed = await check_user_subscription(callback.from_user.id, session)
    if not_subbed:
        keyboard = await build_subscription_keyboard(not_subbed)
        await callback.answer("❌ Siz hali barcha kanal/guruhlarga obuna bo'lmagansiz!", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
    else:
        await callback.answer("✅ Obuna tasdiqlandi! Endi botdan to'liq foydalanishingiz mumkin.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass

@dp.message(Cmd("start"))
async def start_command_handler(message: types.Message):
    await message.answer(
        "👋 Assalomu alaykum! Botga xush kelibsiz.\n\n"
        "Bot vazifasi va buyruqlar ro'yxati uchun /help buyrug'ini yuboring."
    )

@dp.message(Cmd("help"))
async def help_command_handler(message: types.Message):
    text = (
        "🤖 **Bot haqida**\n"
        "Bu bot Free Fire o'yinchilari haqida ma'lumot olish uchun mo'ljallangan: "
        "profil ma'lumotlari, ban holati, banner/outfit rasmlari, region va JWT token.\n\n"
        "📜 **Foydalanuvchi buyruqlari:**\n"
        "├─ `info <uid>` — o'yinchining to'liq profil ma'lumotlari (banner va outfit rasmi bilan)\n"
        "├─ `bancheck <uid>` — akkauntning ban holatini tekshirish\n"
        "├─ `banner <uid>` — avatar-banner va live outfit rasmlarini olish\n"
        "├─ `region <uid>` — akkaunt region va umumiy ma'lumotlari\n"
        "├─ `token <uid> <parol>` — JWT token olish\n"
        "└─ `help` — ushbu yordam xabari\n\n"
        "ℹ️ Barcha buyruqlarni `/` bilan ham (`/info 123`), `/`siz ham (`info 123`) yuborishingiz mumkin.\n"
        "ℹ️ Barcha buyruqlardan foydalanish uchun avval botga majburiy obuna kanallariga "
        "a'zo bo'lishingiz kerak bo'lishi mumkin."
    )



    await message.answer(text, parse_mode="Markdown")

# ==========================================
# 🔔 MAJBURIY A'ZOLIK BOSHQARUV BUYRUQLARI (FAQAT OWNER, FAQAT LICHKA)
# ==========================================

async def resolve_chat_id(username_or_id: str):
    """@username yoki id orqali chat obyektini topadi"""
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
            "To'g'ri ishlatish: `majburiy @kanalguruh`",
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
            "To'g'ri ishlatish: `remover @kanalguruh`",
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

def translate_uzbek_datetime(text):
    if not text or not isinstance(text, str):
        return text or "Noma'lum"

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

def translate_gender(gender_str):
    val = str(gender_str).lower().strip()
    if 'male' in val and 'female' not in val:
        return "Erkak ♂️"
    elif 'female' in val:
        return "Ayol ♀️"
    return "Maxfiy 🔒"

def translate_ban_info(ban):
    status_raw = str(ban.get('ban_status', '')).lower()
    if 'not banned' in status_raw or 'clean' in status_raw or 'normal' in status_raw or status_raw in ['none', '', '0']:
        ban_status = "🟢 Toza (Ayblov yo'q)"
    elif 'temporary' in status_raw:
        ban_status = "⏳ Umrbod bloklangan"
    elif 'permanent' in status_raw:
        ban_status = "🚫 Doimiy (Cheksiz) bloklangan"
    else:
        ban_status = "🔴 Bloklangan"

    is_banned_raw = str(ban.get('is_banned', '')).lower()
    is_banned = is_banned_raw in ['true', '1', 'yes']

    type_raw = str(ban.get('ban_type', '')).lower()
    if 'temporary' in type_raw:
        ban_type = "Umrbod"
    elif 'permanent' in type_raw:
        ban_type = "Doimiy"
    elif type_raw in ['not banned', 'none', 'null', '', '0']:
        ban_type = "Mavjud emas"
    else:
        ban_type = ban.get('ban_type', "Mavjud emas")

    period_raw = ban.get('ban_period') or ban.get('since') or ban.get('period')
    ban_period = translate_uzbek_datetime(period_raw)

    is_banned_str = "🔴 Ha (Bloklangan)" if is_banned else "🟢 Yo'q (Toza)"

    return ban_status, is_banned_str, ban_type, ban_period, is_banned

def translate_booyah_pass(bp_str):
    val = str(bp_str).lower()
    if 'free' in val:
        return "Bepul 🆓"
    elif 'premium' in val:
        return "Premium ⭐"
    return bp_str or "Noma'lum"

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
        canvas.save(out_buffer, format="JPEG", quality=95)
        return out_buffer.getvalue()
    except Exception as e:
        logging.error(f"Rasm birlashtirish xatosi: {e}")
        return banner_bytes or outfit_bytes

# --- API SO'ROVLARI ---

async def fetch_json(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None

async def fetch_bytes(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None

# ==========================================
# 📢 REKLAMA YUBORISH KOMANDASI (rek)
# ==========================================

@dp.message(Cmd("rek"))
async def rek_command_handler(message: types.Message, session: aiohttp.ClientSession):
    # Faqat Owner ishlata oladi
    if message.from_user.id != OWNER_ID:
        return

    # Postga reply qilinganini tekshirish
    if not message.reply_to_message:
        await message.answer("❌ **Xatolik!** `rek` buyrug'ini yubormoqchi bo'lgan postingizga **reply** (javob) qilib yozing!")
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

        # 5 martagacha qayta urinish taktikasi
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
                # Telegram cheklov qo'ysa kutiladi
                await asyncio.sleep(e.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                # Bot bloklangan yoki guruhdan chiqarilgan
                errors_count = 5
                break
            except Exception as e:
                errors_count += 1
                await asyncio.sleep(1)

        # Agar 5 marta ketma-ket xato bersa, ID bazadan o'chiriladi
        if not sent and errors_count >= 5:
            failed_count += 1
            await db_remove_id(session, chat_id)

        # Telegram FloodWait oldini olish uchun qisqa tanaffus
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
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer("❌ Xato! UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `info 8530477563`", parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer("❌ UID faqat raqamlardan iborat bo'lishi kerak!")
        return

    waiting_msg = await message.answer("🔍 Ma'lumotlar yuklanmoqda...")

    info_url = f"https://solanki-info-free-fire-player-statu.vercel.app/player-info?uid={uid}"
    banner_url = f"https://solanki-info-free-fire-player-statu.vercel.app/avatar-banner?uid={uid}"
    outfit_url = f"https://solanki-info-free-fire-player-statu.vercel.app/player-live-outfits?uid={uid}"

    data, banner_bytes, outfit_bytes = await asyncio.gather(
        fetch_json(session, info_url),
        fetch_bytes(session, banner_url),
        fetch_bytes(session, outfit_url)
    )

    if not data:
        await waiting_msg.edit_text("❌ Bu UID bo'yicha ma'lumot topilmadi.")
        return

    acc = data.get("AccountInfo", {})
    prof = data.get("AccountProfileInfo", {})
    guild = data.get("GuildInfo", {})
    cap = data.get("CaptainInfo", {})
    credit = data.get("CreditScoreInfo", {})
    pet = data.get("PetInfo", {})
    soc = data.get("SocialInfo", {})
    ban = data.get("BanStatus", {})

    ban_status, is_banned_str, ban_type, ban_period, _ = translate_ban_info(ban)
    gender_text = translate_gender(soc.get('genderLabel'))
    booyah_pass_text = translate_booyah_pass(acc.get('booyahPass'))
    clean_ranking_points = clean_text(acc.get('rankingPoints'))

    acc_age = translate_uzbek_datetime(acc.get('accountAge'))
    created_at = translate_uzbek_datetime(acc.get('createAt'))
    last_login = translate_uzbek_datetime(acc.get('lastLoginAt'))

    result_text = f"""🎮 **FREE FIRE PLAYER INFO**

┌ 👤 **Asosiy Ma'lumotlar**
├─ 🆔 UID: `{acc.get('accountId')}`
├─ 🏷 Nik: `{acc.get('nickname')}`
├─ 🌍 Region: `{acc.get('region')}`
├─ ⭐ Daraja: `{acc.get('level')}` (Keyingi darajaga: `{acc.get('ExpNeededForNextLevel')}`)
├─ ✨ Tajriba (Exp): `{acc.get('exp')}` (Progress: `{acc.get('Progress')}`)
├─ ⏳ Akkaunt yoshi: `{acc_age}`
├─ 📅 Yaratilgan vaqti: `{created_at}`
├─ 🚪 Oxirgi kirish: `{last_login}`
├─ ❤️ Layklar: `{acc.get('liked')}`
├─ 🏅 Rank: `{acc.get('rank')}` | Max: `{acc.get('maxRank')}`
├─ 📊 Reyting ballari: `{clean_ranking_points}`
├─ ⚔️ CS Rank: `{acc.get('csRank')}` | CS Max: `{acc.get('csMaxRank')}`
├─ 🎟 Booyah Pass: `{booyah_pass_text}`
├─ 🎖 Unvon: `{acc.get('titleName')}`
├─ 🖼 Avatar: `{acc.get('avatarName')}`
├─ 🚩 Banner: `{acc.get('bannerName')}`
└─ 📌 Pin: `{acc.get('pinName')}`

┌ 👕 **Profil Jihozlari**
├─ 🎨 Teri rangi: `{prof.get('skinColor')}`
├─ 👗 Kiyimlar ID: `{prof.get('clothes')}`
├─ ⚡ Qobiliyatlar ID: `{prof.get('equipedSkills')}`
└─ 🔓 Qulfdan chiqish vaqti: `{prof.get('unlockTime')}`

┌ 🛡 **Klan (Guild) Ma'lumotlari**
├─ 🏰 Nomi: `{guild.get('clanName')}` (ID: `{guild.get('clanId')}`)
├─ 👑 Lider: `{cap.get('nickname')}` (UID: `{cap.get('accountId')}`)
├─ 📊 Klan darajasi: `{guild.get('clanLevel')}`
└─ 👥 A'zolar: `{guild.get('memberNum')} / {guild.get('capacity')}`

┌ 💯 **Kredit Reyting**
├─ 📈 Ball: `{credit.get('creditScore')}`
└─ 🎁 Mukofot holati: `{credit.get('rewardState')}`

┌ 🐾 **Uy Hayvoni (Pet)**
├─ 🐕 Nomi: `{pet.get('displayName')}`
└─ 📈 Darajasi: `{pet.get('level')}` (Exp: `{pet.get('exp')}`)

┌ 💬 **Ijtimoiy Ma'lumotlar**
├─ 🌐 Til: `{soc.get('languageLabel')}`
├─ 🌙 Faollik vaqti: `{soc.get('timeActiveLabel')}`
├─ ✍️ Status (Imzo): `{soc.get('signature')}`
└─ 👤 Jinsi: `{gender_text}`

┌ 🚫 **Ban Holati**
├─ 🔒 Ban Holati: `{ban_status}`
├─ 🚫 Bloklanganmi?: `{is_banned_str}`
├─ ⚠️ Ban turi: `{ban_type}`
└─ ⏳ Ban bo'lgan oy: `{ban_period}`
"""

    await waiting_msg.delete()
    sent_msg = await message.answer(result_text, parse_mode="Markdown")

    if banner_bytes and outfit_bytes:
        final_image = combine_banner_and_outfit(banner_bytes, outfit_bytes)
        photo_file = BufferedInputFile(final_image, filename="player_info.jpg")
        await message.answer_photo(
            photo=photo_file,
            caption="🖼 **Avatar & Banner hamda Live Outfits**",
            reply_to_message_id=sent_msg.message_id
        )

@dp.message(Cmd("bancheck"))
async def bancheck_command_handler(message: types.Message, session: aiohttp.ClientSession):
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer("❌ Xato! UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `bancheck 7429653776`", parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer("❌ UID faqat raqamlardan iborat bo'lishi kerak!")
        return

    waiting_msg = await message.answer("🔍 Ban holati tekshirilmoqda...")

    info_url = f"https://solanki-info-free-fire-player-statu.vercel.app/player-info?uid={uid}"
    data = await fetch_json(session, info_url)

    if not data:
        await waiting_msg.edit_text("❌ Bu UID bo'yicha ma'lumot topilmadi.")
        return

    acc = data.get("AccountInfo", {})
    ban = data.get("BanStatus", {})

    ban_status, is_banned_str, ban_type, ban_period, is_banned = translate_ban_info(ban)

    nickname = acc.get('nickname', "Noma'lum")
    region = acc.get('region', "Noma'lum")
    level = acc.get('level', "Noma'lum")
    liked = acc.get('liked', "0")
    account_id = acc.get('accountId', uid)

    if not is_banned:
        result_text = f"""┌ 🚫 **Ban Tekshiruvi (Bancheck Info)**
├─ 🆔 UID: `{account_id}`
├─ 🏷 Nik: `{nickname}`
├─ 🌍 Region: `{region}`
├─ ⭐ Daraja: `{level}`
├─ ❤️ Layklar: `{liked}`
└─ 🔒 Holati: Toza (Bloklanmagan) 🟢"""
    else:
        if ban_type == "Doimiy":
            ban_desc = "Doimiy (Cheksiz ban)"
        elif ban_period and ban_period != "Noma'lum" and ban_period != "Mavjud emas":
            ban_desc =  "Umrbod Ban" 
        else:
            ban_desc = "Umrbod Ban"

        result_text = f"""┌ 🚫 **Ban Tekshiruvi (Bancheck Info)**
├─ 🆔 UID: `{account_id}`
├─ 🏷 Nik: `{nickname}`
├─ 🌍 Region: `{region}`
├─ ⭐ Daraja: `{level}`
├─ ❤️ Layklar: `{liked}`
├─ 🔒 Holati: Bloklangan 🔴
└─ ⏳ Ban muddati: `{ban_desc}`"""

    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("banner"))
async def banner_command_handler(message: types.Message, session: aiohttp.ClientSession):
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer("❌ Xato! UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `banner 7429653776`", parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer("❌ UID faqat raqamlardan iborat bo'lishi kerak!")
        return

    waiting_msg = await message.answer("🔍 Rasmlar yuklanmoqda...")

    banner_url = f"https://solanki-info-free-fire-player-statu.vercel.app/avatar-banner?uid={uid}"
    outfit_url = f"https://solanki-info-free-fire-player-statu.vercel.app/player-live-outfits?uid={uid}"

    banner_bytes, outfit_bytes = await asyncio.gather(
        fetch_bytes(session, banner_url),
        fetch_bytes(session, outfit_url)
    )

    await waiting_msg.delete()

    if not banner_bytes and not outfit_bytes:
        await message.answer("❌ Rasmlarni yuklab bo'lmadi.")
        return

    if banner_bytes:
        file1 = BufferedInputFile(banner_bytes, filename="banner.jpg")
        await message.answer_photo(
            photo=file1,
            caption="🖼 Avatar va Banner",
            reply_to_message_id=message.message_id
        )

    if outfit_bytes:
        file2 = BufferedInputFile(outfit_bytes, filename="outfit.jpg")
        await message.answer_photo(
            photo=file2,
            caption="👕 O'yinchining kiyimlari (Live Outfits)",
            reply_to_message_id=message.message_id
        )

@dp.message(Cmd("region"))
async def region_command_handler(message: types.Message, session: aiohttp.ClientSession):
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.answer("❌ Xato! UID kiritishni unutdingiz.\nTo'g'ri ishlatish: `region 8530477563`", parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    if not uid.isdigit():
        await message.answer("❌ UID faqat raqamlardan iborat bo'lishi kerak!")
        return

    waiting_msg = await message.answer("🔍 Region ma'lumotlari yuklanmoqda...")

    info_url = f"https://solanki-info-free-fire-player-statu.vercel.app/player-info?uid={uid}"
    data = await fetch_json(session, info_url)

    if not data:
        await waiting_msg.edit_text("❌ Bu UID bo'yicha ma'lumot topilmadi.")
        return

    acc = data.get("AccountInfo", {})

    account_id = acc.get('accountId', uid)
    nickname = acc.get('nickname', "Noma'lum")
    region = acc.get('region', "Noma'lum")
    level = acc.get('level', "Noma'lum")
    liked = acc.get('liked', "0")
    created_at = translate_uzbek_datetime(acc.get('createAt'))
    last_login = translate_uzbek_datetime(acc.get('lastLoginAt'))

    result_text = f"""┌ 🌐 **Region Ma'lumotlari (Region Information)**
├─ 🆔 UID: `{account_id}`
├─ 🏷 Nik: `{nickname}`
├─ 🌍 Region: `{region}`
├─ ⭐ Daraja: `{level}`
├─ ❤️ Layklar: `{liked}`
├─ 📅 Yaratilgan: `{created_at}`
└─ 🚪 Oxirgi kirish: `{last_login}`"""

    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

@dp.message(Cmd("token"))
async def token_command_handler(message: types.Message, session: aiohttp.ClientSession):
    command_parts = message.text.split(maxsplit=2)
    if len(command_parts) < 3:
        await message.answer("❌ Xato! UID va parolni kiritishni unutdingiz.\nTo'g'ri ishlatish: `token 15088864083 sizning_parolingiz`", parse_mode="Markdown")
        return

    uid = command_parts[1].strip()
    password = command_parts[2].strip()

    if not uid.isdigit():
        await message.answer("❌ UID faqat raqamlardan iborat bo'lishi kerak!")
        return

    waiting_msg = await message.answer("🔑 JWT Token olinmoqda...")

    jwt_url = f"https://solanki-info-free-fire-player-statu.vercel.app/token?uid={uid}&password={password}"
    data = await fetch_json(session, jwt_url)

    if not data or not isinstance(data, dict):
        await waiting_msg.edit_text("❌ Token olib bo'lmadi! UID yoki parol xato.")
        return

    account_id = data.get("accountId", uid)
    agora_env = data.get("agoraEnvironment", "Noma'lum")
    ip_region = data.get("ipRegion", "Noma'lum")
    lock_region = data.get("lockRegion", "Noma'lum")
    noti_region = data.get("notiRegion", "Noma'lum")
    server_url = data.get("serverUrl", "Noma'lum")
    openid = data.get("openid", "Noma'lum")
    access_token = data.get("access_token", "Noma'lum")
    token = data.get("token", "Noma'lum")
    ttl = data.get("ttl", "Noma'lum")

    result_text = f"""┌ 🔑 **JWT Token Ma'lumotlari (JWT Information)**
├─ 🆔 Akkaunt ID: `{account_id}`
├─ 🌐 IP Region: `{ip_region}`
├─ 🔒 Qulflangan Region: `{lock_region}`
├─ 🔔 Bildirishnoma Region: `{noti_region}`
├─ 🎮 Agora Muhiti: `{agora_env}`
├─ 🖥️ Server Havolasi: `{server_url}`
├─ 🗝️ OpenID: `{openid}`
├─ ⏱️ Amal qilish vaqti (TTL): `{ttl}`
├─ 🎫 Access Token: `{access_token}`
└─ 🔐 Token (JWT): `{token}`"""

    await waiting_msg.edit_text(result_text, parse_mode="Markdown")

# ==========================================
# 🌐 RENDER UCHUN KEEP-ALIVE (WEB SERVER + SELF-PING)
# ==========================================

async def handle_ping(request):
    return web.Response(text="Bot ishlayapti ✅")

async def start_webserver():
    """Render bepul tarifida 'Web Service' sifatida ishlashi uchun HTTP server ochadi"""
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server {port}-portda ishga tushdi (Render uchun).")

async def self_ping_loop(session: aiohttp.ClientSession):
    """Render 15 daqiqa tashqi HTTP so'rov kelmasa botni uxlatib qo'yadi,
    shuning uchun har 5 daqiqada o'ziga o'zi yengil GET so'rov yuboradi."""
    port = int(os.environ.get("PORT", 8080))
    target_url = SELF_URL or f"http://127.0.0.1:{port}/"

    if not SELF_URL:
        logging.warning(
            "RENDER_EXTERNAL_URL topilmadi, shuning uchun lokal manzilga ping qilinmoqda. "
            "Bu Render'da mahalliy muhitda (dev rejimida) ishlayotganda normal holat; "
            "Render'ga joylashtirilganda bu o'zgaruvchi avtomatik mavjud bo'ladi."
        )

    while True:
        await asyncio.sleep(300)  # 5 daqiqa
        try:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                logging.info(f"Self-ping yuborildi ({target_url}), status: {resp.status}")
        except Exception as e:
            logging.warning(f"Self-ping xatosi: {e}")

# --- MAIN RUNNER ---

async def main():
    async with aiohttp.ClientSession() as session:
        # Middleware'lar
        dp.message.outer_middleware(AutoRegisterMiddleware())
        dp.message.outer_middleware(ForceSubscribeMiddleware())

        # Har bir handlerga session ulash
        @dp.update.outer_middleware
        async def session_middleware(handler, event, data):
            data["session"] = session
            return await handler(event, data)

        # Render uchun web server va self-ping
        await start_webserver()
        asyncio.create_task(self_ping_loop(session))

        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
