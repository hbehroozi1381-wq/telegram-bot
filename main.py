import os
import hashlib
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

ADMIN_ID = 888720947


# =========================================================
# DATABASE
# =========================================================

async def db():
    return await asyncpg.connect(DATABASE_URL)


async def init_db():
    conn = await db()

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS brands (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            active BOOLEAN DEFAULT TRUE
        );

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

        CREATE TABLE IF NOT EXISTS product_images (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL,
            position INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            size TEXT DEFAULT '',
            quantity INTEGER DEFAULT 1,
            UNIQUE(telegram_id, product_id, size)
        );

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

        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            product_name TEXT,
            size TEXT,
            quantity INTEGER DEFAULT 1,
            price BIGINT DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS bot_buttons (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            callback_data TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE
        );
    """)

    defaults = {
        "card_number": "",
        "shipping_cost": "0",
        "support_text": "📞 برای پشتیبانی با ما در ارتباط باشید.",
        "admin_password": hashlib.sha256("123456".encode()).hexdigest(),
    }

    for key, value in defaults.items():
        await conn.execute("""
            INSERT INTO settings(key, value)
            VALUES($1, $2)
            ON CONFLICT(key) DO NOTHING
        """, key, value)

    default_buttons = [
        ("🛍 محصولات", "products", 1),
        ("🛒 سبد خرید", "cart", 2),
        ("📦 سفارش‌های من", "orders", 3),
        ("🔎 جستجو", "search", 4),
        ("📞 پشتیبانی", "support", 5),
        ("👥 اعضای ربات", "members", 6),
    ]

    for title, callback, position in default_buttons:
        await conn.execute("""
            INSERT INTO bot_buttons(title, callback_data, position)
            SELECT $1, $2, $3
            WHERE NOT EXISTS(
                SELECT 1 FROM bot_buttons WHERE callback_data=$2
            )
        """, title, callback, position)

    await conn.close()
    print("DATABASE READY")


# =========================================================
# HELPERS
# =========================================================

async def setting(key):
    conn = await db()
    value = await conn.fetchval(
        "SELECT value FROM settings WHERE key=$1",
        key
    )
    await conn.close()
    return value or ""


async def set_setting(key, value):
    conn = await db()
    await conn.execute("""
        INSERT INTO settings(key,value)
        VALUES($1,$2)
        ON CONFLICT(key)
        DO UPDATE SET value=EXCLUDED.value
    """, key, value)
    await conn.close()


async def save_user(update):
    user = update.effective_user

    if not user:
        return

    conn = await db()

    await conn.execute("""
        INSERT INTO users(telegram_id, username, first_name)
        VALUES($1,$2,$3)
        ON CONFLICT(telegram_id)
        DO UPDATE SET
            username=EXCLUDED.username,
            first_name=EXCLUDED.first_name
    """,
        user.id,
        user.username,
        user.first_name
    )

    await conn.close()


def admin_only(user_id):
    return user_id == ADMIN_ID


async def main_menu():
    conn = await db()

    buttons = await conn.fetch("""
        SELECT title, callback_data
        FROM bot_buttons
        WHERE active=TRUE
        ORDER BY position
    """)

    await conn.close()

    keyboard = []
    row = []

    for b in buttons:
        row.append(
            InlineKeyboardButton(
                b["title"],
                callback_data=b["callback_data"]
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


def back_button(callback="home"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 برگشت", callback_data=callback)]
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_user(update)

    context.user_data.clear()

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=await main_menu()
    )


# =========================================================
# PRODUCTS
# =========================================================

async def products_menu(query):

    conn = await db()

    brands = await conn.fetch("""
        SELECT id,name
        FROM brands
        WHERE active=TRUE
        ORDER BY name
    """)

    await conn.close()

    keyboard = [
        [InlineKeyboardButton("🔥 حراج", callback_data="sale")]
    ]

    row = []

    for brand in brands:
        row.append(
            InlineKeyboardButton(
                f"🏷 {brand['name']}",
                callback_data=f"brand:{brand['id']}"
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton("🔙 برگشت", callback_data="home")
    ])

    await query.edit_message_text(
        "🛍 محصولات فروشگاه\n\n"
        "🔥 حراج همیشه بالای لیست قرار دارد.\n"
        "برند مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def brand_products(query, brand_id):

    conn = await db()

    brand = await conn.fetchrow(
        "SELECT name FROM brands WHERE id=$1 AND active=TRUE",
        brand_id
    )

    products = await conn.fetch("""
        SELECT id,name,price,sale_price
        FROM products
        WHERE brand_id=$1 AND active=TRUE
        ORDER BY id DESC
    """, brand_id)

    await conn.close()

    if not brand:
        await query.edit_message_text("❌ برند پیدا نشد.")
        return

    if not products:
        await query.edit_message_text(
            f"🏷 {brand['name']}\n\n"
            "فعلاً محصولی از این برند ثبت نشده است.",
            reply_markup=back_button("products")
        )
        return

    keyboard = []

    for p in products:

        if p["sale_price"] > 0 and p["sale_price"] < p["price"]:
            text = f"🔥 {p['name']} | {p['sale_price']:,} تومان"
        else:
            text = f"👟 {p['name']} | {p['price']:,} تومان"

        keyboard.append([
            InlineKeyboardButton(
                text,
                callback_data=f"product:{p['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("🔙 برندها", callback_data="products")
    ])

    await query.edit_message_text(
        f"🏷 {brand['name']}\n\n"
        "مدل مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def sale_products(query):

    conn = await db()

    products = await conn.fetch("""
        SELECT id,name,sale_price
        FROM products
        WHERE active=TRUE
        AND sale_price>0
        AND sale_price<price
        ORDER BY id DESC
    """)

    await conn.close()

    if not products:
        await query.edit_message_text(
            "🔥 حراج\n\n"
            "فعلاً محصولی در حراج نیست.",
            reply_markup=back_button("products")
        )
        return

    keyboard = []

    for p in products:
        keyboard.append([
            InlineKeyboardButton(
                f"🔥 {p['name']} | {p['sale_price']:,} تومان",
                callback_data=f"product:{p['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("🔙 محصولات", callback_data="products")
    ])

    await query.edit_message_text(
        "🔥 محصولات حراج:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def product_details(query, product_id):

    conn = await db()

    p = await conn.fetchrow("""
        SELECT p.*, b.name AS brand_name
        FROM products p
        LEFT JOIN brands b ON b.id=p.brand_id
        WHERE p.id=$1 AND p.active=TRUE
    """, product_id)

    images = await conn.fetch("""
        SELECT file_id
        FROM product_images
        WHERE product_id=$1
        ORDER BY position
    """, product_id)

    await conn.close()

    if not p:
        await query.edit_message_text("❌ محصول پیدا نشد.")
        return

    sale = p["sale_price"] > 0 and p["sale_price"] < p["price"]

    if sale:
        price_text = (
            f"💰 قیمت اصلی: {p['price']:,} تومان\n"
            f"🔥 قیمت حراج: {p['sale_price']:,} تومان"
        )
    else:
        price_text = f"💰 قیمت: {p['price']:,} تومان"

    text = (
        f"👟 {p['name']}\n\n"
        f"🏷 برند: {p['brand_name'] or '---'}\n"
        f"{price_text}\n"
        f"📏 سایزها: {p['sizes'] or '---'}\n"
        f"📦 موجودی: {p['stock']}\n\n"
        f"{p['description'] or ''}"
    )

    keyboard = [
        [InlineKeyboardButton(
            "🛒 افزودن به سبد خرید",
            callback_data=f"buy:{product_id}"
        )],
        [InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="products"
        )]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    # حداکثر 5 عکس
    if images:
        try:
            await query.message.delete()

            for i, image in enumerate(images[:5]):

                if i == 0:
                    await query.message.chat.send_photo(
                        image["file_id"],
                        caption=text,
                        reply_markup=markup
                    )
                else:
                    await query.message.chat.send_photo(
                        image["file_id"]
                    )

            return

        except Exception as e:
            print("PHOTO ERROR:", e)

    await query.edit_message_text(
        text,
        reply_markup=markup
    )


# =========================================================
# CART
# =========================================================

async def add_to_cart(update, product_id):

    conn = await db()

    p = await conn.fetchrow("""
        SELECT *
        FROM products
        WHERE id=$1 AND active=TRUE
    """, product_id)

    await conn.close()

    if not p:
        await update.callback_query.answer(
            "محصول پیدا نشد.",
            show_alert=True
        )
        return

    sizes = [
        x.strip()
        for x in (p["sizes"] or "").split(",")
        if x.strip()
    ]

    if len(sizes) > 1:

        keyboard = []

        for size in sizes:
            keyboard.append([
                InlineKeyboardButton(
                    f"📏 سایز {size}",
                    callback_data=f"addsize:{product_id}:{size}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data=f"product:{product_id}"
            )
        ])

        await update.callback_query.edit_message_text(
            "📏 سایز مورد نظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    size = sizes[0] if sizes else ""

    await insert_cart(
        update,
        product_id,
        size
    )


async def insert_cart(update, product_id, size):

    telegram_id = update.effective_user.id

    conn = await db()

    p = await conn.fetchrow(
        "SELECT name FROM products WHERE id=$1",
        product_id
    )

    await conn.execute("""
        INSERT INTO cart_items
        (telegram_id,product_id,size,quantity)
        VALUES($1,$2,$3,1)
        ON CONFLICT(telegram_id,product_id,size)
        DO UPDATE SET quantity=cart_items.quantity+1
    """,
        telegram_id,
        product_id,
        size
    )

    await conn.close()

    await update.callback_query.edit_message_text(
        f"✅ {p['name']}\n\n"
        "به سبد خرید اضافه شد.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 سبد خرید",
                    callback_data="cart"
                )
            ],
            [
                InlineKeyboardButton(
                    "🛍 ادامه خرید",
                    callback_data="products"
                )
            ]
        ])
    )


async def show_cart(query):

    conn = await db()

    items = await conn.fetch("""
        SELECT
            c.id,
            c.product_id,
            c.size,
            c.quantity,
            p.name,
            p.price,
            p.sale_price
        FROM cart_items c
        JOIN products p ON p.id=c.product_id
        WHERE c.telegram_id=$1
        ORDER BY c.id
    """, query.from_user.id)

    await conn.close()

    if not items:
        await query.edit_message_text(
            "🛒 سبد خرید خالی است.",
            reply_markup=back_button("home")
        )
        return

    total = 0
    text = "🛒 سبد خرید شما:\n\n"

    for item in items:

        price = item["price"]

        if item["sale_price"] > 0 and item["sale_price"] < price:
            price = item["sale_price"]

        subtotal = price * item["quantity"]
        total += subtotal

        text += (
            f"👟 {item['name']}\n"
            f"📏 سایز: {item['size'] or '---'}\n"
            f"🔢 تعداد: {item['quantity']}\n"
            f"💰 {subtotal:,} تومان\n\n"
        )

    shipping = int(await setting("shipping_cost") or 0)

    text += (
        f"🛍 جمع کالاها: {total:,} تومان\n"
        f"🚚 ارسال: {shipping:,} تومان\n"
        f"💵 مبلغ نهایی: {total + shipping:,} تومان"
    )

    keyboard = [
        [InlineKeyboardButton(
            "📦 ثبت سفارش",
            callback_data="checkout"
        )],
        [InlineKeyboardButton(
            "🛍 ادامه خرید",
            callback_data="products"
        )],
        [InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="home"
        )]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# SEARCH
# =========================================================

async def start_search(query, context):

    context.user_data["state"] = "search"

    await query.edit_message_text(
        "🔎 جستجوی محصول\n\n"
        "اسم مدل، برند یا کاربرد را بنویس.\n\n"
        "مثلاً:\n"
        "Nike Air Max\n"
        "باشگاه\n"
        "پیاده روی\n"
        "آدیداس",
        reply_markup=back_button("home")
    )


async def do_search(update, context):

    if context.user_data.get("state") != "search":
        return

    word = update.message.text.strip()

    context.user_data["state"] = None

    conn = await db()

    products = await conn.fetch("""
        SELECT id,name,price,sale_price
        FROM products
        WHERE active=TRUE
        AND (
            name ILIKE $1
            OR description ILIKE $1
            OR category ILIKE $1
            OR keywords ILIKE $1
        )
        ORDER BY id DESC
    """, f"%{word}%")

    await conn.close()

    if not products:
        await update.message.reply_text(
            "❌ محصولی پیدا نشد.",
            reply_markup=await main_menu()
        )
        return

    keyboard = []

    for p in products:

        price = p["price"]

        if p["sale_price"] > 0 and p["sale_price"] < price:
            price = p["sale_price"]

        keyboard.append([
            InlineKeyboardButton(
                f"👟 {p['name']} | {price:,} تومان",
                callback_data=f"product:{p['id']}"
            )
        ])

    await update.message.reply_text(
        f"🔎 نتایج جستجو برای «{word}»:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# CUSTOMER INFO / CHECKOUT
# =========================================================

async def checkout_start(query, context):

    conn = await db()

    count = await conn.fetchval("""
        SELECT COUNT(*)
        FROM cart_items
        WHERE telegram_id=$1
    """, query.from_user.id)

    await conn.close()

    if not count:
        await query.edit_message_text(
            "🛒 سبد خرید خالی است.",
            reply_markup=back_button("home")
        )
        return

    context.user_data["state"] = "customer_name"

    await query.edit_message_text(
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


async def checkout_message(update, context):

    state = context.user_data.get("state")

    if state == "customer_name":
        context.user_data["customer_name"] = update.message.text
        context.user_data["state"] = "phone"

        await update.message.reply_text(
            "📱 شماره موبایل خود را ارسال کنید:"
        )
        return

    if state == "phone":
        context.user_data["phone"] = update.message.text
        context.user_data["state"] = "address"

        await update.message.reply_text(
            "📍 آدرس کامل را ارسال کنید:"
        )
        return

    if state == "address":
        context.user_data["address"] = update.message.text
        context.user_data["state"] = "postal"

        await update.message.reply_text(
            "📮 کد پستی را ارسال کنید:"
        )
        return

    if state == "postal":

        context.user_data["postal_code"] = update.message.text
        context.user_data["state"] = None

        await create_order(update, context)


async def create_order(update, context):

    telegram_id = update.effective_user.id

    conn = await db()

    items = await conn.fetch("""
        SELECT
            c.product_id,
            c.size,
            c.quantity,
            p.name,
            p.price,
            p.sale_price
        FROM cart_items c
        JOIN products p ON p.id=c.product_id
        WHERE c.telegram_id=$1
    """, telegram_id)

    if not items:
        await conn.close()
        await update.message.reply_text(
            "سبد خرید خالی است."
        )
        return

    total = 0

    for item in items:

        price = item["price"]

        if item["sale_price"] > 0 and item["sale_price"] < price:
            price = item["sale_price"]

        total += price * item["quantity"]

    shipping = int(await setting("shipping_cost") or 0)
    final_total = total + shipping

    order_id = await conn.fetchval("""
        INSERT INTO orders(
            telegram_id,
            customer_name,
            phone,
            address,
            postal_code,
            shipping_cost,
            total,
            status
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,'waiting_payment')
        RETURNING id
    """,
        telegram_id,
        context.user_data["customer_name"],
        context.user_data["phone"],
        context.user_data["address"],
        context.user_data["postal_code"],
        shipping,
        final_total
    )

    for item in items:

        price = item["price"]

        if item["sale_price"] > 0 and item["sale_price"] < price:
            price = item["sale_price"]

        await conn.execute("""
            INSERT INTO order_items(
                order_id,
                product_id,
                product_name,
                size,
                quantity,
                price
            )
            VALUES($1,$2,$3,$4,$5,$6)
        """,
            order_id,
            item["product_id"],
            item["name"],
            item["size"],
            item["quantity"],
            price
        )

    await conn.execute(
        "DELETE FROM cart_items WHERE telegram_id=$1",
        telegram_id
    )

    await conn.close()

    card = await setting("card_number")

    if card:
        payment_text = (
            f"💳 شماره کارت:\n"
            f"`{card}`\n\n"
        )
    else:
        payment_text = (
            "⚠️ شماره کارت هنوز توسط مدیریت ثبت نشده است.\n\n"
        )

    await update.message.reply_text(
        f"✅ سفارش شما ثبت شد.\n\n"
        f"🧾 شماره سفارش: #{order_id}\n"
        f"💰 مبلغ قابل پرداخت: {final_total:,} تومان\n\n"
        f"{payment_text}"
        "پس از پرداخت، عکس رسید را همینجا ارسال کنید.",
        parse_mode="Markdown"
    )

    context.user_data["state"] = f"receipt:{order_id}"


# =========================================================
# RECEIPT
# =========================================================

async def receive_receipt(update, context):

    state = context.user_data.get("state", "")

    if not state.startswith("receipt:"):
        return

    order_id = int(state.split(":")[1])

    if not update.message.photo:
        await update.message.reply_text(
            "❌ لطفاً عکس رسید پرداخت را ارسال کنید."
        )
        return

    file_id = update.message.photo[-1].file_id

    conn = await db()

    await conn.execute("""
        UPDATE orders
        SET receipt_file_id=$1,
            status='waiting_admin'
        WHERE id=$2
    """, file_id, order_id)

    order = await conn.fetchrow("""
        SELECT *
        FROM orders
        WHERE id=$1
    """, order_id)

    await conn.close()

    context.user_data["state"] = None

    await update.message.reply_text(
        "🧾 رسید دریافت شد.\n\n"
        "⏳ بعد از بررسی پرداخت، نتیجه برای شما ارسال می‌شود."
    )

    # ارسال سفارش برای مدیر
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                f"🧾 رسید جدید\n\n"
                f"شماره سفارش: #{order_id}\n"
                f"مبلغ: {order['total']:,} تومان\n"
                f"مشتری: {order['customer_name']}\n"
                f"تلفن: {order['phone']}\n"
                f"آدرس: {order['address']}\n"
                f"کد پستی: {order['postal_code']}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ تأیید پرداخت",
                        callback_data=f"approve:{order_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ رد پرداخت",
                        callback_data=f"reject:{order_id}"
                    )
                ]
            ])
        )
    except Exception as e:
        print("ADMIN RECEIPT ERROR:", e)


# =========================================================
# ORDERS
# =========================================================

async def customer_orders(query):

    conn = await db()

    orders = await conn.fetch("""
        SELECT id,total,status,created_at
        FROM orders
        WHERE telegram_id=$1
        ORDER BY id DESC
        LIMIT 20
    """, query.from_user.id)

    await conn.close()

    if not orders:
        await query.edit_message_text(
            "📦 هنوز سفارشی ثبت نکرده‌اید.",
            reply_markup=back_button("home")
        )
        return

    status_names = {
        "waiting_payment": "⏳ منتظر پرداخت",
        "waiting_admin": "🔎 در انتظار بررسی",
        "paid": "✅ پرداخت تأیید شد",
        "rejected": "❌ پرداخت رد شد",
        "shipped": "🚚 ارسال شد",
        "completed": "🏁 تکمیل شد",
    }

    text = "📦 سفارش‌های شما:\n\n"

    for order in orders:
        text += (
            f"🧾 سفارش #{order['id']}\n"
            f"💰 {order['total']:,} تومان\n"
            f"📌 {status_names.get(order['status'], order['status'])}\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=back_button("home")
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

async def admin_command(update, context):

    if not admin_only(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    context.user_data.clear()
    context.user_data["state"] = "admin_password"

    await update.message.reply_text(
        "🔐 رمز پنل مدیریت را وارد کنید:"
    )


async def admin_password(update, context):

    if not admin_only(update.effective_user.id):
        return

    if context.user_data.get("state") != "admin_password":
        return

    password = update.message.text

    saved = await setting("admin_password")

    hashed = hashlib.sha256(
        password.encode()
    ).hexdigest()

    if hashed != saved:
        await update.message.reply_text(
            "❌ رمز اشتباه است."
        )
        return

    context.user_data["admin_logged"] = True
    context.user_data["state"] = None

    await send_admin_panel(update)


async def send_admin_panel(update):

    keyboard = [
        [InlineKeyboardButton(
            "📦 مدیریت محصولات",
            callback_data="adm_products"
        )],
        [InlineKeyboardButton(
            "🏷 مدیریت برندها",
            callback_data="adm_brands"
        )],
        [InlineKeyboardButton(
            "🧾 سفارش‌ها",
            callback_data="adm_orders"
        )],
        [InlineKeyboardButton(
            "⚙️ تنظیمات فروشگاه",
            callback_data="adm_settings"
        )],
        [InlineKeyboardButton(
            "🔘 مدیریت دکمه‌ها",
            callback_data="adm_buttons"
        )],
        [InlineKeyboardButton(
            "🔑 تغییر رمز",
            callback_data="adm_password"
        )],
        [InlineKeyboardButton(
            "🚪 خروج",
            callback_data="adm_logout"
        )]
    ]

    await update.message.reply_text(
        "👑 پنل مدیریت فروشگاه\n\n"
        "از این قسمت می‌توانی کل فروشگاه را مدیریت کنی:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def is_logged(context):
    return (
        context.user_data.get("admin_logged") is True
    )


# =========================================================
# ADMIN BRANDS
# =========================================================

async def admin_brands(query):

    conn = await db()

    brands = await conn.fetch("""
        SELECT id,name,active
        FROM brands
        ORDER BY id DESC
    """)

    await conn.close()

    keyboard = [
        [InlineKeyboardButton(
            "➕ افزودن برند",
            callback_data="adm_add_brand"
        )]
    ]

    for b in brands:
        state = "🟢" if b["active"] else "🔴"

        keyboard.append([
            InlineKeyboardButton(
                f"{state} {b['name']}",
                callback_data=f"adm_brand:{b['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 پنل",
            callback_data="adm_panel"
        )
    ])

    await query.edit_message_text(
        "🏷 مدیریت برندها:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_brand_start(query, context):

    context.user_data["state"] = "add_brand"

    await query.edit_message_text(
        "🏷 نام برند جدید را ارسال کن:"
    )


async def add_brand(update, context):

    if context.user_data.get("state") != "add_brand":
        return

    name = update.message.text.strip()

    conn = await db()

    try:
        await conn.execute(
            "INSERT INTO brands(name) VALUES($1)",
            name
        )

        result = "✅ برند اضافه شد."

    except Exception:
        result = "❌ این برند قبلاً وجود دارد."

    await conn.close()

    context.user_data["state"] = None

    await update.message.reply_text(result)


# =========================================================
# ADMIN PRODUCTS
# =========================================================

async def admin_products(query):

    conn = await db()

    products = await conn.fetch("""
        SELECT
            p.id,
            p.name,
            p.price,
            p.sale_price,
            p.active,
            b.name AS brand
        FROM products p
        LEFT JOIN brands b ON b.id=p.brand_id
        ORDER BY p.id DESC
        LIMIT 50
    """)

    await conn.close()

    keyboard = [
        [InlineKeyboardButton(
            "➕ افزودن محصول",
            callback_data="adm_add_product"
        )]
    ]

    for p in products:

        state = "🟢" if p["active"] else "🔴"

        keyboard.append([
            InlineKeyboardButton(
                f"{state} {p['name']}",
                callback_data=f"adm_product:{p['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 پنل",
            callback_data="adm_panel"
        )
    ])

    await query.edit_message_text(
        "📦 مدیریت محصولات:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_product_start(query, context):

    context.user_data["product"] = {}
    context.user_data["state"] = "product_name"

    await query.edit_message_text(
        "👟 نام مدل را ارسال کن:"
    )


async def product_add_message(update, context):

    state = context.user_data.get("state")
    data = context.user_data.setdefault("product", {})

    if state == "product_name":

        data["name"] = update.message.text
        context.user_data["state"] = "product_brand"

        conn = await db()

        brands = await conn.fetch("""
            SELECT id,name
            FROM brands
            WHERE active=TRUE
            ORDER BY name
        """)

        await conn.close()

        if not brands:
            await update.message.reply_text(
                "❌ اول حداقل یک برند بساز."
            )
            context.user_data["state"] = None
            return

        keyboard = []

        for b in brands:
            keyboard.append([
                InlineKeyboardButton(
                    b["name"],
                    callback_data=f"choosebrand:{b['id']}"
                )
            ])

        await update.message.reply_text(
            "🏷 برند محصول را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if state == "product_description":

        data["description"] = update.message.text
        context.user_data["state"] = "product_price"

        await update.message.reply_text(
            "💰 قیمت اصلی را فقط به عدد وارد کن.\n"
            "مثلاً:\n"
            "2500000"
        )
        return

    if state == "product_price":

        try:
            data["price"] = int(
                update.message.text.replace(",", "")
            )
        except:
            await update.message.reply_text(
                "❌ فقط عدد وارد کن."
            )
            return

        context.user_data["state"] = "product_sale"

        await update.message.reply_text(
            "🔥 قیمت حراج را وارد کن.\n"
            "اگر حراج ندارد، عدد 0 بزن."
        )
        return

    if state == "product_sale":

        try:
            data["sale_price"] = int(
                update.message.text.replace(",", "")
            )
        except:
            await update.message.reply_text(
                "❌ فقط عدد وارد کن."
            )
            return

        context.user_data["state"] = "product_sizes"

        await update.message.reply_text(
            "📏 سایزها را با کاما جدا کن.\n"
            "مثلاً:\n"
            "40,41,42,43,44,45"
        )
        return

    if state == "product_sizes":

        data["sizes"] = update.message.text
        context.user_data["state"] = "product_stock"

        await update.message.reply_text(
            "📦 تعداد موجودی کل را وارد کن:"
        )
        return

    if state == "product_stock":

        try:
            data["stock"] = int(update.message.text)
        except:
            await update.message.reply_text(
                "❌ فقط عدد وارد کن."
            )
            return

        context.user_data["state"] = "product_category"

        await update.message.reply_text(
            "👟 دسته‌بندی/کاربرد محصول را بنویس.\n"
            "مثلاً:\n"
            "باشگاه، دویدن، روزمره"
        )
        return

    if state == "product_category":

        data["category"] = update.message.text
        context.user_data["state"] = "product_keywords"

        await update.message.reply_text(
            "🔎 کلمات جستجو را وارد کن.\n"
            "مثلاً:\n"
            "باشگاه,ورزش,تمرین,بدنسازی"
        )
        return

    if state == "product_keywords":

        data["keywords"] = update.message.text
        context.user_data["state"] = "product_images"

        data["images"] = []

        await update.message.reply_text(
            "🖼 حالا عکس‌های محصول را یکی‌یکی بفرست.\n\n"
            "حداکثر ۵ عکس.\n"
            "وقتی تمام شد بنویس:\n"
            "تمام"
        )
        return

    if state == "product_images":

        if update.message.photo:

            images = data.setdefault("images", [])

            if len(images) >= 5:
                await update.message.reply_text(
                    "⚠️ حداکثر ۵ عکس مجاز است.\n"
                    "بنویس «تمام»."
                )
                return

            images.append(
                update.message.photo[-1].file_id
            )

            await update.message.reply_text(
                f"✅ عکس {len(images)} دریافت شد.\n"
                f"عکس بعدی یا «تمام»."
            )

            return

        if update.message.text.strip() == "تمام":

            await save_product(update, context)
            return


async def save_product(update, context):

    data = context.user_data["product"]

    conn = await db()

    product_id = await conn.fetchval("""
        INSERT INTO products(
            brand_id,
            name,
            description,
            price,
            sale_price,
            sizes,
            stock,
            category,
            keywords
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING id
    """,
        data["brand_id"],
        data["name"],
        data.get("description", ""),
        data["price"],
        data["sale_price"],
        data["sizes"],
        data["stock"],
        data.get("category", ""),
        data.get("keywords", "")
    )

    for position, file_id in enumerate(
        data.get("images", [])[:5],
        start=1
    ):
        await conn.execute("""
            INSERT INTO product_images(
                product_id,file_id,position
            )
            VALUES($1,$2,$3)
        """,
            product_id,
            file_id,
            position
        )

    await conn.close()

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ محصول «{data['name']}» اضافه شد.\n\n"
        f"🆔 شماره محصول: {product_id}\n"
        f"🖼 تعداد عکس: {len(data.get('images', []))}"
    )


# =========================================================
# ADMIN ORDERS
# =========================================================

async def admin_orders(query):

    conn = await db()

    orders = await conn.fetch("""
        SELECT id,customer_name,total,status,created_at
        FROM orders
        ORDER BY id DESC
        LIMIT 50
    """)

    await conn.close()

    status_names = {
        "waiting_payment": "⏳ پرداخت",
        "waiting_admin": "🔎 بررسی",
        "paid": "✅ تأیید",
        "rejected": "❌ رد",
        "shipped": "🚚 ارسال",
        "completed": "🏁 تکمیل"
    }

    keyboard = []

    for o in orders:

        keyboard.append([
            InlineKeyboardButton(
                f"#{o['id']} | {o['customer_name']} | "
                f"{o['total']:,} | "
                f"{status_names.get(o['status'], o['status'])}",
                callback_data=f"adm_order:{o['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 پنل",
            callback_data="adm_panel"
        )
    ])

    await query.edit_message_text(
        "🧾 سفارش‌های فروشگاه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN SETTINGS
# =========================================================

async def admin_settings(query):

    card = await setting("card_number")
    shipping = await setting("shipping_cost")

    keyboard = [
        [InlineKeyboardButton(
            "💳 تغییر شماره کارت",
            callback_data="set_card"
        )],
        [InlineKeyboardButton(
            "🚚 تغییر هزینه ارسال",
            callback_data="set_shipping"
        )],
        [InlineKeyboardButton(
            "📞 تغییر متن پشتیبانی",
            callback_data="set_support"
        )],
        [InlineKeyboardButton(
            "🔙 پنل",
            callback_data="adm_panel"
        )]
    ]

    await query.edit_message_text(
        "⚙️ تنظیمات فروشگاه\n\n"
        f"💳 کارت: {card or 'ثبت نشده'}\n"
        f"🚚 ارسال: {shipping or '0'} تومان",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN PASSWORD
# =========================================================

async def change_password_start(query, context):

    context.user_data["state"] = "new_password"

    await query.edit_message_text(
        "🔑 رمز جدید را ارسال کن:"
    )


async def change_password(update, context):

    if context.user_data.get("state") != "new_password":
        return

    password = update.message.text.strip()

    if len(password) < 4:
        await update.message.reply_text(
            "❌ رمز باید حداقل ۴ کاراکتر باشد."
        )
        return

    await set_setting(
        "admin_password",
        hashlib.sha256(password.encode()).hexdigest()
    )

    context.user_data["state"] = None

    await update.message.reply_text(
        "✅ رمز پنل با موفقیت تغییر کرد."
    )


# =========================================================
# ADMIN CALLBACKS
# =========================================================

async def admin_callback(query, context):

    if not admin_only(query.from_user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    if not is_logged(context):
        await query.answer(
            "ابتدا با /admin وارد شوید.",
            show_alert=True
        )
        return

    data = query.data

    if data == "adm_panel":

        keyboard = [
            [InlineKeyboardButton(
                "📦 مدیریت محصولات",
                callback_data="adm_products"
            )],
            [InlineKeyboardButton(
                "🏷 مدیریت برندها",
                callback_data="adm_brands"
            )],
            [InlineKeyboardButton(
                "🧾 سفارش‌ها",
                callback_data="adm_orders"
            )],
            [InlineKeyboardButton(
                "⚙️ تنظیمات فروشگاه",
                callback_data="adm_settings"
            )],
            [InlineKeyboardButton(
                "🔑 تغییر رمز",
                callback_data="adm_password"
            )],
            [InlineKeyboardButton(
                "🚪 خروج",
                callback_data="adm_logout"
            )]
        ]

        await query.edit_message_text(
            "👑 پنل مدیریت",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "adm_products":
        await admin_products(query)

    elif data == "adm_brands":
        await admin_brands(query)

    elif data == "adm_add_brand":
        await add_brand_start(query, context)

    elif data == "adm_add_product":
        await add_product_start(query, context)

    elif data.startswith("choosebrand:"):

        brand_id = int(data.split(":")[1])

        context.user_data["product"]["brand_id"] = brand_id
        context.user_data["state"] = "product_description"

        await query.edit_message_text(
            "📝 توضیحات محصول را بنویس.\n"
            "اگر توضیحی نداری، بنویس:\n"
            "ندارد"
        )

    elif data == "adm_orders":
        await admin_orders(query)

    elif data == "adm_settings":
        await admin_settings(query)

    elif data == "adm_password":
        await change_password_start(query, context)

    elif data == "set_card":

        context.user_data["state"] = "set_card"

        await query.edit_message_text(
            "💳 شماره کارت جدید را ارسال کن:"
        )

    elif data == "set_shipping":

        context.user_data["state"] = "set_shipping"

        await query.edit_message_text(
            "🚚 هزینه ارسال را به تومان وارد کن:"
        )

    elif data == "set_support":

        context.user_data["state"] = "set_support"

        await query.edit_message_text(
            "📞 متن جدید پشتیبانی را ارسال کن:"
        )

    elif data.startswith("approve:"):

        order_id = int(data.split(":")[1])

        conn = await db()

        order = await conn.fetchrow(
            "SELECT telegram_id FROM orders WHERE id=$1",
            order_id
        )

        await conn.execute("""
            UPDATE orders
            SET status='paid'
            WHERE id=$1
        """, order_id)

        await conn.close()

        if order:
            await context.bot.send_message(
                order["telegram_id"],
                f"✅ پرداخت سفارش #{order_id} تأیید شد.\n\n"
                "📦 سفارش شما ثبت نهایی شد و در اسرع وقت ارسال می‌شود."
            )

        await query.answer("پرداخت تأیید شد.")

    elif data.startswith("reject:"):

        order_id = int(data.split(":")[1])

        conn = await db()

        order = await conn.fetchrow(
            "SELECT telegram_id FROM orders WHERE id=$1",
            order_id
        )

        await conn.execute("""
            UPDATE orders
            SET status='rejected'
            WHERE id=$1
        """, order_id)

        await conn.close()

        if order:
            await context.bot.send_message(
                order["telegram_id"],
                f"❌ پرداخت سفارش #{order_id} تأیید نشد.\n\n"
                "لطفاً رسید پرداخت را بررسی کرده و دوباره ارسال کنید."
            )

        await query.answer("پرداخت رد شد.")

    elif data == "adm_logout":

        context.user_data.clear()

        await query.edit_message_text(
            "🚪 از پنل مدیریت خارج شدید."
        )


# =========================================================
# ADMIN SETTINGS TEXT
# =========================================================

async def admin_setting_message(update, context):

    state = context.user_data.get("state")

    if state == "set_card":

        await set_setting(
            "card_number",
            update.message.text.strip()
        )

        context.user_data["state"] = None

        await update.message.reply_text(
            "✅ شماره کارت ذخیره شد."
        )
        return

    if state == "set_shipping":

        try:
            int(update.message.text.replace(",", ""))
        except:
            await update.message.reply_text(
                "❌ فقط عدد وارد کن."
            )
            return

        await set_setting(
            "shipping_cost",
            update.message.text.replace(",", "")
        )

        context.user_data["state"] = None

        await update.message.reply_text(
            "✅ هزینه ارسال ذخیره شد."
        )
        return

    if state == "set_support":

        await set_setting(
            "support_text",
            update.message.text
        )

        context.user_data["state"] = None

        await update.message.reply_text(
            "✅ متن پشتیبانی ذخیره شد."
        )
        return


# =========================================================
# MAIN CALLBACK
# =========================================================

async def callback_handler(update, context):

    query = update.callback_query
    await query.answer()

    data = query.data

    # مشتری
    if data == "home":
        await query.edit_message_text(
            "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
            "از منوی زیر انتخاب کنید:",
            reply_markup=await main_menu()
        )

    elif data == "products":
        await products_menu(query)

    elif data == "sale":
        await sale_products(query)

    elif data.startswith("brand:"):
        await brand_products(
            query,
            int(data.split(":")[1])
        )

    elif data.startswith("product:"):
        await product_details(
            query,
            int(data.split(":")[1])
        )

    elif data.startswith("buy:"):
        await add_to_cart(
            update,
            int(data.split(":")[1])
        )

    elif data.startswith("addsize:"):

        parts = data.split(":", 2)

        await insert_cart(
            update,
            int(parts[1]),
            parts[2]
        )

    elif data == "cart":
        await show_cart(query)

    elif data == "checkout":
        await checkout_start(query, context)

    elif data == "orders":
        await customer_orders(query)

    elif data == "search":
        await start_search(query, context)

    elif data == "members":

        conn = await db()
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users"
        )
        await conn.close()

        await query.edit_message_text(
            f"👥 اعضای ربات\n\n"
            f"تعداد اعضا: {count}",
            reply_markup=back_button("home")
        )

    elif data == "support":

        text = await setting("support_text")

        await query.edit_message_text(
            text,
            reply_markup=back_button("home")
        )

    # ادمین
    elif data.startswith("adm_") or data.startswith("approve:") or data.startswith("reject:") or data.startswith("set_") or data.startswith("choosebrand:"):

        await admin_callback(
            query,
            context
        )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):

    state = context.user_data.get("state")

    # ورود ادمین
    if state == "admin_password":
        await admin_password(update, context)
        return

    # تنظیمات ادمین
    if state in (
        "set_card",
        "set_shipping",
        "set_support"
    ):
        await admin_setting_message(update, context)
        return

    # تغییر رمز
    if state == "new_password":
        await change_password(update, context)
        return

    # افزودن برند
    if state == "add_brand":
        await add_brand(update, context)
        return

    # افزودن محصول
    if state and state.startswith("product_"):
        await product_add_message(update, context)
        return

    # اطلاعات مشتری
    if state in (
        "customer_name",
        "phone",
        "address",
        "postal"
    ):
        await checkout_message(update, context)
        return

    # جستجو
    if state == "search":
        await do_search(update, context)
        return


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(update, context):

    state = context.user_data.get("state")

    if state == "product_images":
        await product_add_message(update, context)
        return

    if state and state.startswith("receipt:"):
        await receive_receipt(update, context)
        return


# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):
    print("ERROR:", context.error)


# =========================================================
# START BOT
# =========================================================

async def post_init(application):
    await init_db()


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
    CommandHandler("admin", admin_command)
)

app.add_handler(
    CallbackQueryHandler(callback_handler)
)

app.add_handler(
    MessageHandler(
        filters.PHOTO,
        photo_handler
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler
    )
)

app.add_error_handler(error_handler)

print("BOT STARTED")

app.run_polling()
