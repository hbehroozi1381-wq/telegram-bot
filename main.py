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

# فقط این Telegram ID اجازه ورود به پنل مدیریت را دارد
ADMIN_ID = 888720947


# =========================================================
# DATABASE
# =========================================================

async def get_db():
    return await asyncpg.connect(DATABASE_URL)


async def init_database():

    db = await get_db()

    # کاربران
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # برندها
    await db.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # محصولات
    await db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            brand_id INTEGER REFERENCES brands(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price BIGINT DEFAULT 0,
            sale_price BIGINT DEFAULT 0,
            sizes TEXT DEFAULT '',
            stock INTEGER DEFAULT 0,
            category TEXT DEFAULT '',
            keywords TEXT DEFAULT '',
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # عکس‌های محصولات
    await db.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL,
            position INTEGER DEFAULT 1
        );
    """)

    # سبد خرید
    await db.execute("""
        CREATE TABLE IF NOT EXISTS cart_items (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            size TEXT DEFAULT '',
            quantity INTEGER DEFAULT 1,
            UNIQUE(telegram_id, product_id, size)
        );
    """)

    # سفارش‌ها
    await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            customer_name TEXT,
            phone TEXT,
            address TEXT,
            postal_code TEXT,
            shipping_cost BIGINT DEFAULT 0,
            total BIGINT DEFAULT 0,
            status TEXT DEFAULT 'waiting_payment',
            receipt_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # آیتم‌های سفارش
    await db.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            product_name TEXT,
            size TEXT,
            quantity INTEGER DEFAULT 1,
            price BIGINT DEFAULT 0
        );
    """)

    # تنظیمات فروشگاه
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );
    """)

    # دکمه‌های اصلی
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_buttons (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            callback_data TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE
        );
    """)

    # تنظیمات اولیه
    await db.execute("""
        INSERT INTO settings (key, value)
        VALUES
        ('card_number', ''),
        ('shipping_cost', '0'),
        ('support_text', 'برای پشتیبانی با ما در ارتباط باشید.')
        ON CONFLICT (key) DO NOTHING;
    """)

    # دکمه‌های اولیه
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
            ('🔎 جستجو', 'search', 4),
            ('📞 پشتیبانی', 'support', 5),
            ('👥 اعضای ربات', 'members', 6)
        """)

    await db.close()

    print("✅ PostgreSQL connected")
    print("✅ Database ready")


# =========================================================
# USERS
# =========================================================

async def save_user(update: Update):

    user = update.effective_user

    if not user:
        return

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


# =========================================================
# MAIN MENU
# =========================================================

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


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await save_user(update)

    menu = await get_main_menu()

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=menu
    )


# =========================================================
# PRODUCTS / BRANDS
# =========================================================

async def show_products(query):

    db = await get_db()

    brands = await db.fetch("""
        SELECT id, name
        FROM brands
        WHERE active = TRUE
        ORDER BY name
    """)

    await db.close()

    keyboard = []

    # حراج همیشه اولین گزینه
    keyboard.append([
        InlineKeyboardButton(
            "🔥 حراج",
            callback_data="sale"
        )
    ])

    row = []

    for brand in brands:

        row.append(
            InlineKeyboardButton(
                f"🏷 {brand['name']}",
                callback_data=f"brand_{brand['id']}"
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "🛍 محصولات فروشگاه\n\n"
        "برند مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# BRAND PRODUCTS
# =========================================================

async def show_brand_products(query, brand_id):

    db = await get_db()

    brand = await db.fetchrow("""
        SELECT name
        FROM brands
        WHERE id = $1
    """, brand_id)

    products = await db.fetch("""
        SELECT id, name, price, sale_price
        FROM products
        WHERE brand_id = $1
        AND active = TRUE
        ORDER BY id DESC
    """, brand_id)

    await db.close()

    if not brand:

        await query.edit_message_text(
            "❌ برند پیدا نشد."
        )
        return

    if not products:

        await query.edit_message_text(
            f"🏷 {brand['name']}\n\n"
            "فعلاً محصولی از این برند ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برندها",
                        callback_data="products"
                    )
                ]
            ])
        )
        return

    keyboard = []

    for product in products:

        if product["sale_price"] and product["sale_price"] < product["price"]:

            text = (
                f"🔥 {product['name']} | "
                f"{product['sale_price']:,} تومان"
            )

        else:

            text = (
                f"👟 {product['name']} | "
                f"{product['price']:,} تومان"
            )

        keyboard.append([
            InlineKeyboardButton(
                text,
                callback_data=f"product_{product['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برندها",
            callback_data="products"
        )
    ])

    await query.edit_message_text(
        f"🏷 برند {brand['name']}\n\n"
        "مدل مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# SALE
# =========================================================

async def show_sale_products(query):

    db = await get_db()

    products = await db.fetch("""
        SELECT id, name, price, sale_price
        FROM products
        WHERE active = TRUE
        AND sale_price > 0
        AND sale_price < price
        ORDER BY id DESC
    """)

    await db.close()

    if not products:

        await query.edit_message_text(
            "🔥 حراج\n\n"
            "فعلاً محصولی در حراج نیست.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 محصولات",
                        callback_data="products"
                    )
                ]
            ])
        )
        return

    keyboard = []

    for product in products:

        keyboard.append([
            InlineKeyboardButton(
                f"🔥 {product['name']} | "
                f"{product['sale_price']:,} تومان",
                callback_data=f"product_{product['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 محصولات",
            callback_data="products"
        )
    ])

    await query.edit_message_text(
        "🔥 محصولات حراج:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# PRODUCT DETAILS
# =========================================================

async def show_product(query, product_id):

    db = await get_db()

    product = await db.fetchrow("""
        SELECT
            p.*,
            b.name AS brand_name
        FROM products p
        LEFT JOIN brands b
        ON p.brand_id = b.id
        WHERE p.id = $1
        AND p.active = TRUE
    """, product_id)

    images = await db.fetch("""
        SELECT file_id
        FROM product_images
        WHERE product_id = $1
        ORDER BY position
    """, product_id)

    await db.close()

    if not product:

        await query.edit_message_text(
            "❌ محصول پیدا نشد."
        )
        return

    if product["sale_price"] and product["sale_price"] < product["price"]:

        price_text = (
            f"💰 قیمت اصلی: {product['price']:,} تومان\n"
            f"🔥 قیمت حراج: {product['sale_price']:,} تومان"
        )

    else:

        price_text = (
            f"💰 قیمت: {product['price']:,} تومان"
        )

    text = (
        f"👟 {product['name']}\n\n"
        f"🏷 برند: {product['brand_name'] or 'بدون برند'}\n"
        f"{price_text}\n"
        f"📏 سایزها: {product['sizes'] or 'ثبت نشده'}\n"
        f"📦 موجودی: {product['stock']}\n\n"
        f"{product['description'] or ''}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 افزودن به سبد خرید",
                callback_data=f"buy_{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="products"
            )
        ]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    # اگر عکس دارد، اولین عکس نمایش داده می‌شود
    if images:

        try:

            await query.message.delete()

            await query.message.chat.send_photo(
                photo=images[0]["file_id"],
                caption=text,
                reply_markup=markup
            )

            return

        except Exception as e:

            print("Image error:", e)

    await query.edit_message_text(
        text,
        reply_markup=markup
    )


# =========================================================
# CART
# =========================================================

async def show_cart(query):

    telegram_id = query.from_user.id

    db = await get_db()

    items = await db.fetch("""
        SELECT
            c.product_id,
            c.size,
            c.quantity,
            p.name,
            p.price,
            p.sale_price
        FROM cart_items c
        JOIN products p
        ON c.product_id = p.id
        WHERE c.telegram_id = $1
    """, telegram_id)

    await db.close()

    if not items:

        await query.edit_message_text(
            "🛒 سبد خرید شما خالی است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    total = 0
    text = "🛒 سبد خرید شما:\n\n"

    for item in items:

        price = item["price"]

        if item["sale_price"] and item["sale_price"] < price:
            price = item["sale_price"]

        item_total = price * item["quantity"]
        total += item_total

        text += (
            f"👟 {item['name']}\n"
            f"📏 سایز: {item['size']}\n"
            f"🔢 تعداد: {item['quantity']}\n"
            f"💰 {item_total:,} تومان\n\n"
        )

    text += f"💵 مجموع: {total:,} تومان"

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ ادامه خرید",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 ثبت سفارش",
                callback_data="checkout"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="home"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# MEMBERS
# =========================================================

async def show_members(query):

    db = await get_db()

    count = await db.fetchval(
        "SELECT COUNT(*) FROM users"
    )

    await db.close()

    await query.edit_message_text(
        f"👥 اعضای ربات\n\n"
        f"تعداد اعضا: {count}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="home"
                )
            ]
        ])
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(query):

    db = await get_db()

    text = await db.fetchval("""
        SELECT value
        FROM settings
        WHERE key = 'support_text'
    """)

    await db.close()

    await query.edit_message_text(
        f"📞 پشتیبانی\n\n{text or 'برای پشتیبانی با ما در ارتباط باشید.'}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="home"
                )
            ]
        ])
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

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

    elif data == "sale":

        await show_sale_products(query)

    elif data.startswith("brand_"):

        brand_id = int(data.split("_")[1])

        await show_brand_products(
            query,
            brand_id
        )

    elif data.startswith("product_"):

        product_id = int(data.split("_")[1])

        await show_product(
            query,
            product_id
        )

    elif data == "cart":

        await show_cart(query)

    elif data == "members":

        await show_members(query)

    elif data == "support":

        await show_support(query)

    elif data == "search":

        context.user_data["searching"] = True

        await query.edit_message_text(
            "🔎 جستجوی محصول\n\n"
            "نام مدل، برند یا کاربرد کفش را بنویسید.\n\n"
            "مثلاً:\n"
            "Nike Air Max\n"
            "باشگاه\n"
            "پیاده‌روی",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "❌ لغو",
                        callback_data="home"
                    )
                ]
            ])
        )


# =========================================================
# SEARCH
# =========================================================

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("searching"):
        return

    search_text = update.message.text.strip()

    context.user_data["searching"] = False

    db = await get_db()

    products = await db.fetch("""
        SELECT id, name, price, sale_price
        FROM products
        WHERE active = TRUE
        AND (
            LOWER(name) LIKE LOWER($1)
            OR LOWER(description) LIKE LOWER($1)
            OR LOWER(category) LIKE LOWER($1)
            OR LOWER(keywords) LIKE LOWER($1)
        )
        ORDER BY id DESC
    """, f"%{search_text}%")

    await db.close()

    if not products:

        await update.message.reply_text(
            "❌ محصولی با این مشخصات پیدا نشد.",
            reply_markup=await get_main_menu()
        )

        return

    keyboard = []

    for product in products:

        price = product["sale_price"]

        if not price or price >= product["price"]:
            price = product["price"]

        keyboard.append([
            InlineKeyboardButton(
                f"👟 {product['name']} | {price:,} تومان",
                callback_data=f"product_{product['id']}"
            )
        ])

    await update.message.reply_text(
        f"🔎 نتایج جستجو برای: {search_text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )

        return

    keyboard = [
        [
            InlineKeyboardButton(
                "📦 مدیریت محصولات",
                callback_data="admin_products"
            )
        ],
        [
            InlineKeyboardButton(
                "🏷 مدیریت برندها",
                callback_data="admin_brands"
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
                "⚙️ تنظیمات فروشگاه",
                callback_data="admin_settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 مدیریت دکمه‌ها",
                callback_data="admin_buttons"
            )
        ],
    ]

    await update.message.reply_text(
        "👑 پنل مدیریت\n\n"
        "به پنل مدیریت فروشگاه خوش آمدید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# UNKNOWN TEXT
# =========================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("searching"):

        await search_products(
            update,
            context
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):

    print("❌ ERROR:", context.error)


# =========================================================
# START APPLICATION
# =========================================================

async def post_init(application):

    await init_database()


app = (
    Application.builder()
    .token(TOKEN)
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
        text_handler
    )
)

app.add_error_handler(error_handler)

print("👟 فروشگاه آنلاین شد...")

app.run_polling()
