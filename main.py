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

# =========================================================
# CONFIG
# =========================================================

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

    await conn.close()

    print("✅ DATABASE READY")


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
        INSERT INTO settings(key, value)
        VALUES($1, $2)
        ON CONFLICT(key)
        DO UPDATE SET value=EXCLUDED.value
    """, key, value)

    await conn.close()


# =========================================================
# HELPERS
# =========================================================

async def save_user(update):
    user = update.effective_user

    if not user:
        return

    conn = await db()

    await conn.execute("""
        INSERT INTO users(telegram_id, username, first_name)
        VALUES($1, $2, $3)
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


def is_admin(user_id):
    return user_id == ADMIN_ID


def is_logged(context):
    return (
        context.user_data.get("admin_logged") is True
        and context.user_data.get("admin_id") == ADMIN_ID
    )


def back_button(callback="home"):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data=callback
            )
        ]
    ])


async def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛍 محصولات",
                callback_data="products"
            ),
            InlineKeyboardButton(
                "🛒 سبد خرید",
                callback_data="cart"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 سفارش‌های من",
                callback_data="orders"
            ),
            InlineKeyboardButton(
                "🔎 جستجو",
                callback_data="search"
            )
        ],
        [
            InlineKeyboardButton(
                "📞 پشتیبانی",
                callback_data="support"
            )
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update, context):
    await save_user(update)

    context.user_data.clear()

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=await main_menu()
    )


# =========================================================
# CUSTOMER PRODUCTS
# =========================================================

async def products_menu(query):

    conn = await db()

    brands = await conn.fetch("""
        SELECT id, name
        FROM brands
        WHERE active=TRUE
        ORDER BY name
    """)

    await conn.close()

    keyboard = [
        [
            InlineKeyboardButton(
                "🔥 حراج",
                callback_data="sale"
            )
        ]
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
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "🛍 محصولات فروشگاه\n\n"
        "🔥 حراج\n"
        "🏷 برند موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def brand_products(query, brand_id):

    conn = await db()

    brand = await conn.fetchrow("""
        SELECT name
        FROM brands
        WHERE id=$1 AND active=TRUE
    """, brand_id)

    products = await conn.fetch("""
        SELECT id, name, price, sale_price
        FROM products
        WHERE brand_id=$1 AND active=TRUE
        ORDER BY id DESC
    """, brand_id)

    await conn.close()

    if not brand:
        await query.edit_message_text(
            "❌ برند پیدا نشد.",
            reply_markup=back_button("products")
        )
        return

    if not products:
        await query.edit_message_text(
            f"🏷 {brand['name']}\n\n"
            "فعلاً محصولی ثبت نشده.",
            reply_markup=back_button("products")
        )
        return

    keyboard = []

    for p in products:

        price = p["price"]

        if p["sale_price"] > 0 and p["sale_price"] < p["price"]:
            price = p["sale_price"]
            text = f"🔥 {p['name']} | {price:,} تومان"
        else:
            text = f"👟 {p['name']} | {price:,} تومان"

        keyboard.append([
            InlineKeyboardButton(
                text,
                callback_data=f"product:{p['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برندها",
            callback_data="products"
        )
    ])

    await query.edit_message_text(
        f"🏷 {brand['name']}\n\n"
        "مدل موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def sale_products(query):

    conn = await db()

    products = await conn.fetch("""
        SELECT id, name, sale_price
        FROM products
        WHERE active=TRUE
        AND sale_price > 0
        AND sale_price < price
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
        InlineKeyboardButton(
            "🔙 محصولات",
            callback_data="products"
        )
    ])

    await query.edit_message_text(
        "🔥 محصولات حراج:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def product_details(query, product_id):

    conn = await db()

    product = await conn.fetchrow("""
        SELECT
            p.*,
            b.name AS brand_name
        FROM products p
        LEFT JOIN brands b
            ON b.id=p.brand_id
        WHERE p.id=$1 AND p.active=TRUE
    """, product_id)

    images = await conn.fetch("""
        SELECT file_id
        FROM product_images
        WHERE product_id=$1
        ORDER BY position
        LIMIT 5
    """, product_id)

    await conn.close()

    if not product:
        await query.edit_message_text(
            "❌ محصول پیدا نشد."
        )
        return

    sale = (
        product["sale_price"] > 0
        and product["sale_price"] < product["price"]
    )

    if sale:
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
        f"🏷 برند: {product['brand_name'] or '---'}\n"
        f"{price_text}\n"
        f"📏 سایزها: {product['sizes'] or '---'}\n"
        f"📦 موجودی: {product['stock']}\n\n"
        f"{product['description'] or ''}"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 افزودن به سبد خرید",
                callback_data=f"buy:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 محصولات",
                callback_data="products"
            )
        ]
    ])

    if images:
        try:
            await query.message.delete()

            for i, image in enumerate(images):

                if i == 0:
                    await query.message.chat.send_photo(
                        photo=image["file_id"],
                        caption=text,
                        reply_markup=markup
                    )
                else:
                    await query.message.chat.send_photo(
                        photo=image["file_id"]
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

    query = update.callback_query

    conn = await db()

    product = await conn.fetchrow("""
        SELECT *
        FROM products
        WHERE id=$1 AND active=TRUE
    """, product_id)

    await conn.close()

    if not product:
        await query.answer(
            "❌ محصول پیدا نشد.",
            show_alert=True
        )
        return

    if product["stock"] <= 0:
        await query.answer(
            "❌ این محصول ناموجود است.",
            show_alert=True
        )
        return

    sizes = [
        x.strip()
        for x in (product["sizes"] or "").split(",")
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

        await query.edit_message_text(
            "📏 سایز موردنظر را انتخاب کنید:",
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

    product = await conn.fetchrow("""
        SELECT name, stock
        FROM products
        WHERE id=$1 AND active=TRUE
    """, product_id)

    if not product:
        await conn.close()
        await update.callback_query.answer(
            "❌ محصول پیدا نشد.",
            show_alert=True
        )
        return

    current = await conn.fetchval("""
        SELECT COALESCE(quantity,0)
        FROM cart_items
        WHERE telegram_id=$1
        AND product_id=$2
        AND size=$3
    """, telegram_id, product_id, size)

    current = current or 0

    if current >= product["stock"]:
        await conn.close()
        await update.callback_query.answer(
            "❌ بیشتر از موجودی نمی‌توانی اضافه کنی.",
            show_alert=True
        )
        return

    await conn.execute("""
        INSERT INTO cart_items(
            telegram_id,
            product_id,
            size,
            quantity
        )
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
        f"✅ {product['name']}\n\n"
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
            p.sale_price,
            p.stock
        FROM cart_items c
        JOIN products p
            ON p.id=c.product_id
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

        if (
            item["sale_price"] > 0
            and item["sale_price"] < item["price"]
        ):
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

    final_total = total + shipping

    text += (
        f"🛍 جمع کالاها: {total:,} تومان\n"
        f"🚚 ارسال: {shipping:,} تومان\n"
        f"💵 مبلغ نهایی: {final_total:,} تومان"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📦 ثبت سفارش",
                callback_data="checkout"
            )
        ],
        [
            InlineKeyboardButton(
                "🛍 ادامه خرید",
                callback_data="products"
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

    word = update.message.text.strip()

    if not word:
        await update.message.reply_text(
            "❌ چیزی وارد نکردی."
        )
        return

    context.user_data["state"] = None

    conn = await db()

    products = await conn.fetch("""
        SELECT
            p.id,
            p.name,
            p.price,
            p.sale_price
        FROM products p
        LEFT JOIN brands b
            ON b.id=p.brand_id
        WHERE p.active=TRUE
        AND (
            p.name ILIKE $1
            OR p.description ILIKE $1
            OR p.category ILIKE $1
            OR p.keywords ILIKE $1
            OR b.name ILIKE $1
        )
        ORDER BY p.id DESC
    """, f"%{word}%")

    await conn.close()

    if not products:
        await update.message.reply_text(
            f"❌ برای «{word}» محصولی پیدا نشد.",
            reply_markup=await main_menu()
        )
        return

    keyboard = []

    for p in products:

        price = p["price"]

        if (
            p["sale_price"] > 0
            and p["sale_price"] < p["price"]
        ):
            price = p["sale_price"]

        keyboard.append([
            InlineKeyboardButton(
                f"👟 {p['name']} | {price:,} تومان",
                callback_data=f"product:{p['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="home"
        )
    ])

    await update.message.reply_text(
        f"🔎 نتایج جستجو برای «{word}»:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# CHECKOUT
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
        "👤 نام و نام خانوادگی را ارسال کنید:"
    )


async def checkout_message(update, context):

    state = context.user_data.get("state")

    if state == "customer_name":

        name = update.message.text.strip()

        if len(name) < 3:
            await update.message.reply_text(
                "❌ نام را کامل وارد کنید."
            )
            return

        context.user_data["customer_name"] = name
        context.user_data["state"] = "phone"

        await update.message.reply_text(
            "📱 شماره موبایل را ارسال کنید:"
        )
        return

    if state == "phone":

        phone = update.message.text.strip()

        context.user_data["phone"] = phone
        context.user_data["state"] = "address"

        await update.message.reply_text(
            "📍 آدرس کامل را ارسال کنید:"
        )
        return

    if state == "address":

        address = update.message.text.strip()

        if len(address) < 10:
            await update.message.reply_text(
                "❌ آدرس را کامل‌تر وارد کنید."
            )
            return

        context.user_data["address"] = address
        context.user_data["state"] = "postal"

        await update.message.reply_text(
            "📮 کد پستی را ارسال کنید:"
        )
        return

    if state == "postal":

        postal = update.message.text.strip()

        context.user_data["postal_code"] = postal
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
            p.sale_price,
            p.stock
        FROM cart_items c
        JOIN products p
            ON p.id=c.product_id
        WHERE c.telegram_id=$1
    """, telegram_id)

    if not items:
        await conn.close()
        await update.message.reply_text(
            "❌ سبد خرید خالی است."
        )
        return

    total = 0

    for item in items:

        if item["quantity"] > item["stock"]:
            await conn.close()

            await update.message.reply_text(
                f"❌ موجودی «{item['name']}» کافی نیست.\n"
                f"موجودی فعلی: {item['stock']}"
            )
            return

        price = item["price"]

        if (
            item["sale_price"] > 0
            and item["sale_price"] < item["price"]
        ):
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

        if (
            item["sale_price"] > 0
            and item["sale_price"] < item["price"]
        ):
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

    await conn.execute("""
        DELETE FROM cart_items
        WHERE telegram_id=$1
    """, telegram_id)

    await conn.close()

    card = await setting("card_number")

    if card:
        payment_text = (
            "💳 شماره کارت:\n"
            f"`{card}`\n\n"
        )
    else:
        payment_text = (
            "⚠️ شماره کارت هنوز توسط مدیریت ثبت نشده.\n\n"
        )

    await update.message.reply_text(
        f"✅ سفارش شما ثبت شد.\n\n"
        f"🧾 شماره سفارش: #{order_id}\n"
        f"💰 مبلغ نهایی: {final_total:,} تومان\n\n"
        f"{payment_text}"
        "بعد از پرداخت، عکس رسید را همینجا ارسال کنید.",
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
            "❌ لطفاً عکس رسید را ارسال کنید."
        )
        return

    file_id = update.message.photo[-1].file_id

    conn = await db()

    order = await conn.fetchrow("""
        SELECT *
        FROM orders
        WHERE id=$1
    """, order_id)

    if not order:
        await conn.close()
        await update.message.reply_text(
            "❌ سفارش پیدا نشد."
        )
        return

    await conn.execute("""
        UPDATE orders
        SET receipt_file_id=$1,
            status='waiting_admin'
        WHERE id=$2
    """, file_id, order_id)

    await conn.close()

    context.user_data["state"] = None

    await update.message.reply_text(
        "🧾 رسید دریافت شد.\n\n"
        "⏳ بعد از بررسی پرداخت، نتیجه برای شما ارسال می‌شود."
    )

    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                f"🧾 رسید جدید\n\n"
                f"🧾 سفارش: #{order_id}\n"
                f"💰 مبلغ: {order['total']:,} تومان\n"
                f"👤 مشتری: {order['customer_name']}\n"
                f"📱 تلفن: {order['phone']}\n"
                f"📍 آدرس: {order['address']}\n"
                f"📮 کد پستی: {order['postal_code']}"
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
# CUSTOMER ORDERS
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

    statuses = {
        "waiting_payment": "⏳ منتظر پرداخت",
        "waiting_admin": "🔎 در انتظار بررسی",
        "paid": "✅ پرداخت تأیید شد",
        "rejected": "❌ پرداخت رد شد",
        "shipped": "🚚 ارسال شد",
        "completed": "🏁 تکمیل شد"
    }

    text = "📦 سفارش‌های شما:\n\n"

    for order in orders:

        status = statuses.get(
            order["status"],
            order["status"]
        )

        text += (
            f"🧾 سفارش #{order['id']}\n"
            f"💰 {order['total']:,} تومان\n"
            f"📌 {status}\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=back_button("home")
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

async def admin_command(update, context):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ شما دسترسی مدیریت ندارید."
        )
        return

    context.user_data.clear()

    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = "admin_password"

    await update.message.reply_text(
        "🔐 رمز پنل مدیریت را وارد کنید:"
    )


async def admin_password(update, context):

    if not is_admin(update.effective_user.id):
        return

    if context.user_data.get("state") != "admin_password":
        return

    password = update.message.text.strip()

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
    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = None

    await send_admin_panel(update)


async def send_admin_panel(update):

    keyboard = [
        [
            InlineKeyboardButton(
                "📦 مدیریت محصولات",
                callback_data="adm_products"
            )
        ],
        [
            InlineKeyboardButton(
                "🏷 مدیریت برندها",
                callback_data="adm_brands"
            )
        ],
        [
            InlineKeyboardButton(
                "🧾 سفارش‌ها",
                callback_data="adm_orders"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 اعضای ربات",
                callback_data="adm_members"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ تنظیمات فروشگاه",
                callback_data="adm_settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🔑 تغییر رمز",
                callback_data="adm_password"
            )
        ],
        [
            InlineKeyboardButton(
                "🚪 خروج",
                callback_data="adm_logout"
            )
        ]
    ]

    await update.message.reply_text(
        "👑 پنل مدیریت فروشگاه\n\n"
        "از منوی زیر مدیریت کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel_callback(query, context):

    keyboard = [
        [
            InlineKeyboardButton(
                "📦 مدیریت محصولات",
                callback_data="adm_products"
            )
        ],
        [
            InlineKeyboardButton(
                "🏷 مدیریت برندها",
                callback_data="adm_brands"
            )
        ],
        [
            InlineKeyboardButton(
                "🧾 سفارش‌ها",
                callback_data="adm_orders"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 اعضای ربات",
                callback_data="adm_members"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ تنظیمات فروشگاه",
                callback_data="adm_settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🔑 تغییر رمز",
                callback_data="adm_password"
            )
        ],
        [
            InlineKeyboardButton(
                "🚪 خروج",
                callback_data="adm_logout"
            )
        ]
    ]

    await query.edit_message_text(
        "👑 پنل مدیریت",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
        [
            InlineKeyboardButton(
                "➕ افزودن برند",
                callback_data="adm_add_brand"
            )
        ]
    ]

    for brand in brands:

        icon = "🟢" if brand["active"] else "🔴"

        keyboard.append([
            InlineKeyboardButton(
                f"{icon} {brand['name']}",
                callback_data=f"adm_brand:{brand['id']}"
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

    name = update.message.text.strip()

    if not name:
        return

    conn = await db()

    exists = await conn.fetchval("""
        SELECT id
        FROM brands
        WHERE LOWER(name)=LOWER($1)
    """, name)

    if exists:
        await conn.close()
        await update.message.reply_text(
            "❌ این برند قبلاً وجود دارد."
        )
        return

    await conn.execute(
        "INSERT INTO brands(name) VALUES($1)",
        name
    )

    await conn.close()

    context.user_data["state"] = None

    await update.message.reply_text(
        f"✅ برند «{name}» اضافه شد."
    )


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
        LEFT JOIN brands b
            ON b.id=p.brand_id
        ORDER BY p.id DESC
        LIMIT 50
    """)

    await conn.close()

    keyboard = [
        [
            InlineKeyboardButton(
                "➕ افزودن محصول",
                callback_data="adm_add_product"
            )
        ]
    ]

    for p in products:

        icon = "🟢" if p["active"] else "🔴"

        keyboard.append([
            InlineKeyboardButton(
                f"{icon} {p['name']}",
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
    data = context.user_data.setdefault(
        "product",
        {}
    )

    if state == "product_name":

        data["name"] = update.message.text.strip()
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
            context.user_data["state"] = None

            await update.message.reply_text(
                "❌ اول حداقل یک برند بساز."
            )
            return

        keyboard = []

        for brand in brands:
            keyboard.append([
                InlineKeyboardButton(
                    brand["name"],
                    callback_data=f"choosebrand:{brand['id']}"
                )
            ])

        await update.message.reply_text(
            "🏷 برند محصول را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if state == "product_description":

        text = update.message.text.strip()

        data["description"] = (
            "" if text == "ندارد" else text
        )

        context.user_data["state"] = "product_price"

        await update.message.reply_text(
            "💰 قیمت اصلی را فقط عدد وارد کن.\n"
            "مثال: 2500000"
        )
        return

    if state == "product_price":

        try:
            price = int(
                update.message.text.replace(",", "")
            )

            if price < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ فقط عدد صحیح وارد کن."
            )
            return

        data["price"] = price
        context.user_data["state"] = "product_sale"

        await update.message.reply_text(
            "🔥 قیمت حراج را وارد کن.\n"
            "اگر حراج ندارد: 0"
        )
        return

    if state == "product_sale":

        try:
            sale = int(
                update.message.text.replace(",", "")
            )

            if sale < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ فقط عدد صحیح وارد کن."
            )
            return

        data["sale_price"] = sale
        context.user_data["state"] = "product_sizes"

        await update.message.reply_text(
            "📏 سایزها را با کاما جدا کن.\n"
            "مثال:\n"
            "40,41,42,43,44,45"
        )
        return

    if state == "product_sizes":

        data["sizes"] = update.message.text.strip()
        context.user_data["state"] = "product_stock"

        await update.message.reply_text(
            "📦 تعداد موجودی کل را وارد کن:"
        )
        return

    if state == "product_stock":

        try:
            stock = int(update.message.text)

            if stock < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ فقط عدد صحیح وارد کن."
            )
            return

        data["stock"] = stock
        context.user_data["state"] = "product_category"

        await update.message.reply_text(
            "👟 دسته‌بندی/کاربرد محصول را بنویس.\n"
            "مثال:\n"
            "باشگاه، دویدن، روزمره"
        )
        return

    if state == "product_category":

        data["category"] = update.message.text.strip()

        context.user_data["state"] = "product_keywords"

        await update.message.reply_text(
            "🔎 کلمات جستجو را با کاما بنویس.\n"
            "مثال:\n"
            "باشگاه,ورزش,تمرین,بدنسازی"
        )
        return

    if state == "product_keywords":

        data["keywords"] = update.message.text.strip()
        data["images"] = []

        context.user_data["state"] = "product_images"

        await update.message.reply_text(
            "🖼 عکس‌های محصول را یکی‌یکی بفرست.\n\n"
            "حداکثر ۵ عکس.\n"
            "وقتی تمام شد بنویس:\n"
            "تمام"
        )
        return

    if state == "product_images":

        if update.message.text:

            if update.message.text.strip() == "تمام":

                await save_product(
                    update,
                    context
                )

                return

        await update.message.reply_text(
            "❌ لطفاً عکس بفرست یا «تمام» بنویس."
        )


async def save_product(update, context):

    data = context.user_data.get("product", {})

    if not data.get("images"):
        await update.message.reply_text(
            "❌ حداقل یک عکس برای محصول بفرست."
        )
        return

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
        data["images"][:5],
        start=1
    ):

        await conn.execute("""
            INSERT INTO product_images(
                product_id,
                file_id,
                position
            )
            VALUES($1,$2,$3)
        """,
            product_id,
            file_id,
            position
        )

    await conn.close()

    product_name = data["name"]

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ محصول «{product_name}» اضافه شد.\n\n"
        f"🆔 شماره محصول: {product_id}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📦 مدیریت محصولات",
                    callback_data="adm_products"
                )
            ],
            [
                InlineKeyboardButton(
                    "👑 پنل مدیریت",
                    callback_data="adm_panel"
                )
            ]
        ])
    )


# =========================================================
# ADMIN MEMBERS
# =========================================================

async def admin_members(query):

    conn = await db()

    count = await conn.fetchval(
        "SELECT COUNT(*) FROM users"
    )

    members = await conn.fetch("""
        SELECT
            telegram_id,
            username,
            first_name,
            created_at
        FROM users
        ORDER BY created_at DESC
        LIMIT 100
    """)

    await conn.close()

    text = (
        f"👥 اعضای ربات\n\n"
        f"👤 تعداد کل اعضا: {count}\n\n"
    )

    if not members:
        text += "هنوز عضوی ثبت نشده."
    else:

        for member in members:

            username = (
                f"@{member['username']}"
                if member["username"]
                else "بدون یوزرنیم"
            )

            text += (
                f"👤 {member['first_name'] or 'بدون نام'}\n"
                f"🆔 {member['telegram_id']}\n"
                f"📱 {username}\n"
                f"📅 {member['created_at']}\n"
                f"━━━━━━━━━━━━\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 بروزرسانی",
                    callback_data="adm_members"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل",
                    callback_data="adm_panel"
                )
            ]
        ])
    )


# =========================================================
# ADMIN ORDERS
# =========================================================

async def admin_orders(query):

    conn = await db()

    orders = await conn.fetch("""
        SELECT
            id,
            customer_name,
            total,
            status
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

    for order in orders:

        keyboard.append([
            InlineKeyboardButton(
                f"#{order['id']} | "
                f"{order['customer_name']} | "
                f"{order['total']:,} | "
                f"{status_names.get(order['status'], order['status'])}",
                callback_data=f"adm_order:{order['id']}"
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


async def admin_order_details(query, order_id):

    conn = await db()

    order = await conn.fetchrow("""
        SELECT *
        FROM orders
        WHERE id=$1
    """, order_id)

    items = await conn.fetch("""
        SELECT *
        FROM order_items
        WHERE order_id=$1
    """, order_id)

    await conn.close()

    if not order:
        await query.edit_message_text(
            "❌ سفارش پیدا نشد.",
            reply_markup=back_button("adm_orders")
        )
        return

    text = (
        f"🧾 سفارش #{order_id}\n\n"
        f"👤 {order['customer_name']}\n"
        f"📱 {order['phone']}\n"
        f"📍 {order['address']}\n"
        f"📮 {order['postal_code']}\n\n"
    )

    for item in items:
        text += (
            f"👟 {item['product_name']}\n"
            f"📏 سایز: {item['size'] or '---'}\n"
            f"🔢 تعداد: {item['quantity']}\n"
            f"💰 قیمت: {item['price']:,}\n\n"
        )

    text += (
        f"🚚 ارسال: {order['shipping_cost']:,}\n"
        f"💵 مجموع: {order['total']:,}\n"
        f"📌 وضعیت: {order['status']}"
    )

    keyboard = []

    if order["status"] == "waiting_admin":
        keyboard.append([
            InlineKeyboardButton(
                "✅ تأیید پرداخت",
                callback_data=f"approve:{order_id}"
            ),
            InlineKeyboardButton(
                "❌ رد پرداخت",
                callback_data=f"reject:{order_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 سفارش‌ها",
            callback_data="adm_orders"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN SETTINGS
# =========================================================

async def admin_settings(query):

    card = await setting("card_number")
    shipping = await setting("shipping_cost")

    await query.edit_message_text(
        "⚙️ تنظیمات فروشگاه\n\n"
        f"💳 کارت: {card or 'ثبت نشده'}\n"
        f"🚚 ارسال: {shipping:,} تومان"
        if shipping.isdigit()
        else
        "⚙️ تنظیمات فروشگاه",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💳 تغییر شماره کارت",
                    callback_data="set_card"
                )
            ],
            [
                InlineKeyboardButton(
                    "🚚 تغییر هزینه ارسال",
                    callback_data="set_shipping"
                )
            ],
            [
                InlineKeyboardButton(
                    "📞 تغییر پشتیبانی",
                    callback_data="set_support"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل",
                    callback_data="adm_panel"
                )
            ]
        ])
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

    password = update.message.text.strip()

    if len(password) < 4:
        await update.message.reply_text(
            "❌ رمز باید حداقل ۴ کاراکتر باشد."
        )
        return

    await set_setting(
        "admin_password",
        hashlib.sha256(
            password.encode()
        ).hexdigest()
    )

    context.user_data["state"] = None

    await update.message.reply_text(
        "✅ رمز با موفقیت تغییر کرد."
    )


# =========================================================
# ADMIN TEXT SETTINGS
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
            value = int(
                update.message.text.replace(",", "")
            )

            if value < 0:
                raise ValueError

        except ValueError:
            await update.message.reply_text(
                "❌ فقط عدد وارد کن."
            )
            return

        await set_setting(
            "shipping_cost",
            str(value)
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


# =========================================================
# ADMIN CALLBACK
# =========================================================

async def admin_callback(query, context):

    if not is_admin(query.from_user.id):
        await query.answer(
            "❌ دسترسی ندارید.",
            show_alert=True
        )
        return

    if not is_logged(context):
        await query.answer(
            "❌ ابتدا /admin را بزن و وارد پنل شو.",
            show_alert=True
        )
        return

    data = query.data

    if data == "adm_panel":
        await admin_panel_callback(
            query,
            context
        )

    elif data == "adm_products":
        await admin_products(query)

    elif data == "adm_brands":
        await admin_brands(query)

    elif data == "adm_orders":
        await admin_orders(query)

    elif data == "adm_members":
        await admin_members(query)

    elif data == "adm_settings":
        await admin_settings(query)

    elif data == "adm_add_brand":
        await add_brand_start(
            query,
            context
        )

    elif data == "adm_add_product":
        await add_product_start(
            query,
            context
        )

    elif data.startswith("choosebrand:"):

        brand_id = int(
            data.split(":")[1]
        )

        if "product" not in context.user_data:
            await query.answer(
                "❌ فرایند افزودن محصول منقضی شده.",
                show_alert=True
            )
            return

        context.user_data["product"]["brand_id"] = brand_id
        context.user_data["state"] = "product_description"

        await query.edit_message_text(
            "📝 توضیحات محصول را بنویس.\n"
            "اگر توضیح نداری بنویس:\n"
            "ندارد"
        )

    elif data.startswith("adm_order:"):

        order_id = int(
            data.split(":")[1]
        )

        await admin_order_details(
            query,
            order_id
        )

    elif data == "adm_password":
        await change_password_start(
            query,
            context
        )

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

        order_id = int(
            data.split(":")[1]
        )

        conn = await db()

        order = await conn.fetchrow("""
            SELECT *
            FROM orders
            WHERE id=$1
        """, order_id)

        if not order:
            await conn.close()

            await query.answer(
                "❌ سفارش پیدا نشد.",
                show_alert=True
            )
            return

        await conn.execute("""
            UPDATE orders
            SET status='paid'
            WHERE id=$1
        """, order_id)

        await conn.close()

        try:
            await context.bot.send_message(
                chat_id=order["telegram_id"],
                text=(
                    f"✅ پرداخت سفارش #{order_id} تأیید شد.\n\n"
                    "📦 سفارش شما ثبت نهایی شد و "
                    "در اسرع وقت ارسال می‌شود."
                )
            )
        except Exception as e:
            print("CUSTOMER MESSAGE ERROR:", e)

        await query.answer(
            "✅ پرداخت تأیید شد."
        )

        await admin_order_details(
            query,
            order_id
        )

    elif data.startswith("reject:"):

        order_id = int(
            data.split(":")[1]
        )

        conn = await db()

        order = await conn.fetchrow("""
            SELECT *
            FROM orders
            WHERE id=$1
        """, order_id)

        if not order:
            await conn.close()

            await query.answer(
                "❌ سفارش پیدا نشد.",
                show_alert=True
            )
            return

        await conn.execute("""
            UPDATE orders
            SET status='rejected'
            WHERE id=$1
        """, order_id)

        await conn.close()

        try:
            await context.bot.send_message(
                chat_id=order["telegram_id"],
                text=(
                    f"❌ پرداخت سفارش #{order_id} تأیید نشد.\n\n"
                    "لطفاً رسید پرداخت را بررسی کنید."
                )
            )
        except Exception as e:
            print("CUSTOMER MESSAGE ERROR:", e)

        await query.answer(
            "❌ پرداخت رد شد."
        )

        await admin_order_details(
            query,
            order_id
        )

    elif data == "adm_logout":

        context.user_data.clear()

        await query.edit_message_text(
            "🚪 از پنل مدیریت خارج شدید."
        )


# =========================================================
# CUSTOMER CALLBACK
# =========================================================

async def customer_callback(query, context):

    data = query.data

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
            type(
                "Obj",
                (),
                {
                    "callback_query": query,
                    "effective_user": query.from_user
                }
            )(),
            int(data.split(":")[1])
        )

    elif data.startswith("addsize:"):

        parts = data.split(":", 2)

        await insert_cart(
            type(
                "Obj",
                (),
                {
                    "callback_query": query,
                    "effective_user": query.from_user
                }
            )(),
            int(parts[1]),
            parts[2]
        )

    elif data == "cart":
        await show_cart(query)

    elif data == "checkout":
        await checkout_start(
            query,
            context
        )

    elif data == "orders":
        await customer_orders(query)

    elif data == "search":
        await start_search(
            query,
            context
        )

    elif data == "support":

        text = await setting(
            "support_text"
        )

        await query.edit_message_text(
            text,
            reply_markup=back_button("home")
        )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def callback_handler(update, context):

    query = update.callback_query

    await query.answer()

    data = query.data

    admin_callbacks = (
        data.startswith("adm_")
        or data.startswith("approve:")
        or data.startswith("reject:")
        or data.startswith("set_")
        or data.startswith("choosebrand:")
    )

    if admin_callbacks:

        await admin_callback(
            query,
            context
        )

    else:

        await customer_callback(
            query,
            context
        )


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_handler(update, context):

    state = context.user_data.get("state")

    if state == "admin_password":

        await admin_password(
            update,
            context
        )
        return

    if state in (
        "set_card",
        "set_shipping",
        "set_support"
    ):

        if not is_admin(
            update.effective_user.id
        ):
            return

        await admin_setting_message(
            update,
            context
        )
        return

    if state == "new_password":

        if not is_admin(
            update.effective_user.id
        ):
            return

        await change_password(
            update,
            context
        )
        return

    if state == "add_brand":

        if not is_admin(
            update.effective_user.id
        ):
            return

        await add_brand(
            update,
            context
        )
        return

    if state and state.startswith("product_"):

        if not is_admin(
            update.effective_user.id
        ):
            return

        await product_add_message(
            update,
            context
        )
        return

    if state in (
        "customer_name",
        "phone",
        "address",
        "postal"
    ):

        await checkout_message(
            update,
            context
        )
        return

    if state == "search":

        await do_search(
            update,
            context
        )
        return


# =========================================================
# PHOTO ROUTER
# =========================================================

async def photo_handler(update, context):

    state = context.user_data.get("state")

    if state == "product_images":

        if not is_admin(
            update.effective_user.id
        ):
            return

        images = context.user_data.setdefault(
            "product",
            {}
        ).setdefault(
            "images",
            []
        )

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
            "عکس بعدی یا «تمام»."
        )
        return

    if state and state.startswith("receipt:"):

        await receive_receipt(
            update,
            context
        )


# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):

    print(
        "❌ ERROR:",
        repr(context.error)
    )


# =========================================================
# POST INIT
# =========================================================

async def post_init(application):

    await init_db()


# =========================================================
# APPLICATION
# =========================================================

app = (
    Application.builder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

app.add_handler(
    CommandHandler(
        "admin",
        admin_command
    )
)

app.add_handler(
    CallbackQueryHandler(
        callback_handler
    )
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

app.add_error_handler(
    error_handler
)

print("🚀 BOT STARTED")

app.run_polling()
