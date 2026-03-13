import asyncio
import logging
import sqlite3
import html
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

# --- KONFIGURATSIYA ---
API_TOKEN = "8773028400:AAGBWrajqsRhTqp3nYsLTTaTtfRqGAHkyyY"
ADMIN_ID = 7957774091
LOG_GROUP_ID = -1003225370008

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- BAZA BILAN ISHLASH ---
conn = sqlite3.connect("open_budget_pro.db", check_same_thread=False)
cursor = conn.cursor()

def db_setup():
    # Foydalanuvchilar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, phone TEXT,
        balance INTEGER DEFAULT 0, votes INTEGER DEFAULT 0,
        withdrawn INTEGER DEFAULT 0, referrer_id INTEGER, ref_paid INTEGER DEFAULT 0)''')
    
    # Kanallar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, title TEXT, url TEXT)''')

    # Ishlatilgan raqamlar
    cursor.execute('''CREATE TABLE IF NOT EXISTS used_phones (phone TEXT PRIMARY KEY)''')
    
    # Sozlamalar
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')

    default_start = (
        "<b>BOT AKTIV ISHLAMOQDA ✅</b>\n\n"
        "⁉️ BOT ORQALI QANDAY QILIB OVOZ BERISH VIDEODA KO'RSATILGAN.\n\n"
        "🎉 To'g'ri ovoz berganlarga pul shu zahoti o'tkazilmoqda!\n\n"
        "🥳 Aziz {name}! 🗳 Ovoz berish tugmasini bosib, ovoz bering!"
    )

    sets = [
        ('vote_price', '5000'), 
        ('ref_price', '1000'), 
        ('min_withdraw', '15000'), 
        ('vote_link', 'https://t.me/ochiqbudjetbot?start=053465392013'),
        ('payment_channel', 'O\'rnatilmagan'),
        ('start_text', default_start),
        ('start_video_id', '')
    ]
    
    for k, v in sets:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()

db_setup()

# --- YORDAMCHI FUNKSIYALAR ---
def get_config(key):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cursor.fetchone()
    return res[0] if res else ""

def set_config(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

async def check_sub(user_id):
    cursor.execute("SELECT channel_id FROM channels")
    rows = cursor.fetchall()
    for (ch_id,) in rows:
        try:
            m = await bot.get_chat_member(ch_id, user_id)
            if m.status in ['left', 'kicked', 'member_not_found']: 
                return False
        except: 
            return False
    return True

async def send_channel_log(text):
    """Maxsus log kanaliga ma'lumot yuborish"""
    try:
        await bot.send_message(LOG_GROUP_ID, text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Log kanaliga yozishda xato: {e}")

# --- STATES ---
class UserStates(StatesGroup):
    get_phone_for_vote = State()
    waiting_for_screenshot = State()
    withdraw_method = State()
    withdraw_details = State()
    withdraw_amount = State()

class AdminState(StatesGroup):
    broadcast_text = State()
    broadcast_forward = State()
    add_ch_title = State()
    add_ch_url = State()
    add_ch_id = State()

# --- KLAVIATURALAR ---
def main_menu(user_id):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🗳 Ovoz berish")
    kb.row(types.KeyboardButton(text="💰 Hisobim"), types.KeyboardButton(text="💸 Pul yechib olish"))
    kb.row(types.KeyboardButton(text="🔗 Referal"), types.KeyboardButton(text="🏆 Yutuqlar"))
    if user_id == ADMIN_ID: 
        kb.row(types.KeyboardButton(text="⚙️ Admin Panel"))
    return kb.as_markup(resize_keyboard=True)

def admin_panel_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="✉️ Oddiy xabar"), types.KeyboardButton(text="📩 Forward xabar"))
    kb.row(types.KeyboardButton(text="📄 Ulangan kanallar"), types.KeyboardButton(text="📢 Kanal ulash"))
    kb.row(types.KeyboardButton(text="📊 Statistika"), types.KeyboardButton(text="🏠 Orqaga"))
    return kb.as_markup(resize_keyboard=True)

def withdraw_methods_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="💳 Karta raqam"), types.KeyboardButton(text="📱 Paynet (Telefon)"))
    kb.row(types.KeyboardButton(text="🏠 Orqaga"))
    return kb.as_markup(resize_keyboard=True)

# --- ASOSIY HANDLERLAR ---
@dp.message(F.text == "🏠 Orqaga")
async def back_main_handler(message: types.Message, state: FSMContext):
    await state.clear()
    start_msg = get_config('start_text').replace("{name}", html.escape(message.from_user.full_name))
    await message.answer(start_msg, reply_markup=main_menu(message.from_user.id), parse_mode="HTML")

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    u_id = message.from_user.id
    name = message.from_user.full_name
    username = message.from_user.username or "yo'q"
    
    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (u_id,))
    user_exists = cursor.fetchone()
    
    if not user_exists:
        ref_id = None
        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            p_ref = int(parts[1])
            if p_ref != u_id: 
                ref_id = p_ref
                # Referal egasiga pul qo'shish
                ref_price = int(get_config('ref_price'))
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (ref_price, ref_id))
                try:
                    await bot.send_message(ref_id, f"🎉 <b>Yangi referal qo'shildi!</b>\nSizga {ref_price} so'm bonus berildi.", parse_mode="HTML")
                except:
                    pass

        cursor.execute("INSERT INTO users (user_id, username, name, referrer_id) VALUES (?, ?, ?, ?)", (u_id, username, name, ref_id))
        conn.commit()
    else:
        # Username yangilash
        cursor.execute("UPDATE users SET username=?, name=? WHERE user_id=?", (username, name, u_id))
        conn.commit()

    if not await check_sub(u_id):
        kb = InlineKeyboardBuilder()
        cursor.execute("SELECT title, url FROM channels")
        for t, u in cursor.fetchall(): 
            kb.button(text=t, url=u)
        kb.button(text="✅ Tasdiqlash", callback_data="recheck")
        kb.adjust(1)
        return await message.answer("❌ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")

    start_msg = get_config('start_text').replace("{name}", html.escape(name))
    vid_id = get_config('start_video_id')

    try:
        if vid_id and vid_id != "":
            await message.answer_video(vid_id, caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
        elif os.path.exists("11.mp4"):
            msg = await message.answer_video(FSInputFile("11.mp4"), caption=start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
            set_config('start_video_id', msg.video.file_id)
        else:
            await message.answer(start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")
    except:
        await message.answer(start_msg, reply_markup=main_menu(u_id), parse_mode="HTML")

@dp.callback_query(F.data == "recheck")
async def recheck_sub(call: types.CallbackQuery, state: FSMContext):
    if await check_sub(call.from_user.id):
        await call.message.delete()
        await cmd_start(call.message, state)
    else:
        await call.answer("❌ Hali obuna bo'lmagansiz!", show_alert=True)

# --- OVOZ BERISH MANTIQI ---
@dp.message(F.text == "🗳 Ovoz berish")
async def vote_step_1(message: types.Message, state: FSMContext):
    await message.answer("📞 Ovoz berish uchun telefon raqamingizni kiriting\n(Masalan: 998901234567):",
                         reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(UserStates.get_phone_for_vote)

@dp.message(UserStates.get_phone_for_vote)
async def vote_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    phone = message.text.strip().replace("+", "").replace(" ", "")
    
    if not phone.isdigit() or len(phone) < 9:
        return await message.answer("❌ Noto'g'ri raqam formati. Iltimos raqamni to'g'ri kiriting.")

    cursor.execute("SELECT phone FROM used_phones WHERE phone=?", (phone,))
    if cursor.fetchone():
        return await message.answer("❌ Bu raqam orqali allaqachon ovoz berilgan! Boshqa raqam kiriting.")

    await state.update_data(vote_phone=phone)
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Ovoz berish sahifasi", url=get_config('vote_link'))
    kb.button(text="✅ Ovoz berdim", callback_data="voted_done")
    kb.adjust(1)

    await message.answer(
        f"📱 Raqam qabul qilindi: <b>{phone}</b>\n\n"
        "1. Quyidagi <b>'Ovoz berish sahifasi'</b> tugmasini bosing.\n"
        "2. Ochiq byudjet tizimida shu raqamdan ovoz bering.\n"
        "3. Ovoz berib bo'lgach, botga qaytib <b>'✅ Ovoz berdim'</b> tugmasini bosing.", 
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "voted_done")
async def vote_step_3(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await call.message.answer(
        "📸 Ovoz berganingizni tasdiqlovchi <b>skrinshotni (rasmni)</b> shu yerga yuboring:", 
        reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True),
        parse_mode="HTML"
    )
    await state.set_state(UserStates.waiting_for_screenshot)
    await call.answer()

@dp.message(UserStates.waiting_for_screenshot, F.photo)
async def vote_step_4_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    phone = data.get('vote_phone')
    u_id = message.from_user.id
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"v_ok_{u_id}_{phone}")
    kb.button(text="❌ Rad etish", callback_data=f"v_no_{u_id}")
    kb.adjust(2)

    admin_text = f"🗳 <b>Yangi ovoz keldi!</b>\n\n👤 Foydalanuvchi: {message.from_user.full_name}\n🆔 ID: <code>{u_id}</code>\n📞 Raqam: <code>{phone}</code>"
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_text, reply_markup=kb.as_markup(), parse_mode="HTML")

    await message.answer("✅ Skrinshot adminga yuborildi. Admin tekshirib tasdiqlagach balansingizga pul qo'shiladi.", reply_markup=main_menu(u_id))
    await state.clear()

@dp.message(UserStates.waiting_for_screenshot)
async def vote_step_4_wrong(message: types.Message):
    await message.answer("❌ Iltimos, faqat rasm (skrinshot) yuboring!")

# Admin Ovoz tasdiqlashi
@dp.callback_query(F.data.startswith("v_ok_"))
async def admin_confirm_vote(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return await call.answer("Siz admin emassiz!", show_alert=True)

    parts = call.data.split("_")
    u_id = int(parts[2])
    phone = parts[3]
    price = int(get_config('vote_price'))
    
    cursor.execute("SELECT phone FROM used_phones WHERE phone=?", (phone,))
    if cursor.fetchone():
        await call.message.edit_caption(caption=call.message.caption + "\n\n⚠️ <b>BU RAQAM TASDIQLAB BO'LINGAN!</b>", parse_mode="HTML")
        return await call.answer("Bu raqam tasdiqlangan!", show_alert=True)

    cursor.execute("UPDATE users SET balance = balance + ?, votes = votes + 1, phone = ? WHERE user_id=?", (price, phone, u_id))
    cursor.execute("INSERT INTO used_phones (phone) VALUES (?)", (phone,))
    conn.commit()

    cursor.execute("SELECT username, name FROM users WHERE user_id=?", (u_id,))
    usr = cursor.fetchone()
    u_name = usr[1] if usr else "Noma'lum"
    u_user = usr[0] if usr else "yo'q"

    # Kanalga log tashlash
    log_text = (f"🗳 <b>Yangi Ovoz tasdiqlandi!</b>\n\n"
                f"👤 Foydalanuvchi: {u_name} (@{u_user})\n"
                f"🆔 ID: <code>{u_id}</code>\n"
                f"📞 Ovoz bergan raqami: <code>{phone}</code>")
    await send_channel_log(log_text)

    try: 
        await bot.send_message(u_id, f"✅ Tabriklaymiz! Skrinshotingiz tasdiqlandi.\n💰 Balansingizga <b>{price} so'm</b> qo'shildi.", parse_mode="HTML")
    except: pass
    
    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ <b>TASDIQLANDI</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("v_no_"))
async def admin_reject_vote(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return await call.answer("Siz admin emassiz!", show_alert=True)
    u_id = int(call.data.split("_")[2])
    try: await bot.send_message(u_id, "❌ Skrinshotingiz admin tomonidan <b>rad etildi</b>. Qaytadan urinib ko'ring.", parse_mode="HTML")
    except: pass
    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ <b>RAD ETILDI</b>", parse_mode="HTML")

# --- QOLGAN BO'LIMLAR ---

@dp.message(F.text == "💰 Hisobim")
async def my_account(message: types.Message):
    cursor.execute("SELECT balance, votes, withdrawn FROM users WHERE user_id=?", (message.from_user.id,))
    u = cursor.fetchone()
    if u:
        text = (f"👤 <b>Kabinet:</b> {message.from_user.full_name}\n\n"
                f"💰 Asosiy balans: <b>{u[0]} so'm</b>\n"
                f"🗳 Ovozlar soni: <b>{u[1]} ta</b>\n"
                f"💸 Yechib olingan jami pul: <b>{u[2]} so'm</b>")
        await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🔗 Referal")
async def my_referral(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    ref_price = get_config('ref_price')
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (message.from_user.id,))
    count = cursor.fetchone()[0]

    text = (f"🔗 <b>Sizning referal havolangiz:</b>\n{ref_link}\n\n"
            f"Bitta do'stingiz uchun to'lov: <b>{ref_price} so'm</b>\n"
            f"👥 Taklif qilgan do'stlaringiz soni: <b>{count} ta</b>\n\n"
            f"<i>Havolani do'stlaringizga tarqating va ko'proq pul ishlang!</i>")
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(F.text == "🏆 Yutuqlar")
async def leaderboard(message: types.Message):
    cursor.execute("SELECT name, votes FROM users ORDER BY votes DESC LIMIT 10")
    top_users = cursor.fetchall()
    
    text = "🏆 <b>Eng ko'p ovoz to'plaganlar (Top-10):</b>\n\n"
    for i, (name, votes) in enumerate(top_users, 1):
        text += f"{i}. {name} — {votes} ta ovoz\n"
    
    await message.answer(text, parse_mode="HTML")

# --- PUL YECHISH ---
@dp.message(F.text == "💸 Pul yechib olish")
async def withdraw_step_1(message: types.Message, state: FSMContext):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,))
    balance = cursor.fetchone()[0]
    min_w = int(get_config('min_withdraw'))
    
    if balance < min_w:
        return await message.answer(f"❌ Hisobingizda pul yetarli emas!\nMinimal yechish summasi: <b>{min_w} so'm</b>", parse_mode="HTML")
    
    await message.answer("💸 Pul yechish usulini tanlang:", reply_markup=withdraw_methods_kb())
    await state.set_state(UserStates.withdraw_method)

@dp.message(UserStates.withdraw_method)
async def withdraw_step_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    
    if message.text == "💳 Karta raqam":
        await state.update_data(w_method="Karta")
        await message.answer("💳 Karta raqamingizni kiriting (16 xona):", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    elif message.text == "📱 Paynet (Telefon)":
        await state.update_data(w_method="Paynet")
        await message.answer("📱 Telefon raqamingizni kiriting:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    else:
        return await message.answer("Tugmalardan birini tanlang!")
    
    await state.set_state(UserStates.withdraw_details)

@dp.message(UserStates.withdraw_details)
async def withdraw_step_3(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    
    await state.update_data(w_details=message.text)
    
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,))
    balance = cursor.fetchone()[0]
    
    await message.answer(f"💰 Qancha yechib olmoqchisiz?\nBalansingiz: <b>{balance} so'm</b>\nFaqat raqam bilan yozing:", parse_mode="HTML")
    await state.set_state(UserStates.withdraw_amount)

@dp.message(UserStates.withdraw_amount)
async def withdraw_step_4(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting!")
        
    amount = int(message.text)
    min_w = int(get_config('min_withdraw'))
    
    if amount < min_w:
        return await message.answer(f"❌ Minimal yechish: {min_w} so'm")
        
    u_id = message.from_user.id
    cursor.execute("SELECT balance, username, phone FROM users WHERE user_id=?", (u_id,))
    user_data = cursor.fetchone()
    balance = user_data[0]
    
    if balance < amount:
        return await message.answer("❌ Balansingizda buncha pul yo'q!")

    # Balansdan yechib qolish (spamni oldini olish uchun)
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, u_id))
    conn.commit()

    data = await state.get_data()
    w_method = data.get('w_method')
    w_details = data.get('w_details')
    
    # Adminga yuborish
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ To'landi", callback_data=f"w_ok_{u_id}_{amount}")
    kb.button(text="❌ Rad etish", callback_data=f"w_no_{u_id}_{amount}")
    kb.adjust(2)

    admin_text = (f"💸 <b>Yangi pul yechish so'rovi!</b>\n\n"
                  f"👤 Foydalanuvchi: {message.from_user.full_name}\n"
                  f"🆔 ID: <code>{u_id}</code>\n"
                  f"💰 Miqdor: <b>{amount} so'm</b>\n"
                  f"🏦 Usul: <b>{w_method}</b>\n"
                  f"📋 Rekvizit: <code>{w_details}</code>")

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb.as_markup(), parse_mode="HTML")
    
    await message.answer("✅ So'rovingiz adminga yuborildi. Tez orada to'lab beriladi.", reply_markup=main_menu(u_id))
    await state.clear()

# Admin pul yechishni tasdiqlashi
@dp.callback_query(F.data.startswith("w_ok_"))
async def admin_confirm_withdraw(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return await call.answer("Siz admin emassiz!")
    
    _, _, u_id, amount = call.data.split("_")
    u_id, amount = int(u_id), int(amount)
    
    # withdrawn summani oshirish
    cursor.execute("UPDATE users SET withdrawn = withdrawn + ? WHERE user_id=?", (amount, u_id))
    conn.commit()

    cursor.execute("SELECT username, name, phone FROM users WHERE user_id=?", (u_id,))
    usr = cursor.fetchone()
    u_name = usr[1] if usr else "Noma'lum"
    u_user = usr[0] if usr else "yo'q"
    u_phone = usr[2] if usr[2] else "Noma'lum"

    # Kanalga log
    log_text = (f"💸 <b>Muvaffaqiyatli to'lov amalga oshirildi!</b>\n\n"
                f"👤 Foydalanuvchi: {u_name} (@{u_user})\n"
                f"🆔 ID: <code>{u_id}</code>\n"
                f"📱 Telefon: <code>{u_phone}</code>\n"
                f"💰 Miqdor: <b>{amount} so'm</b>")
    await send_channel_log(log_text)

    try:
        await bot.send_message(u_id, f"✅ Sizning <b>{amount} so'm</b> pul yechish so'rovingiz muvaffaqiyatli to'lab berildi!", parse_mode="HTML")
    except: pass
    
    await call.message.edit_text(text=call.message.text + "\n\n✅ <b>TO'LANDI</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("w_no_"))
async def admin_reject_withdraw(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return await call.answer("Siz admin emassiz!")
    
    _, _, u_id, amount = call.data.split("_")
    u_id, amount = int(u_id), int(amount)
    
    # Pulni egasiga qaytarish
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, u_id))
    conn.commit()

    try:
        await bot.send_message(u_id, f"❌ Sizning <b>{amount} so'm</b> pul yechish so'rovingiz rad etildi va pulingiz balansingizga qaytarildi.", parse_mode="HTML")
    except: pass
    
    await call.message.edit_text(text=call.message.text + "\n\n❌ <b>RAD ETILDI (Pul qaytarildi)</b>", parse_mode="HTML")


# --- ADMIN PANEL ---
@dp.message(F.text == "⚙️ Admin Panel")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("⚙️ Admin paneliga xush kelibsiz!", reply_markup=admin_panel_kb())

@dp.message(F.text == "📊 Statistika")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*), SUM(balance), SUM(withdrawn), SUM(votes) FROM users")
    res = cursor.fetchone()
    users, balances, withdrawn, votes = res
    text = (f"📊 <b>Bot Statistikasi:</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{users or 0} ta</b>\n"
            f"🗳 Jami ovozlar: <b>{votes or 0} ta</b>\n"
            f"💰 Foydalanuvchilar balansi: <b>{balances or 0} so'm</b>\n"
            f"💸 To'lab berilgan jami pul: <b>{withdrawn or 0} so'm</b>")
    await message.answer(text, parse_mode="HTML")

# Xabar yuborish
@dp.message(F.text == "✉️ Oddiy xabar")
async def broadcast_text_1(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Yuboriladigan xabarni kiriting (yoki bekor qilish uchun '🏠 Orqaga'):", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(AdminState.broadcast_text)

@dp.message(AdminState.broadcast_text)
async def broadcast_text_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    count = 0
    await message.answer("⏳ Xabar yuborilmoqda...")
    for u in users:
        try:
            await message.copy_to(u[0])
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi.", reply_markup=admin_panel_kb())
    await state.clear()

@dp.message(F.text == "📩 Forward xabar")
async def broadcast_fwd_1(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Forward xabarni yuboring:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(AdminState.broadcast_forward)

@dp.message(AdminState.broadcast_forward)
async def broadcast_fwd_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    count = 0
    await message.answer("⏳ Xabar yuborilmoqda...")
    for u in users:
        try:
            await bot.forward_message(u[0], message.chat.id, message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi.", reply_markup=admin_panel_kb())
    await state.clear()

# Kanal qo'shish
@dp.message(F.text == "📢 Kanal ulash")
async def add_channel_1(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("1. Kanal nomini kiriting:", reply_markup=ReplyKeyboardBuilder().button(text="🏠 Orqaga").as_markup(resize_keyboard=True))
    await state.set_state(AdminState.add_ch_title)

@dp.message(AdminState.add_ch_title)
async def add_channel_2(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    await state.update_data(ch_title=message.text)
    await message.answer("2. Kanal havolasini kiriting (https://t.me/...):")
    await state.set_state(AdminState.add_ch_url)

@dp.message(AdminState.add_ch_url)
async def add_channel_3(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    await state.update_data(ch_url=message.text)
    await message.answer("3. Kanal ID sini kiriting (-100...):\n\n<i>Eslatma: Bot kanalda admin bo'lishi shart!</i>", parse_mode="HTML")
    await state.set_state(AdminState.add_ch_id)

@dp.message(AdminState.add_ch_id)
async def add_channel_4(message: types.Message, state: FSMContext):
    if message.text == "🏠 Orqaga": return await back_main_handler(message, state)
    data = await state.get_data()
    cursor.execute("INSERT INTO channels (title, url, channel_id) VALUES (?, ?, ?)", (data['ch_title'], data['ch_url'], message.text))
    conn.commit()
    await message.answer("✅ Kanal muvaffaqiyatli qo'shildi!", reply_markup=admin_panel_kb())
    await state.clear()

@dp.message(F.text == "📄 Ulangan kanallar")
async def show_channels(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT id, title, channel_id FROM channels")
    channels = cursor.fetchall()
    if not channels:
        return await message.answer("Hozircha kanallar ulanmagan.")
    
    kb = InlineKeyboardBuilder()
    text = "📄 <b>Ulangan kanallar:</b>\n\n"
    for ch in channels:
        text += f"Nom: {ch[1]} | ID: {ch[2]}\n"
        kb.button(text=f"❌ {ch[1]} ni o'chirish", callback_data=f"del_ch_{ch[0]}")
    kb.adjust(1)
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_ch_"))
async def del_channel(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    ch_id = int(call.data.split("_")[2])
    cursor.execute("DELETE FROM channels WHERE id=?", (ch_id,))
    conn.commit()
    await call.message.edit_text("✅ Kanal o'chirildi!")
    await call.answer()

# --- BOTNI ISHGA TUSHIRISH ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())