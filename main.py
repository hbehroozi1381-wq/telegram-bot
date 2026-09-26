import os
import hashlib
import secrets
import asyncio
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters,
)

# =========================================================
# CONFIG
# =========================================================
TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "888720947"))
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "123456")

DB_POOL = None
PAGE_SIZE = 8
CANCEL_WORDS = {"Ù„ØºÙˆ", "Ø§Ù†ØµØ±Ø§Ù", "cancel", "Cancel"}
CANCEL_HINT = "\n\n(Ø¨Ø±Ø§ÛŒ Ù„ØºÙˆ Ø¨Ù†ÙˆÛŒØ³: Ù„ØºÙˆ)"

STATUS_LABELS = {
    "waiting_payment": "â³ Ù…Ù†ØªØ¸Ø± Ù¾Ø±Ø¯Ø§Ø®Øª",
    "waiting_admin": "ðŸ”Ž Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø¯Ù…ÛŒÙ†",
    "paid": "âœ… Ù¾Ø±Ø¯Ø§Ø®Øª ØªØ£ÛŒÛŒØ¯ Ø´Ø¯",
    "rejected": "âŒ Ù¾Ø±Ø¯Ø§Ø®Øª Ø±Ø¯ Ø´Ø¯",
    "shipped": "ðŸšš Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯",
    "completed": "ðŸ ØªÚ©Ù…ÛŒÙ„ Ø´Ø¯",
}

FIELD_PROMPTS = {
    "name": "ðŸ‘Ÿ Ù†Ø§Ù… Ø¬Ø¯ÛŒØ¯ Ù…Ø­ØµÙˆÙ„ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:",
    "description": "ðŸ“ ØªÙˆØ¶ÛŒØ­Ø§Øª Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†Ø› Ø§Ú¯Ø± Ù†Ø¯Ø§Ø±ÛŒ Ø¨Ù†ÙˆÛŒØ³: Ù†Ø¯Ø§Ø±Ø¯",
    "price": "ðŸ’° Ù‚ÛŒÙ…Øª Ø§ØµÙ„ÛŒ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ÙˆØ§Ø±Ø¯ Ú©Ù†:",
    "sale": "ðŸ”¥ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†Ø› Ø§Ú¯Ø± Ù†Ø¯Ø§Ø±Ø¯ 0:",
    "sizes": "ðŸ“ Ø³Ø§ÛŒØ²Ù‡Ø§ÛŒ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø¨Ø§ Ú©Ø§Ù…Ø§ Ø¬Ø¯Ø§ Ú©Ù†Ø› Ù…Ø«Ø§Ù„ 40,41,42:",
    "stock": "ðŸ“¦ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†:",
    "category": "ðŸ‘Ÿ Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ/Ú©Ø§Ø±Ø¨Ø±Ø¯ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø¨Ù†ÙˆÛŒØ³:",
    "keywords": "ðŸ”Ž Ú©Ù„Ù…Ø§Øª Ø¬Ø³ØªØ¬ÙˆÛŒ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø¨Ø§ Ú©Ø§Ù…Ø§ Ø¨Ù†ÙˆÛŒØ³:",
}

FIELD_LABELS = {
    "name": "âœï¸ Ù†Ø§Ù…",
    "description": "ðŸ“ ØªÙˆØ¶ÛŒØ­Ø§Øª",
    "price": "ðŸ’° Ù‚ÛŒÙ…Øª",
    "sale": "ðŸ”¥ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬",
    "sizes": "ðŸ“ Ø³Ø§ÛŒØ²Ù‡Ø§",
    "stock": "ðŸ“¦ Ù…ÙˆØ¬ÙˆØ¯ÛŒ",
    "category": "ðŸ‘Ÿ Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ",
    "keywords": "ðŸ”Ž Ú©Ù„Ù…Ø§Øª Ø¬Ø³ØªØ¬Ùˆ",
}


# =========================================================
# DATABASE
# =========================================================
async def db():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return DB_POOL


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    if not stored:
        return False
    if "$" in stored:
        salt, _ = stored.split("$", 1)
        return hash_password(password, salt) == stored
    # Ø³Ø§Ø²Ú¯Ø§Ø±ÛŒ Ø¨Ø§ Ù†ØµØ¨â€ŒÙ‡Ø§ÛŒ Ù‚Ø¯ÛŒÙ…ÛŒ Ú©Ù‡ Ø±Ù…Ø² Ø±Ø§ Ø¨Ø§ SHA-256 Ø³Ø§Ø¯Ù‡ Ø°Ø®ÛŒØ±Ù‡ Ú©Ø±Ø¯Ù‡ Ø¨ÙˆØ¯Ù†Ø¯
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored


async def init_db():
    pool = await db()
    async with pool.acquire() as conn:
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
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                brand_id INTEGER REFERENCES brands(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                price BIGINT DEFAULT 0 CHECK(price >= 0),
                sale_price BIGINT DEFAULT 0 CHECK(sale_price >= 0),
                sizes TEXT DEFAULT '',
                stock INTEGER DEFAULT 0 CHECK(stock >= 0),
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
                quantity INTEGER DEFAULT 1 CHECK(quantity > 0),
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
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
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

        # Ø§ÛŒÙ†Ø¯Ú©Ø³â€ŒÙ‡Ø§ÛŒ Ù…ÙˆØ±Ø¯ Ù†ÛŒØ§Ø² - migration-safe Ùˆ Ø¨Ø¯ÙˆÙ† Ø­Ø°Ù Ø§Ø·Ù„Ø§Ø¹Ø§Øª
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_id);
            CREATE INDEX IF NOT EXISTS idx_products_active ON products(active);
            CREATE INDEX IF NOT EXISTS idx_cart_telegram ON cart_items(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_orders_telegram ON orders(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id);
            CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
        """)

        defaults = {
            "card_number": "",
            "shipping_cost": "0",
            "support_text": "ðŸ“ž Ø¨Ø±Ø§ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø¨Ø§ Ù…Ø§ Ø¯Ø± Ø§Ø±ØªØ¨Ø§Ø· Ø¨Ø§Ø´ÛŒØ¯.",
            "welcome_text": "ðŸ‘Ÿ Ø¨Ù‡ ÙØ±ÙˆØ´Ú¯Ø§Ù‡ Ú©ÙØ´ Ùˆ Ú©ØªÙˆÙ†ÛŒ Ø®ÙˆØ´ Ø¢Ù…Ø¯ÛŒØ¯!\n\nØ§Ø² Ù…Ù†ÙˆÛŒ Ø²ÛŒØ± Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯:",
            "admin_password": hash_password(DEFAULT_ADMIN_PASSWORD),
        }
        for key, value in defaults.items():
            await conn.execute("""
                INSERT INTO settings(key,value) VALUES($1,$2)
                ON CONFLICT(key) DO NOTHING
            """, key, value)

    print("âœ… DATABASE READY")


async def setting(key):
    pool = await db()
    async with pool.acquire() as conn:
        return (await conn.fetchval("SELECT value FROM settings WHERE key=$1", key)) or ""


async def set_setting(key, value):
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings(key,value) VALUES($1,$2)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """, key, value)


# =========================================================
# HELPERS
# =========================================================
def is_admin(user_id):
    return user_id == ADMIN_ID


def is_logged(context):
    return bool(
        context.user_data.get("admin_logged") is True
        and context.user_data.get("admin_id") == ADMIN_ID
    )


def back_button(callback="home"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data=callback)]])


def pagination_row(prefix, offset, has_more):
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton("â¬…ï¸ Ù‚Ø¨Ù„ÛŒ", callback_data=f"{prefix}:{max(0, offset - PAGE_SIZE)}"))
    if has_more:
        row.append(InlineKeyboardButton("âž¡ï¸ Ø¨Ø¹Ø¯ÛŒ", callback_data=f"{prefix}:{offset + PAGE_SIZE}"))
    return row


async def safe_edit(query, text, reply_markup=None, parse_mode=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            try:
                await query.message.chat.send_message(text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e2:
                print("SAFE_EDIT ERROR:", e2)
    except Exception as e:
        print("SAFE_EDIT ERROR:", e)


def admin_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ“¦ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="adm_products")],
        [InlineKeyboardButton("ðŸ· Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ø±Ù†Ø¯Ù‡Ø§", callback_data="adm_brands")],
        [InlineKeyboardButton("ðŸ§¾ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§", callback_data="adm_orders")],
        [InlineKeyboardButton("ðŸ‘¥ Ø§Ø¹Ø¶Ø§ÛŒ Ø±Ø¨Ø§Øª", callback_data="adm_members")],
        [InlineKeyboardButton("ðŸ“Š Ø¢Ù…Ø§Ø± ÙØ±ÙˆØ´Ú¯Ø§Ù‡", callback_data="adm_stats")],
        [InlineKeyboardButton("ðŸ“¢ Ù¾ÛŒØ§Ù… Ù‡Ù…Ú¯Ø§Ù†ÛŒ", callback_data="adm_broadcast")],
        [InlineKeyboardButton("âš™ï¸ ØªÙ†Ø¸ÛŒÙ…Ø§Øª ÙØ±ÙˆØ´Ú¯Ø§Ù‡", callback_data="adm_settings")],
        [InlineKeyboardButton("ðŸ”‘ ØªØºÛŒÛŒØ± Ø±Ù…Ø²", callback_data="adm_password")],
        [InlineKeyboardButton("ðŸšª Ø®Ø±ÙˆØ¬", callback_data="adm_logout")],
    ])


async def save_user(update):
    user = update.effective_user
    if not user:
        return
    pool = await db()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users(telegram_id,username,first_name)
            VALUES($1,$2,$3)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name
        """, user.id, user.username, user.first_name)


async def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ› Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="products"), InlineKeyboardButton("ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯", callback_data="cart")],
        [InlineKeyboardButton("ðŸ“¦ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§ÛŒ Ù…Ù†", callback_data="orders"), InlineKeyboardButton("ðŸ”Ž Ø¬Ø³ØªØ¬Ùˆ", callback_data="search")],
        [InlineKeyboardButton("ðŸ“ž Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ", callback_data="support")],
    ])


# =========================================================
# START
# =========================================================
async def start(update, context):
    await save_user(update)
    context.user_data.clear()
    welcome = await setting("welcome_text")
    await update.message.reply_text(welcome, reply_markup=await main_menu())


# =========================================================
# CUSTOMER PRODUCTS
# =========================================================
async def products_menu(query):
    pool = await db()
    async with pool.acquire() as conn:
        brands = await conn.fetch("SELECT id,name FROM brands WHERE active=TRUE ORDER BY name")
    keyboard = [[InlineKeyboardButton("ðŸ”¥ Ø­Ø±Ø§Ø¬", callback_data="sale")]]
    row = []
    for b in brands:
        row.append(InlineKeyboardButton(f"ðŸ· {b['name']}", callback_data=f"brand:{b['id']}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data="home")])
    await safe_edit(query, "ðŸ› Ù…Ø­ØµÙˆÙ„Ø§Øª ÙØ±ÙˆØ´Ú¯Ø§Ù‡\n\nðŸ”¥ Ø­Ø±Ø§Ø¬\nðŸ· Ø¨Ø±Ù†Ø¯ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯:", InlineKeyboardMarkup(keyboard))


async def brand_products(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        brand = await conn.fetchrow("SELECT name FROM brands WHERE id=$1 AND active=TRUE", brand_id)
        products = await conn.fetch("""
            SELECT id,name,price,sale_price FROM products
            WHERE brand_id=$1 AND active=TRUE AND stock>0 ORDER BY id DESC
        """, brand_id)
    if not brand:
        await safe_edit(query, "âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.", back_button("products")); return
    if not products:
        await safe_edit(query, f"ðŸ· {brand['name']}\n\nÙØ¹Ù„Ø§Ù‹ Ù…Ø­ØµÙˆÙ„ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ù†Ø¯Ø§Ø±Ø¯.", back_button("products")); return
    keyboard = []
    for p in products:
        price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
        prefix = "ðŸ”¥" if price != p["price"] else "ðŸ‘Ÿ"
        keyboard.append([InlineKeyboardButton(f"{prefix} {p['name']} | {price:,} ØªÙˆÙ…Ø§Ù†", callback_data=f"product:{p['id']}")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ù†Ø¯Ù‡Ø§", callback_data="products")])
    await safe_edit(query, f"ðŸ· {brand['name']}\n\nÙ…Ø¯Ù„ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯:", InlineKeyboardMarkup(keyboard))


async def sale_products(query):
    pool = await db()
    async with pool.acquire() as conn:
        products = await conn.fetch("""
            SELECT p.id,p.name,p.sale_price FROM products p
            LEFT JOIN brands b ON b.id=p.brand_id
            WHERE p.active=TRUE AND p.stock>0 AND p.sale_price>0 AND p.sale_price<p.price
                AND (b.id IS NULL OR b.active=TRUE)
            ORDER BY p.id DESC
        """)
    if not products:
        await safe_edit(query, "ðŸ”¥ Ø­Ø±Ø§Ø¬\n\nÙØ¹Ù„Ø§Ù‹ Ù…Ø­ØµÙˆÙ„ÛŒ Ø¯Ø± Ø­Ø±Ø§Ø¬ Ù†ÛŒØ³Øª.", back_button("products")); return
    keyboard = [[InlineKeyboardButton(f"ðŸ”¥ {p['name']} | {p['sale_price']:,} ØªÙˆÙ…Ø§Ù†", callback_data=f"product:{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="products")])
    await safe_edit(query, "ðŸ”¥ Ù…Ø­ØµÙˆÙ„Ø§Øª Ø­Ø±Ø§Ø¬:", InlineKeyboardMarkup(keyboard))


async def product_details(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("""
            SELECT p.*, b.name AS brand_name, b.active AS brand_active
            FROM products p LEFT JOIN brands b ON b.id=p.brand_id
            WHERE p.id=$1 AND p.active=TRUE
        """, product_id)
        images = await conn.fetch("SELECT file_id FROM product_images WHERE product_id=$1 ORDER BY position LIMIT 5", product_id) if product else []
    if not product or product["brand_active"] is False:
        await safe_edit(query, "âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯ ÛŒØ§ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.", back_button("products")); return
    price = product["sale_price"] if 0 < product["sale_price"] < product["price"] else product["price"]
    price_text = f"ðŸ’° Ù‚ÛŒÙ…Øª: {price:,} ØªÙˆÙ…Ø§Ù†"
    if price != product["price"]:
        price_text = f"ðŸ’° Ù‚ÛŒÙ…Øª Ø§ØµÙ„ÛŒ: {product['price']:,} ØªÙˆÙ…Ø§Ù†\nðŸ”¥ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬: {price:,} ØªÙˆÙ…Ø§Ù†"
    text = (f"ðŸ‘Ÿ {product['name']}\n\nðŸ· Ø¨Ø±Ù†Ø¯: {product['brand_name'] or '---'}\n{price_text}\n"
            f"ðŸ“ Ø³Ø§ÛŒØ²Ù‡Ø§: {product['sizes'] or '---'}\nðŸ“¦ Ù…ÙˆØ¬ÙˆØ¯ÛŒ: {product['stock']}\n\n{product['description'] or ''}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ›’ Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ù‡ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯", callback_data=f"buy:{product_id}")],
        [InlineKeyboardButton("ðŸ”™ Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="products")],
    ])
    if images:
        try:
            await query.message.delete()
            for i, image in enumerate(images):
                await query.message.chat.send_photo(
                    photo=image["file_id"],
                    caption=text if i == 0 else None,
                    reply_markup=markup if i == 0 else None,
                )
            return
        except Exception as e:
            print("PHOTO ERROR:", e)
    await safe_edit(query, text, markup)


# =========================================================
# CART / CHECKOUT
# =========================================================
async def add_to_cart(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("""
            SELECT p.*, (b.id IS NULL OR b.active) AS brand_ok FROM products p
            LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=$1 AND p.active=TRUE
        """, product_id)
    if not product or not product["brand_ok"]:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯ ÛŒØ§ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.", show_alert=True); return
    if product["stock"] <= 0:
        await query.answer("âŒ Ø§ÛŒÙ† Ù…Ø­ØµÙˆÙ„ Ù†Ø§Ù…ÙˆØ¬ÙˆØ¯ Ø§Ø³Øª.", show_alert=True); return
    sizes = [x.strip() for x in (product["sizes"] or "").split(",") if x.strip()]
    if len(sizes) > 1:
        keyboard = [[InlineKeyboardButton(f"ðŸ“ Ø³Ø§ÛŒØ² {s}", callback_data=f"addsize:{product_id}:{s}")] for s in sizes]
        keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data=f"product:{product_id}")])
        await safe_edit(query, "ðŸ“ Ø³Ø§ÛŒØ² Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯:", InlineKeyboardMarkup(keyboard)); return
    await insert_cart(query, product_id, sizes[0] if sizes else "")


async def insert_cart(query, product_id, size):
    telegram_id = query.from_user.id
    pool = await db()
    product = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            product = await conn.fetchrow("""
                SELECT p.name,p.stock,(b.id IS NULL OR b.active) AS brand_ok FROM products p
                LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=$1 AND p.active=TRUE FOR UPDATE OF p
            """, product_id)
            if not product or not product["brand_ok"]:
                await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.", show_alert=True); return
            current = await conn.fetchval(
                "SELECT quantity FROM cart_items WHERE telegram_id=$1 AND product_id=$2 AND size=$3",
                telegram_id, product_id, size,
            ) or 0
            if current >= product["stock"]:
                await query.answer("âŒ Ø¨ÛŒØ´ØªØ± Ø§Ø² Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ù†Ù…ÛŒâ€ŒØªÙˆØ§Ù†ÛŒ Ø§Ø¶Ø§ÙÙ‡ Ú©Ù†ÛŒ.", show_alert=True); return
            await conn.execute("""
                INSERT INTO cart_items(telegram_id,product_id,size,quantity) VALUES($1,$2,$3,1)
                ON CONFLICT(telegram_id,product_id,size) DO UPDATE SET quantity=cart_items.quantity+1
            """, telegram_id, product_id, size)
    await safe_edit(query, f"âœ… {product['name']}\n\nØ¨Ù‡ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø§Ø¶Ø§ÙÙ‡ Ø´Ø¯.", InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯", callback_data="cart")],
        [InlineKeyboardButton("ðŸ› Ø§Ø¯Ø§Ù…Ù‡ Ø®Ø±ÛŒØ¯", callback_data="products")],
    ]))


async def show_cart(query):
    pool = await db()
    async with pool.acquire() as conn:
        items = await conn.fetch("""
            SELECT c.id,c.product_id,c.size,c.quantity,p.name,p.price,p.sale_price,p.stock,p.active,
                   (b.id IS NULL OR b.active) AS brand_ok
            FROM cart_items c JOIN products p ON p.id=c.product_id
            LEFT JOIN brands b ON b.id=p.brand_id
            WHERE c.telegram_id=$1 ORDER BY c.id
        """, query.from_user.id)
    if not items:
        await safe_edit(query, "ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª.", back_button("home")); return
    total = 0
    text = "ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø´Ù…Ø§:\n\n"
    keyboard = []
    valid_count = 0
    for item in items:
        if not item["active"] or not item["brand_ok"] or item["stock"] <= 0:
            continue
        qty = min(item["quantity"], item["stock"])
        price = item["sale_price"] if 0 < item["sale_price"] < item["price"] else item["price"]
        subtotal = price * qty
        total += subtotal
        valid_count += 1
        text += f"ðŸ‘Ÿ {item['name']}\nðŸ“ Ø³Ø§ÛŒØ²: {item['size'] or '---'}\nðŸ”¢ ØªØ¹Ø¯Ø§Ø¯: {qty}\nðŸ’° {subtotal:,} ØªÙˆÙ…Ø§Ù†\n\n"
        keyboard.append([
            InlineKeyboardButton("âž–", callback_data=f"cart_dec:{item['id']}"),
            InlineKeyboardButton(f"{qty} Ø¹Ø¯Ø¯", callback_data="cart_noop"),
            InlineKeyboardButton("âž•", callback_data=f"cart_inc:{item['id']}"),
            InlineKeyboardButton("ðŸ—‘", callback_data=f"cart_del:{item['id']}"),
        ])
    if valid_count == 0:
        await safe_edit(query, "ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª ÛŒØ§ Ù…Ø­ØµÙˆÙ„Ø§Øª Ø¢Ù† Ø¯ÛŒÚ¯Ø± Ù…ÙˆØ¬ÙˆØ¯ Ù†ÛŒØ³ØªÙ†Ø¯.", back_button("home")); return
    shipping = int(await setting("shipping_cost") or 0)
    final_total = total + shipping
    text += f"ðŸ› Ø¬Ù…Ø¹ Ú©Ø§Ù„Ø§Ù‡Ø§: {total:,} ØªÙˆÙ…Ø§Ù†\nðŸšš Ø§Ø±Ø³Ø§Ù„: {shipping:,} ØªÙˆÙ…Ø§Ù†\nðŸ’µ Ù…Ø¨Ù„Øº Ù†Ù‡Ø§ÛŒÛŒ: {final_total:,} ØªÙˆÙ…Ø§Ù†"
    keyboard.append([InlineKeyboardButton("ðŸ“¦ Ø«Ø¨Øª Ø³ÙØ§Ø±Ø´", callback_data="checkout")])
    keyboard.append([InlineKeyboardButton("ðŸ› Ø§Ø¯Ø§Ù…Ù‡ Ø®Ø±ÛŒØ¯", callback_data="products")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data="home")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def cart_change_qty(query, cart_id, delta):
    telegram_id = query.from_user.id
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT c.id,c.quantity,p.stock FROM cart_items c JOIN products p ON p.id=c.product_id
                WHERE c.id=$1 AND c.telegram_id=$2 FOR UPDATE OF c
            """, cart_id, telegram_id)
            if not row:
                await query.answer("âŒ Ø¢ÛŒØªÙ… Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
            new_qty = row["quantity"] + delta
            if new_qty <= 0:
                await conn.execute("DELETE FROM cart_items WHERE id=$1", cart_id)
            elif new_qty > row["stock"]:
                await query.answer("âŒ Ø¨ÛŒØ´ØªØ± Ø§Ø² Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§Ù…Ú©Ø§Ù†â€ŒÙ¾Ø°ÛŒØ± Ù†ÛŒØ³Øª.", show_alert=True); return
            else:
                await conn.execute("UPDATE cart_items SET quantity=$1 WHERE id=$2", new_qty, cart_id)
    await query.answer()
    await show_cart(query)


async def cart_remove(query, cart_id):
    telegram_id = query.from_user.id
    pool = await db()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval("DELETE FROM cart_items WHERE id=$1 AND telegram_id=$2 RETURNING id", cart_id, telegram_id)
    if not deleted:
        await query.answer("âŒ Ø¢ÛŒØªÙ… Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("ðŸ—‘ Ø­Ø°Ù Ø´Ø¯.")
    await show_cart(query)


async def checkout_start(query, context):
    pool = await db()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM cart_items WHERE telegram_id=$1", query.from_user.id)
    if not count:
        await safe_edit(query, "ðŸ›’ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª.", back_button("home")); return
    context.user_data["state"] = "customer_name"
    await safe_edit(query, "ðŸ‘¤ Ù†Ø§Ù… Ùˆ Ù†Ø§Ù… Ø®Ø§Ù†ÙˆØ§Ø¯Ú¯ÛŒ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯:" + CANCEL_HINT, None)


async def checkout_message(update, context):
    state = context.user_data.get("state")
    text = update.message.text.strip()
    if state == "customer_name":
        if len(text) < 3:
            await update.message.reply_text("âŒ Ù†Ø§Ù… Ø±Ø§ Ú©Ø§Ù…Ù„ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯."); return
        context.user_data["customer_name"] = text
        context.user_data["state"] = "phone"
        await update.message.reply_text("ðŸ“± Ø´Ù…Ø§Ø±Ù‡ Ù…ÙˆØ¨Ø§ÛŒÙ„ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯:" + CANCEL_HINT); return
    if state == "phone":
        if len(text) < 7:
            await update.message.reply_text("âŒ Ø´Ù…Ø§Ø±Ù‡ Ù…ÙˆØ¨Ø§ÛŒÙ„ Ù…Ø¹ØªØ¨Ø± ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯."); return
        context.user_data["phone"] = text
        context.user_data["state"] = "address"
        await update.message.reply_text("ðŸ“ Ø¢Ø¯Ø±Ø³ Ú©Ø§Ù…Ù„ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯:" + CANCEL_HINT); return
    if state == "address":
        if len(text) < 10:
            await update.message.reply_text("âŒ Ø¢Ø¯Ø±Ø³ Ø±Ø§ Ú©Ø§Ù…Ù„â€ŒØªØ± ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯."); return
        context.user_data["address"] = text
        context.user_data["state"] = "postal"
        await update.message.reply_text("ðŸ“® Ú©Ø¯ Ù¾Ø³ØªÛŒ Û±Û° Ø±Ù‚Ù…ÛŒ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯:" + CANCEL_HINT); return
    if state == "postal":
        postal = "".join(x for x in text if x.isdigit())
        if len(postal) != 10:
            await update.message.reply_text("âŒ Ú©Ø¯ Ù¾Ø³ØªÛŒ Ø¨Ø§ÛŒØ¯ Û±Û° Ø±Ù‚Ù… Ø¨Ø§Ø´Ø¯."); return
        context.user_data["postal_code"] = postal
        context.user_data["state"] = None
        await create_order(update, context)


async def create_order(update, context):
    telegram_id = update.effective_user.id
    pool = await db()
    order_id = None
    final_total = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            items = await conn.fetch("""
                SELECT c.product_id,c.size,c.quantity,p.name,p.price,p.sale_price,p.stock,p.active,
                       (b.id IS NULL OR b.active) AS brand_ok
                FROM cart_items c JOIN products p ON p.id=c.product_id
                LEFT JOIN brands b ON b.id=p.brand_id
                WHERE c.telegram_id=$1 FOR UPDATE OF p
            """, telegram_id)
            if not items:
                await update.message.reply_text("âŒ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª."); return
            total = 0
            for item in items:
                if not item["active"] or not item["brand_ok"] or item["stock"] < item["quantity"]:
                    await update.message.reply_text(
                        f"âŒ Â«{item['name']}Â» Ø¯ÛŒÚ¯Ø± Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª ÛŒØ§ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©Ø§ÙÛŒ Ù†Ø¯Ø§Ø±Ø¯.\nÙ„Ø·ÙØ§Ù‹ Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ø±Ø§ Ø§ØµÙ„Ø§Ø­ Ú©Ù†."
                    )
                    return
                price = item["sale_price"] if 0 < item["sale_price"] < item["price"] else item["price"]
                total += price * item["quantity"]
            shipping = int(await conn.fetchval("SELECT value FROM settings WHERE key='shipping_cost'") or 0)
            final_total = total + shipping
            order_id = await conn.fetchval("""
                INSERT INTO orders(telegram_id,customer_name,phone,address,postal_code,shipping_cost,total,status)
                VALUES($1,$2,$3,$4,$5,$6,$7,'waiting_payment') RETURNING id
            """, telegram_id, context.user_data["customer_name"], context.user_data["phone"],
                context.user_data["address"], context.user_data["postal_code"], shipping, final_total)
            for item in items:
                price = item["sale_price"] if 0 < item["sale_price"] < item["price"] else item["price"]
                await conn.execute("""
                    INSERT INTO order_items(order_id,product_id,product_name,size,quantity,price)
                    VALUES($1,$2,$3,$4,$5,$6)
                """, order_id, item["product_id"], item["name"], item["size"], item["quantity"], price)
                await conn.execute("UPDATE products SET stock=stock-$1 WHERE id=$2", item["quantity"], item["product_id"])
            await conn.execute("DELETE FROM cart_items WHERE telegram_id=$1", telegram_id)
    if order_id is None:
        return
    card = await setting("card_number")
    payment = f"ðŸ’³ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª:\n`{card}`\n\n" if card else "âš ï¸ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª Ù‡Ù†ÙˆØ² Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.\n\n"
    await update.message.reply_text(
        f"âœ… Ø³ÙØ§Ø±Ø´ Ø´Ù…Ø§ Ø«Ø¨Øª Ø´Ø¯.\n\nðŸ§¾ Ø´Ù…Ø§Ø±Ù‡ Ø³ÙØ§Ø±Ø´: #{order_id}\nðŸ’° Ù…Ø¨Ù„Øº Ù†Ù‡Ø§ÛŒÛŒ: {final_total:,} ØªÙˆÙ…Ø§Ù†\n\n"
        f"{payment}Ø¨Ø¹Ø¯ Ø§Ø² Ù¾Ø±Ø¯Ø§Ø®ØªØŒ Ø¹Ú©Ø³ Ø±Ø³ÛŒØ¯ Ø±Ø§ Ù‡Ù…ÛŒÙ†Ø¬Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯.",
        parse_mode="Markdown",
    )
    context.user_data["state"] = f"receipt:{order_id}"


# =========================================================
# RECEIPT / ORDERS
# =========================================================
async def receive_receipt(update, context):
    state = context.user_data.get("state", "")
    if not state.startswith("receipt:"):
        return
    if not update.message.photo:
        await update.message.reply_text("âŒ Ù„Ø·ÙØ§Ù‹ Ø¹Ú©Ø³ Ø±Ø³ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯."); return
    order_id = int(state.split(":")[1])
    file_id = update.message.photo[-1].file_id
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND telegram_id=$2", order_id, update.effective_user.id)
        if not order:
            await update.message.reply_text("âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯."); return
        await conn.execute("UPDATE orders SET receipt_file_id=$1,status='waiting_admin' WHERE id=$2", file_id, order_id)
    context.user_data["state"] = None
    await update.message.reply_text("ðŸ§¾ Ø±Ø³ÛŒØ¯ Ø¯Ø±ÛŒØ§ÙØª Ø´Ø¯.\n\nâ³ Ø¨Ø¹Ø¯ Ø§Ø² Ø¨Ø±Ø±Ø³ÛŒ Ù¾Ø±Ø¯Ø§Ø®ØªØŒ Ù†ØªÛŒØ¬Ù‡ Ø¨Ø±Ø§ÛŒ Ø´Ù…Ø§ Ø§Ø±Ø³Ø§Ù„ Ù…ÛŒâ€ŒØ´ÙˆØ¯.")
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(f"ðŸ§¾ Ø±Ø³ÛŒØ¯ Ø¬Ø¯ÛŒØ¯\n\nðŸ§¾ Ø³ÙØ§Ø±Ø´: #{order_id}\nðŸ’° Ù…Ø¨Ù„Øº: {order['total']:,} ØªÙˆÙ…Ø§Ù†\n"
                     f"ðŸ‘¤ Ù…Ø´ØªØ±ÛŒ: {order['customer_name']}\nðŸ“± ØªÙ„ÙÙ†: {order['phone']}\n"
                     f"ðŸ“ Ø¢Ø¯Ø±Ø³: {order['address']}\nðŸ“® Ú©Ø¯ Ù¾Ø³ØªÛŒ: {order['postal_code']}"),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("âœ… ØªØ£ÛŒÛŒØ¯ Ù¾Ø±Ø¯Ø§Ø®Øª", callback_data=f"adm_order_approve:{order_id}"),
                InlineKeyboardButton("âŒ Ø±Ø¯ Ù¾Ø±Ø¯Ø§Ø®Øª", callback_data=f"adm_order_reject:{order_id}"),
            ]]),
        )
    except Exception as e:
        print("ADMIN RECEIPT ERROR:", e)


async def customer_orders(query, offset=0):
    pool = await db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id,total,status FROM orders WHERE telegram_id=$1 ORDER BY id DESC OFFSET $2 LIMIT $3",
            query.from_user.id, offset, PAGE_SIZE + 1,
        )
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    if not rows and offset == 0:
        await safe_edit(query, "ðŸ“¦ Ù‡Ù†ÙˆØ² Ø³ÙØ§Ø±Ø´ÛŒ Ø«Ø¨Øª Ù†Ú©Ø±Ø¯Ù‡â€ŒØ§ÛŒØ¯.", back_button("home")); return
    keyboard = [[InlineKeyboardButton(
        f"ðŸ§¾ #{o['id']} | {STATUS_LABELS.get(o['status'], o['status'])} | {o['total']:,} ØªÙˆÙ…Ø§Ù†",
        callback_data=f"myorder:{o['id']}")] for o in rows]
    nav = pagination_row("myorders", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data="home")])
    await safe_edit(query, "ðŸ“¦ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§ÛŒ Ø´Ù…Ø§:", InlineKeyboardMarkup(keyboard))


async def customer_order_details(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND telegram_id=$2", order_id, query.from_user.id)
        items = await conn.fetch("SELECT * FROM order_items WHERE order_id=$1", order_id) if order else []
    if not order:
        await query.answer("âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    text = f"ðŸ§¾ Ø³ÙØ§Ø±Ø´ #{order_id}\n\n"
    for i in items:
        text += f"ðŸ‘Ÿ {i['product_name']}\nðŸ“ Ø³Ø§ÛŒØ²: {i['size'] or '---'}\nðŸ”¢ ØªØ¹Ø¯Ø§Ø¯: {i['quantity']}\nðŸ’° {i['price']:,} ØªÙˆÙ…Ø§Ù†\n\n"
    text += (f"ðŸšš Ø§Ø±Ø³Ø§Ù„: {order['shipping_cost']:,} ØªÙˆÙ…Ø§Ù†\nðŸ’µ Ù…Ø¬Ù…ÙˆØ¹: {order['total']:,} ØªÙˆÙ…Ø§Ù†\n"
             f"ðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {STATUS_LABELS.get(order['status'], order['status'])}")
    keyboard = []
    if order["status"] == "waiting_payment":
        keyboard.append([InlineKeyboardButton("ðŸ§¾ Ø§Ø±Ø³Ø§Ù„ Ø±Ø³ÛŒØ¯ Ù¾Ø±Ø¯Ø§Ø®Øª", callback_data=f"send_receipt:{order_id}")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§ÛŒ Ù…Ù†", callback_data="orders")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def send_receipt_start(query, context, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT status FROM orders WHERE id=$1 AND telegram_id=$2", order_id, query.from_user.id)
    if not order:
        await query.answer("âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    if order["status"] != "waiting_payment":
        await query.answer("âš ï¸ Ø§ÛŒÙ† Ø³ÙØ§Ø±Ø´ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø§Ø±Ø³Ø§Ù„ Ø±Ø³ÛŒØ¯ Ù†ÛŒØ³Øª.", show_alert=True); return
    context.user_data["state"] = f"receipt:{order_id}"
    await safe_edit(query, "ðŸ§¾ Ø¹Ú©Ø³ Ø±Ø³ÛŒØ¯ Ù¾Ø±Ø¯Ø§Ø®Øª Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:", None)


# =========================================================
# SEARCH
# =========================================================
async def start_search(query, context):
    context.user_data["state"] = "search"
    await safe_edit(query, "ðŸ”Ž Ø¬Ø³ØªØ¬ÙˆÛŒ Ù…Ø­ØµÙˆÙ„\n\nØ§Ø³Ù… Ù…Ø¯Ù„ØŒ Ø¨Ø±Ù†Ø¯ ÛŒØ§ Ú©Ø§Ø±Ø¨Ø±Ø¯ Ø±Ø§ Ø¨Ù†ÙˆÛŒØ³." + CANCEL_HINT, back_button("home"))


async def do_search(update, context):
    word = update.message.text.strip()
    if not word:
        await update.message.reply_text("âŒ Ú†ÛŒØ²ÛŒ ÙˆØ§Ø±Ø¯ Ù†Ú©Ø±Ø¯ÛŒ."); return
    context.user_data["state"] = None
    pool = await db()
    async with pool.acquire() as conn:
        products = await conn.fetch("""
            SELECT p.id,p.name,p.price,p.sale_price FROM products p
            LEFT JOIN brands b ON b.id=p.brand_id
            WHERE p.active=TRUE AND p.stock>0 AND (b.id IS NULL OR b.active=TRUE)
                AND (p.name ILIKE $1 OR p.description ILIKE $1 OR p.category ILIKE $1
                     OR p.keywords ILIKE $1 OR b.name ILIKE $1)
            ORDER BY p.id DESC LIMIT 30
        """, f"%{word}%")
    if not products:
        await update.message.reply_text(f"âŒ Ø¨Ø±Ø§ÛŒ Â«{word}Â» Ù…Ø­ØµÙˆÙ„ÛŒ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", reply_markup=await main_menu()); return
    keyboard = []
    for p in products:
        price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
        keyboard.append([InlineKeyboardButton(f"ðŸ‘Ÿ {p['name']} | {price:,} ØªÙˆÙ…Ø§Ù†", callback_data=f"product:{p['id']}")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù…Ù†ÙˆÛŒ Ø§ØµÙ„ÛŒ", callback_data="home")])
    await update.message.reply_text(f"ðŸ”Ž Ù†ØªØ§ÛŒØ¬ Ø¬Ø³ØªØ¬Ùˆ Ø¨Ø±Ø§ÛŒ Â«{word}Â»:", reply_markup=InlineKeyboardMarkup(keyboard))


# =========================================================
# CUSTOMER CALLBACK ROUTER
# =========================================================
async def customer_callback(query, context):
    data = query.data
    context.user_data["state"] = None

    if data == "home":
        welcome = await setting("welcome_text")
        await safe_edit(query, welcome, await main_menu())
    elif data == "products":
        await products_menu(query)
    elif data == "sale":
        await sale_products(query)
    elif data.startswith("brand:"):
        await brand_products(query, int(data.split(":")[1]))
    elif data.startswith("product:"):
        await product_details(query, int(data.split(":")[1]))
    elif data.startswith("buy:"):
        await add_to_cart(query, int(data.split(":")[1]))
    elif data.startswith("addsize:"):
        parts = data.split(":", 2)
        await insert_cart(query, int(parts[1]), parts[2])
    elif data == "cart":
        await show_cart(query)
    elif data.startswith("cart_inc:"):
        await cart_change_qty(query, int(data.split(":")[1]), 1)
    elif data.startswith("cart_dec:"):
        await cart_change_qty(query, int(data.split(":")[1]), -1)
    elif data.startswith("cart_del:"):
        await cart_remove(query, int(data.split(":")[1]))
    elif data == "cart_noop":
        pass
    elif data == "checkout":
        await checkout_start(query, context)
    elif data == "orders":
        await customer_orders(query, 0)
    elif data.startswith("myorders:"):
        await customer_orders(query, int(data.split(":")[1]))
    elif data.startswith("myorder:"):
        await customer_order_details(query, int(data.split(":")[1]))
    elif data.startswith("send_receipt:"):
        await send_receipt_start(query, context, int(data.split(":")[1]))
    elif data == "search":
        await start_search(query, context)
    elif data == "support":
        await safe_edit(query, await setting("support_text"), back_button("home"))


# =========================================================
# ADMIN LOGIN/PANEL
# =========================================================
async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("âŒ Ø´Ù…Ø§ Ø¯Ø³ØªØ±Ø³ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ù†Ø¯Ø§Ø±ÛŒØ¯."); return
    context.user_data.clear()
    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = "admin_password"
    await update.message.reply_text("ðŸ” Ø±Ù…Ø² Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯:")


async def admin_password(update, context):
    if not is_admin(update.effective_user.id) or context.user_data.get("state") != "admin_password":
        return
    entered = update.message.text.strip()
    stored = await setting("admin_password")
    if not verify_password(entered, stored):
        await update.message.reply_text("âŒ Ø±Ù…Ø² Ø§Ø´ØªØ¨Ø§Ù‡ Ø§Ø³Øª."); return
    if "$" not in stored:
        await set_setting("admin_password", hash_password(entered))
    context.user_data["admin_logged"] = True
    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = None
    await update.message.reply_text("ðŸ‘‘ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª ÙØ±ÙˆØ´Ú¯Ø§Ù‡\n\nØ§Ø² Ù…Ù†ÙˆÛŒ Ø²ÛŒØ± Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ù†:", reply_markup=admin_menu_markup())


async def admin_panel_callback(query, context):
    await safe_edit(query, "ðŸ‘‘ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª", admin_menu_markup())


# =========================================================
# ADMIN BRANDS
# =========================================================
async def admin_brands(query):
    pool = await db()
    async with pool.acquire() as conn:
        brands = await conn.fetch("""
            SELECT b.id,b.name,b.active,COUNT(p.id) AS product_count
            FROM brands b LEFT JOIN products p ON p.brand_id=b.id
            GROUP BY b.id ORDER BY b.id DESC
        """)
    keyboard = [[InlineKeyboardButton("âž• Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ø±Ù†Ø¯", callback_data="adm_add_brand")]]
    for b in brands:
        icon = "ðŸŸ¢" if b["active"] else "ðŸ”´"
        keyboard.append([InlineKeyboardButton(f"{icon} {b['name']} | {b['product_count']} Ù…Ø­ØµÙˆÙ„", callback_data=f"adm_brand:{b['id']}")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")])
    await safe_edit(query, "ðŸ· Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ø±Ù†Ø¯Ù‡Ø§:", InlineKeyboardMarkup(keyboard))


async def admin_brand_details(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT id,name,active FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await safe_edit(query, "âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", back_button("adm_brands")); return
    status = "ðŸŸ¢ ÙØ¹Ø§Ù„" if b["active"] else "ðŸ”´ ØºÛŒØ±ÙØ¹Ø§Ù„"
    keyboard = [
        [InlineKeyboardButton("âœï¸ ÙˆÛŒØ±Ø§ÛŒØ´ Ù†Ø§Ù…", callback_data=f"adm_brand_edit:{brand_id}")],
        [InlineKeyboardButton("ðŸ”´ ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ" if b["active"] else "ðŸŸ¢ ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ", callback_data=f"adm_brand_toggle:{brand_id}")],
        [InlineKeyboardButton("ðŸ—‘ Ø­Ø°Ù Ú©Ø§Ù…Ù„ Ø¨Ø±Ù†Ø¯", callback_data=f"adm_brand_delete:{brand_id}")],
        [InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ù†Ø¯Ù‡Ø§", callback_data="adm_brands")],
    ]
    await safe_edit(query, (
        f"ðŸ· Ø¨Ø±Ù†Ø¯: {b['name']}\n\nðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {status}\nðŸ“¦ ØªØ¹Ø¯Ø§Ø¯ Ù…Ø­ØµÙˆÙ„Ø§Øª: {count}\n\n"
        "âš ï¸ ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ø§Ù…Ù† Ø§Ø³Øª Ùˆ Ù…Ø­ØµÙˆÙ„Ø§Øª Ø±Ø§ Ø­Ø°Ù Ù†Ù…ÛŒâ€ŒÚ©Ù†Ø¯Ø› ÙÙ‚Ø· Ø§Ø² Ø¯ÛŒØ¯ Ù…Ø´ØªØ±ÛŒ Ù…Ø®ÙÛŒ Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯.\n"
        "ðŸ—‘ Ø­Ø°Ù Ú©Ø§Ù…Ù„ ÙÙ‚Ø· ÙˆÙ‚ØªÛŒ Ù…Ù…Ú©Ù† Ø§Ø³Øª Ú©Ù‡ Ù‡ÛŒÚ† Ù…Ø­ØµÙˆÙ„ÛŒ Ø¨Ù‡ Ø¨Ø±Ù†Ø¯ Ù…ØªØµÙ„ Ù†Ø¨Ø§Ø´Ø¯."
    ), InlineKeyboardMarkup(keyboard))


async def brand_edit_start(query, context, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT name FROM brands WHERE id=$1", brand_id)
    if not b:
        await query.answer("âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    context.user_data["state"] = f"edit_brand_name:{brand_id}"
    await safe_edit(query, f"âœï¸ Ù†Ø§Ù… ÙØ¹Ù„ÛŒ: {b['name']}\n\nÙ†Ø§Ù… Ø¬Ø¯ÛŒØ¯ Ø¨Ø±Ù†Ø¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, back_button(f"adm_brand:{brand_id}"))


async def brand_edit_message(update, context, state):
    brand_id = int(state.split(":", 1)[1])
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("âŒ Ù†Ø§Ù… Ø¨Ø±Ù†Ø¯ Ø®ÛŒÙ„ÛŒ Ú©ÙˆØªØ§Ù‡ Ø§Ø³Øª."); return
    pool = await db()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM brands WHERE LOWER(name)=LOWER($1) AND id<>$2", name, brand_id)
        if exists:
            await update.message.reply_text("âŒ Ø¨Ø±Ù†Ø¯ Ø¯ÛŒÚ¯Ø±ÛŒ Ø¨Ø§ Ø§ÛŒÙ† Ù†Ø§Ù… ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯."); return
        updated = await conn.fetchval("UPDATE brands SET name=$1 WHERE id=$2 RETURNING id", name, brand_id)
    context.user_data["state"] = None
    if not updated:
        await update.message.reply_text("âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯."); return
    await update.message.reply_text("âœ… Ù†Ø§Ù… Ø¨Ø±Ù†Ø¯ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø´Ø¯.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("ðŸ· Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ø¨Ø±Ù†Ø¯", callback_data=f"adm_brand:{brand_id}")]]))


async def toggle_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE brands SET active=NOT active WHERE id=$1 RETURNING name,active", brand_id)
    if not row:
        await query.answer("âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… ÙˆØ¶Ø¹ÛŒØª Ø¨Ø±Ù†Ø¯ ØªØºÛŒÛŒØ± Ú©Ø±Ø¯.")
    await admin_brand_details(query, brand_id)


async def confirm_brand_delete(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT name FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await query.answer("âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    if count:
        await query.answer(
            f"âŒ Ø§ÛŒÙ† Ø¨Ø±Ù†Ø¯ {count} Ù…Ø­ØµÙˆÙ„ Ù…ØªØµÙ„ Ø¯Ø§Ø±Ø¯. Ø§ÙˆÙ„ Ø¨Ø±Ù†Ø¯ Ø±Ø§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ù† ÛŒØ§ Ù…Ø­ØµÙˆÙ„Ø§ØªØ´ Ø±Ø§ Ø­Ø°Ù/ØªØºÛŒÛŒØ± Ø¨Ø±Ù†Ø¯ Ø¨Ø¯Ù‡Ø› "
            "ØªØ§ ÙˆÙ‚ØªÛŒ Ù…Ø­ØµÙˆÙ„ Ù…ØªØµÙ„ Ø¯Ø§Ø±Ø¯ Ø­Ø°Ù Ù†Ù…ÛŒâ€ŒØ´ÙˆØ¯.", show_alert=True
        )
        return
    await safe_edit(query, f"âš ï¸ Ø­Ø°Ù Ø¨Ø±Ù†Ø¯ Â«{b['name']}Â» Ù‚Ø·Ø¹ÛŒ Ø§Ø³Øª. Ø§Ø¯Ø§Ù…Ù‡ Ù…ÛŒâ€ŒØ¯Ù‡ÛŒØŸ", InlineKeyboardMarkup([
        [InlineKeyboardButton("âœ… Ø¨Ù„Ù‡ØŒ Ø­Ø°Ù Ø´ÙˆØ¯", callback_data=f"adm_brand_delete_confirm:{brand_id}")],
        [InlineKeyboardButton("âŒ Ù„ØºÙˆ", callback_data=f"adm_brand:{brand_id}")],
    ]))


async def delete_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id)
            if count:
                await query.answer("âŒ Ø§ÛŒÙ† Ø¨Ø±Ù†Ø¯ Ù‡Ù†ÙˆØ² Ù…Ø­ØµÙˆÙ„ Ù…ØªØµÙ„ Ø¯Ø§Ø±Ø¯.", show_alert=True); return
            deleted = await conn.fetchval("DELETE FROM brands WHERE id=$1 RETURNING name", brand_id)
    if not deleted:
        await query.answer("âŒ Ø¨Ø±Ù†Ø¯ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… Ø¨Ø±Ù†Ø¯ Ø­Ø°Ù Ø´Ø¯.")
    await admin_brands(query)


async def add_brand_start(query, context):
    context.user_data["state"] = "add_brand"
    await safe_edit(query, "ðŸ· Ù†Ø§Ù… Ø¨Ø±Ù†Ø¯ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, None)


async def add_brand(update, context):
    name = update.message.text.strip()
    if not name:
        return
    pool = await db()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM brands WHERE LOWER(name)=LOWER($1)", name)
        if exists:
            await update.message.reply_text("âŒ Ø§ÛŒÙ† Ø¨Ø±Ù†Ø¯ Ù‚Ø¨Ù„Ø§Ù‹ ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯."); return
        await conn.execute("INSERT INTO brands(name) VALUES($1)", name)
    context.user_data["state"] = None
    await update.message.reply_text(f"âœ… Ø¨Ø±Ù†Ø¯ Â«{name}Â» Ø§Ø¶Ø§ÙÙ‡ Ø´Ø¯.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("ðŸ· Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ø±Ù†Ø¯Ù‡Ø§", callback_data="adm_brands")]]))


# =========================================================
# ADMIN PRODUCTS - LIST / DETAILS / TOGGLE / DELETE
# =========================================================
async def admin_products(query, offset=0):
    pool = await db()
    async with pool.acquire() as conn:
        products = await conn.fetch("""
            SELECT p.id,p.name,p.active,p.stock FROM products p
            ORDER BY p.id DESC OFFSET $1 LIMIT $2
        """, offset, PAGE_SIZE + 1)
    has_more = len(products) > PAGE_SIZE
    products = products[:PAGE_SIZE]
    keyboard = [[InlineKeyboardButton("âž• Ø§ÙØ²ÙˆØ¯Ù† Ù…Ø­ØµÙˆÙ„", callback_data="adm_add_product")]]
    for p in products:
        icon = "ðŸŸ¢" if p["active"] else "ðŸ”´"
        keyboard.append([InlineKeyboardButton(f"{icon} {p['name']} | {p['stock']} Ø¹Ø¯Ø¯", callback_data=f"adm_product:{p['id']}")])
    nav = pagination_row("adm_products", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")])
    await safe_edit(query, "ðŸ“¦ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø­ØµÙˆÙ„Ø§Øª:", InlineKeyboardMarkup(keyboard))


async def admin_product_details(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT p.*,b.name AS brand FROM products p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=$1", product_id)
        image_count = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id) if p else 0
    if not p:
        await safe_edit(query, "âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", back_button("adm_products")); return
    status = "ðŸŸ¢ ÙØ¹Ø§Ù„" if p["active"] else "ðŸ”´ ØºÛŒØ±ÙØ¹Ø§Ù„"
    price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
    text = (f"ðŸ“¦ {p['name']}\n\nðŸ· Ø¨Ø±Ù†Ø¯: {p['brand'] or '---'}\nðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {status}\nðŸ’° Ù‚ÛŒÙ…Øª: {price:,} ØªÙˆÙ…Ø§Ù†\n"
            f"ðŸ“ Ø³Ø§ÛŒØ²: {p['sizes'] or '---'}\nðŸ“¦ Ù…ÙˆØ¬ÙˆØ¯ÛŒ: {p['stock']}\nðŸ–¼ Ø¹Ú©Ø³: {image_count}\n"
            f"ðŸ‘Ÿ Ø¯Ø³ØªÙ‡: {p['category'] or '---'}\nðŸ”Ž Ú©Ù„Ù…Ø§Øª: {p['keywords'] or '---'}")
    keyboard = [
        [InlineKeyboardButton("ðŸ”´ ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ" if p["active"] else "ðŸŸ¢ ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ", callback_data=f"adm_product_toggle:{product_id}")],
        [InlineKeyboardButton("âœï¸ ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø­ØµÙˆÙ„", callback_data=f"adm_pedit_menu:{product_id}")],
        [InlineKeyboardButton("ðŸ—‘ Ø­Ø°Ù Ú©Ø§Ù…Ù„ Ù…Ø­ØµÙˆÙ„", callback_data=f"adm_product_delete:{product_id}")],
        [InlineKeyboardButton("ðŸ”™ Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="adm_products")],
    ]
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def toggle_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("UPDATE products SET active=NOT active WHERE id=$1 RETURNING active", product_id)
    if not p:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… ÙˆØ¶Ø¹ÛŒØª Ù…Ø­ØµÙˆÙ„ ØªØºÛŒÛŒØ± Ú©Ø±Ø¯.")
    await admin_product_details(query, product_id)


async def confirm_product_delete(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT name FROM products WHERE id=$1", product_id)
        cart_count = await conn.fetchval("SELECT COUNT(*) FROM cart_items WHERE product_id=$1", product_id) if p else 0
        order_count = await conn.fetchval("SELECT COUNT(*) FROM order_items WHERE product_id=$1", product_id) if p else 0
    if not p:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    warn = ""
    if cart_count:
        warn += f"\nðŸ›’ Ø§ÛŒÙ† Ù…Ø­ØµÙˆÙ„ Ø¯Ø± {cart_count} Ø³Ø¨Ø¯ Ø®Ø±ÛŒØ¯ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø§Ø³ØªØ› Ø¨Ø§ Ø­Ø°ÙØŒ Ø§Ø² Ø³Ø¨Ø¯Ù‡Ø§ Ù‡Ù… Ø­Ø°Ù Ù…ÛŒâ€ŒØ´ÙˆØ¯."
    if order_count:
        warn += f"\nðŸ§¾ Ø§ÛŒÙ† Ù…Ø­ØµÙˆÙ„ Ø¯Ø± {order_count} Ø³ÙØ§Ø±Ø´ Ù‚Ø¨Ù„ÛŒ Ø«Ø¨Øª Ø´Ø¯Ù‡Ø› Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¢Ù† Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§ Ø­ÙØ¸ Ù…ÛŒâ€ŒØ´ÙˆØ¯."
    await safe_edit(query, f"âš ï¸ Ø­Ø°Ù Â«{p['name']}Â» Ùˆ ØªÙ…Ø§Ù… Ø¹Ú©Ø³â€ŒÙ‡Ø§ÛŒØ´ Ù‚Ø·Ø¹ÛŒ Ø§Ø³Øª.{warn}\n\nØ§Ø¯Ø§Ù…Ù‡ Ù…ÛŒâ€ŒØ¯Ù‡ÛŒØŸ", InlineKeyboardMarkup([
        [InlineKeyboardButton("âœ… Ø¨Ù„Ù‡ØŒ Ø­Ø°Ù Ø´ÙˆØ¯", callback_data=f"adm_product_delete_confirm:{product_id}")],
        [InlineKeyboardButton("âŒ Ù„ØºÙˆ", callback_data=f"adm_product:{product_id}")],
    ]))


async def delete_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval("DELETE FROM products WHERE id=$1 RETURNING name", product_id)
    if not deleted:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… Ù…Ø­ØµÙˆÙ„ Ùˆ Ø¹Ú©Ø³â€ŒÙ‡Ø§ÛŒØ´ Ø­Ø°Ù Ø´Ø¯Ù†Ø¯.")
    await admin_products(query)


# =========================================================
# ADMIN PRODUCTS - EDIT (fields / brand / images)
# =========================================================
async def product_edit_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT id,name FROM products WHERE id=$1", product_id)
    if not p:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    keyboard = [
        [InlineKeyboardButton(FIELD_LABELS["name"], callback_data=f"adm_pset:name:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["description"], callback_data=f"adm_pset:description:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["price"], callback_data=f"adm_pset:price:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["sale"], callback_data=f"adm_pset:sale:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["sizes"], callback_data=f"adm_pset:sizes:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["stock"], callback_data=f"adm_pset:stock:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["category"], callback_data=f"adm_pset:category:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["keywords"], callback_data=f"adm_pset:keywords:{product_id}")],
        [InlineKeyboardButton("ðŸ· ØªØºÛŒÛŒØ± Ø¨Ø±Ù†Ø¯", callback_data=f"adm_pbrand:{product_id}")],
        [InlineKeyboardButton("ðŸ–¼ Ù…Ø¯ÛŒØ±ÛŒØª Ø¹Ú©Ø³â€ŒÙ‡Ø§", callback_data=f"adm_pimages:{product_id}")],
        [InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª Ø¨Ù‡ Ù…Ø­ØµÙˆÙ„", callback_data=f"adm_product:{product_id}")],
    ]
    await safe_edit(query, f"âœï¸ ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø­ØµÙˆÙ„: {p['name']}\n\nÚ©Ø¯Ø§Ù… Ø¨Ø®Ø´ Ø±Ø§ ÙˆÛŒØ±Ø§ÛŒØ´ Ù…ÛŒâ€ŒÚ©Ù†ÛŒØŸ", InlineKeyboardMarkup(keyboard))


async def product_field_prompt(query, context, field, product_id):
    if field not in FIELD_PROMPTS:
        await query.answer("âŒ ÙÛŒÙ„Ø¯ Ù†Ø§Ù…Ø¹ØªØ¨Ø±.", show_alert=True); return
    context.user_data["state"] = f"pedit_{field}:{product_id}"
    await safe_edit(query, FIELD_PROMPTS[field] + CANCEL_HINT, back_button(f"adm_pedit_menu:{product_id}"))


async def product_edit_message(update, context, state):
    rest = state[len("pedit_"):]
    field, pid_str = rest.split(":", 1)
    product_id = int(pid_str)
    text = update.message.text.strip()
    pool = await db()
    if field == "name":
        if len(text) < 2:
            await update.message.reply_text("âŒ Ù†Ø§Ù… Ù…Ø­ØµÙˆÙ„ Ú©ÙˆØªØ§Ù‡ Ø§Ø³Øª."); return
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET name=$1 WHERE id=$2", text, product_id)
    elif field == "description":
        value = "" if text == "Ù†Ø¯Ø§Ø±Ø¯" else text
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET description=$1 WHERE id=$2", value, product_id)
    elif field == "price":
        try:
            value = int(text.replace(",", ""))
            assert value >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET price=$1 WHERE id=$2", value, product_id)
    elif field == "sale":
        try:
            value = int(text.replace(",", ""))
            assert value >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        async with pool.acquire() as conn:
            current_price = await conn.fetchval("SELECT price FROM products WHERE id=$1", product_id)
            if value and current_price is not None and value >= current_price:
                await update.message.reply_text("âŒ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬ Ø¨Ø§ÛŒØ¯ Ø§Ø² Ù‚ÛŒÙ…Øª Ø§ØµÙ„ÛŒ Ú©Ù…ØªØ± Ø¨Ø§Ø´Ø¯ ÛŒØ§ 0 Ø¨Ø§Ø´Ø¯."); return
            await conn.execute("UPDATE products SET sale_price=$1 WHERE id=$2", value, product_id)
    elif field == "sizes":
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET sizes=$1 WHERE id=$2", text, product_id)
    elif field == "stock":
        try:
            value = int(text)
            assert value >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET stock=$1 WHERE id=$2", value, product_id)
    elif field == "category":
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET category=$1 WHERE id=$2", text, product_id)
    elif field == "keywords":
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET keywords=$1 WHERE id=$2", text, product_id)
    else:
        return
    context.user_data["state"] = None
    await update.message.reply_text("âœ… Ù…Ø­ØµÙˆÙ„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø´Ø¯.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("ðŸ“¦ Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ù…Ø­ØµÙˆÙ„", callback_data=f"adm_product:{product_id}")]]))


async def product_brand_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT id FROM products WHERE id=$1", product_id)
        brands = await conn.fetch("SELECT id,name,active FROM brands ORDER BY name")
    if not p:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    if not brands:
        await query.answer("âŒ Ù‡ÛŒÚ† Ø¨Ø±Ù†Ø¯ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯Ø› Ø§ÙˆÙ„ ÛŒÚ© Ø¨Ø±Ù†Ø¯ Ø¨Ø³Ø§Ø².", show_alert=True); return
    keyboard = [[InlineKeyboardButton(("ðŸŸ¢ " if b["active"] else "ðŸ”´ ") + b["name"],
                                       callback_data=f"adm_pbrand_set:{b['id']}:{product_id}")] for b in brands]
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª", callback_data=f"adm_pedit_menu:{product_id}")])
    await safe_edit(query, "ðŸ· Ø¨Ø±Ù†Ø¯ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†:", InlineKeyboardMarkup(keyboard))


async def product_brand_set(query, brand_id, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        updated = await conn.fetchval("UPDATE products SET brand_id=$1 WHERE id=$2 RETURNING id", brand_id, product_id)
    if not updated:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… Ø¨Ø±Ù†Ø¯ Ù…Ø­ØµÙˆÙ„ ØªØºÛŒÛŒØ± Ú©Ø±Ø¯.")
    await admin_product_details(query, product_id)


async def product_images_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT name FROM products WHERE id=$1", product_id)
        images = await conn.fetch("SELECT id,file_id,position FROM product_images WHERE product_id=$1 ORDER BY position", product_id)
    if not p:
        await query.answer("âŒ Ù…Ø­ØµÙˆÙ„ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    try:
        await query.message.delete()
    except Exception:
        pass
    chat = query.message.chat
    for img in images:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ—‘ Ø­Ø°Ù Ø§ÛŒÙ† Ø¹Ú©Ø³", callback_data=f"adm_pimg_del:{img['id']}:{product_id}")]])
        try:
            await chat.send_photo(photo=img["file_id"], caption=f"Ø¹Ú©Ø³ Ø´Ù…Ø§Ø±Ù‡ {img['position']}", reply_markup=kb)
        except Exception as e:
            print("IMG SEND ERROR:", e)
    footer_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("âž• Ø§ÙØ²ÙˆØ¯Ù† Ø¹Ú©Ø³ Ø¬Ø¯ÛŒØ¯", callback_data=f"adm_pimg_add:{product_id}")],
        [InlineKeyboardButton("ðŸ”™ Ø¨Ø±Ú¯Ø´Øª Ø¨Ù‡ ÙˆÛŒØ±Ø§ÛŒØ´", callback_data=f"adm_pedit_menu:{product_id}")],
    ])
    await chat.send_message(f"ðŸ–¼ Ù…Ø¯ÛŒØ±ÛŒØª Ø¹Ú©Ø³â€ŒÙ‡Ø§ÛŒ Â«{p['name']}Â»\n\nØªØ¹Ø¯Ø§Ø¯ ÙØ¹Ù„ÛŒ: {len(images)} Ø§Ø² Ûµ", reply_markup=footer_kb)


async def product_image_delete(query, image_id, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id)
        if total <= 1:
            await query.answer("âŒ Ø­Ø¯Ø§Ù‚Ù„ ÛŒÚ© Ø¹Ú©Ø³ Ø¨Ø§ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ù…Ø­ØµÙˆÙ„ Ø¨Ø§Ù‚ÛŒ Ø¨Ù…Ø§Ù†Ø¯Ø› Ø§ÙˆÙ„ Ø¹Ú©Ø³ Ø¬Ø¯ÛŒØ¯ Ø§Ø¶Ø§ÙÙ‡ Ú©Ù†.", show_alert=True); return
        deleted = await conn.fetchval("DELETE FROM product_images WHERE id=$1 AND product_id=$2 RETURNING id", image_id, product_id)
    if not deleted:
        await query.answer("âŒ Ø¹Ú©Ø³ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
    await query.answer("âœ… Ø¹Ú©Ø³ Ø­Ø°Ù Ø´Ø¯.")
    try:
        await query.message.delete()
    except Exception:
        pass


async def product_image_add_start(query, context, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id)
    if count >= 5:
        await query.answer("âŒ Ø§ÛŒÙ† Ù…Ø­ØµÙˆÙ„ Ûµ Ø¹Ú©Ø³ Ø¯Ø§Ø±Ø¯Ø› Ø§ÙˆÙ„ ÛŒÚ©ÛŒ Ø±Ø§ Ø­Ø°Ù Ú©Ù†.", show_alert=True); return
    context.user_data["state"] = f"pedit_image_add:{product_id}"
    await query.answer()
    await query.message.reply_text("ðŸ–¼ Ø¹Ú©Ø³ Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT)


# =========================================================
# PRODUCT ADD (NEW)
# =========================================================
async def add_product_start(query, context):
    context.user_data["product"] = {}
    context.user_data["state"] = "product_name"
    await safe_edit(query, "ðŸ‘Ÿ Ù†Ø§Ù… Ù…Ø¯Ù„ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, None)


async def product_add_message(update, context):
    state = context.user_data.get("state")
    data = context.user_data.setdefault("product", {})
    if state == "product_name":
        name = update.message.text.strip()
        if len(name) < 2:
            await update.message.reply_text("âŒ Ù†Ø§Ù… Ù…Ø­ØµÙˆÙ„ Ú©ÙˆØªØ§Ù‡ Ø§Ø³Øª."); return
        data["name"] = name
        context.user_data["state"] = "product_brand"
        pool = await db()
        async with pool.acquire() as conn:
            brands = await conn.fetch("SELECT id,name FROM brands WHERE active=TRUE ORDER BY name")
        if not brands:
            context.user_data["state"] = None
            await update.message.reply_text("âŒ Ø§ÙˆÙ„ Ø­Ø¯Ø§Ù‚Ù„ ÛŒÚ© Ø¨Ø±Ù†Ø¯ ÙØ¹Ø§Ù„ Ø¨Ø³Ø§Ø².")
            return
        await update.message.reply_text("ðŸ· Ø¨Ø±Ù†Ø¯ Ù…Ø­ØµÙˆÙ„ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†:", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(b["name"], callback_data=f"adm_newbrand:{b['id']}")] for b in brands]))
        return
    if state == "product_description":
        data["description"] = "" if update.message.text.strip() == "Ù†Ø¯Ø§Ø±Ø¯" else update.message.text.strip()
        context.user_data["state"] = "product_price"
        await update.message.reply_text("ðŸ’° Ù‚ÛŒÙ…Øª Ø§ØµÙ„ÛŒ Ø±Ø§ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ÙˆØ§Ø±Ø¯ Ú©Ù†:" + CANCEL_HINT); return
    if state == "product_price":
        try:
            data["price"] = int(update.message.text.replace(",", ""))
            assert data["price"] >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        context.user_data["state"] = "product_sale"
        await update.message.reply_text("ðŸ”¥ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†Ø› Ø§Ú¯Ø± Ù†Ø¯Ø§Ø±Ø¯ 0:" + CANCEL_HINT); return
    if state == "product_sale":
        try:
            data["sale_price"] = int(update.message.text.replace(",", ""))
            assert data["sale_price"] >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        if data["sale_price"] and data["sale_price"] >= data["price"]:
            await update.message.reply_text("âŒ Ù‚ÛŒÙ…Øª Ø­Ø±Ø§Ø¬ Ø¨Ø§ÛŒØ¯ Ø§Ø² Ù‚ÛŒÙ…Øª Ø§ØµÙ„ÛŒ Ú©Ù…ØªØ± Ø¨Ø§Ø´Ø¯ ÛŒØ§ 0 Ø¨Ø§Ø´Ø¯."); return
        context.user_data["state"] = "product_sizes"
        await update.message.reply_text("ðŸ“ Ø³Ø§ÛŒØ²Ù‡Ø§ Ø±Ø§ Ø¨Ø§ Ú©Ø§Ù…Ø§ Ø¬Ø¯Ø§ Ú©Ù†Ø› Ù…Ø«Ø§Ù„ 40,41,42,43,44,45:" + CANCEL_HINT); return
    if state == "product_sizes":
        data["sizes"] = update.message.text.strip()
        context.user_data["state"] = "product_stock"
        await update.message.reply_text("ðŸ“¦ ØªØ¹Ø¯Ø§Ø¯ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©Ù„ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†:" + CANCEL_HINT); return
    if state == "product_stock":
        try:
            data["stock"] = int(update.message.text)
            assert data["stock"] >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ ØµØ­ÛŒØ­ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        context.user_data["state"] = "product_category"
        await update.message.reply_text("ðŸ‘Ÿ Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ/Ú©Ø§Ø±Ø¨Ø±Ø¯ Ù…Ø­ØµÙˆÙ„ Ø±Ø§ Ø¨Ù†ÙˆÛŒØ³:" + CANCEL_HINT); return
    if state == "product_category":
        data["category"] = update.message.text.strip()
        context.user_data["state"] = "product_keywords"
        await update.message.reply_text("ðŸ”Ž Ú©Ù„Ù…Ø§Øª Ø¬Ø³ØªØ¬Ùˆ Ø±Ø§ Ø¨Ø§ Ú©Ø§Ù…Ø§ Ø¨Ù†ÙˆÛŒØ³:" + CANCEL_HINT); return
    if state == "product_keywords":
        data["keywords"] = update.message.text.strip()
        data["images"] = []
        context.user_data["state"] = "product_images"
        await update.message.reply_text("ðŸ–¼ Ø¹Ú©Ø³â€ŒÙ‡Ø§ Ø±Ø§ ÛŒÚ©ÛŒâ€ŒÛŒÚ©ÛŒ Ø¨ÙØ±Ø³ØªØ› Ø­Ø¯Ø§Ú©Ø«Ø± Ûµ Ø¹Ú©Ø³. ÙˆÙ‚ØªÛŒ ØªÙ…Ø§Ù… Ø´Ø¯ Ø¨Ù†ÙˆÛŒØ³ Â«ØªÙ…Ø§Ù…Â»." + CANCEL_HINT); return
    if state == "product_images" and update.message.text and update.message.text.strip() == "ØªÙ…Ø§Ù…":
        await save_product(update, context); return


async def save_product(update, context):
    data = context.user_data.get("product", {})
    if not data.get("images"):
        await update.message.reply_text("âŒ Ø­Ø¯Ø§Ù‚Ù„ ÛŒÚ© Ø¹Ú©Ø³ Ø¨Ø±Ø§ÛŒ Ù…Ø­ØµÙˆÙ„ Ø¨ÙØ±Ø³Øª."); return
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            product_id = await conn.fetchval("""
                INSERT INTO products(brand_id,name,description,price,sale_price,sizes,stock,category,keywords)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id
            """, data.get("brand_id"), data["name"], data.get("description", ""), data["price"], data["sale_price"],
                data["sizes"], data["stock"], data.get("category", ""), data.get("keywords", ""))
            for pos, file_id in enumerate(data["images"][:5], 1):
                await conn.execute("INSERT INTO product_images(product_id,file_id,position) VALUES($1,$2,$3)", product_id, file_id, pos)
    name = data["name"]
    context.user_data.clear()
    await update.message.reply_text(
        f"âœ… Ù…Ø­ØµÙˆÙ„ Â«{name}Â» Ø§Ø¶Ø§ÙÙ‡ Ø´Ø¯.\n\nðŸ†” Ø´Ù…Ø§Ø±Ù‡ Ù…Ø­ØµÙˆÙ„: {product_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("ðŸ“¦ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø­ØµÙˆÙ„Ø§Øª", callback_data="adm_products")],
            [InlineKeyboardButton("ðŸ‘‘ Ù¾Ù†Ù„", callback_data="adm_panel")],
        ]),
    )


# =========================================================
# ADMIN ORDERS
# =========================================================
async def admin_orders(query, offset=0):
    pool = await db()
    async with pool.acquire() as conn:
        orders = await conn.fetch(
            "SELECT id,customer_name,total,status FROM orders ORDER BY id DESC OFFSET $1 LIMIT $2",
            offset, PAGE_SIZE + 1,
        )
    has_more = len(orders) > PAGE_SIZE
    orders = orders[:PAGE_SIZE]
    keyboard = [[InlineKeyboardButton(
        f"#{o['id']} | {o['customer_name']} | {o['total']:,} | {STATUS_LABELS.get(o['status'], o['status'])}",
        callback_data=f"adm_order:{o['id']}")] for o in orders]
    nav = pagination_row("adm_orders", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")])
    await safe_edit(query, "ðŸ§¾ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§ÛŒ ÙØ±ÙˆØ´Ú¯Ø§Ù‡:", InlineKeyboardMarkup(keyboard))


async def admin_order_details(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
        items = await conn.fetch("SELECT * FROM order_items WHERE order_id=$1", order_id) if order else []
    if not order:
        await safe_edit(query, "âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", back_button("adm_orders")); return
    text = (f"ðŸ§¾ Ø³ÙØ§Ø±Ø´ #{order_id}\n\nðŸ‘¤ {order['customer_name']}\nðŸ“± {order['phone']}\n"
            f"ðŸ“ {order['address']}\nðŸ“® {order['postal_code']}\n\n")
    for i in items:
        text += f"ðŸ‘Ÿ {i['product_name']}\nðŸ“ Ø³Ø§ÛŒØ²: {i['size'] or '---'}\nðŸ”¢ ØªØ¹Ø¯Ø§Ø¯: {i['quantity']}\nðŸ’° Ù‚ÛŒÙ…Øª ÙˆØ§Ø­Ø¯: {i['price']:,}\n\n"
    text += (f"ðŸšš Ø§Ø±Ø³Ø§Ù„: {order['shipping_cost']:,}\nðŸ’µ Ù…Ø¬Ù…ÙˆØ¹: {order['total']:,}\n"
             f"ðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {STATUS_LABELS.get(order['status'], order['status'])}")
    keyboard = []
    if order["status"] == "waiting_admin":
        keyboard.append([
            InlineKeyboardButton("âœ… ØªØ£ÛŒÛŒØ¯ Ù¾Ø±Ø¯Ø§Ø®Øª", callback_data=f"adm_order_approve:{order_id}"),
            InlineKeyboardButton("âŒ Ø±Ø¯ Ù¾Ø±Ø¯Ø§Ø®Øª", callback_data=f"adm_order_reject:{order_id}"),
        ])
    if order["status"] == "paid":
        keyboard.append([InlineKeyboardButton("ðŸšš Ø«Ø¨Øª Ø§Ø±Ø³Ø§Ù„ Ø³ÙØ§Ø±Ø´", callback_data=f"adm_order_status:shipped:{order_id}")])
    if order["status"] == "shipped":
        keyboard.append([InlineKeyboardButton("ðŸ Ø«Ø¨Øª ØªÚ©Ù…ÛŒÙ„ Ø³ÙØ§Ø±Ø´", callback_data=f"adm_order_status:completed:{order_id}")])
    if order["receipt_file_id"]:
        keyboard.append([InlineKeyboardButton("ðŸ§¾ Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ø±Ø³ÛŒØ¯", callback_data=f"adm_order_receipt:{order_id}")])
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§", callback_data="adm_orders")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def admin_order_receipt(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        file_id = await conn.fetchval("SELECT receipt_file_id FROM orders WHERE id=$1", order_id)
    if not file_id:
        await query.answer("âŒ Ø±Ø³ÛŒØ¯ÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡.", show_alert=True); return
    await query.answer()
    await query.message.chat.send_photo(photo=file_id, caption=f"ðŸ§¾ Ø±Ø³ÛŒØ¯ Ø³ÙØ§Ø±Ø´ #{order_id}")


async def set_order_status(query, context, order_id, status):
    pool = await db()
    order = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not order:
                await query.answer("âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
            if order["status"] != "waiting_admin":
                await query.answer("âš ï¸ Ø§ÛŒÙ† Ø³ÙØ§Ø±Ø´ Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø±Ø±Ø³ÛŒ Ø´Ø¯Ù‡.", show_alert=True); return
            await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)
    msg = (f"âœ… Ù¾Ø±Ø¯Ø§Ø®Øª Ø³ÙØ§Ø±Ø´ #{order_id} ØªØ£ÛŒÛŒØ¯ Ø´Ø¯.\n\nðŸ“¦ Ø³ÙØ§Ø±Ø´ Ø´Ù…Ø§ Ø¨Ø±Ø§ÛŒ Ø§Ø±Ø³Ø§Ù„ Ø¢Ù…Ø§Ø¯Ù‡ Ø´Ø¯."
           if status == "paid" else
           f"âŒ Ù¾Ø±Ø¯Ø§Ø®Øª Ø³ÙØ§Ø±Ø´ #{order_id} ØªØ£ÛŒÛŒØ¯ Ù†Ø´Ø¯.\n\nÙ„Ø·ÙØ§Ù‹ Ø±Ø³ÛŒØ¯ Ù¾Ø±Ø¯Ø§Ø®Øª Ø±Ø§ Ø¨Ø±Ø±Ø³ÛŒ Ùˆ Ø¯ÙˆØ¨Ø§Ø±Ù‡ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯.")
    try:
        await context.bot.send_message(chat_id=order["telegram_id"], text=msg)
    except Exception as e:
        print("CUSTOMER MESSAGE ERROR:", e)
    await query.answer("âœ… ÙˆØ¶Ø¹ÛŒØª Ø³ÙØ§Ø±Ø´ Ø«Ø¨Øª Ø´Ø¯.")
    await admin_order_details(query, order_id)


async def set_order_status_generic(query, context, status, order_id):
    valid_transitions = {"paid": ("shipped",), "shipped": ("completed",)}
    pool = await db()
    order = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not order:
                await query.answer("âŒ Ø³ÙØ§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True); return
            if status not in valid_transitions.get(order["status"], ()):
                await query.answer("âš ï¸ Ø§ÛŒÙ† ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª Ø¯Ø± Ø­Ø§Ù„ Ø­Ø§Ø¶Ø± Ù…Ø¬Ø§Ø² Ù†ÛŒØ³Øª.", show_alert=True); return
            await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)
    labels = {"shipped": "ðŸšš Ø³ÙØ§Ø±Ø´ Ø´Ù…Ø§ Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯.", "completed": "ðŸ Ø³ÙØ§Ø±Ø´ Ø´Ù…Ø§ ØªÚ©Ù…ÛŒÙ„ Ø´Ø¯."}
    try:
        await context.bot.send_message(chat_id=order["telegram_id"], text=f"{labels.get(status, '')}\n\nðŸ§¾ Ø³ÙØ§Ø±Ø´ #{order_id}")
    except Exception as e:
        print("CUSTOMER MESSAGE ERROR:", e)
    await query.answer("âœ… ÙˆØ¶Ø¹ÛŒØª Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø´Ø¯.")
    await admin_order_details(query, order_id)


# =========================================================
# ADMIN MEMBERS
# =========================================================
async def admin_members(query, offset=0):
    pool = await db()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        rows = await conn.fetch(
            "SELECT telegram_id,username,first_name,created_at FROM users ORDER BY created_at DESC OFFSET $1 LIMIT $2",
            offset, PAGE_SIZE + 1,
        )
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    text = f"ðŸ‘¥ Ø§Ø¹Ø¶Ø§ÛŒ Ø±Ø¨Ø§Øª\n\nðŸ‘¤ ØªØ¹Ø¯Ø§Ø¯ Ú©Ù„ Ø§Ø¹Ø¶Ø§: {total}\n\n"
    for m in rows:
        created = m["created_at"].strftime("%Y-%m-%d") if m["created_at"] else "---"
        text += f"ðŸ‘¤ {m['first_name'] or 'Ø¨Ø¯ÙˆÙ† Ù†Ø§Ù…'}\nðŸ†” {m['telegram_id']}\nðŸ“Ž @{m['username'] or '---'}\nðŸ“… {created}\nâ”â”â”â”â”â”â”â”â”â”â”â”\n"
    if not rows:
        text += "Ù…ÙˆØ±Ø¯ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯."
    keyboard = []
    nav = pagination_row("adm_members", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


# =========================================================
# ADMIN STATS
# =========================================================
async def admin_stats(query):
    pool = await db()
    async with pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        products_count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE active=TRUE")
        brands_count = await conn.fetchval("SELECT COUNT(*) FROM brands WHERE active=TRUE")
        orders_count = await conn.fetchval("SELECT COUNT(*) FROM orders")
        pending = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='waiting_admin'")
        revenue = await conn.fetchval("SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN ('paid','shipped','completed')")
        low_stock = await conn.fetchval("SELECT COUNT(*) FROM products WHERE active=TRUE AND stock<=3")
    text = (f"ðŸ“Š Ø¢Ù…Ø§Ø± ÙØ±ÙˆØ´Ú¯Ø§Ù‡\n\nðŸ‘¥ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†: {users_count}\nðŸ“¦ Ù…Ø­ØµÙˆÙ„Ø§Øª ÙØ¹Ø§Ù„: {products_count}\n"
            f"ðŸ· Ø¨Ø±Ù†Ø¯Ù‡Ø§ÛŒ ÙØ¹Ø§Ù„: {brands_count}\nðŸ§¾ Ú©Ù„ Ø³ÙØ§Ø±Ø´â€ŒÙ‡Ø§: {orders_count}\nâ³ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ: {pending}\n"
            f"ðŸ’° Ù…Ø¬Ù…ÙˆØ¹ ÙØ±ÙˆØ´ Ù…ÙˆÙÙ‚: {revenue:,} ØªÙˆÙ…Ø§Ù†\nâš ï¸ Ù…Ø­ØµÙˆÙ„Ø§Øª Ø±Ùˆ Ø¨Ù‡ Ø§ØªÙ…Ø§Ù… (â‰¤Û³ Ø¹Ø¯Ø¯): {low_stock}")
    await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")]]))


# =========================================================
# ADMIN BROADCAST
# =========================================================
async def admin_broadcast_start(query, context):
    context.user_data["state"] = "broadcast_message"
    await safe_edit(query, "ðŸ“¢ Ù…ØªÙ† Ù¾ÛŒØ§Ù… Ù‡Ù…Ú¯Ø§Ù†ÛŒ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†Ø› Ø¨Ø±Ø§ÛŒ Ù‡Ù…Ù‡ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø±Ø¨Ø§Øª ÙØ±Ø³ØªØ§Ø¯Ù‡ Ù…ÛŒâ€ŒØ´ÙˆØ¯." + CANCEL_HINT, None)


async def admin_broadcast_send(update, context):
    text = update.message.text
    context.user_data["state"] = None
    pool = await db()
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT telegram_id FROM users")
    await update.message.reply_text(f"â³ Ø¯Ø± Ø­Ø§Ù„ Ø§Ø±Ø³Ø§Ù„ Ø¨Ù‡ {len(users)} Ú©Ø§Ø±Ø¨Ø±...")
    sent = 0
    failed = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["telegram_id"], text=text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(
        f"âœ… Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯: {sent}\nâŒ Ù†Ø§Ù…ÙˆÙÙ‚: {failed}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ‘‘ Ù¾Ù†Ù„", callback_data="adm_panel")]]),
    )


# =========================================================
# ADMIN SETTINGS / PASSWORD
# =========================================================
async def admin_settings(query):
    card = await setting("card_number")
    shipping = await setting("shipping_cost")
    support = await setting("support_text")
    welcome = await setting("welcome_text")
    await safe_edit(query, (
        f"âš™ï¸ ØªÙ†Ø¸ÛŒÙ…Ø§Øª ÙØ±ÙˆØ´Ú¯Ø§Ù‡\n\nðŸ’³ Ú©Ø§Ø±Øª: {card or 'Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡'}\nðŸšš Ø§Ø±Ø³Ø§Ù„: {shipping or '0'} ØªÙˆÙ…Ø§Ù†\n"
        f"ðŸ“ž Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ: {support[:100]}\nðŸ“ Ø®ÙˆØ´â€ŒØ¢Ù…Ø¯Ú¯ÙˆÛŒÛŒ: {welcome[:100]}"
    ), InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ’³ ØªØºÛŒÛŒØ± Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª", callback_data="adm_set_card")],
        [InlineKeyboardButton("ðŸšš ØªØºÛŒÛŒØ± Ù‡Ø²ÛŒÙ†Ù‡ Ø§Ø±Ø³Ø§Ù„", callback_data="adm_set_shipping")],
        [InlineKeyboardButton("ðŸ“ž ØªØºÛŒÛŒØ± Ù…ØªÙ† Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ", callback_data="adm_set_support")],
        [InlineKeyboardButton("ðŸ“ ØªØºÛŒÛŒØ± Ù…ØªÙ† Ø®ÙˆØ´â€ŒØ¢Ù…Ø¯Ú¯ÙˆÛŒÛŒ", callback_data="adm_set_welcome")],
        [InlineKeyboardButton("ðŸ”™ Ù¾Ù†Ù„", callback_data="adm_panel")],
    ]))


async def admin_setting_message(update, context):
    state = context.user_data.get("state")
    text = update.message.text.strip()
    if state == "set_card":
        await set_setting("card_number", text)
    elif state == "set_shipping":
        try:
            value = int(text.replace(",", ""))
            assert value >= 0
        except Exception:
            await update.message.reply_text("âŒ ÙÙ‚Ø· Ø¹Ø¯Ø¯ Ù†Ø§Ù…Ù†ÙÛŒ ÙˆØ§Ø±Ø¯ Ú©Ù†."); return
        await set_setting("shipping_cost", str(value))
    elif state == "set_support":
        await set_setting("support_text", update.message.text)
    elif state == "set_welcome":
        await set_setting("welcome_text", update.message.text)
    else:
        return
    context.user_data["state"] = None
    await update.message.reply_text("âœ… ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø°Ø®ÛŒØ±Ù‡ Ø´Ø¯.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("âš™ï¸ ØªÙ†Ø¸ÛŒÙ…Ø§Øª", callback_data="adm_settings")]]))


async def change_password_start(query, context):
    context.user_data["state"] = "new_password"
    await safe_edit(query, "ðŸ”‘ Ø±Ù…Ø² Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù† (Ø­Ø¯Ø§Ù‚Ù„ Û¶ Ú©Ø§Ø±Ø§Ú©ØªØ±):" + CANCEL_HINT, None)


async def change_password(update, context):
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text("âŒ Ø±Ù…Ø² Ø¨Ø§ÛŒØ¯ Ø­Ø¯Ø§Ù‚Ù„ Û¶ Ú©Ø§Ø±Ø§Ú©ØªØ± Ø¨Ø§Ø´Ø¯."); return
    await set_setting("admin_password", hash_password(password))
    context.user_data["state"] = None
    await update.message.reply_text("âœ… Ø±Ù…Ø² Ø¨Ø§ Ù…ÙˆÙÙ‚ÛŒØª ØªØºÛŒÛŒØ± Ú©Ø±Ø¯.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("ðŸ‘‘ Ù¾Ù†Ù„", callback_data="adm_panel")]]))


# =========================================================
# ADMIN CALLBACK ROUTER
# =========================================================
async def admin_callback(query, context):
    if not is_admin(query.from_user.id):
        await query.answer("âŒ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True); return
    if not is_logged(context):
        await query.answer("âŒ Ø§Ø¨ØªØ¯Ø§ /admin Ø±Ø§ Ø¨Ø²Ù† Ùˆ ÙˆØ§Ø±Ø¯ Ù¾Ù†Ù„ Ø´Ùˆ.", show_alert=True); return

    data = query.data
    context.user_data["state"] = None

    if data == "adm_panel":
        await admin_panel_callback(query, context)
    elif data == "adm_products":
        await admin_products(query, 0)
    elif data.startswith("adm_products:"):
        await admin_products(query, int(data.split(":")[1]))
    elif data == "adm_brands":
        await admin_brands(query)
    elif data == "adm_orders":
        await admin_orders(query, 0)
    elif data.startswith("adm_orders:"):
        await admin_orders(query, int(data.split(":")[1]))
    elif data == "adm_members":
        await admin_members(query, 0)
    elif data.startswith("adm_members:"):
        await admin_members(query, int(data.split(":")[1]))
    elif data == "adm_stats":
        await admin_stats(query)
    elif data == "adm_broadcast":
        await admin_broadcast_start(query, context)
    elif data == "adm_settings":
        await admin_settings(query)
    elif data == "adm_add_brand":
        await add_brand_start(query, context)
    elif data == "adm_add_product":
        await add_product_start(query, context)
    elif data == "adm_password":
        await change_password_start(query, context)
    elif data == "adm_logout":
        context.user_data.clear()
        await safe_edit(query, "ðŸšª Ø§Ø² Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª Ø®Ø§Ø±Ø¬ Ø´Ø¯ÛŒØ¯.", None)

    elif data.startswith("adm_brand_edit:"):
        await brand_edit_start(query, context, int(data.split(":")[1]))
    elif data.startswith("adm_brand_toggle:"):
        await toggle_brand(query, int(data.split(":")[1]))
    elif data.startswith("adm_brand_delete_confirm:"):
        await delete_brand(query, int(data.split(":")[1]))
    elif data.startswith("adm_brand_delete:"):
        await confirm_brand_delete(query, int(data.split(":")[1]))
    elif data.startswith("adm_brand:"):
        await admin_brand_details(query, int(data.split(":")[1]))

    elif data.startswith("adm_pedit_menu:"):
        await product_edit_menu(query, int(data.split(":")[1]))
    elif data.startswith("adm_pset:"):
        parts = data.split(":", 2)
        await product_field_prompt(query, context, parts[1], int(parts[2]))
    elif data.startswith("adm_pbrand_set:"):
        parts = data.split(":")
        await product_brand_set(query, int(parts[1]), int(parts[2]))
    elif data.startswith("adm_pbrand:"):
        await product_brand_menu(query, int(data.split(":")[1]))
    elif data.startswith("adm_pimages:"):
        await product_images_menu(query, int(data.split(":")[1]))
    elif data.startswith("adm_pimg_del:"):
        parts = data.split(":")
        await product_image_delete(query, int(parts[1]), int(parts[2]))
    elif data.startswith("adm_pimg_add:"):
        await product_image_add_start(query, context, int(data.split(":")[1]))
    elif data.startswith("adm_product_toggle:"):
        await toggle_product(query, int(data.split(":")[1]))
    elif data.startswith("adm_product_delete_confirm:"):
        await delete_product(query, int(data.split(":")[1]))
    elif data.startswith("adm_product_delete:"):
        await confirm_product_delete(query, int(data.split(":")[1]))
    elif data.startswith("adm_product:"):
        await admin_product_details(query, int(data.split(":")[1]))

    elif data.startswith("adm_newbrand:"):
        if "product" not in context.user_data:
            await query.answer("âŒ ÙØ±Ø§ÛŒÙ†Ø¯ Ø§ÙØ²ÙˆØ¯Ù† Ù…Ø­ØµÙˆÙ„ Ù…Ù†Ù‚Ø¶ÛŒ Ø´Ø¯Ù‡. Ø¯ÙˆØ¨Ø§Ø±Ù‡ Ø´Ø±ÙˆØ¹ Ú©Ù†.", show_alert=True); return
        context.user_data["product"]["brand_id"] = int(data.split(":")[1])
        context.user_data["state"] = "product_description"
        await safe_edit(query, "ðŸ“ ØªÙˆØ¶ÛŒØ­Ø§Øª Ù…Ø­ØµÙˆÙ„ Ø±Ø§ Ø¨Ù†ÙˆÛŒØ³Ø› Ø§Ú¯Ø± Ù†Ø¯Ø§Ø±ÛŒ Ø¨Ù†ÙˆÛŒØ³: Ù†Ø¯Ø§Ø±Ø¯" + CANCEL_HINT, None)

    elif data.startswith("adm_order_receipt:"):
        await admin_order_receipt(query, int(data.split(":")[1]))
    elif data.startswith("adm_order_approve:"):
        await set_order_status(query, context, int(data.split(":")[1]), "paid")
    elif data.startswith("adm_order_reject:"):
        await set_order_status(query, context, int(data.split(":")[1]), "rejected")
    elif data.startswith("adm_order_status:"):
        parts = data.split(":")
        await set_order_status_generic(query, context, parts[1], int(parts[2]))
    elif data.startswith("adm_order:"):
        await admin_order_details(query, int(data.split(":")[1]))

    elif data == "adm_set_card":
        context.user_data["state"] = "set_card"
        await safe_edit(query, "ðŸ’³ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª Ø¬Ø¯ÛŒØ¯ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, None)
    elif data == "adm_set_shipping":
        context.user_data["state"] = "set_shipping"
        await safe_edit(query, "ðŸšš Ù‡Ø²ÛŒÙ†Ù‡ Ø§Ø±Ø³Ø§Ù„ Ø±Ø§ Ø¨Ù‡ ØªÙˆÙ…Ø§Ù† ÙˆØ§Ø±Ø¯ Ú©Ù†:" + CANCEL_HINT, None)
    elif data == "adm_set_support":
        context.user_data["state"] = "set_support"
        await safe_edit(query, "ðŸ“ž Ù…ØªÙ† Ø¬Ø¯ÛŒØ¯ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, None)
    elif data == "adm_set_welcome":
        context.user_data["state"] = "set_welcome"
        await safe_edit(query, "ðŸ“ Ù…ØªÙ† Ø¬Ø¯ÛŒØ¯ Ø®ÙˆØ´â€ŒØ¢Ù…Ø¯Ú¯ÙˆÛŒÛŒ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†:" + CANCEL_HINT, None)


# =========================================================
# ROUTERS / ERROR / STARTUP
# =========================================================
async def callback_handler(update, context):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    data = query.data or ""
    if data.startswith("adm_"):
        await admin_callback(query, context)
    else:
        await customer_callback(query, context)


async def text_handler(update, context):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()

    if state and text in CANCEL_WORDS:
        context.user_data["state"] = None
        context.user_data.pop("product", None)
        if is_admin(update.effective_user.id) and is_logged(context):
            await update.message.reply_text("âŒ Ø¹Ù…Ù„ÛŒØ§Øª Ù„ØºÙˆ Ø´Ø¯.", reply_markup=admin_menu_markup())
        else:
            await update.message.reply_text("âŒ Ø¹Ù…Ù„ÛŒØ§Øª Ù„ØºÙˆ Ø´Ø¯.", reply_markup=await main_menu())
        return

    if state == "admin_password":
        await admin_password(update, context); return
    if state in ("set_card", "set_shipping", "set_support", "set_welcome"):
        if is_admin(update.effective_user.id) and is_logged(context):
            await admin_setting_message(update, context)
        return
    if state == "new_password":
        if is_admin(update.effective_user.id) and is_logged(context):
            await change_password(update, context)
        return
    if state == "add_brand":
        if is_admin(update.effective_user.id) and is_logged(context):
            await add_brand(update, context)
        return
    if state and state.startswith("edit_brand_name:"):
        if is_admin(update.effective_user.id) and is_logged(context):
            await brand_edit_message(update, context, state)
        return
    if state == "broadcast_message":
        if is_admin(update.effective_user.id) and is_logged(context):
            await admin_broadcast_send(update, context)
        return
    if state and state.startswith("pedit_image_add:"):
        if is_admin(update.effective_user.id) and is_logged(context):
            await update.message.reply_text("âŒ Ù„Ø·ÙØ§Ù‹ ÛŒÚ© Ø¹Ú©Ø³ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†.")
        return
    if state and state.startswith("pedit_"):
        if is_admin(update.effective_user.id) and is_logged(context):
            await product_edit_message(update, context, state)
        return
    if state and state.startswith("product_"):
        if is_admin(update.effective_user.id) and is_logged(context):
            await product_add_message(update, context)
        return
    if state in ("customer_name", "phone", "address", "postal"):
        await checkout_message(update, context); return
    if state == "search":
        await do_search(update, context); return


async def photo_handler(update, context):
    state = context.user_data.get("state")
    if state == "product_images":
        if not (is_admin(update.effective_user.id) and is_logged(context)):
            return
        images = context.user_data.setdefault("product", {}).setdefault("images", [])
        if len(images) >= 5:
            await update.message.reply_text("âš ï¸ Ø­Ø¯Ø§Ú©Ø«Ø± Ûµ Ø¹Ú©Ø³ Ù…Ø¬Ø§Ø² Ø§Ø³Øª. Ø¨Ø±Ø§ÛŒ Ø§ØªÙ…Ø§Ù… Ø¨Ù†ÙˆÛŒØ³ Â«ØªÙ…Ø§Ù…Â»."); return
        images.append(update.message.photo[-1].file_id)
        await update.message.reply_text(f"âœ… Ø¹Ú©Ø³ {len(images)} Ø¯Ø±ÛŒØ§ÙØª Ø´Ø¯.\nØ¹Ú©Ø³ Ø¨Ø¹Ø¯ÛŒ Ø±Ø§ Ø¨ÙØ±Ø³Øª ÛŒØ§ Ø¨Ù†ÙˆÛŒØ³ Â«ØªÙ…Ø§Ù…Â».")
        return
    if state and state.startswith("pedit_image_add:"):
        if not (is_admin(update.effective_user.id) and is_logged(context)):
            return
        product_id = int(state.split(":", 1)[1])
        pool = await db()
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id)
            if count >= 5:
                context.user_data["state"] = None
                await update.message.reply_text("âŒ Ø¸Ø±ÙÛŒØª Ûµ Ø¹Ú©Ø³ ØªÚ©Ù…ÛŒÙ„ Ø´Ø¯Ù‡ Ø§Ø³Øª."); return
            next_pos = (await conn.fetchval("SELECT COALESCE(MAX(position),0) FROM product_images WHERE product_id=$1", product_id)) + 1
            await conn.execute("INSERT INTO product_images(product_id,file_id,position) VALUES($1,$2,$3)",
                                product_id, update.message.photo[-1].file_id, next_pos)
        context.user_data["state"] = None
        await update.message.reply_text("âœ… Ø¹Ú©Ø³ Ø§Ø¶Ø§ÙÙ‡ Ø´Ø¯.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("ðŸ–¼ Ù…Ø¯ÛŒØ±ÛŒØª Ø¹Ú©Ø³â€ŒÙ‡Ø§", callback_data=f"adm_pimages:{product_id}")]]))
        return
    if state and state.startswith("receipt:"):
        await receive_receipt(update, context)


async def error_handler(update, context):
    print("âŒ ERROR:", repr(context.error))
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="âš ï¸ Ø®Ø·Ø§ÛŒÛŒ Ø±Ø® Ø¯Ø§Ø¯. Ù„Ø·ÙØ§Ù‹ Ø¯ÙˆØ¨Ø§Ø±Ù‡ ØªÙ„Ø§Ø´ Ú©Ù† ÛŒØ§ /start Ø±Ø§ Ø¨Ø²Ù†.",
            )
    except Exception:
        pass


async def post_init(application):
    await init_db()


app = (Application.builder().token(TOKEN).post_init(post_init).build())
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_error_handler(error_handler)

print("ðŸš€ BOT STARTED")
app.run_polling()
