import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite

# ━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━
TOKEN = "8781653487:AAGiWE1CLZxAb8fJzTq28f3fMphds25qPKI"  # এখানে আপনার বটের টোকেন দিন
ADMIN_ID = 8781653487  # এখানে আপনার টেলিগ্রাম আইডি দিন (যেমন: 8179643564)
DB_NAME = "premium_saas.db"

# ━━━━━━━━━━━━━━━━━━━━
# FSM STATES
# ━━━━━━━━━━━━━━━━━━━━
class RedeemState(StatesGroup):
    waiting_for_code = State()

class AdminState(StatesGroup):
    waiting_for_pkg_name = State()
    waiting_for_pkg_price = State()
    waiting_for_hidden_key = State() 
    
    waiting_for_stock_data = State() 
    
    waiting_for_redeem_code = State()
    waiting_for_redeem_amount = State()

# ━━━━━━━━━━━━━━━━━━━━
# DATABASE MODULE
# ━━━━━━━━━━━━━━━━━━━━
async def init_db():
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        await db.execute('PRAGMA journal_mode=WAL;')
        await db.execute('PRAGMA synchronous=NORMAL;')
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, ref_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT, 
                duration TEXT, 
                points INTEGER
            );
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_id INTEGER,
                data TEXT
            );
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY, amount INTEGER, is_used INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, package_name TEXT, status TEXT
            );
        ''')
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def add_user(user_id, ref_by=None):
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if await cursor.fetchone(): 
                return False  # Old user, no points will be given

        # Insert new user
        await db.execute("INSERT INTO users (user_id, ref_by) VALUES (?, ?)", (user_id, ref_by))
        
        # Give points to referrer safely
        if ref_by and str(ref_by) != str(user_id):
            await db.execute("UPDATE users SET points = points + 5 WHERE user_id = ?", (ref_by,))
            
        await db.commit()
        return True

async def get_packages_with_stock():
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        query = '''
            SELECT p.id, p.name, p.points, COUNT(s.id) as stock_count
            FROM packages p
            LEFT JOIN stock s ON p.id = s.package_id
            GROUP BY p.id
        '''
        async with db.execute(query) as cursor:
            return await cursor.fetchall()

# ━━━━━━━━━━━━━━━━━━━━
# KEYBOARDS
# ━━━━━━━━━━━━━━━━━━━━
def main_menu_kb(is_admin=False):
    kb = [
        [KeyboardButton(text="📦 Package"), KeyboardButton(text="🎁 Redeem")],
        [KeyboardButton(text="👤 Profile"), KeyboardButton(text="👥 Referral")],
        [KeyboardButton(text="📜 History"), KeyboardButton(text="👑 Owner")]
    ]
    if is_admin: kb.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Back to Main Menu")]], resize_keyboard=True)

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Package", callback_data="admin_add_pkg")],
        [InlineKeyboardButton(text="📥 Add More Stock", callback_data="admin_select_pkg_stock")],
        [InlineKeyboardButton(text="🎁 Add Redeem Code", callback_data="admin_add_code")],
        [InlineKeyboardButton(text="📊 System Stats", callback_data="admin_stats")]
    ])

def cancel_admin_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Operation", callback_data="admin_cancel_fsm")]
    ])

# ━━━━━━━━━━━━━━━━━━━━
# ROUTERS
# ━━━━━━━━━━━━━━━━━━━━
user_router = Router()
admin_router = Router()

# ━━━━━━━━━━━━━━━━━━━━
# USER HANDLERS
# ━━━━━━━━━━━━━━━━━━━━
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot, command: CommandObject):
    await state.clear()
    
    # Safely extract referral ID
    ref_by = None
    if command.args and command.args.isdigit():
        ref_by = int(command.args)
    
    is_new_user = await add_user(message.from_user.id, ref_by)
    
    if is_new_user and ref_by and str(ref_by) != str(message.from_user.id):
        try: 
            await bot.send_message(chat_id=ref_by, text="🎉 *New Referral!*\nSomeone joined using your link. You earned *+5 Tokens!*", parse_mode="Markdown")
        except Exception: 
            pass 

    is_admin = message.from_user.id == ADMIN_ID
    text = "🟢 *Welcome to Premium SaaS*\n━━━━━━━━━━━━━━━━━━━━\nSelect an option below to begin."
    await message.answer(text, reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")

@user_router.message(F.text == "⬅️ Back to Main Menu")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer("🟢 *Main Menu*", reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")

@user_router.message(F.text == "👤 Profile")
async def show_profile(message: Message):
    user = await get_user(message.from_user.id)
    pts = user[1] if user else 0
    text = f"👤 *User Profile*\n━━━━━━━━━━━━━━━━━━━━\n🆔 ID: `{message.from_user.id}`\n🔋 Balance: *{pts} Tokens*\n━━━━━━━━━━━━━━━━━━━━\n🟢 *Status:* Active"
    await message.answer(text, parse_mode="Markdown")

@user_router.message(F.text == "👑 Owner")
async def show_owner(message: Message):
    text = (
        "buy more credit for inbox \n"
        "WhatsApp: `01700513465`\n"
        "Telegram: @jihadxx240"
    )
    await message.answer(text, parse_mode="Markdown")

# --- PACKAGE & PURCHASE ---
@user_router.message(F.text == "📦 Package")
async def show_packages(message: Message):
    packages = await get_packages_with_stock()
    if not packages:
        return await message.answer("🟢 *No packages available.*", parse_mode="Markdown")
    
    text = "📦 *Available Packages*\n━━━━━━━━━━━━━━━━━━━━\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    for pkg in packages:
        text += f"▪️ *{pkg[1]}*\n💰 Price: {pkg[2]} Tokens\n📦 Stock: {pkg[3]} items\n━━━━━━━━━━━━━━━━━━━━\n"
        btn_text = f"🛒 Buy {pkg[1]} (Stock: {pkg[3]})" if pkg[3] > 0 else f"❌ {pkg[1]} (Out of Stock)"
        cb_data = f"buy_pkg_{pkg[0]}" if pkg[3] > 0 else "out_of_stock"
        kb.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
    
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@user_router.callback_query(F.data == "out_of_stock")
async def out_of_stock_alert(call: CallbackQuery):
    await call.answer("🔴 This package is completely sold out! Please wait for restock.", show_alert=True)

@user_router.callback_query(F.data.startswith("buy_pkg_"))
async def process_purchase(call: CallbackQuery):
    pkg_id = int(call.data.split("_")[2])
    user_id = call.from_user.id
    
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT name, points FROM packages WHERE id = ?", (pkg_id,)) as cursor:
            pkg = await cursor.fetchone()
        if not pkg: return
        pkg_name, price = pkg
        
        async with db.execute("SELECT id, data FROM stock WHERE package_id = ? LIMIT 1", (pkg_id,)) as cursor:
            stock_item = await cursor.fetchone()
            
        if not stock_item:
            return await call.answer("🔴 Out of stock! Someone might have just bought the last one.", show_alert=True)
            
        stock_id, hidden_key = stock_item
        
        async with db.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
        balance = user[0] if user else 0
        
        if balance >= price:
            await db.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (price, user_id))
            await db.execute("DELETE FROM stock WHERE id = ?", (stock_id,)) 
            await db.execute("INSERT INTO orders (user_id, package_name, status) VALUES (?, ?, ?)", (user_id, pkg_name, "Completed"))
            await db.commit()
            
            success_msg = (
                f"✅ *Purchase Successful!*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 Package: {pkg_name}\n💰 Paid: {price} Tokens\n\n"
                f"🎁 *Your Hidden Key / Item:*\n`{hidden_key}`\n\n"
                f"_(This item has been removed from our stock for your security)_"
            )
            await call.message.answer(success_msg, parse_mode="Markdown")
            await call.answer("✅ Success! Check your messages.", show_alert=False)
        else:
            await call.answer("🔴 You don't have enough tokens to buy this package!", show_alert=True)

@user_router.message(F.text == "👥 Referral")
async def show_referral(message: Message, bot: Bot):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"👥 *Referral Program*\n━━━━━━━━━━━━━━━━━━━━\nInvite friends and earn *+5 Tokens*.\n\n🔗 Your Link: `{ref_link}`", parse_mode="Markdown")

@user_router.message(F.text == "📜 History")
async def show_history(message: Message):
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT package_name, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5", (message.from_user.id,)) as cursor:
            orders = await cursor.fetchall()
    if not orders: return await message.answer("🟢 *No history available.*", parse_mode="Markdown")
    text = "📜 *Recent Orders*\n━━━━━━━━━━━━━━━━━━━━\n"
    for order in orders: text += f"📦 {order[0]} — [{order[1]}]\n"
    await message.answer(text, parse_mode="Markdown")

# --- REDEEM ---
@user_router.message(F.text == "🎁 Redeem")
async def start_redeem(message: Message, state: FSMContext):
    await state.set_state(RedeemState.waiting_for_code)
    text = (
        "🎁 *Enter your Redeem Code:*\n\n"
        "buy more credit for inbox \n"
        "WhatsApp: `01700513465`\n"
        "Telegram: @jihadxx240\n\n"
        "_(Press Back to cancel)_"
    )
    await message.answer(text, reply_markup=cancel_kb(), parse_mode="Markdown")

@user_router.message(RedeemState.waiting_for_code)
async def process_redeem(message: Message, state: FSMContext):
    code = message.text.strip()
    is_admin = message.from_user.id == ADMIN_ID
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT amount, is_used FROM redeem_codes WHERE code = ?", (code,)) as cursor:
            res = await cursor.fetchone()
            if not res: await message.answer("🔴 *Invalid code.*", reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")
            elif res[1] == 1: await message.answer("🟡 *This code has already been used.*", reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")
            else:
                await db.execute("UPDATE redeem_codes SET is_used = 1 WHERE code = ?", (code,))
                await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (res[0], message.from_user.id))
                await db.commit()
                await message.answer(f"🟢 *Success!* Added *{res[0]} Tokens*.", reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")
    await state.clear()

# ━━━━━━━━━━━━━━━━━━━━
# ADMIN HANDLERS
# ━━━━━━━━━━━━━━━━━━━━
@admin_router.message(F.text == "🛠 Admin Panel")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("🛠 *Admin Control Panel*\n━━━━━━━━━━━━━━━━━━━━", reply_markup=admin_panel_kb(), parse_mode="Markdown")

@admin_router.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM orders") as c: orders = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM stock") as c: stocks = (await c.fetchone())[0]
    await call.message.edit_text(f"📊 *System Stats*\n━━━━━━━━━━━━━━━━━━━━\n👥 Total Users: {users}\n📦 Total Orders: {orders}\n📥 Unsold Stock: {stocks}", parse_mode="Markdown")

@admin_router.callback_query(F.data == "admin_cancel_fsm")
async def admin_cancel_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🟢 *Action cancelled.*", parse_mode="Markdown")

# --- COMBINED ADD PACKAGE & STOCK FLOW ---
@admin_router.callback_query(F.data == "admin_add_pkg")
async def admin_add_pkg(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_for_pkg_name)
    await call.message.edit_text("📦 *Enter package name:*\n_(e.g., Netflix, Jihad)_", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_pkg_name)
async def admin_pkg_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminState.waiting_for_pkg_price)
    await message.answer("💰 *Enter package price in tokens (numbers only):*", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_pkg_price)
async def admin_pkg_price(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("🔴 Numbers only.")
    await state.update_data(price=int(message.text))
    await state.set_state(AdminState.waiting_for_hidden_key)
    await message.answer("📝 *Enter the Hidden Key / Extension for this package:*", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_hidden_key)
async def admin_hidden_key(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data['name']
    price = data['price']
    hidden_key = message.text
    
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        cursor = await db.execute("INSERT INTO packages (name, duration, points) VALUES (?, ?, ?)", (name, "N/A", price))
        pkg_id = cursor.lastrowid
        
        await db.execute("INSERT INTO stock (package_id, data) VALUES (?, ?)", (pkg_id, hidden_key))
        await db.commit()
        
    await state.clear()
    await message.answer(f"🟢 *Package Created & Stock Added!*\n\n📦 Name: {name}\n💰 Price: {price}\n✅ Hidden Key is active and ready to be sold.", parse_mode="Markdown")

# --- ADD MORE STOCK TO EXISTING PACKAGE ---
@admin_router.callback_query(F.data == "admin_select_pkg_stock")
async def admin_select_stock(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    packages = await get_packages_with_stock()
    if not packages:
        return await call.answer("🔴 Create a package first!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for pkg in packages:
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"📥 {pkg[1]}", callback_data=f"addstock_{pkg[0]}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel_fsm")])
    await call.message.edit_text("📦 *Select a package to add extra stock to:*", reply_markup=kb, parse_mode="Markdown")

@admin_router.callback_query(F.data.startswith("addstock_"))
async def admin_add_stock_step2(call: CallbackQuery, state: FSMContext):
    pkg_id = int(call.data.split("_")[1])
    await state.update_data(stock_pkg_id=pkg_id)
    await state.set_state(AdminState.waiting_for_stock_data)
    await call.message.edit_text("📝 *Send the Hidden Key / Extension for this stock:*", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_stock_data)
async def admin_save_stock(message: Message, state: FSMContext):
    data = await state.get_data()
    pkg_id = data['stock_pkg_id']
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        await db.execute("INSERT INTO stock (package_id, data) VALUES (?, ?)", (pkg_id, message.text))
        await db.commit()
    await state.clear()
    await message.answer("🟢 *Extra Stock added successfully!*", parse_mode="Markdown")

# --- ADD REDEEM CODE ---
@admin_router.callback_query(F.data == "admin_add_code")
async def admin_add_code(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_for_redeem_code)
    await call.message.edit_text("🎁 *Send redeem code name:*", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_redeem_code)
async def admin_code_name(message: Message, state: FSMContext):
    await state.update_data(code=message.text)
    await state.set_state(AdminState.waiting_for_redeem_amount)
    await message.answer("💰 *Enter token amount:*", reply_markup=cancel_admin_inline(), parse_mode="Markdown")

@admin_router.message(AdminState.waiting_for_redeem_amount)
async def admin_code_amt(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("🔴 Numbers only.")
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME, timeout=20) as db:
        await db.execute("INSERT INTO redeem_codes (code, amount, is_used) VALUES (?, ?, 0)", (data['code'], int(message.text)))
        await db.commit()
    await state.clear()
    await message.answer(f"🟢 *Code created!*\n🎁 `{data['code']}` = {message.text} Tokens", parse_mode="Markdown")

# ━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
                                   
