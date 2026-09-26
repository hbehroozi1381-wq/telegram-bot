import os
import asyncpg
import hashlib

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

ADMIN_ID = 888720947

# رمز اولیه فقط برای اولین ورود است.
# بعداً از داخل پنل تغییرش می‌دهیم.
DEFAULT_ADMIN_PASSWORD = "123456"


# =========================
# DATABASE
# =========================

async def db_connect():
    return await asyncpg.connect(DATABASE_URL)


async def init_database():
    db = await db_connect()

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
            image_file_id TEXT DEFAULT '',
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

        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY,
            password_hash TEXT NOT NULL
        );
    """)

    # ساخت رمز اولیه فقط اگر هنوز رمز وجود ندارد
    password_hash = hashlib.sha256(
        DEFAULT_ADMIN_PASSWORD.encode()
    ).hexdigest()

    await db.execute("""
        INSERT INTO admin_settings (id, password_hash)
        VALUES (1, $1)
        ON CONFLICT (id) DO NOTHING
    """, password_hash)

    # ساخت دکمه‌های اولیه
    button_count = await db.fetchval("""
        SELECT COUNT(*) FROM bot_buttons
    """)

    if button_count == 0:
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
    print("✅ Database initialized")


# =========================
# USER
# =========================

async def save_user(update: Update):
    user = update.effective_user

    if not user:
        return

    db = await db_connect()

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
        user.first_name,
    )

    await db.close()


# =========================
# CUSTOMER MENU
# =========================

async def customer_menu():
    db = await db_connect()

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
                callback_data=button["callback_data"],
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

    menu = await customer_menu()

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=menu,
    )


# =========================
# PRODUCTS
# =========================

async def show_products(query):
    db = await db_connect()

    products = await db.fetch("""
        SELECT id, name, price
        FROM products
        WHERE active = TRUE
        ORDER BY id DESC
    """)

    await db.close()

    if not products:
        await query.edit_message_text(
            "🛍 فعلاً محصولی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home",
                    )
                ]
            ]),
        )
        return

    keyboard = []

    for product in products:
        keyboard.append([
            InlineKeyboardButton(
                f"👟 {product['name']} | "
                f"{product['price']:,} تومان",
                callback_data=f"product:{product['id']}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="home",
        )
    ])

    await query.edit_message_text(
        "🛍 محصولات فروشگاه:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_product(query, product_id):
    db = await db_connect()

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
        f"📏 سایزها: "
        f"{product['sizes'] or 'ثبت نشده'}\n"
        f"📦 موجودی: {product['stock']}\n\n"
        f"{product['description'] or ''}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 افزودن به سبد",
                callback_data=f"buy:{product['id']}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 محصولات",
                callback_data="products",
            )
        ],
    ]

    markup = InlineKeyboardMarkup(keyboard)

    if product["image_file_id"]:
        try:
            await query.message.delete()

            await query.message.chat.send_photo(
                photo=product["image_file_id"],
                caption=text,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

    await query.edit_message_text(
        text,
        reply_markup=markup,
    )


# =========================
# ADMIN SECURITY
# =========================

def is_admin(user_id):
    return user_id == ADMIN_ID


async def check_password(password):
    db = await db_connect()

    password_hash = hashlib.sha256(
        password.encode()
    ).hexdigest()

    result = await db.fetchval("""
        SELECT COUNT(*)
        FROM admin_settings
        WHERE id = 1 AND password_hash = $1
    """, password_hash)

    await db.close()

    return result == 1


# =========================
# ADMIN COMMAND
# =========================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ دسترسی غیرمجاز."
        )
        return

    context.user_data["admin_login"] = False
    context.user_data["waiting_password"] = True

    await update.message.reply_text(
        "🔐 پنل مدیریت\n\n"
        "رمز مدیریت را وارد کنید:"
    )


# =========================
# ADMIN PANEL
# =========================

async def show_admin_panel(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "➕ افزودن محصول",
                callback_data="admin:add",
            )
        ],
        [
            InlineKeyboardButton(
                "📦 مدیریت محصولات",
                callback_data="admin:products",
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 سفارش‌ها",
                callback_data="admin:orders",
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ مدیریت دکمه‌ها",
                callback_data="admin:buttons",
            )
        ],
        [
            InlineKeyboardButton(
                "🔑 تغییر رمز",
                callback_data="admin:password",
            )
        ],
    ]

    text = (
        "👑 پنل مدیریت فروشگاه\n\n"
        "از اینجا فروشگاه را مدیریت کن:"
    )

    if hasattr(update, "message") and update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# =========================
# ADMIN CALLBACK
# =========================

async def admin_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text(
            "❌ دسترسی غیرمجاز."
        )
        return

    if not context.user_data.get("admin_login"):
        await query.edit_message_text(
            "🔐 ابتدا با /admin وارد پنل شوید."
        )
        return

    data = query.data

    if data == "admin:add":
        await query.edit_message_text(
            "➕ افزودن محصول\n\n"
            "این بخش را در مرحله بعد فعال می‌کنیم.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin:home",
                    )
                ]
            ]),
        )

    elif data == "admin:products":
        await query.edit_message_text(
            "📦 مدیریت محصولات\n\n"
            "این بخش در مرحله بعد فعال می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin:home",
                    )
                ]
            ]),
        )

    elif data == "admin:orders":
        await query.edit_message_text(
            "🛒 مدیریت سفارش‌ها\n\n"
            "این بخش در مرحله بعد فعال می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin:home",
                    )
                ]
            ]),
        )

    elif data == "admin:buttons":
        await query.edit_message_text(
            "⚙️ مدیریت دکمه‌ها\n\n"
            "این بخش در مرحله بعد فعال می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin:home",
                    )
                ]
            ]),
        )

    elif data == "admin:password":
        context.user_data["changing_password"] = True

        await query.edit_message_text(
            "🔑 رمز جدید را ارسال کنید:"
        )

    elif data == "admin:home":
        await show_admin_panel(update, context)


# =========================
# TEXT HANDLER
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # فقط مدیر می‌تواند این بخش را استفاده کند
    if not is_admin(user_id):
        return

    # ورود به پنل
    if context.user_data.get("waiting_password"):
        context.user_data["waiting_password"] = False

        if await check_password(text):
            context.user_data["admin_login"] = True

            await update.message.reply_text(
                "✅ ورود موفق بود."
            )

            await show_admin_panel(update, context)

        else:
            await update.message.reply_text(
                "❌ رمز اشتباه است."
            )

        return

    # تغییر رمز
    if context.user_data.get("changing_password"):
        context.user_data["changing_password"] = False

        new_hash = hashlib.sha256(
            text.encode()
        ).hexdigest()

        db = await db_connect()

        await db.execute("""
            UPDATE admin_settings
            SET password_hash = $1
            WHERE id = 1
        """, new_hash)

        await db.close()

        await update.message.reply_text(
            "✅ رمز مدیریت با موفقیت تغییر کرد."
        )

        await show_admin_panel(update, context)


# =========================
# CALLBACK ROUTER
# =========================

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("admin:"):
        await admin_callback(update, context)
        return

    if data == "home":
        menu = await customer_menu()

        await query.edit_message_text(
            "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
            "از منوی زیر انتخاب کنید:",
            reply_markup=menu,
        )

    elif data == "products":
        await show_products(query)

    elif data.startswith("product:"):
        product_id = int(data.split(":")[1])
        await show_product(query, product_id)

    elif data == "cart":
        await query.edit_message_text(
            "🛒 سبد خرید شما فعلاً خالی است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home",
                    )
                ]
            ]),
        )

    elif data == "orders":
        await query.edit_message_text(
            "📦 هنوز سفارشی ثبت نکرده‌اید.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home",
                    )
                ]
            ]),
        )

    elif data == "support":
        await query.edit_message_text(
            "📞 برای پشتیبانی با ما در ارتباط باشید.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home",
                    )
                ]
            ]),
        )


# =========================
# APP START
# =========================

async def post_init(application):
    await init_database()


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("admin", admin)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    print("👟 فروشگاه آنلاین شد...")

    app.run_polling()


if __name__ == "__main__":
    main()
