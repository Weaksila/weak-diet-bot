import os, io, asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import google.generativeai as genai
import database as db

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
ADMIN_CODE = "89049032020008885500238921632027"

db.init_db()
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_single_msg_id = State()
    waiting_for_single_msg_text = State()

class ProfileState(StatesGroup):
    waiting_for_height = State()
    waiting_for_weight = State()
    waiting_for_goal = State()

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 VIP Obuna", callback_data="show_premium"),
         InlineKeyboardButton(text="👤 Profilim", callback_data="show_profile")],
        [InlineKeyboardButton(text="📖 Qo'llanma", callback_data="show_guide"),
         InlineKeyboardButton(text="🌐 Til", callback_data="show_lang")],
    ])

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👑 Premium berish", callback_data="admin_premium"),
         InlineKeyboardButton(text="❌ Obuna bekor", callback_data="admin_revoke")],
        [InlineKeyboardButton(text="📢 Hammaga", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="✉️ Bitta odamga", callback_data="admin_single_msg")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
    ])

# ─── START ───────────────────────────────────────────────
@dp.message(CommandStart())
async def start_cmd(message: Message):
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

# ─── MAIN MENU CALLBACKS ──────────────────────────────────
@dp.callback_query(F.data == "show_guide")
async def cb_guide(call: CallbackQuery):
    await call.message.answer(
        "📖 *WEAK QO'LLANMASI*\n\n"
        "*1. Kaloriya hisoblash:* Ovqat rasmini yuboring\n"
        "*2. Muzlatgichdan retsept:* Xolodilnik ichini rasmga oling\n"
        "*3. Yorliq skaner:* Qadoq orqasini rasmga oling\n"
        "*4. Ovozli xabar:* Gapirib yuboring, tushunaman\n"
        "*5. Profil:* Bo'y/vazn kiriting — shaxsiy maslahat\n"
        "*6. Til:* /til bilan o'zgartiring"
    )
    await call.answer()

@dp.callback_query(F.data == "show_lang")
async def cb_lang(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]
    ])
    await call.message.answer("🌐 Tilni tanlang:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("lang_"))
async def process_lang(call: CallbackQuery):
    l = call.data.split("_")[1]
    LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
    db.update_lang(call.from_user.id, l)
    await call.message.edit_text(f"✅ Til o'zgartirildi: {LANGS[l]}")
    await call.answer()

@dp.callback_query(F.data == "show_profile")
async def cb_profile(call: CallbackQuery, state: FSMContext):
    profile = db.get_profile(call.from_user.id)
    if profile and profile[0] > 0:
        h, w, g = profile
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Yangilash", callback_data="edit_profile")]
        ])
        await call.message.answer(
            f"👤 *Sizning profilingiz:*\n\n"
            f"📏 Bo'y: {h} sm\n"
            f"⚖️ Vazn: {w} kg\n"
            f"🎯 Maqsad: {g}", reply_markup=kb
        )
    else:
        await call.message.answer("📏 Bo'yingiz necha sm? (Masalan: 175)")
        await state.set_state(ProfileState.waiting_for_height)
    await call.answer()

@dp.callback_query(F.data == "edit_profile")
async def cb_edit_profile(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📏 Yangi bo'yingizni kiriting (sm):")
    await state.set_state(ProfileState.waiting_for_height)
    await call.answer()

@dp.callback_query(F.data == "show_premium")
async def cb_premium(call: CallbackQuery):
    user = call.from_user
    is_vip = db.is_premium(user.id)
    if is_vip:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Obunani bekor qilish", callback_data="user_cancel_premium")]
        ])
        await call.message.answer("✅ *Siz hozir VIP foydalanuvchisiz!*\n\nCheksiz so'rovlardan bahramand bo'ling.", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Olish", callback_data="buy_premium"),
             InlineKeyboardButton(text="⏳ Keyinroq", callback_data="cancel_premium_view")]
        ])
        await call.message.answer(
            "💎 *VIP OBUNA — Cheksiz foydalanish!*\n\n"
            "Oddiy foydalanuvchilar kuniga faqat 3 ta so'rov yuborishi mumkin. VIP bilan:\n"
            "✅ Cheksiz rasmlar va savollar\n"
            "✅ Yuqori tezlik\n\n"
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
    await call.message.edit_text(
        "❌ *Obunani bekor qilish*\n\n"
        "Obunangizni bekor qilish uchun adminга murojaat qiling:\n"
        "📞 [Admin](https://t.me/backeer)",
        disable_web_page_preview=True
    )
    await call.answer()

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_cb(call: CallbackQuery):
    user = call.from_user
    try:
        uname = f"@{user.username}" if user.username else "username yo'q"
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 7 kunlik berish", callback_data=f"give_prem_7_{user.id}")],
            [InlineKeyboardButton(text="🎁 15 kunlik berish", callback_data=f"give_prem_15_{user.id}")],
            [InlineKeyboardButton(text="🎁 30 kunlik berish", callback_data=f"give_prem_30_{user.id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_reject_prem")]
        ])
        await bot.send_message(
            ADMIN_ID,
            f"🔔 *Yangi mijoz!*\n\n"
            f"👤 Ism: {user.full_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📱 Username: {uname}\n\n"
            f"💎 VIP obuna xohlayapti!",
            reply_markup=admin_kb
        )
    except: pass
    
    await call.message.edit_text("✅ *So'rovingiz Adminga yuborildi!*\n\nIltimos, to'lovni amalga oshiring va chekni adminga yuboring. Tez orada obunangiz faollashadi.", reply_markup=None)
    await call.answer()

@dp.callback_query(F.data == "cancel_premium_view")
async def cancel_premium_view_cb(call: CallbackQuery):
    await call.message.delete()
    await call.answer()

@dp.callback_query(F.data == "admin_reject_prem")
async def admin_reject_prem_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await call.message.edit_text("❌ *So'rov bekor qilindi.*")
    await call.answer()

# ─── COMMANDS ────────────────────────────────────────────
@dp.message(Command("premium"))
async def premium_cmd(message: Message):
    user = message.from_user
    is_vip = db.is_premium(user.id)
    if is_vip:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Obunani bekor qilish", callback_data="user_cancel_premium")]
        ])
        await message.answer("✅ *Siz hozir VIP foydalanuvchisiz!*\n\nCheksiz so'rovlardan bahramand bo'ling.", reply_markup=kb)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Olish", callback_data="buy_premium"),
         InlineKeyboardButton(text="⏳ Keyinroq", callback_data="cancel_premium_view")]
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
    profile = db.get_profile(message.from_user.id)
    if profile and profile[0] > 0:
        h, w, g = profile
        await message.answer(
            f"👤 *Profilingiz:*\n📏 Bo'y: {h} sm\n⚖️ Vazn: {w} kg\n🎯 Maqsad: {g}\n\n"
            "Yangilash uchun /update_profile")
    else:
        await message.answer("📏 Bo'yingiz necha sm? (Masalan: 175)")
        await state.set_state(ProfileState.waiting_for_height)

@dp.message(Command("update_profile"))
async def update_profile_cmd(message: Message, state: FSMContext):
    await message.answer("📏 Yangi bo'yingizni kiriting (sm):")
    await state.set_state(ProfileState.waiting_for_height)

@dp.message(Command("til"))
async def lang_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]
    ])
    await message.answer("🌐 Tilni tanlang:", reply_markup=kb)

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
            [InlineKeyboardButton(text="📉 Ozish", callback_data="goal_ozish")],
            [InlineKeyboardButton(text="⚖️ Vaznni saqlash", callback_data="goal_saqlash")],
            [InlineKeyboardButton(text="💪 Mushak oshirish", callback_data="goal_mushak")]
        ])
        await message.answer("🎯 Maqsadingiz?", reply_markup=kb)
        await state.set_state(ProfileState.waiting_for_goal)
    except:
        await message.answer("❌ Faqat raqam kiriting (Masalan: 70)")

@dp.callback_query(ProfileState.waiting_for_goal)
async def process_goal(call: CallbackQuery, state: FSMContext):
    goal_map = {"goal_ozish": "📉 Ozish", "goal_saqlash": "⚖️ Vaznni saqlash", "goal_mushak": "💪 Mushak oshirish"}
    g = goal_map.get(call.data, "Noma'lum")
    data = await state.get_data()
    db.update_profile(call.from_user.id, data['height'], data['weight'], g)
    await state.clear()
    await call.message.edit_text("✅ Profil saqlandi! Endi shaxsiy maslahatlar olasiz.")

# ─── ADMIN PANEL ──────────────────────────────────────────
@dp.message(F.text == ADMIN_CODE)
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    count = db.get_users_count()
    vip = len(db.get_premium_users())
    await message.answer(
        f"👨‍💻 *ADMIN PANEL — WEAK Bot*\n\n"
        f"👥 Jami: {count} ta foydalanuvchi\n"
        f"💎 VIP: {vip} ta\n"
        f"👤 Oddiy: {count - vip} ta",
        reply_markup=admin_menu_kb()
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    count = db.get_users_count()
    vip = len(db.get_premium_users())
    await call.message.answer(
        f"📊 *Bot statistikasi:*\n\n"
        f"👥 Jami foydalanuvchi: *{count} ta*\n"
        f"💎 VIP foydalanuvchi: *{vip} ta*\n"
        f"👤 Oddiy foydalanuvchi: *{count - vip} ta*"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    users = db.get_recent_users(10)
    if not users:
        await call.message.answer("Hozircha foydalanuvchilar yo'q.")
        await call.answer()
        return
    text = "👥 *Oxirgi 10 ta foydalanuvchi:*\n\n"
    for uid, name, uname in users:
        tag = f"@{uname}" if uname else "—"
        text += f"• {name or 'Nomsiz'} | {tag} | `{uid}`\n"
    await call.message.answer(text)
    await call.answer()

@dp.callback_query(F.data == "admin_premium")
async def admin_premium_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    users = db.get_recent_users()
    if not users:
        await call.message.answer("Foydalanuvchilar yo'q.")
        await call.answer()
        return
    keyboard = []
    for uid, name, uname in users:
        label = (name or uname or str(uid))[:22]
        keyboard.append([InlineKeyboardButton(text=f"👤 {label}", callback_data=f"give_prem_30_{uid}")])
    await call.message.answer("👑 30 kunlik VIP bermoqchi bo'lgan foydalanuvchini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()

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
async def admin_revoke_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    users = db.get_premium_users()
    if not users:
        await call.message.answer("Hozircha VIP foydalanuvchilar yo'q.")
        await call.answer()
        return
    keyboard = []
    for uid, name, uname, exp in users:
        label = (name or uname or str(uid))[:20]
        keyboard.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"revoke_{uid}")])
    await call.message.answer("❌ Obunasini bekor qilish uchun foydalanuvchini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()

@dp.callback_query(F.data.startswith("revoke_"))
async def revoke_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    uid = int(call.data.split("_")[1])
    db.revoke_premium(uid)
    await call.message.edit_text(f"✅ {uid} ning VIP obunasi bekor qilindi!")
    try:
        await bot.send_message(uid, "ℹ️ VIP obunangiz bekor qilindi. Yangilash uchun /premium ni bosing.")
    except: pass

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
    await process_request(message, "voice")

@dp.message()
async def fallback(message: Message):
    if not (message.text or message.photo or message.voice):
        await message.answer("🤖 Rasm, matn yoki ovozli xabar yuboring.")

async def process_request(message: Message, input_type: str):
    db.add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    uid = message.from_user.id

    if uid == ADMIN_ID:
        has_limit = True
    else:
        has_limit = db.check_and_update_limit(uid)

    if not has_limit:
        await message.answer(
            "⚠️ *Kunlik bepul limitingiz tugadi!* (kuniga 3 ta so'rov)\n\n"
            "Cheksiz foydalanish uchun VIP xarid qiling! 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 VIP Olish", callback_data="show_premium")]
            ])
        )
        return

    if not GEMINI_API_KEY:
        await message.answer("⚠️ API kaliti topilmadi.")
        return

    lang_code = db.get_lang(uid)
    lang_names = {"uz": "O'zbek tilida", "ru": "на русском языке", "en": "in English"}
    target_lang = lang_names.get(lang_code, "O'zbek tilida")

    wait_text = {"uz": "⏳ Tahlil qilinmoqda...", "ru": "⏳ Анализируем...", "en": "⏳ Analyzing..."}
    wait_msg = await message.answer(wait_text.get(lang_code, "⏳ Tahlil qilinmoqda..."))

    try:
        profile = db.get_profile(uid)
        personal = ""
        if profile and profile[0] > 0:
            h, w, g = profile
            personal = (f"\n\nFOYDALANUVCHI: bo'y={h}sm, vazn={w}kg, maqsad={g}. "
                       "Maslahatni aynan shunga moslang.")

        prompt = (
            f"Siz WEAK — professional AI dietolog botisiz. Javob {target_lang} bo'lsin.\n"
            "DIQQAT: Agar sizga OVOZLI XABAR kelgan bo'lsa, uni eshitib tushuning va javob bering!\n\n"
            "Javobingiz QISQA, LONDА va chiroyli shaklda bo'lishi SHART. Ortiqcha gaplarsiz, faqat KERAKLI ma'lumotni bering.\n"
            "1. Ovqat rasmida: kaloriya, oqsil/uglevod/yog'.\n"
            "2. Xolodilnik rasmida: qisqa retsept va kaloriya.\n"
            "3. Qadoq rasmida: foydali yoki zararli xulosasi.\n"
            "4. Ovoz yoki matnda: savolga bevosita, qisqa va aniq javob." + personal
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

        resp = model.generate_content(contents)
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

async def main():
    print("WEAK Bot ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
