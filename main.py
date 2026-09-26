import os
import asyncpg

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

# بعداً آیدی عددی تلگرام خودت را اینجا قرار می‌دهیم
ADMIN_IDS = set()


# =========================
# DATABASE
# =========================

async def get_db():
    return await asyncpg.connect(DATABASE_URL)


async def init_database():
    db = await get_db()

    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT NOT NULL DEFAULT 0,
            sizes TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            description TEXT DEFAULT '',
            stock INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            total BIGINT DEFAULT 0,
            status TEXT DEFAULT 'pending',
            receipt_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            product_name TEXT,
            size TEXT,
            quantity INTEGER DEFAULT 1,
            price BIGINT DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS bot_buttons (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            callback_data TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE
        );
    """)

    # دکمه‌های پیش‌فرض
    count = await db.fetchval(
        "SELECT COUNT(*) FROM bot_buttons"
    )

    if count == 0:
        await db.execute("""
            INSERT INTO bot_buttons
            (title, callback_data, position)
            VALUES
            ('🛍 محصولات', 'products', 1),
            ('🛒 سبد خرید', 'cart', 2),
            ('📦 سفارش‌های من', 'orders', 3),
            ('📞 پشتیبانی', 'support', 4)
        """)

    await db.close()

    print("✅ PostgreSQL connected")
    print("✅ Database tables ready")


# =========================
# USERS
# =========================

async def save_user(update: Update):
    user = update.effective_user

    db = await get_db()

    await db.execute("""
        INSERT INTO users
        (telegram_id, username, first_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name
    """,
        user.id,
        user.username,
        user.first_name
    )

    await db.close()


# =========================
# MAIN MENU
# =========================

async def get_main_menu():
    db = await get_db()

    buttons = await db.fetch("""
        SELECT title, callback_data
        FROM bot_buttons
        WHERE active = TRUE
        ORDER BY position
    """)

    await db.close()

    keyboard = []

    row = []

    for button in buttons:
        row.append(
            InlineKeyboardButton(
                button["title"],
                callback_data=button["callback_data"]
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_user(update)

    menu = await get_main_menu()

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=menu
    )


# =========================
# PRODUCTS
# =========================

async def show_products(query):
    db = await get_db()

    products = await db.fetch("""
        SELECT id, name, price, sizes
        FROM products
        WHERE active = TRUE
        ORDER BY id DESC
    """)

    await db.close()

    if not products:
        await query.edit_message_text(
            "🛍 فعلاً محصولی ثبت نشده است."
        )
        return

    keyboard = []

    for product in products:
        text = f"👟 {product['name']} | {product['price']:,} تومان"

        keyboard.append([
            InlineKeyboardButton(
                text,
                callback_data=f"product_{product['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("🔙 برگشت", callback_data="home")
    ])

    await query.edit_message_text(
        "🛍 محصولات فروشگاه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_product(query, product_id):
    db = await get_db()

    product = await db.fetchrow("""
        SELECT *
        FROM products
        WHERE id = $1 AND active = TRUE
    """, product_id)

    await db.close()

    if not product:
        await query.edit_message_text(
            "❌ محصول پیدا نشد."
        )
        return

    text = (
        f"👟 {product['name']}\n\n"
        f"💰 قیمت: {product['price']:,} تومان\n"
        f"📏 سایزها: {product['sizes'] or 'ثبت نشده'}\n"
        f"📦 موجودی: {product['stock']}\n\n"
        f"{product['description'] or ''}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 افزودن به سفارش",
                callback_data=f"buy_{product['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 محصولات",
                callback_data="products"
            )
        ]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    if product["image_url"]:
        try:
            await query.message.delete()

            await query.message.chat.send_photo(
                photo=product["image_url"],
                caption=text,
                reply_markup=markup
            )
            return
        except Exception:
            pass

    await query.edit_message_text(
        text,
        reply_markup=markup
    )


# =========================
# BUTTON HANDLER
# =========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "home":
        menu = await get_main_menu()

        await query.edit_message_text(
            "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
            "از منوی زیر انتخاب کنید:",
            reply_markup=menu
        )

    elif data == "products":
        await show_products(query)

    elif data.startswith("product_"):
        product_id = int(data.split("_")[1])
        await show_product(query, product_id)

    elif data == "cart":
        await query.edit_message_text(
            "🛒 سبد خرید شما فعلاً خالی است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home"
                    )
                ]
            ])
        )

    elif data == "orders":
        await query.edit_message_text(
            "📦 سفارش‌های شما\n\n"
            "فعلاً سفارشی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home"
                    )
                ]
            ])
        )

    elif data == "support":
        await query.edit_message_text(
            "📞 برای پشتیبانی با ما در ارتباط باشید.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home"
                    )
                ]
            ])
        )

    elif data == "admin":
        await admin_panel(query)


# =========================
# ADMIN PANEL
# =========================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def admin_panel(query):
    keyboard = [
        [
            InlineKeyboardButton(
                "➕ افزودن محصول",
                callback_data="admin_add"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 محصولات",
                callback_data="admin_products"
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 سفارش‌ها",
                callback_data="admin_orders"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ مدیریت دکمه‌ها",
                callback_data="admin_buttons"
            )
        ],
    ]

    await query.edit_message_text(
        "👑 پنل مدیریت\n\n"
        "یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# ADMIN COMMAND
# =========================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ شما دسترسی مدیریت ندارید."
        )
        return

    keyboard
