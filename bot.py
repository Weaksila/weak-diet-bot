import os, io, asyncio, re
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import google.generativeai as genai
import database as db
from aiohttp import web

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
ADMIN_CODE = "89049032020008885500238921632027"

# Parse multiple API keys if configured as a comma-separated list
api_keys = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()] if GEMINI_API_KEY else []
current_key_idx = 0
key_lock = asyncio.Lock()

async def generate_content_with_fallback(contents, is_vip=False):
    global current_key_idx
    if not api_keys:
        raise ValueError("No Gemini API keys configured.")
        
    if is_vip:
        # Prioritize working, responsive models first to ensure successful execution,
        # fallback to pro/flash models if quota/availability changes.
        models_to_try = ['gemini-3.1-flash-lite', 'gemini-2.5-flash-lite', 'gemini-2.5-pro', 'gemini-2.5-flash']
    else:
        # For free users (3 daily limits), prioritize the lowest/lightest models first to save quota
        models_to_try = ['gemini-3.1-flash-lite', 'gemini-2.5-flash-lite', 'gemini-2.5-flash']
        
    last_error = None
    for model_name in models_to_try:
        for attempt in range(len(api_keys)):
            key = api_keys[current_key_idx]
            try:
                # Thread/async safe configuration and model setup
                async with key_lock:
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel(model_name)
                    task = model.generate_content_async(contents)
                
                resp = await task
                print(f"[Gemini Log] Successfully generated content using model {model_name} (Key index: {current_key_idx})")
                return resp
            except Exception as e:
                err_msg = str(e).lower()
                is_quota = "429" in err_msg or "quota" in err_msg or "rate limit" in err_msg or "limit exceeded" in err_msg
                
                if is_quota:
                    print(f"[Gemini Log] Key index {current_key_idx} exhausted for model {model_name}. Rotating key...")
                    current_key_idx = (current_key_idx + 1) % len(api_keys)
                    last_error = e
                    continue
                else:
                    if "404" in err_msg or "not found" in err_msg:
                        print(f"[Gemini Log] Model {model_name} not available. Moving to next model.")
                        last_error = e
                        break # Break current key loop and try next model
                    
                    print(f"[Gemini Log] Error {type(e).__name__} for model {model_name} with key index {current_key_idx}: {e}. Rotating key...")
                    current_key_idx = (current_key_idx + 1) % len(api_keys)
                    last_error = e
                    continue
                    
    raise last_error

def calculate_calorie_target(height, weight, gender, age, goal):
    if not height or not weight or not age:
        return 2000 # default fallback
    
    # BMR calculation using Mifflin-St Jeor formula
    if gender and "ayol" in gender.lower():
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    else:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
        
    tdee = bmr * 1.25 # assume moderate/light activity
    
    if "ozish" in goal.lower() or "defitsit" in goal.lower():
        target = tdee - 500
    elif "mushak" in goal.lower() or "oshirish" in goal.lower():
        target = tdee + 500
    else:
        target = tdee
        
    return int(max(1200, target)) # Keep it above 1200 kcal for safety

def parse_calories_and_macros(text):
    calories = 0
    protein = 0.0
    carbs = 0.0
    fat = 0.0
    
    try:
        # Extract calories (look for text near fire emoji or "kaloriya" followed by numbers)
        cal_match = re.search(r'(?:kaloriya|🔥).*?(?:taxminan|\*)*\s*(\d+)(?:\s*-\s*(\d+))?\s*(?:kkal|calories)', text, re.IGNORECASE | re.DOTALL)
        if cal_match:
            val1 = int(cal_match.group(1))
            if cal_match.group(2):
                val2 = int(cal_match.group(2))
                calories = int((val1 + val2) / 2)
            else:
                calories = val1
        else:
            # Fallback regex
            cal_match_alt = re.search(r'(\d+)(?:\s*-\s*(\d+))?\s*(?:kkal|kkal|calories)', text, re.IGNORECASE)
            if cal_match_alt:
                val1 = int(cal_match_alt.group(1))
                if cal_match_alt.group(2):
                    val2 = int(cal_match_alt.group(2))
                    calories = int((val1 + val2) / 2)
                else:
                    calories = val1
                    
        # Extract macros (Protein, Carbs, Fat) by reading lines
        for line in text.split('\n'):
            line_lower = line.lower()
            num_match = re.search(r'(\d+(?:\.\d+)?)', line)
            if num_match:
                val = float(num_match.group(1))
                if "oqsil" in line_lower or "protein" in line_lower:
                    protein = val
                elif "uglevod" in line_lower or "carb" in line_lower:
                    carbs = val
                elif "yog'" in line_lower or "yog`" in line_lower or "fat" in line_lower:
                    fat = val
    except Exception as e:
        print(f"[Parser Error] Failed to parse macros: {e}")
        
    return calories, protein, carbs, fat

db.init_db()

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_single_msg_id = State()
    waiting_for_single_msg_text = State()
    waiting_for_new_limit = State()
    waiting_for_search_id = State()
    waiting_for_ban_id = State()
    waiting_for_unban_id = State()
    waiting_for_prem_id = State()
    waiting_for_prem_days = State()
    waiting_for_revoke_id = State()

class ProfileState(StatesGroup):
    waiting_for_height = State()
    waiting_for_weight = State()
    waiting_for_gender = State()
    waiting_for_age = State()
    waiting_for_goal = State()

class UserState(StatesGroup):
    waiting_for_receipt = State()

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 VIP Obuna", callback_data="show_premium"),
         InlineKeyboardButton(text="👤 Profilim", callback_data="show_profile")],
        [InlineKeyboardButton(text="🥗 Mening Menyum (VIP)", callback_data="generate_diet_plan")],
        [InlineKeyboardButton(text="💧 Suv balansi", callback_data="water_tracker"),
         InlineKeyboardButton(text="📖 Qo'llanma", callback_data="show_guide")],
        [InlineKeyboardButton(text="🌐 Tilni o'zgartirish", callback_data="show_lang")]
    ])

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton(text="🔍 Odam qidirish", callback_data="admin_search")],
        [InlineKeyboardButton(text="👥 Barcha foydalanuvchilar", callback_data="admin_users"),
         InlineKeyboardButton(text="💾 Bazani yuklash", callback_data="admin_download_db")],
        [InlineKeyboardButton(text="👑 Premium berish", callback_data="admin_premium"),
         InlineKeyboardButton(text="❌ Obunani bekor qilish", callback_data="admin_revoke")],
        [InlineKeyboardButton(text="📢 Xabar yuborish (Barchaga)", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="✉️ Xabar yuborish (Bittaga)", callback_data="admin_single_msg")],
        [InlineKeyboardButton(text="⚙️ Kunlik limitni o'zgartirish", callback_data="admin_set_limit")],
        [InlineKeyboardButton(text="🚫 Bloklash (Ban)", callback_data="admin_ban"),
         InlineKeyboardButton(text="✅ Bandan yechish", callback_data="admin_unban")],
    ])

# ─── START ───────────────────────────────────────────────
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if db.is_banned(message.from_user.id): return
    db.add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    await message.answer(
        "👋 *Salom! Men WEAK — AI dietolog botiman!*\n\n"
        "📸 Ovqat rasmini yuboring — kaloriya, oqsil, uglevod tahlil qilaman\n"
        "🧊 Muzlatgich ichini rasmga oling — retsept tuzaman\n"
        "🔍 Qadoq yorlig'ini yuboring — tarkibini tekshiraman\n"
        "🎙 Ovozli xabar yuboring — eshitib javob beraman\n\n"
        "🎁 *Kuniga 3 ta so'rov BEPUL!*",
        reply_markup=main_menu_kb()
    )

@dp.callback_query(F.data == "back_to_main")
async def cb_back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "👋 *Salom! Men WEAK — AI dietolog botiman!*\n\n"
        "📸 Ovqat rasmini yuboring — kaloriya, oqsil, uglevod tahlil qilaman\n"
        "🧊 Muzlatgich ichini rasmga oling — retsept tuzaman\n"
        "🔍 Qadoq yorlig'ini yuboring — tarkibini tekshiraman\n"
        "🎙 Ovozli xabar yuboring — eshitib javob beraman\n\n"
        "🎁 *Kuniga 3 ta so'rov BEPUL!*",
        reply_markup=main_menu_kb()
    )
    await call.answer()

# ─── MAIN MENU CALLBACKS ──────────────────────────────────
@dp.callback_query(F.data == "show_guide")
async def cb_guide(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await call.message.edit_text(
        "📖 *WEAK QO'LLANMASI*\n\n"
        "📸 *1. Kaloriya tahlili:* Ovqat rasmini yuboring\n"
        "🧊 *2. Muzlatgich retsepti:* Xolodilnik ichini rasmga oling\n"
        "🔍 *3. Yorliq skaner:* Qadoq orqasini rasmga oling\n"
        "🎙 *4. Ovozli xabar:* Gapirib yuboring, tushunaman\n"
        "👤 *5. Profil:* Bo'y/vazn kiriting — shaxsiy maslahat\n"
        "🌐 *6. Til:* /til orqali tilni o'zgartiring",
        reply_markup=kb
    )
    await call.answer()

@dp.callback_query(F.data == "show_lang")
async def cb_lang(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
         InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await call.message.edit_text("🌐 Tilni tanlang / Выберите язык / Select language:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("lang_"))
async def process_lang(call: CallbackQuery):
    l = call.data.split("_")[1]
    LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
    db.update_lang(call.from_user.id, l)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await call.message.edit_text(f"✅ Til o'zgartirildi: {LANGS[l]}", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "show_profile")
async def cb_profile(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    profile = db.get_profile(uid)
    if profile and profile[0] > 0:
        h, w, gender, age, g = profile
        target = calculate_calorie_target(h, w, gender, age, g)
        eaten_cal, eaten_prot, eaten_carb, eaten_fat = db.get_daily_intake(uid)
        
        pct = min(100, int((eaten_cal / target) * 100)) if target > 0 else 0
        filled = int(pct / 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Profilni yangilash", callback_data="edit_profile")],
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        
        msg = (
            f"👤 *Sizning profilingiz:*\n\n"
            f"📏 Bo'y: *{h} sm*\n"
            f"⚖️ Vazn: *{w} kg*\n"
            f"⚧ Jins: *{gender}*\n"
            f"🎂 Yosh: *{age} yosh*\n"
            f"🎯 Maqsad: *{g}*\n\n"
            f"🔥 *Kunlik kaloriya normasi:* *{target} kkal*\n"
            f"📊 *Bugun iste'mol qilindi:* *{eaten_cal} kkal*\n"
            f"└ {bar} ({pct}%)\n\n"
            f"💪 *Kunlik makroslar (Bugun):*\n"
            f"🥩 Protein: *{eaten_prot:.1f}g*\n"
            f"🍚 Uglevod: *{eaten_carb:.1f}g*\n"
            f"🧈 Yog': *{eaten_fat:.1f}g*"
        )
        await call.message.edit_text(msg, reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        await call.message.edit_text("📏 Bo'yingiz necha sm? (Masalan: 175)", reply_markup=kb)
        await state.set_state(ProfileState.waiting_for_height)
    await call.answer()

@dp.callback_query(F.data == "edit_profile")
async def cb_edit_profile(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await call.message.edit_text("📏 Yangi bo'yingizni kiriting (sm):", reply_markup=kb)
    await state.set_state(ProfileState.waiting_for_height)
    await call.answer()

@dp.callback_query(F.data == "show_premium")
async def cb_premium(call: CallbackQuery):
    user = call.from_user
    is_vip = db.is_premium(user.id)
    if is_vip:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Obunani bekor qilish", callback_data="user_cancel_premium")],
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        await call.message.edit_text("✅ *Siz hozir VIP foydalanuvchisiz!*\n\nCheksiz so'rovlardan bahramand bo'ling.", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 VIP Sotib olish", callback_data="buy_premium")],
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        await call.message.edit_text(
            "💎 *VIP OBUNA — Cheksiz foydalanish!*\n\n"
            "Oddiy foydalanuvchilar kuniga faqat 3 ta so'rov yuborishi mumkin. VIP bilan:\n"
            "✅ Cheksiz rasmlar va savollar\n"
            "✅ Yuqori tezlik va zaxira modellar\n\n"
            "💰 *Tariflar:*\n"
            "🔹 7 kunlik — 20,000 so'm\n"
            "🔹 15 kunlik — 40,000 so'm\n"
            "🔥 30 kunlik — 50,000 so'm *(skidka!)*\n\n"
            "💳 *To'lov:* `5614 6819 1943 1944`\n"
            "Chekni adminga yuboring!\n"
            "📞 [Admin](https://t.me/backeer) | +998 20 000 08 98",
            reply_markup=kb,
            disable_web_page_preview=True
        )
    await call.answer()

@dp.callback_query(F.data == "user_cancel_premium")
async def user_cancel_premium(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="show_premium")]
    ])
    await call.message.edit_text(
        "❌ *Obunani bekor qilish*\n\n"
        "Obunangizni bekor qilish uchun adminga murojaat qiling:\n"
        "📞 [Admin](https://t.me/backeer)",
        disable_web_page_preview=True,
        reply_markup=kb
    )
    await call.answer()

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_cb(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="show_premium")]
    ])
    await call.message.edit_text(
        "💳 *To'lovni amalga oshiring:*\n"
        "`5614 6819 1943 1944`\n\n"
        "Iltimos, to'lovni amalga oshirganingizdan so'ng, *to'lov chekini (skrinshot)* shu yerga rasm qilib yuboring 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    await state.set_state(UserState.waiting_for_receipt)
    await call.answer()

@dp.message(UserState.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext):
    user = message.from_user
    photo = message.photo[-1]
    
    uname = f"@{user.username}" if user.username else "username yo'q"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ 7 kun", callback_data=f"confirm_prem_7_{user.id}"),
         InlineKeyboardButton(text="✅ 15 kun", callback_data=f"confirm_prem_15_{user.id}")],
        [InlineKeyboardButton(text="✅ 30 kun", callback_data=f"confirm_prem_30_{user.id}")],
        [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_prem_{user.id}")]
    ])
    
    caption = (
        f"🧾 *Yangi to'lov cheki!*\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"📱 Username: {uname}\n"
    )
    
    try:
        await bot.send_photo(
            ADMIN_ID,
            photo=photo.file_id,
            caption=caption,
            reply_markup=admin_kb,
            parse_mode=ParseMode.MARKDOWN
        )
        await message.answer("✅ *Chek adminga yuborildi!*\n\nTez orada tasdiqlanadi va obunangiz faollashadi.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.answer("❌ Xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.")
    
    await state.clear()

@dp.message(UserState.waiting_for_receipt)
async def process_receipt_invalid(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        if message.text == '/cancel':
            await message.answer("❌ Bekor qilindi.")
        return
    await message.answer("⚠️ Iltimos, to'lov chekini faqat *RASM* (skrinshot) ko'rinishida yuboring yoki bekor qilish uchun /cancel bosing.")

@dp.callback_query(F.data == "cancel_premium_view")
async def cancel_premium_view_cb(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@dp.callback_query(F.data.startswith("confirm_prem_"))
async def confirm_prem_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split("_")
    days = int(parts[2])
    uid = int(parts[3])
    
    db.make_premium(uid, days)
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ *{days} kunlik VIP TASDIQLANDI!*", reply_markup=None)
    try:
        await bot.send_message(uid, f"🎉 *Tabriklaymiz!* To'lovingiz tasdiqlandi va sizga {days} kunlik *VIP OBUNA* taqdim etildi! Cheksiz foydalaning!")
    except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("reject_prem_"))
async def reject_prem_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    uid = int(call.data.split("_")[2])
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ *RAD ETILDI!*", reply_markup=None)
    try:
        await bot.send_message(uid, "❌ To'lovingiz tasdiqlanmadi. Iltimos, ma'lumotlarni qaytadan tekshirib, chekni to'g'ri yuboring yoki admin bilan bog'laning.")
    except: pass
    await call.answer()

# ─── COMMANDS ────────────────────────────────────────────
@dp.message(Command("premium"))
async def premium_cmd(message: Message):
    user = message.from_user
    is_vip = db.is_premium(user.id)
    if is_vip:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Obunani bekor qilish", callback_data="user_cancel_premium")],
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        await message.answer("✅ *Siz hozir VIP foydalanuvchisiz!*\n\nCheksiz so'rovlardan bahramand bo'ling.", reply_markup=kb)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 VIP Sotib olish", callback_data="buy_premium")],
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await message.answer(
        "💎 *VIP OBUNA — Cheksiz foydalanish!*\n\n"
        "🔹 7 kunlik — 20,000 so'm\n"
        "🔹 15 kunlik — 40,000 so'm\n"
        "🔥 30 kunlik — 50,000 so'm\n\n"
        "💳 *To'lov:* `5614 6819 1943 1944`\n"
        "📞 [Admin](https://t.me/backeer) | +998 20 000 08 98",
        reply_markup=kb,
        disable_web_page_preview=True
    )

@dp.message(Command("profil"))
async def profile_cmd(message: Message, state: FSMContext):
    uid = message.from_user.id
    profile = db.get_profile(uid)
    if profile and profile[0] > 0:
        h, w, gender, age, g = profile
        target = calculate_calorie_target(h, w, gender, age, g)
        eaten_cal, eaten_prot, eaten_carb, eaten_fat = db.get_daily_intake(uid)
        
        pct = min(100, int((eaten_cal / target) * 100)) if target > 0 else 0
        filled = int(pct / 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Profilni yangilash", callback_data="edit_profile")],
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        
        msg = (
            f"👤 *Sizning profilingiz:*\n\n"
            f"📏 Bo'y: *{h} sm*\n"
            f"⚖️ Vazn: *{w} kg*\n"
            f"⚧ Jins: *{gender}*\n"
            f"🎂 Yosh: *{age} yosh*\n"
            f"🎯 Maqsad: *{g}*\n\n"
            f"🔥 *Kunlik kaloriya normasi:* *{target} kkal*\n"
            f"📊 *Bugun iste'mol qilindi:* *{eaten_cal} kkal*\n"
            f"└ {bar} ({pct}%)\n\n"
            f"💪 *Kunlik makroslar (Bugun):*\n"
            f"🥩 Protein: *{eaten_prot:.1f}g*\n"
            f"🍚 Uglevod: *{eaten_carb:.1f}g*\n"
            f"🧈 Yog': *{eaten_fat:.1f}g*"
        )
        await message.answer(msg, reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
        ])
        await message.answer("📏 Bo'yingiz necha sm? (Masalan: 175)", reply_markup=kb)
        await state.set_state(ProfileState.waiting_for_height)

@dp.callback_query(F.data == "generate_diet_plan")
async def generate_diet_plan_cb(call: CallbackQuery):
    uid = call.from_user.id
    if not (uid == ADMIN_ID or db.is_premium(uid)):
        await call.message.answer("⚠️ Ushbu funksiya faqat *VIP mijozlar* uchun ochiq!\n\nVIP olish uchun /premium ni bosing.")
        await call.answer()
        return
        
    profile = db.get_profile(uid)
    if not profile or profile[0] == 0:
        await call.message.answer("⚠️ Avval profilingizni to'ldiring! (Bo'y, vazn, jins, yosh, maqsad)\n/profil ni bosing.")
        await call.answer()
        return
        
    h, w, gender, age, g = profile
    wait_msg = await call.message.answer("⏳ *Sizning shaxsiy 1 haftalik menyuingiz tuzilmoqda...*\n_(Bu biroz vaqt olishi mumkin)_", parse_mode=ParseMode.MARKDOWN)
    
    prompt = (
        f"Siz yuqori toifali (PRO) professional AI dietologsiz. Mijozning ko'rsatkichlari:\n"
        f"Bo'yi: {h} sm\n"
        f"Vazni: {w} kg\n"
        f"Jinsi: {gender}\n"
        f"Yoshi: {age} yosh\n"
        f"Maqsadi: {g}\n\n"
        f"Iltimos, ushbu mijoz uchun AYNAN uning maqsadiga moslashtirilgan *1 haftalik (Dushanba-Yakshanba)* aniq ovqatlanish jadvalini (menyu) yozib bering.\n"
        f"Har bir kun uchun: Nonushta, Tushlik, Kechki ovqat (va oraliq snek) mahsulotlari, grammlari va taxminiy kaloriyalari kiritilsin.\n"
        f"Javob faqat O'zbek tilida, chiroyli formatda va professional darajada bo'lsin."
    )
    
    try:
        resp = await generate_content_with_fallback([prompt], is_vip=True)
        await wait_msg.edit_text(resp.text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        try:
            await wait_msg.edit_text(resp.text, parse_mode=None)
        except:
            await wait_msg.edit_text("❌ Xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring.")
    await call.answer()

@dp.callback_query(F.data == "water_tracker")
async def water_tracker_cb(call: CallbackQuery):
    uid = call.from_user.id
    w = db.get_water(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥛 +1 stakan (250 ml)", callback_data="add_water_250")],
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    try:
        await call.message.edit_text(
            f"💧 *Suv Balansi*\n\n"
            f"Bugun ichilgan suv: *{w} ml*\n"
            f"Kunlik norma: ~2000 ml\n\n"
            f"Har safar suv ichganingizda quyidagi tugmani bosing!", 
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=kb
        )
    except: pass
    await call.answer()

@dp.callback_query(F.data == "add_water_250")
async def add_water_cb(call: CallbackQuery):
    db.add_water(call.from_user.id, 250)
    await water_tracker_cb(call)

@dp.message(Command("update_profile"))
async def update_profile_cmd(message: Message, state: FSMContext):
    await message.answer("📏 Yangi bo'yingizni kiriting (sm):")
    await state.set_state(ProfileState.waiting_for_height)

@dp.message(Command("til"))
async def lang_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
         InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await message.answer("🌐 Tilni tanlang / Выберите язык / Select language:", reply_markup=kb)

@dp.message(Command("qollanma"))
async def guide_cmd(message: Message):
    await message.answer(
        "📖 *WEAK QO'LLANMASI*\n\n"
        "*1.* Ovqat rasmini yuboring — kaloriya tahlili\n"
        "*2.* Xolodilnik ichini rasmga oling — retsept\n"
        "*3.* Qadoq orqasini rasmga oling — tarkib tekshiruvi\n"
        "*4.* Ovozli xabar yuboring — eshitib javob beraman\n"
        "*5.* /profil — shaxsiy maslahat uchun ma'lumot kiriting\n"
        "*6.* /til — tilni o'zgartiring\n"
        "*7.* /premium — VIP obuna"
    )

# ─── PROFILE STATES ───────────────────────────────────────
@dp.message(ProfileState.waiting_for_height)
async def process_height(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Profil kiritish bekor qilindi.")
        return
    try:
        h = int(message.text)
        await state.update_data(height=h)
        await message.answer("⚖️ Vazningiz (kg)? (Masalan: 70)")
        await state.set_state(ProfileState.waiting_for_weight)
    except:
        await message.answer("❌ Faqat raqam kiriting (Masalan: 175)")

@dp.message(ProfileState.waiting_for_weight)
async def process_weight(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Profil kiritish bekor qilindi.")
        return
    try:
        w = int(message.text)
        await state.update_data(weight=w)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👨 Erkak", callback_data="gender_erkak"),
             InlineKeyboardButton(text="👩 Ayol", callback_data="gender_ayol")]
        ])
        await message.answer("⚧ Jinsingizni tanlang:", reply_markup=kb)
        await state.set_state(ProfileState.waiting_for_gender)
    except:
        await message.answer("❌ Faqat raqam kiriting (Masalan: 70)")

@dp.callback_query(ProfileState.waiting_for_gender)
async def process_gender(call: CallbackQuery, state: FSMContext):
    gender_map = {"gender_erkak": "Erkak", "gender_ayol": "Ayol"}
    gender = gender_map.get(call.data, "Erkak")
    await state.update_data(gender=gender)
    await call.message.edit_text("🎂 Yoshingiz nechada? (Masalan: 25)")
    await state.set_state(ProfileState.waiting_for_age)
    await call.answer()

@dp.message(ProfileState.waiting_for_age)
async def process_age(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Profil kiritish bekor qilindi.")
        return
    try:
        age = int(message.text)
        if age <= 0 or age > 120: raise ValueError
        await state.update_data(age=age)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📉 Ozish (Defitsit)", callback_data="goal_ozish")],
            [InlineKeyboardButton(text="⚖️ Hozirgi vaznni saqlash", callback_data="goal_saqlash")],
            [InlineKeyboardButton(text="💪 Mushak massasini oshirish", callback_data="goal_mushak")]
        ])
        await message.answer("🎯 Maqsadingiz?", reply_markup=kb)
        await state.set_state(ProfileState.waiting_for_goal)
    except:
        await message.answer("❌ Haqiqiy yoshingizni kiriting (Masalan: 25)")

@dp.callback_query(ProfileState.waiting_for_goal)
async def process_goal(call: CallbackQuery, state: FSMContext):
    goal_map = {"goal_ozish": "📉 Ozish", "goal_saqlash": "⚖️ Vaznni saqlash", "goal_mushak": "💪 Mushak oshirish"}
    g = goal_map.get(call.data, "Noma'lum")
    data = await state.get_data()
    db.update_profile(call.from_user.id, data['height'], data['weight'], data['gender'], data['age'], g)
    
    target = calculate_calorie_target(data['height'], data['weight'], data['gender'], data['age'], g)
    
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menuga", callback_data="back_to_main")]
    ])
    await call.message.edit_text(
        f"✅ *Profil muvaffaqiyatli saqlandi!*\n\n"
        f"🔥 Sizning kunlik kaloriya me'yoringiz: *{target} kkal*\n"
        f"Endi bot sizning parametrlaringiz bo'yicha maslahat beradi.", reply_markup=kb
    )
    await call.answer()

# ─── ADMIN PANEL ──────────────────────────────────────────
@dp.message(F.text == ADMIN_CODE)
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    count = db.get_users_count()
    vip = len(db.get_premium_users())
    active_today = db.get_today_active_users()
    await message.answer(
        f"👨‍💻 *ADMIN PANEL — WEAK Bot*\n\n"
        f"👥 Jami: {count} ta foydalanuvchi\n"
        f"💎 VIP: {vip} ta\n"
        f"👤 Oddiy: {count - vip} ta\n"
        f"📈 Bugungi aktivlar: {active_today} ta",
        reply_markup=admin_menu_kb()
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    count = db.get_users_count()
    vip = len(db.get_premium_users())
    active_today = db.get_today_active_users()
    await call.message.answer(
        f"📊 *Bot statistikasi:*\n\n"
        f"👥 Jami foydalanuvchi: *{count} ta*\n"
        f"💎 VIP foydalanuvchi: *{vip} ta*\n"
        f"👤 Oddiy foydalanuvchi: *{count - vip} ta*\n\n"
        f"📈 Bugungi aktiv foydalanuvchilar: *{active_today} ta*"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_download_db")
async def admin_download_db(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    try:
        file = FSInputFile("bot.db")
        await call.message.answer_document(document=file, caption="💾 *Bot ma'lumotlar bazasi (SQLite)*\nBarcha foydalanuvchilar va statistika shu yerda.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await call.message.answer(f"❌ Xatolik yuz berdi: {e}")
    await call.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    users = db.get_all_users()
    if not users:
        await call.message.answer("Hozircha foydalanuvchilar yo'q.")
        await call.answer()
        return
    
    text = f"👥 *Barcha foydalanuvchilar (Jami: {len(users)} ta):*\n\n"
    chunks = []
    current_chunk = text
    
    for idx, (uid, name, uname) in enumerate(users, start=1):
        tag = f"@{uname}" if uname else "—"
        line = f"{idx}. {name or 'Nomsiz'} | {tag} | `{uid}`\n"
        if len(current_chunk) + len(line) > 4000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += line
    if current_chunk:
        chunks.append(current_chunk)
        
    for chunk in chunks:
        await call.message.answer(chunk, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(0.1)
    await call.answer()

@dp.callback_query(F.data == "admin_premium")
async def admin_premium_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("👑 VIP bermoqchi bo'lgan foydalanuvchining ID raqamini kiriting:")
    await state.set_state(AdminState.waiting_for_prem_id)
    await call.answer()

@dp.message(AdminState.waiting_for_prem_id)
async def process_prem_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        uid = int(message.text)
        await state.update_data(prem_uid=uid)
        await message.answer(f"✅ ID qabul qilindi. Endi necha kun VIP bermoqchisiz? (raqamda kiriting, masalan: 30)")
        await state.set_state(AdminState.waiting_for_prem_days)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID. Faqat raqam kiriting.")

@dp.message(AdminState.waiting_for_prem_days)
async def process_prem_days(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        days = int(message.text)
        data = await state.get_data()
        uid = data['prem_uid']
        db.make_premium(uid, days)
        await message.answer(f"✅ ID {uid} ga {days} kunlik VIP obuna taqdim etildi!")
        try:
            await bot.send_message(uid, f"🎉 *Tabriklaymiz!* Sizga Admin tomonidan {days} kunlik *VIP OBUNA* taqdim etildi! Cheksiz foydalaning!")
        except: pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Faqat raqam kiriting.")

@dp.callback_query(F.data.startswith("give_prem_"))
async def give_prem_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split("_")
    
    if len(parts) == 4:
        days = int(parts[2])
        uid = int(parts[3])
    else:
        days = 30
        uid = int(parts[2])

    db.make_premium(uid, days)
    await call.message.edit_text(f"✅ {uid} ga {days} kunlik VIP berildi!")
    try:
        await bot.send_message(uid, f"🎉 *Tabriklaymiz!* Sizga {days} kunlik *VIP OBUNA* taqdim etildi! Cheksiz foydalaning!")
    except: pass

@dp.callback_query(F.data == "admin_revoke")
async def admin_revoke_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("❌ Obunasini bekor qilmoqchi bo'lgan foydalanuvchining ID raqamini kiriting:")
    await state.set_state(AdminState.waiting_for_revoke_id)
    await call.answer()

@dp.message(AdminState.waiting_for_revoke_id)
async def process_revoke_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        uid = int(message.text)
        db.revoke_premium(uid)
        await message.answer(f"✅ ID {uid} ning VIP obunasi bekor qilindi!")
        try:
            await bot.send_message(uid, "ℹ️ VIP obunangiz bekor qilindi. Yangilash uchun /premium ni bosing.")
        except: pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri ID kiritildi.")

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabarni yozing (/cancel — bekor qilish):")
    await state.set_state(AdminState.waiting_for_broadcast)
    await call.answer()

@dp.callback_query(F.data == "admin_single_msg")
async def admin_single_msg_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("✉️ Xabar yubormoqchi bo'lgan foydalanuvchining ID raqamini kiriting:")
    await state.set_state(AdminState.waiting_for_single_msg_id)
    await call.answer()

@dp.callback_query(F.data == "admin_set_limit")
async def admin_set_limit_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    current_limit = db.get_free_limit()
    await call.message.answer(
        f"⚙️ Hozirgi kunlik bepul limit: *{current_limit} ta*\n\n"
        "Yangi limitni raqamda kiriting (0 qilsangiz bepul xizmat butunlay to'xtaydi):"
    )
    await state.set_state(AdminState.waiting_for_new_limit)
    await call.answer()

@dp.message(AdminState.waiting_for_new_limit)
async def process_new_limit(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        new_limit = int(message.text)
        if new_limit < 0: raise ValueError
        db.set_free_limit(new_limit)
        await message.answer(f"✅ Bepul limit barcha uchun *{new_limit}* taga o'zgartirildi!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri. Faqat musbat raqam kiriting (yoki bekor qilish uchun /cancel).")

@dp.callback_query(F.data == "admin_search")
async def admin_search_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("🔍 Mijozning ID raqamini kiriting:")
    await state.set_state(AdminState.waiting_for_search_id)
    await call.answer()

@dp.message(AdminState.waiting_for_search_id)
async def process_search_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        target_id = int(message.text)
        user_info = db.get_user_details(target_id)
        if not user_info:
            await message.answer("❌ Bunday ID ga ega mijoz topilmadi.")
        else:
            is_vip = "✅ VIP" if user_info.get('is_premium') else "❌ Yo'q"
            banned = "🚫 BLOKLANGAN" if user_info.get('is_banned') else "✅ Faol"
            exp = user_info.get('premium_expire_date') or "Yo'q"
            info = (
                f"👤 *Mijoz ma'lumotlari:*\n\n"
                f"Ismi: {user_info.get('full_name')}\n"
                f"Username: {user_info.get('username')}\n"
                f"ID: `{user_info.get('user_id')}`\n\n"
                f"💎 VIP status: {is_vip} (Tugash: {exp})\n"
                f"📊 Bugungi ishlatishlar: {user_info.get('daily_usage')} ta\n"
                f"⚙️ Holati: {banned}\n\n"
                f"📏 Bo'y: {user_info.get('height')} sm | ⚖️ Vazn: {user_info.get('weight')} kg\n"
                f"🎯 Maqsad: {user_info.get('goal')}\n"
                f"🌐 Til: {user_info.get('lang')}"
            )
            await message.answer(info)
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri ID kiritildi.")

@dp.callback_query(F.data == "admin_ban")
async def admin_ban_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("🚫 Bloklanadigan foydalanuvchi ID sini kiriting:")
    await state.set_state(AdminState.waiting_for_ban_id)
    await call.answer()

@dp.message(AdminState.waiting_for_ban_id)
async def process_ban_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        target_id = int(message.text)
        db.ban_user(target_id)
        await message.answer(f"✅ ID {target_id} muvaffaqiyatli BLOKLANDI!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri ID kiritildi.")

@dp.callback_query(F.data == "admin_unban")
async def admin_unban_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await call.message.answer("✅ Bandan yechiladigan foydalanuvchi ID sini kiriting:")
    await state.set_state(AdminState.waiting_for_unban_id)
    await call.answer()

@dp.message(AdminState.waiting_for_unban_id)
async def process_unban_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        target_id = int(message.text)
        db.unban_user(target_id)
        await message.answer(f"✅ ID {target_id} dan ban yechildi!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri ID kiritildi.")

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.")

@dp.message(AdminState.waiting_for_single_msg_id)
async def process_single_msg_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text)
        await state.update_data(target_id=target_id)
        await message.answer(f"✅ ID qabul qilindi ({target_id}). Endi yubormoqchi bo'lgan xabaringizni yozing (rasm/video/matn):")
        await state.set_state(AdminState.waiting_for_single_msg_text)
    except ValueError:
        await message.answer("❌ ID noto'g'ri. Faqat raqam kiriting (yoki bekor qilish uchun /cancel).")

@dp.message(AdminState.waiting_for_single_msg_text)
async def process_single_msg_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    target_id = data.get('target_id')
    try:
        await bot.copy_message(target_id, message.chat.id, message.message_id)
        await message.answer(f"✅ Xabar muvaffaqiyatli yetkazildi! (ID: {target_id})")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi. Foydalanuvchi botni bloklagan bo'lishi mumkin.\nSabab: {e}")
    await state.clear()

@dp.message(AdminState.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    uids = db.get_all_user_ids()
    sent = 0
    for uid in uids:
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer(f"✅ Xabar yuborildi: {sent} ta foydalanuvchi")

# ─── MAIN HANDLERS ───────────────────────────────────────
@dp.message(F.text)
async def handle_text(message: Message):
    if message.text in (ADMIN_CODE,) or message.text.startswith('/'): return
    await process_request(message, "text")

@dp.message(F.photo)
async def handle_photo(message: Message):
    await process_request(message, "photo")

@dp.message(F.voice)
async def handle_voice(message: Message):
    uid = message.from_user.id
    if uid == ADMIN_ID or db.is_premium(uid):
        await process_request(message, "voice")
    else:
        lang_code = db.get_lang(uid)
        msg_text = {
            "uz": "🎙 *Ovozli xabarlar faqat VIP foydalanuvchilar uchun!* Ushbu funksiyadan foydalanish uchun VIP obuna sotib olishingiz kerak.",
            "ru": "🎙 *Голосовые сообщения только для VIP пользователей!* Чтобы использовать эту функцию, вам необходимо приобрести VIP-подписку.",
            "en": "🎙 *Voice messages are for VIP users only!* You need to purchase a VIP subscription to use this feature."
        }
        await message.answer(msg_text.get(lang_code, msg_text["uz"]))

@dp.message()
async def fallback(message: Message):
    if not (message.text or message.photo or message.voice):
        await message.answer("🤖 Rasm, matn yoki ovozli xabar yuboring.")

async def process_request(message: Message, input_type: str):
    uid = message.from_user.id
    if db.is_banned(uid): return

    db.add_user(uid, message.from_user.full_name, message.from_user.username)

    is_vip = False
    if uid == ADMIN_ID:
        has_limit = True
        is_vip = True
    else:
        is_vip = db.is_premium(uid)
        if is_vip:
            has_limit = True
        else:
            has_limit = db.check_and_update_limit(uid)

    if not has_limit:
        free_limit = db.get_free_limit()
        if free_limit == 0:
            msg = "⚠️ *Hozirda bepul xizmat vaqtincha to'xtatilgan!*\n\nBotdan cheksiz foydalanish uchun VIP xarid qiling 👇"
        else:
            msg = f"⚠️ *Kunlik bepul limitingiz tugadi!* (kuniga {free_limit} ta so'rov)\n\nCheksiz foydalanish uchun VIP xarid qiling! 👇"
            
        await message.answer(
            msg,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 VIP Olish", callback_data="show_premium")]
            ])
        )
        return

    if not api_keys:
        await message.answer("⚠️ API kaliti topilmadi.")
        return

    lang_code = db.get_lang(uid)
    lang_names = {"uz": "O'zbek tilida", "ru": "на русском языке", "en": "in English"}
    target_lang = lang_names.get(lang_code, "O'zbek tilida")

    if is_vip:
        wait_text = {"uz": "⚡ *VIP* tezlikda tahlil qilinmoqda...", "ru": "⚡ *VIP* быстрый анализ...", "en": "⚡ *VIP* fast analyzing..."}
    else:
        wait_text = {"uz": "⏳ Tahlil qilinmoqda...", "ru": "⏳ Анализируем...", "en": "⏳ Analyzing..."}
        
    wait_msg = await message.answer(wait_text.get(lang_code, wait_text["uz"]), parse_mode=ParseMode.MARKDOWN)

    try:
        profile = db.get_profile(uid)
        personal = ""
        if profile and profile[0] > 0:
            h, w, g = profile
            personal = (f"\n\nFOYDALANUVCHI: bo'y={h}sm, vazn={w}kg, maqsad={g}. "
                       "Maslahatni aynan shunga moslang.")

        prompt_prefix = (
            f"Siz WEAK — yuqori toifali (PRO) professional AI dietolog botisiz. Javobingiz {target_lang} tilida bo'lsin.\n"
            "Mijozingiz VIP maqomiga ega, shuning uchun taom tarkibi va ta'siri haqida ilmiy asoslangan, eng chuqur va aniq (Premium) tahlil bering.\n"
        ) if is_vip else (
            f"Siz WEAK — professional AI dietolog botisiz. Javobingiz {target_lang} bo'lsin.\n"
        )

        prompt = (
            prompt_prefix +
            "Foydalanuvchi yuborgan rasm yoki matndagi taomni diqqat bilan tahlil qiling va AYNAN quyidagi shablon bo'yicha javob bering. Hech qanday salom-alik yoki ortiqcha gaplarsiz, faqat shablondagi ma'lumotlarni yozing:\n\n"
            "---\n\n"
            "### [Taom yoki mahsulot nomi] Ozuqaviy Tahlili (taxminan [vazni/porsiyasi] uchun)\n\n"
            "1. 🔥 *Taxminiy kaloriya (kkal) miqdori:*\n"
            "   [Kaloriya miqdori va u haqida qisqa izoh, masalan: Taxminan 1100 - 1300 kkal.]\n\n"
            "2. *Oqsil (protein), uglevod va yog' miqdori (grammda):*\n"
            "   💪 *Oqsil (Protein):* Taxminan [miqdor] gramm\n"
            "   🍚 *Uglevod:* Taxminan [miqdor] gramm\n"
            "   🧈 *Yog':* Taxminan [miqdor] gramm\n\n"
            "3. ⚠️ *Ushbu taom dieta va ozish (kaloriya defitsiti) uchun mos keladimi yoki yo'qligini tushuntiring:*\n"
            "   [Batafsil tushuntirish: mos keladimi, nima uchun mos kelmaydi yoki mos keladi, kunlik me'yorga ta'siri.]\n\n"
            "4. ✅ *Atletlar va faqat mushak massasini oshirmoqchi bo'lganlar uchun ushbu taomning foydasi haqida xulosa bering:*\n"
            "   ⚡ *Energiya manbai:* [izoh]\n"
            "   📈 *Mushak massasini oshirish:* [izoh]\n"
            "   ✅ *Xulosa:* [taomning mushak tiklanishi uchun yakuniy xulosasi]\n\n"
            "---" + personal
        )

        contents = [prompt]
        if input_type == "photo":
            photo = message.photo[-1]
            f = await bot.get_file(photo.file_id)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, buf)
            buf.seek(0)
            contents.append({"mime_type": "image/jpeg", "data": buf.read()})
            if message.caption: contents.append(message.caption)
        elif input_type == "voice":
            f = await bot.get_file(message.voice.file_id)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, buf)
            buf.seek(0)
            contents.append({"mime_type": "audio/ogg", "data": buf.read()})
        elif input_type == "text":
            contents.append(message.text)

        resp = await generate_content_with_fallback(contents, is_vip=is_vip)
        if not is_vip:
            await asyncio.sleep(5)  # Sun'iy sekinlashtirish (VIP obuna afzalligini ko'rsatish uchun)
        try:
            await wait_msg.edit_text(resp.text, parse_mode=ParseMode.MARKDOWN)
        except:
            await wait_msg.edit_text(resp.text, parse_mode=None)

    except Exception as e:
        err = str(e)
        if "can't parse entities" not in err:
            try:
                await bot.send_message(ADMIN_ID, f"🚨 API Xatolik!\n{err[:500]}")
            except: pass
            await wait_msg.edit_text("⚙️ Vaqtincha texnik nosozlik. Biroz kutib qayta urinib ko'ring.")
        else:
            try:
                await wait_msg.edit_text(resp.text, parse_mode=None)
            except:
                await wait_msg.edit_text("⚙️ Javobni yuborishda xatolik. Qayta urinib ko'ring.")

async def handle_web(request):
    return web.Response(text="WEAK Dietolog Bot is running!")

async def nightly_cron():
    import datetime
    while True:
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute == 0:
            uids = db.get_all_user_ids()
            for uid in uids:
                try:
                    await bot.send_message(
                        uid, 
                        "🌙 *Xayrli kech!*\n\n"
                        "Bugun maqsadingiz sari nimalar qildingiz? Rejimni buzmadingizmi?\n"
                        "Istalgan savol yoki dardingiz bo'lsa menga yozing, men AI psixolog sifatida sizga dalda berishga va ertangi kunga motivatsiya berishga tayyorman!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await asyncio.sleep(0.05)
                except: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def main():
    app = web.Application()
    app.router.add_get('/', handle_web)
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"Web server started on port {port}")
    print("WEAK Bot ishga tushdi!")
    
    asyncio.create_task(nightly_cron())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
