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
CANCEL_WORDS = {"لغو", "انصراف", "cancel", "Cancel"}
CANCEL_HINT = "\n\n(برای لغو بنویس: لغو)"

STATUS_LABELS = {
    "waiting_payment": "⏳ منتظر پرداخت",
    "waiting_admin": "🔎 در انتظار بررسی ادمین",
    "paid": "✅ پرداخت تأیید شد",
    "rejected": "❌ پرداخت رد شد",
    "shipped": "🚚 ارسال شد",
    "completed": "🏁 تکمیل شد",
}

FIELD_PROMPTS = {
    "name": "👟 نام جدید محصول را ارسال کن:",
    "description": "📝 توضیحات جدید را ارسال کن؛ اگر نداری بنویس: ندارد",
    "price": "💰 قیمت اصلی جدید را فقط عدد وارد کن:",
    "sale": "🔥 قیمت حراج جدید را وارد کن؛ اگر ندارد 0:",
    "sizes": "📏 سایزهای جدید را با کاما جدا کن؛ مثال 40,41,42:",
    "stock": "📦 موجودی جدید را وارد کن:",
    "category": "👟 دسته‌بندی/کاربرد جدید را بنویس:",
    "keywords": "🔎 کلمات جستجوی جدید را با کاما بنویس:",
}

FIELD_LABELS = {
    "name": "✏️ نام",
    "description": "📝 توضیحات",
    "price": "💰 قیمت",
    "sale": "🔥 قیمت حراج",
    "sizes": "📏 سایزها",
    "stock": "📦 موجودی",
    "category": "👟 دسته‌بندی",
    "keywords": "🔎 کلمات جستجو",
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
    # سازگاری با نصب‌های قدیمی که رمز را با SHA-256 ساده ذخیره کرده بودند
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored


async def init_db():
    """Create the schema and safely migrate older Railway databases.

    IMPORTANT:
    CREATE TABLE IF NOT EXISTS does NOT modify an existing table.  The
    migration section below is therefore required when an older database
    already exists (for example, when products was created without brand_id).
    """
    pool = await db()
    async with pool.acquire() as conn:
        # -----------------------------------------------------
        # Base tables. Existing tables are preserved.
        # -----------------------------------------------------
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
                brand_id INTEGER,
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
                product_id INTEGER,
                file_id TEXT NOT NULL,
                position INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS cart_items (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                product_id INTEGER,
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
                order_id INTEGER,
                product_id INTEGER,
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

        # -----------------------------------------------------
        # SAFE MIGRATION FOR OLD DATABASES
        # -----------------------------------------------------
        # PostgreSQL will simply skip these when the columns already exist.
        # This fixes the exact Railway error:
        # UndefinedColumn: column "brand_id" does not exist
        # -----------------------------------------------------
        migrations = [
            ("users", "username", "TEXT"),
            ("users", "first_name", "TEXT"),
            ("users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),

            ("brands", "active", "BOOLEAN DEFAULT TRUE"),
            ("brands", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),

            ("products", "brand_id", "INTEGER"),
            ("products", "description", "TEXT DEFAULT ''"),
            ("products", "price", "BIGINT DEFAULT 0"),
            ("products", "sale_price", "BIGINT DEFAULT 0"),
            ("products", "sizes", "TEXT DEFAULT ''"),
            ("products", "stock", "INTEGER DEFAULT 0"),
            ("products", "category", "TEXT DEFAULT ''"),
            ("products", "keywords", "TEXT DEFAULT ''"),
            ("products", "active", "BOOLEAN DEFAULT TRUE"),
            ("products", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),

            ("product_images", "product_id", "INTEGER"),
            ("product_images", "file_id", "TEXT"),
            ("product_images", "position", "INTEGER DEFAULT 1"),

            ("cart_items", "telegram_id", "BIGINT"),
            ("cart_items", "product_id", "INTEGER"),
            ("cart_items", "size", "TEXT DEFAULT ''"),
            ("cart_items", "quantity", "INTEGER DEFAULT 1"),

            ("orders", "telegram_id", "BIGINT"),
            ("orders", "customer_name", "TEXT"),
            ("orders", "phone", "TEXT"),
            ("orders", "address", "TEXT"),
            ("orders", "postal_code", "TEXT"),
            ("orders", "shipping_cost", "BIGINT DEFAULT 0"),
            ("orders", "total", "BIGINT DEFAULT 0"),
            ("orders", "status", "TEXT DEFAULT 'waiting_payment'"),
            ("orders", "receipt_file_id", "TEXT"),
            ("orders", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),

            ("order_items", "order_id", "INTEGER"),
            ("order_items", "product_id", "INTEGER"),
            ("order_items", "product_name", "TEXT"),
            ("order_items", "size", "TEXT"),
            ("order_items", "quantity", "INTEGER DEFAULT 1"),
            ("order_items", "price", "BIGINT DEFAULT 0"),
        ]

        for table, column, definition in migrations:
            await conn.execute(
                f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {definition}'
            )

        # Existing rows may have NULL values after adding a column.
        # Normalize only fields where NULL would break application logic.
        await conn.execute("UPDATE brands SET active=TRUE WHERE active IS NULL")
        await conn.execute("UPDATE products SET description='' WHERE description IS NULL")
        await conn.execute("UPDATE products SET price=0 WHERE price IS NULL")
        await conn.execute("UPDATE products SET sale_price=0 WHERE sale_price IS NULL")
        await conn.execute("UPDATE products SET sizes='' WHERE sizes IS NULL")
        await conn.execute("UPDATE products SET stock=0 WHERE stock IS NULL")
        await conn.execute("UPDATE products SET category='' WHERE category IS NULL")
        await conn.execute("UPDATE products SET keywords='' WHERE keywords IS NULL")
        await conn.execute("UPDATE products SET active=TRUE WHERE active IS NULL")
        await conn.execute("UPDATE product_images SET position=1 WHERE position IS NULL")
        await conn.execute("UPDATE cart_items SET size='' WHERE size IS NULL")
        await conn.execute("UPDATE cart_items SET quantity=1 WHERE quantity IS NULL OR quantity < 1")
        await conn.execute("UPDATE orders SET shipping_cost=0 WHERE shipping_cost IS NULL")
        await conn.execute("UPDATE orders SET total=0 WHERE total IS NULL")
        await conn.execute("UPDATE orders SET status='waiting_payment' WHERE status IS NULL")
        await conn.execute("UPDATE order_items SET quantity=1 WHERE quantity IS NULL OR quantity < 1")
        await conn.execute("UPDATE order_items SET price=0 WHERE price IS NULL")

        # Remove orphan references before adding foreign keys.
        # This keeps old installations migratable even if an older version
        # left a deleted brand/product behind.
        await conn.execute("""
            UPDATE products p
            SET brand_id = NULL
            WHERE brand_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM brands b WHERE b.id = p.brand_id)
        """)
        await conn.execute("""
            DELETE FROM product_images pi
            WHERE pi.product_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM products p WHERE p.id = pi.product_id)
        """)
        await conn.execute("""
            DELETE FROM cart_items c
            WHERE c.product_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM products p WHERE p.id = c.product_id)
        """)
        await conn.execute("""
            DELETE FROM order_items oi
            WHERE oi.order_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = oi.order_id)
        """)
        await conn.execute("""
            UPDATE order_items oi
            SET product_id = NULL
            WHERE product_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM products p WHERE p.id = oi.product_id)
        """)

        # -----------------------------------------------------
        # Foreign keys: add them only when they do not already exist.
        # The DO blocks also avoid duplicate-constraint crashes.
        # -----------------------------------------------------
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'products_brand_id_fkey'
                ) THEN
                    ALTER TABLE products
                    ADD CONSTRAINT products_brand_id_fkey
                    FOREIGN KEY (brand_id) REFERENCES brands(id)
                    ON DELETE SET NULL;
                END IF;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
        """)

        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'product_images_product_id_fkey'
                ) THEN
                    ALTER TABLE product_images
                    ADD CONSTRAINT product_images_product_id_fkey
                    FOREIGN KEY (product_id) REFERENCES products(id)
                    ON DELETE CASCADE;
                END IF;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
        """)

        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'cart_items_product_id_fkey'
                ) THEN
                    ALTER TABLE cart_items
                    ADD CONSTRAINT cart_items_product_id_fkey
                    FOREIGN KEY (product_id) REFERENCES products(id)
                    ON DELETE CASCADE;
                END IF;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
        """)

        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'order_items_order_id_fkey'
                ) THEN
                    ALTER TABLE order_items
                    ADD CONSTRAINT order_items_order_id_fkey
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                    ON DELETE CASCADE;
                END IF;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
        """)

        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'order_items_product_id_fkey'
                ) THEN
                    ALTER TABLE order_items
                    ADD CONSTRAINT order_items_product_id_fkey
                    FOREIGN KEY (product_id) REFERENCES products(id)
                    ON DELETE SET NULL;
                END IF;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
        """)

        # -----------------------------------------------------
        # Indexes MUST be created AFTER the migration above.
        # -----------------------------------------------------
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_id);
            CREATE INDEX IF NOT EXISTS idx_products_active ON products(active);
            CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock);
            CREATE INDEX IF NOT EXISTS idx_cart_telegram ON cart_items(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_orders_telegram ON orders(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id);
            CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
        """)

        defaults = {
            "card_number": "",
            "shipping_cost": "0",
            "support_text": "📞 برای پشتیبانی با ما در ارتباط باشید.",
            "welcome_text": "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\nاز منوی زیر انتخاب کنید:",
            "admin_password": hash_password(DEFAULT_ADMIN_PASSWORD),
        }
        for key, value in defaults.items():
            await conn.execute("""
                INSERT INTO settings(key,value) VALUES($1,$2)
                ON CONFLICT(key) DO NOTHING
            """, key, value)

    print("✅ DATABASE READY / MIGRATIONS OK")


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
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=callback)]])


def pagination_row(prefix, offset, has_more):
    row = []
    if offset > 0:
        row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"{prefix}:{max(0, offset - PAGE_SIZE)}"))
    if has_more:
        row.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"{prefix}:{offset + PAGE_SIZE}"))
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
        [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="adm_products")],
        [InlineKeyboardButton("🏷 مدیریت برندها", callback_data="adm_brands")],
        [InlineKeyboardButton("🧾 سفارش‌ها", callback_data="adm_orders")],
        [InlineKeyboardButton("👥 اعضای ربات", callback_data="adm_members")],
        [InlineKeyboardButton("📊 آمار فروشگاه", callback_data="adm_stats")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast")],
        [InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data="adm_settings")],
        [InlineKeyboardButton("🔑 تغییر رمز", callback_data="adm_password")],
        [InlineKeyboardButton("🚪 خروج", callback_data="adm_logout")],
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
        [InlineKeyboardButton("🛍 محصولات", callback_data="products"), InlineKeyboardButton("🛒 سبد خرید", callback_data="cart")],
        [InlineKeyboardButton("📦 سفارش‌های من", callback_data="orders"), InlineKeyboardButton("🔎 جستجو", callback_data="search")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
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
    keyboard = [[InlineKeyboardButton("🔥 حراج", callback_data="sale")]]
    row = []
    for b in brands:
        row.append(InlineKeyboardButton(f"🏷 {b['name']}", callback_data=f"brand:{b['id']}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="home")])
    await safe_edit(query, "🛍 محصولات فروشگاه\n\n🔥 حراج\n🏷 برند موردنظر را انتخاب کنید:", InlineKeyboardMarkup(keyboard))


async def brand_products(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        brand = await conn.fetchrow("SELECT name FROM brands WHERE id=$1 AND active=TRUE", brand_id)
        products = await conn.fetch("""
            SELECT id,name,price,sale_price FROM products
            WHERE brand_id=$1 AND active=TRUE AND stock>0 ORDER BY id DESC
        """, brand_id)
    if not brand:
        await safe_edit(query, "❌ برند پیدا نشد یا غیرفعال است.", back_button("products")); return
    if not products:
        await safe_edit(query, f"🏷 {brand['name']}\n\nفعلاً محصول موجودی ندارد.", back_button("products")); return
    keyboard = []
    for p in products:
        price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
        prefix = "🔥" if price != p["price"] else "👟"
        keyboard.append([InlineKeyboardButton(f"{prefix} {p['name']} | {price:,} تومان", callback_data=f"product:{p['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 برندها", callback_data="products")])
    await safe_edit(query, f"🏷 {brand['name']}\n\nمدل موردنظر را انتخاب کنید:", InlineKeyboardMarkup(keyboard))


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
        await safe_edit(query, "🔥 حراج\n\nفعلاً محصولی در حراج نیست.", back_button("products")); return
    keyboard = [[InlineKeyboardButton(f"🔥 {p['name']} | {p['sale_price']:,} تومان", callback_data=f"product:{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("🔙 محصولات", callback_data="products")])
    await safe_edit(query, "🔥 محصولات حراج:", InlineKeyboardMarkup(keyboard))


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
        await safe_edit(query, "❌ محصول پیدا نشد یا در دسترس نیست.", back_button("products")); return
    price = product["sale_price"] if 0 < product["sale_price"] < product["price"] else product["price"]
    price_text = f"💰 قیمت: {price:,} تومان"
    if price != product["price"]:
        price_text = f"💰 قیمت اصلی: {product['price']:,} تومان\n🔥 قیمت حراج: {price:,} تومان"
    text = (f"👟 {product['name']}\n\n🏷 برند: {product['brand_name'] or '---'}\n{price_text}\n"
            f"📏 سایزها: {product['sizes'] or '---'}\n📦 موجودی: {product['stock']}\n\n{product['description'] or ''}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 افزودن به سبد خرید", callback_data=f"buy:{product_id}")],
        [InlineKeyboardButton("🔙 محصولات", callback_data="products")],
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
        await query.answer("❌ محصول پیدا نشد یا در دسترس نیست.", show_alert=True); return
    if product["stock"] <= 0:
        await query.answer("❌ این محصول ناموجود است.", show_alert=True); return
    sizes = [x.strip() for x in (product["sizes"] or "").split(",") if x.strip()]
    if len(sizes) > 1:
        keyboard = [[InlineKeyboardButton(f"📏 سایز {s}", callback_data=f"addsize:{product_id}:{s}")] for s in sizes]
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"product:{product_id}")])
        await safe_edit(query, "📏 سایز موردنظر را انتخاب کنید:", InlineKeyboardMarkup(keyboard)); return
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
                await query.answer("❌ محصول در دسترس نیست.", show_alert=True); return
            current = await conn.fetchval(
                "SELECT quantity FROM cart_items WHERE telegram_id=$1 AND product_id=$2 AND size=$3",
                telegram_id, product_id, size,
            ) or 0
            if current >= product["stock"]:
                await query.answer("❌ بیشتر از موجودی نمی‌توانی اضافه کنی.", show_alert=True); return
            await conn.execute("""
                INSERT INTO cart_items(telegram_id,product_id,size,quantity) VALUES($1,$2,$3,1)
                ON CONFLICT(telegram_id,product_id,size) DO UPDATE SET quantity=cart_items.quantity+1
            """, telegram_id, product_id, size)
    await safe_edit(query, f"✅ {product['name']}\n\nبه سبد خرید اضافه شد.", InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 سبد خرید", callback_data="cart")],
        [InlineKeyboardButton("🛍 ادامه خرید", callback_data="products")],
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
        await safe_edit(query, "🛒 سبد خرید خالی است.", back_button("home")); return
    total = 0
    text = "🛒 سبد خرید شما:\n\n"
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
        text += f"👟 {item['name']}\n📏 سایز: {item['size'] or '---'}\n🔢 تعداد: {qty}\n💰 {subtotal:,} تومان\n\n"
        keyboard.append([
            InlineKeyboardButton("➖", callback_data=f"cart_dec:{item['id']}"),
            InlineKeyboardButton(f"{qty} عدد", callback_data="cart_noop"),
            InlineKeyboardButton("➕", callback_data=f"cart_inc:{item['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"cart_del:{item['id']}"),
        ])
    if valid_count == 0:
        await safe_edit(query, "🛒 سبد خرید خالی است یا محصولات آن دیگر موجود نیستند.", back_button("home")); return
    shipping = int(await setting("shipping_cost") or 0)
    final_total = total + shipping
    text += f"🛍 جمع کالاها: {total:,} تومان\n🚚 ارسال: {shipping:,} تومان\n💵 مبلغ نهایی: {final_total:,} تومان"
    keyboard.append([InlineKeyboardButton("📦 ثبت سفارش", callback_data="checkout")])
    keyboard.append([InlineKeyboardButton("🛍 ادامه خرید", callback_data="products")])
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="home")])
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
                await query.answer("❌ آیتم پیدا نشد.", show_alert=True); return
            new_qty = row["quantity"] + delta
            if new_qty <= 0:
                await conn.execute("DELETE FROM cart_items WHERE id=$1", cart_id)
            elif new_qty > row["stock"]:
                await query.answer("❌ بیشتر از موجودی امکان‌پذیر نیست.", show_alert=True); return
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
        await query.answer("❌ آیتم پیدا نشد.", show_alert=True); return
    await query.answer("🗑 حذف شد.")
    await show_cart(query)


async def checkout_start(query, context):
    pool = await db()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM cart_items WHERE telegram_id=$1", query.from_user.id)
    if not count:
        await safe_edit(query, "🛒 سبد خرید خالی است.", back_button("home")); return
    context.user_data["state"] = "customer_name"
    await safe_edit(query, "👤 نام و نام خانوادگی را ارسال کنید:" + CANCEL_HINT, None)


async def checkout_message(update, context):
    state = context.user_data.get("state")
    text = update.message.text.strip()
    if state == "customer_name":
        if len(text) < 3:
            await update.message.reply_text("❌ نام را کامل وارد کنید."); return
        context.user_data["customer_name"] = text
        context.user_data["state"] = "phone"
        await update.message.reply_text("📱 شماره موبایل را ارسال کنید:" + CANCEL_HINT); return
    if state == "phone":
        if len(text) < 7:
            await update.message.reply_text("❌ شماره موبایل معتبر وارد کنید."); return
        context.user_data["phone"] = text
        context.user_data["state"] = "address"
        await update.message.reply_text("📍 آدرس کامل را ارسال کنید:" + CANCEL_HINT); return
    if state == "address":
        if len(text) < 10:
            await update.message.reply_text("❌ آدرس را کامل‌تر وارد کنید."); return
        context.user_data["address"] = text
        context.user_data["state"] = "postal"
        await update.message.reply_text("📮 کد پستی ۱۰ رقمی را ارسال کنید:" + CANCEL_HINT); return
    if state == "postal":
        postal = "".join(x for x in text if x.isdigit())
        if len(postal) != 10:
            await update.message.reply_text("❌ کد پستی باید ۱۰ رقم باشد."); return
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
                await update.message.reply_text("❌ سبد خرید خالی است."); return
            total = 0
            for item in items:
                if not item["active"] or not item["brand_ok"] or item["stock"] < item["quantity"]:
                    await update.message.reply_text(
                        f"❌ «{item['name']}» دیگر در دسترس نیست یا موجودی کافی ندارد.\nلطفاً سبد خرید را اصلاح کن."
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
    payment = f"💳 شماره کارت:\n`{card}`\n\n" if card else "⚠️ شماره کارت هنوز ثبت نشده.\n\n"
    await update.message.reply_text(
        f"✅ سفارش شما ثبت شد.\n\n🧾 شماره سفارش: #{order_id}\n💰 مبلغ نهایی: {final_total:,} تومان\n\n"
        f"{payment}بعد از پرداخت، عکس رسید را همینجا ارسال کنید.",
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
        await update.message.reply_text("❌ لطفاً عکس رسید را ارسال کنید."); return
    order_id = int(state.split(":")[1])
    file_id = update.message.photo[-1].file_id
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND telegram_id=$2 FOR UPDATE", order_id, update.effective_user.id)
        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد."); return
        if order["status"] not in ("waiting_payment", "rejected"):
            await update.message.reply_text("⚠️ این سفارش در حال حاضر امکان دریافت رسید ندارد."); return
        await conn.execute("UPDATE orders SET receipt_file_id=$1,status='waiting_admin' WHERE id=$2", file_id, order_id)
    context.user_data["state"] = None
    await update.message.reply_text("🧾 رسید دریافت شد.\n\n⏳ بعد از بررسی پرداخت، نتیجه برای شما ارسال می‌شود.")
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(f"🧾 رسید جدید\n\n🧾 سفارش: #{order_id}\n💰 مبلغ: {order['total']:,} تومان\n"
                     f"👤 مشتری: {order['customer_name']}\n📱 تلفن: {order['phone']}\n"
                     f"📍 آدرس: {order['address']}\n📮 کد پستی: {order['postal_code']}"),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ تأیید پرداخت", callback_data=f"adm_order_approve:{order_id}"),
                InlineKeyboardButton("❌ رد پرداخت", callback_data=f"adm_order_reject:{order_id}"),
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
        await safe_edit(query, "📦 هنوز سفارشی ثبت نکرده‌اید.", back_button("home")); return
    keyboard = [[InlineKeyboardButton(
        f"🧾 #{o['id']} | {STATUS_LABELS.get(o['status'], o['status'])} | {o['total']:,} تومان",
        callback_data=f"myorder:{o['id']}")] for o in rows]
    nav = pagination_row("myorders", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="home")])
    await safe_edit(query, "📦 سفارش‌های شما:", InlineKeyboardMarkup(keyboard))


async def customer_order_details(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND telegram_id=$2", order_id, query.from_user.id)
        items = await conn.fetch("SELECT * FROM order_items WHERE order_id=$1", order_id) if order else []
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    text = f"🧾 سفارش #{order_id}\n\n"
    for i in items:
        text += f"👟 {i['product_name']}\n📏 سایز: {i['size'] or '---'}\n🔢 تعداد: {i['quantity']}\n💰 {i['price']:,} تومان\n\n"
    text += (f"🚚 ارسال: {order['shipping_cost']:,} تومان\n💵 مجموع: {order['total']:,} تومان\n"
             f"📌 وضعیت: {STATUS_LABELS.get(order['status'], order['status'])}")
    keyboard = []
    if order["status"] in ("waiting_payment", "rejected"):
        keyboard.append([InlineKeyboardButton("🧾 ارسال/ارسال مجدد رسید پرداخت", callback_data=f"send_receipt:{order_id}")])
    keyboard.append([InlineKeyboardButton("🔙 سفارش‌های من", callback_data="orders")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def send_receipt_start(query, context, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT status FROM orders WHERE id=$1 AND telegram_id=$2", order_id, query.from_user.id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order["status"] not in ("waiting_payment", "rejected"):
        await query.answer("⚠️ این سفارش در حال حاضر امکان ارسال رسید ندارد.", show_alert=True); return
    context.user_data["state"] = f"receipt:{order_id}"
    await safe_edit(query, "🧾 عکس رسید پرداخت را ارسال کن:", None)


# =========================================================
# SEARCH
# =========================================================
async def start_search(query, context):
    context.user_data["state"] = "search"
    await safe_edit(query, "🔎 جستجوی محصول\n\nاسم مدل، برند یا کاربرد را بنویس." + CANCEL_HINT, back_button("home"))


async def do_search(update, context):
    word = update.message.text.strip()
    if not word:
        await update.message.reply_text("❌ چیزی وارد نکردی."); return
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
        await update.message.reply_text(f"❌ برای «{word}» محصولی پیدا نشد.", reply_markup=await main_menu()); return
    keyboard = []
    for p in products:
        price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
        keyboard.append([InlineKeyboardButton(f"👟 {p['name']} | {price:,} تومان", callback_data=f"product:{p['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")])
    await update.message.reply_text(f"🔎 نتایج جستجو برای «{word}»:", reply_markup=InlineKeyboardMarkup(keyboard))


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
        await update.message.reply_text("❌ شما دسترسی مدیریت ندارید."); return
    context.user_data.clear()
    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = "admin_password"
    await update.message.reply_text("🔐 رمز پنل مدیریت را وارد کنید:")


async def admin_password(update, context):
    if not is_admin(update.effective_user.id) or context.user_data.get("state") != "admin_password":
        return
    entered = update.message.text.strip()
    stored = await setting("admin_password")
    if not verify_password(entered, stored):
        await update.message.reply_text("❌ رمز اشتباه است."); return
    if "$" not in stored:
        await set_setting("admin_password", hash_password(entered))
    context.user_data["admin_logged"] = True
    context.user_data["admin_id"] = ADMIN_ID
    context.user_data["state"] = None
    await update.message.reply_text("👑 پنل مدیریت فروشگاه\n\nاز منوی زیر مدیریت کن:", reply_markup=admin_menu_markup())


async def admin_panel_callback(query, context):
    await safe_edit(query, "👑 پنل مدیریت", admin_menu_markup())


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
    keyboard = [[InlineKeyboardButton("➕ افزودن برند", callback_data="adm_add_brand")]]
    for b in brands:
        icon = "🟢" if b["active"] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{icon} {b['name']} | {b['product_count']} محصول", callback_data=f"adm_brand:{b['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")])
    await safe_edit(query, "🏷 مدیریت برندها:", InlineKeyboardMarkup(keyboard))


async def admin_brand_details(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT id,name,active FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await safe_edit(query, "❌ برند پیدا نشد.", back_button("adm_brands")); return
    status = "🟢 فعال" if b["active"] else "🔴 غیرفعال"
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"adm_brand_edit:{brand_id}")],
        [InlineKeyboardButton("🔴 غیرفعال‌سازی" if b["active"] else "🟢 فعال‌سازی", callback_data=f"adm_brand_toggle:{brand_id}")],
        [InlineKeyboardButton("🗑 حذف کامل برند", callback_data=f"adm_brand_delete:{brand_id}")],
        [InlineKeyboardButton("🔙 برندها", callback_data="adm_brands")],
    ]
    await safe_edit(query, (
        f"🏷 برند: {b['name']}\n\n📌 وضعیت: {status}\n📦 تعداد محصولات: {count}\n\n"
        "⚠️ غیرفعال‌سازی امن است و محصولات را حذف نمی‌کند؛ فقط از دید مشتری مخفی می‌شوند.\n"
        "🗑 حذف کامل فقط وقتی ممکن است که هیچ محصولی به برند متصل نباشد."
    ), InlineKeyboardMarkup(keyboard))


async def brand_edit_start(query, context, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT name FROM brands WHERE id=$1", brand_id)
    if not b:
        await query.answer("❌ برند پیدا نشد.", show_alert=True); return
    context.user_data["state"] = f"edit_brand_name:{brand_id}"
    await safe_edit(query, f"✏️ نام فعلی: {b['name']}\n\nنام جدید برند را ارسال کن:" + CANCEL_HINT, back_button(f"adm_brand:{brand_id}"))


async def brand_edit_message(update, context, state):
    brand_id = int(state.split(":", 1)[1])
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ نام برند خیلی کوتاه است."); return
    pool = await db()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM brands WHERE LOWER(name)=LOWER($1) AND id<>$2", name, brand_id)
        if exists:
            await update.message.reply_text("❌ برند دیگری با این نام وجود دارد."); return
        updated = await conn.fetchval("UPDATE brands SET name=$1 WHERE id=$2 RETURNING id", name, brand_id)
    context.user_data["state"] = None
    if not updated:
        await update.message.reply_text("❌ برند پیدا نشد."); return
    await update.message.reply_text("✅ نام برند بروزرسانی شد.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏷 مشاهده برند", callback_data=f"adm_brand:{brand_id}")]]))


async def toggle_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE brands SET active=NOT active WHERE id=$1 RETURNING name,active", brand_id)
    if not row:
        await query.answer("❌ برند پیدا نشد.", show_alert=True); return
    await query.answer("✅ وضعیت برند تغییر کرد.")
    await admin_brand_details(query, brand_id)


async def confirm_brand_delete(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT name FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await query.answer("❌ برند پیدا نشد.", show_alert=True); return
    if count:
        await query.answer(
            f"❌ این برند {count} محصول متصل دارد. اول برند را غیرفعال کن یا محصولاتش را حذف/تغییر برند بده؛ "
            "تا وقتی محصول متصل دارد حذف نمی‌شود.", show_alert=True
        )
        return
    await safe_edit(query, f"⚠️ حذف برند «{b['name']}» قطعی است. ادامه می‌دهی؟", InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"adm_brand_delete_confirm:{brand_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"adm_brand:{brand_id}")],
    ]))


async def delete_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id)
            if count:
                await query.answer("❌ این برند هنوز محصول متصل دارد.", show_alert=True); return
            deleted = await conn.fetchval("DELETE FROM brands WHERE id=$1 RETURNING name", brand_id)
    if not deleted:
        await query.answer("❌ برند پیدا نشد.", show_alert=True); return
    await query.answer("✅ برند حذف شد.")
    await admin_brands(query)


async def add_brand_start(query, context):
    context.user_data["state"] = "add_brand"
    await safe_edit(query, "🏷 نام برند جدید را ارسال کن:" + CANCEL_HINT, None)


async def add_brand(update, context):
    name = update.message.text.strip()
    if not name:
        return
    pool = await db()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM brands WHERE LOWER(name)=LOWER($1)", name)
        if exists:
            await update.message.reply_text("❌ این برند قبلاً وجود دارد."); return
        await conn.execute("INSERT INTO brands(name) VALUES($1)", name)
    context.user_data["state"] = None
    await update.message.reply_text(f"✅ برند «{name}» اضافه شد.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏷 مدیریت برندها", callback_data="adm_brands")]]))


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
    keyboard = [[InlineKeyboardButton("➕ افزودن محصول", callback_data="adm_add_product")]]
    for p in products:
        icon = "🟢" if p["active"] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{icon} {p['name']} | {p['stock']} عدد", callback_data=f"adm_product:{p['id']}")])
    nav = pagination_row("adm_products", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")])
    await safe_edit(query, "📦 مدیریت محصولات:", InlineKeyboardMarkup(keyboard))


async def admin_product_details(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT p.*,b.name AS brand FROM products p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=$1", product_id)
        image_count = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id) if p else 0
    if not p:
        await safe_edit(query, "❌ محصول پیدا نشد.", back_button("adm_products")); return
    status = "🟢 فعال" if p["active"] else "🔴 غیرفعال"
    price = p["sale_price"] if 0 < p["sale_price"] < p["price"] else p["price"]
    text = (f"📦 {p['name']}\n\n🏷 برند: {p['brand'] or '---'}\n📌 وضعیت: {status}\n💰 قیمت: {price:,} تومان\n"
            f"📏 سایز: {p['sizes'] or '---'}\n📦 موجودی: {p['stock']}\n🖼 عکس: {image_count}\n"
            f"👟 دسته: {p['category'] or '---'}\n🔎 کلمات: {p['keywords'] or '---'}")
    keyboard = [
        [InlineKeyboardButton("🔴 غیرفعال‌سازی" if p["active"] else "🟢 فعال‌سازی", callback_data=f"adm_product_toggle:{product_id}")],
        [InlineKeyboardButton("✏️ ویرایش محصول", callback_data=f"adm_pedit_menu:{product_id}")],
        [InlineKeyboardButton("🗑 حذف کامل محصول", callback_data=f"adm_product_delete:{product_id}")],
        [InlineKeyboardButton("🔙 محصولات", callback_data="adm_products")],
    ]
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def toggle_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("UPDATE products SET active=NOT active WHERE id=$1 RETURNING active", product_id)
    if not p:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    await query.answer("✅ وضعیت محصول تغییر کرد.")
    await admin_product_details(query, product_id)


async def confirm_product_delete(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT name FROM products WHERE id=$1", product_id)
        cart_count = await conn.fetchval("SELECT COUNT(*) FROM cart_items WHERE product_id=$1", product_id) if p else 0
        order_count = await conn.fetchval("SELECT COUNT(*) FROM order_items WHERE product_id=$1", product_id) if p else 0
    if not p:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    warn = ""
    if cart_count:
        warn += f"\n🛒 این محصول در {cart_count} سبد خرید کاربران است؛ با حذف، از سبدها هم حذف می‌شود."
    if order_count:
        warn += f"\n🧾 این محصول در {order_count} سفارش قبلی ثبت شده؛ اطلاعات آن سفارش‌ها حفظ می‌شود."
    await safe_edit(query, f"⚠️ حذف «{p['name']}» و تمام عکس‌هایش قطعی است.{warn}\n\nادامه می‌دهی؟", InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"adm_product_delete_confirm:{product_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"adm_product:{product_id}")],
    ]))


async def delete_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval("DELETE FROM products WHERE id=$1 RETURNING name", product_id)
    if not deleted:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    await query.answer("✅ محصول و عکس‌هایش حذف شدند.")
    await admin_products(query)


# =========================================================
# ADMIN PRODUCTS - EDIT (fields / brand / images)
# =========================================================
async def product_edit_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT id,name FROM products WHERE id=$1", product_id)
    if not p:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    keyboard = [
        [InlineKeyboardButton(FIELD_LABELS["name"], callback_data=f"adm_pset:name:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["description"], callback_data=f"adm_pset:description:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["price"], callback_data=f"adm_pset:price:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["sale"], callback_data=f"adm_pset:sale:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["sizes"], callback_data=f"adm_pset:sizes:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["stock"], callback_data=f"adm_pset:stock:{product_id}")],
        [InlineKeyboardButton(FIELD_LABELS["category"], callback_data=f"adm_pset:category:{product_id}"),
         InlineKeyboardButton(FIELD_LABELS["keywords"], callback_data=f"adm_pset:keywords:{product_id}")],
        [InlineKeyboardButton("🏷 تغییر برند", callback_data=f"adm_pbrand:{product_id}")],
        [InlineKeyboardButton("🖼 مدیریت عکس‌ها", callback_data=f"adm_pimages:{product_id}")],
        [InlineKeyboardButton("🔙 برگشت به محصول", callback_data=f"adm_product:{product_id}")],
    ]
    await safe_edit(query, f"✏️ ویرایش محصول: {p['name']}\n\nکدام بخش را ویرایش می‌کنی؟", InlineKeyboardMarkup(keyboard))


async def product_field_prompt(query, context, field, product_id):
    if field not in FIELD_PROMPTS:
        await query.answer("❌ فیلد نامعتبر.", show_alert=True); return
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
            await update.message.reply_text("❌ نام محصول کوتاه است."); return
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET name=$1 WHERE id=$2", text, product_id)
    elif field == "description":
        value = "" if text == "ندارد" else text
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET description=$1 WHERE id=$2", value, product_id)
    elif field == "price":
        try:
            value = int(text.replace(",", ""))
            assert value >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET price=$1 WHERE id=$2", value, product_id)
    elif field == "sale":
        try:
            value = int(text.replace(",", ""))
            assert value >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
        async with pool.acquire() as conn:
            current_price = await conn.fetchval("SELECT price FROM products WHERE id=$1", product_id)
            if value and current_price is not None and value >= current_price:
                await update.message.reply_text("❌ قیمت حراج باید از قیمت اصلی کمتر باشد یا 0 باشد."); return
            await conn.execute("UPDATE products SET sale_price=$1 WHERE id=$2", value, product_id)
    elif field == "sizes":
        async with pool.acquire() as conn:
            await conn.execute("UPDATE products SET sizes=$1 WHERE id=$2", text, product_id)
    elif field == "stock":
        try:
            value = int(text)
            assert value >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
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
    await update.message.reply_text("✅ محصول بروزرسانی شد.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("📦 مشاهده محصول", callback_data=f"adm_product:{product_id}")]]))


async def product_brand_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT id FROM products WHERE id=$1", product_id)
        brands = await conn.fetch("SELECT id,name,active FROM brands ORDER BY name")
    if not p:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    if not brands:
        await query.answer("❌ هیچ برندی وجود ندارد؛ اول یک برند بساز.", show_alert=True); return
    keyboard = [[InlineKeyboardButton(("🟢 " if b["active"] else "🔴 ") + b["name"],
                                       callback_data=f"adm_pbrand_set:{b['id']}:{product_id}")] for b in brands]
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"adm_pedit_menu:{product_id}")])
    await safe_edit(query, "🏷 برند جدید را انتخاب کن:", InlineKeyboardMarkup(keyboard))


async def product_brand_set(query, brand_id, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        updated = await conn.fetchval("UPDATE products SET brand_id=$1 WHERE id=$2 RETURNING id", brand_id, product_id)
    if not updated:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    await query.answer("✅ برند محصول تغییر کرد.")
    await admin_product_details(query, product_id)


async def product_images_menu(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT name FROM products WHERE id=$1", product_id)
        images = await conn.fetch("SELECT id,file_id,position FROM product_images WHERE product_id=$1 ORDER BY position", product_id)
    if not p:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    try:
        await query.message.delete()
    except Exception:
        pass
    chat = query.message.chat
    for img in images:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 حذف این عکس", callback_data=f"adm_pimg_del:{img['id']}:{product_id}")]])
        try:
            await chat.send_photo(photo=img["file_id"], caption=f"عکس شماره {img['position']}", reply_markup=kb)
        except Exception as e:
            print("IMG SEND ERROR:", e)
    footer_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن عکس جدید", callback_data=f"adm_pimg_add:{product_id}")],
        [InlineKeyboardButton("🔙 برگشت به ویرایش", callback_data=f"adm_pedit_menu:{product_id}")],
    ])
    await chat.send_message(f"🖼 مدیریت عکس‌های «{p['name']}»\n\nتعداد فعلی: {len(images)} از ۵", reply_markup=footer_kb)


async def product_image_delete(query, image_id, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id)
        if total <= 1:
            await query.answer("❌ حداقل یک عکس باید برای محصول باقی بماند؛ اول عکس جدید اضافه کن.", show_alert=True); return
        deleted = await conn.fetchval("DELETE FROM product_images WHERE id=$1 AND product_id=$2 RETURNING id", image_id, product_id)
    if not deleted:
        await query.answer("❌ عکس پیدا نشد.", show_alert=True); return
    await query.answer("✅ عکس حذف شد.")
    try:
        await query.message.delete()
    except Exception:
        pass


async def product_image_add_start(query, context, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM product_images WHERE product_id=$1", product_id)
    if count >= 5:
        await query.answer("❌ این محصول ۵ عکس دارد؛ اول یکی را حذف کن.", show_alert=True); return
    context.user_data["state"] = f"pedit_image_add:{product_id}"
    await query.answer()
    await query.message.reply_text("🖼 عکس جدید را ارسال کن:" + CANCEL_HINT)


# =========================================================
# PRODUCT ADD (NEW)
# =========================================================
async def add_product_start(query, context):
    context.user_data["product"] = {}
    context.user_data["state"] = "product_name"
    await safe_edit(query, "👟 نام مدل را ارسال کن:" + CANCEL_HINT, None)


async def product_add_message(update, context):
    state = context.user_data.get("state")
    data = context.user_data.setdefault("product", {})
    if state == "product_name":
        name = update.message.text.strip()
        if len(name) < 2:
            await update.message.reply_text("❌ نام محصول کوتاه است."); return
        data["name"] = name
        context.user_data["state"] = "product_brand"
        pool = await db()
        async with pool.acquire() as conn:
            brands = await conn.fetch("SELECT id,name FROM brands WHERE active=TRUE ORDER BY name")
        if not brands:
            context.user_data["state"] = None
            await update.message.reply_text("❌ اول حداقل یک برند فعال بساز.")
            return
        await update.message.reply_text("🏷 برند محصول را انتخاب کن:", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(b["name"], callback_data=f"adm_newbrand:{b['id']}")] for b in brands]))
        return
    if state == "product_description":
        data["description"] = "" if update.message.text.strip() == "ندارد" else update.message.text.strip()
        context.user_data["state"] = "product_price"
        await update.message.reply_text("💰 قیمت اصلی را فقط عدد وارد کن:" + CANCEL_HINT); return
    if state == "product_price":
        try:
            data["price"] = int(update.message.text.replace(",", ""))
            assert data["price"] >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
        context.user_data["state"] = "product_sale"
        await update.message.reply_text("🔥 قیمت حراج را وارد کن؛ اگر ندارد 0:" + CANCEL_HINT); return
    if state == "product_sale":
        try:
            data["sale_price"] = int(update.message.text.replace(",", ""))
            assert data["sale_price"] >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
        if data["sale_price"] and data["sale_price"] >= data["price"]:
            await update.message.reply_text("❌ قیمت حراج باید از قیمت اصلی کمتر باشد یا 0 باشد."); return
        context.user_data["state"] = "product_sizes"
        await update.message.reply_text("📏 سایزها را با کاما جدا کن؛ مثال 40,41,42,43,44,45:" + CANCEL_HINT); return
    if state == "product_sizes":
        data["sizes"] = update.message.text.strip()
        context.user_data["state"] = "product_stock"
        await update.message.reply_text("📦 تعداد موجودی کل را وارد کن:" + CANCEL_HINT); return
    if state == "product_stock":
        try:
            data["stock"] = int(update.message.text)
            assert data["stock"] >= 0
        except Exception:
            await update.message.reply_text("❌ فقط عدد صحیح نامنفی وارد کن."); return
        context.user_data["state"] = "product_category"
        await update.message.reply_text("👟 دسته‌بندی/کاربرد محصول را بنویس:" + CANCEL_HINT); return
    if state == "product_category":
        data["category"] = update.message.text.strip()
        context.user_data["state"] = "product_keywords"
        await update.message.reply_text("🔎 کلمات جستجو را با کاما بنویس:" + CANCEL_HINT); return
    if state == "product_keywords":
        data["keywords"] = update.message.text.strip()
        data["images"] = []
        context.user_data["state"] = "product_images"
        await update.message.reply_text("🖼 عکس‌ها را یکی‌یکی بفرست؛ حداکثر ۵ عکس. وقتی تمام شد بنویس «تمام»." + CANCEL_HINT); return
    if state == "product_images" and update.message.text and update.message.text.strip() == "تمام":
        await save_product(update, context); return


async def save_product(update, context):
    data = context.user_data.get("product", {})
    if not data.get("images"):
        await update.message.reply_text("❌ حداقل یک عکس برای محصول بفرست."); return
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
        f"✅ محصول «{name}» اضافه شد.\n\n🆔 شماره محصول: {product_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="adm_products")],
            [InlineKeyboardButton("👑 پنل", callback_data="adm_panel")],
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
    keyboard.append([InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")])
    await safe_edit(query, "🧾 سفارش‌های فروشگاه:", InlineKeyboardMarkup(keyboard))


async def admin_order_details(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
        items = await conn.fetch("SELECT * FROM order_items WHERE order_id=$1", order_id) if order else []
    if not order:
        await safe_edit(query, "❌ سفارش پیدا نشد.", back_button("adm_orders")); return
    text = (f"🧾 سفارش #{order_id}\n\n👤 {order['customer_name']}\n📱 {order['phone']}\n"
            f"📍 {order['address']}\n📮 {order['postal_code']}\n\n")
    for i in items:
        text += f"👟 {i['product_name']}\n📏 سایز: {i['size'] or '---'}\n🔢 تعداد: {i['quantity']}\n💰 قیمت واحد: {i['price']:,}\n\n"
    text += (f"🚚 ارسال: {order['shipping_cost']:,}\n💵 مجموع: {order['total']:,}\n"
             f"📌 وضعیت: {STATUS_LABELS.get(order['status'], order['status'])}")
    keyboard = []
    if order["status"] == "waiting_admin":
        keyboard.append([
            InlineKeyboardButton("✅ تأیید پرداخت", callback_data=f"adm_order_approve:{order_id}"),
            InlineKeyboardButton("❌ رد پرداخت", callback_data=f"adm_order_reject:{order_id}"),
        ])
    if order["status"] == "paid":
        keyboard.append([InlineKeyboardButton("🚚 ثبت ارسال سفارش", callback_data=f"adm_order_status:shipped:{order_id}")])
    if order["status"] == "shipped":
        keyboard.append([InlineKeyboardButton("🏁 ثبت تکمیل سفارش", callback_data=f"adm_order_status:completed:{order_id}")])
    if order["receipt_file_id"]:
        keyboard.append([InlineKeyboardButton("🧾 مشاهده رسید", callback_data=f"adm_order_receipt:{order_id}")])
    keyboard.append([InlineKeyboardButton("🔙 سفارش‌ها", callback_data="adm_orders")])
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))


async def admin_order_receipt(query, order_id):
    pool = await db()
    async with pool.acquire() as conn:
        file_id = await conn.fetchval("SELECT receipt_file_id FROM orders WHERE id=$1", order_id)
    if not file_id:
        await query.answer("❌ رسیدی ثبت نشده.", show_alert=True); return
    await query.answer()
    await query.message.chat.send_photo(photo=file_id, caption=f"🧾 رسید سفارش #{order_id}")


async def set_order_status(query, context, order_id, status):
    pool = await db()
    order = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not order:
                await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
            if order["status"] != "waiting_admin":
                await query.answer("⚠️ این سفارش قبلاً بررسی شده.", show_alert=True); return
            await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)
    msg = (f"✅ پرداخت سفارش #{order_id} تأیید شد.\n\n📦 سفارش شما برای ارسال آماده شد."
           if status == "paid" else
           f"❌ پرداخت سفارش #{order_id} تأیید نشد.\n\nلطفاً رسید پرداخت را بررسی و دوباره ارسال کنید.")
    try:
        await context.bot.send_message(chat_id=order["telegram_id"], text=msg)
    except Exception as e:
        print("CUSTOMER MESSAGE ERROR:", e)
    await query.answer("✅ وضعیت سفارش ثبت شد.")
    await admin_order_details(query, order_id)


async def set_order_status_generic(query, context, status, order_id):
    valid_transitions = {"paid": ("shipped",), "shipped": ("completed",)}
    pool = await db()
    order = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not order:
                await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
            if status not in valid_transitions.get(order["status"], ()):
                await query.answer("⚠️ این تغییر وضعیت در حال حاضر مجاز نیست.", show_alert=True); return
            await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)
    labels = {"shipped": "🚚 سفارش شما ارسال شد.", "completed": "🏁 سفارش شما تکمیل شد."}
    try:
        await context.bot.send_message(chat_id=order["telegram_id"], text=f"{labels.get(status, '')}\n\n🧾 سفارش #{order_id}")
    except Exception as e:
        print("CUSTOMER MESSAGE ERROR:", e)
    await query.answer("✅ وضعیت بروزرسانی شد.")
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
    text = f"👥 اعضای ربات\n\n👤 تعداد کل اعضا: {total}\n\n"
    for m in rows:
        created = m["created_at"].strftime("%Y-%m-%d") if m["created_at"] else "---"
        text += f"👤 {m['first_name'] or 'بدون نام'}\n🆔 {m['telegram_id']}\n📎 @{m['username'] or '---'}\n📅 {created}\n━━━━━━━━━━━━\n"
    if not rows:
        text += "موردی یافت نشد."
    keyboard = []
    nav = pagination_row("adm_members", offset, has_more)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")])
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
    text = (f"📊 آمار فروشگاه\n\n👥 کاربران: {users_count}\n📦 محصولات فعال: {products_count}\n"
            f"🏷 برندهای فعال: {brands_count}\n🧾 کل سفارش‌ها: {orders_count}\n⏳ در انتظار بررسی: {pending}\n"
            f"💰 مجموع فروش موفق: {revenue:,} تومان\n⚠️ محصولات رو به اتمام (≤۳ عدد): {low_stock}")
    await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")]]))


# =========================================================
# ADMIN BROADCAST
# =========================================================
async def admin_broadcast_start(query, context):
    context.user_data["state"] = "broadcast_message"
    await safe_edit(query, "📢 متن پیام همگانی را ارسال کن؛ برای همه کاربران ربات فرستاده می‌شود." + CANCEL_HINT, None)


async def admin_broadcast_send(update, context):
    text = update.message.text
    context.user_data["state"] = None
    pool = await db()
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT telegram_id FROM users")
    await update.message.reply_text(f"⏳ در حال ارسال به {len(users)} کاربر...")
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
        f"✅ ارسال شد: {sent}\n❌ ناموفق: {failed}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 پنل", callback_data="adm_panel")]]),
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
        f"⚙️ تنظیمات فروشگاه\n\n💳 کارت: {card or 'ثبت نشده'}\n🚚 ارسال: {shipping or '0'} تومان\n"
        f"📞 پشتیبانی: {support[:100]}\n📝 خوش‌آمدگویی: {welcome[:100]}"
    ), InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 تغییر شماره کارت", callback_data="adm_set_card")],
        [InlineKeyboardButton("🚚 تغییر هزینه ارسال", callback_data="adm_set_shipping")],
        [InlineKeyboardButton("📞 تغییر متن پشتیبانی", callback_data="adm_set_support")],
        [InlineKeyboardButton("📝 تغییر متن خوش‌آمدگویی", callback_data="adm_set_welcome")],
        [InlineKeyboardButton("🔙 پنل", callback_data="adm_panel")],
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
            await update.message.reply_text("❌ فقط عدد نامنفی وارد کن."); return
        await set_setting("shipping_cost", str(value))
    elif state == "set_support":
        await set_setting("support_text", update.message.text)
    elif state == "set_welcome":
        await set_setting("welcome_text", update.message.text)
    else:
        return
    context.user_data["state"] = None
    await update.message.reply_text("✅ تنظیمات ذخیره شد.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm_settings")]]))


async def change_password_start(query, context):
    context.user_data["state"] = "new_password"
    await safe_edit(query, "🔑 رمز جدید را ارسال کن (حداقل ۶ کاراکتر):" + CANCEL_HINT, None)


async def change_password(update, context):
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text("❌ رمز باید حداقل ۶ کاراکتر باشد."); return
    await set_setting("admin_password", hash_password(password))
    context.user_data["state"] = None
    await update.message.reply_text("✅ رمز با موفقیت تغییر کرد.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("👑 پنل", callback_data="adm_panel")]]))


# =========================================================
# ADMIN CALLBACK ROUTER
# =========================================================
async def admin_callback(query, context):
    if not is_admin(query.from_user.id):
        await query.answer("❌ دسترسی ندارید.", show_alert=True); return
    if not is_logged(context):
        await query.answer("❌ ابتدا /admin را بزن و وارد پنل شو.", show_alert=True); return

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
        await safe_edit(query, "🚪 از پنل مدیریت خارج شدید.", None)

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
            await query.answer("❌ فرایند افزودن محصول منقضی شده. دوباره شروع کن.", show_alert=True); return
        context.user_data["product"]["brand_id"] = int(data.split(":")[1])
        context.user_data["state"] = "product_description"
        await safe_edit(query, "📝 توضیحات محصول را بنویس؛ اگر نداری بنویس: ندارد" + CANCEL_HINT, None)

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
        await safe_edit(query, "💳 شماره کارت جدید را ارسال کن:" + CANCEL_HINT, None)
    elif data == "adm_set_shipping":
        context.user_data["state"] = "set_shipping"
        await safe_edit(query, "🚚 هزینه ارسال را به تومان وارد کن:" + CANCEL_HINT, None)
    elif data == "adm_set_support":
        context.user_data["state"] = "set_support"
        await safe_edit(query, "📞 متن جدید پشتیبانی را ارسال کن:" + CANCEL_HINT, None)
    elif data == "adm_set_welcome":
        context.user_data["state"] = "set_welcome"
        await safe_edit(query, "📝 متن جدید خوش‌آمدگویی را ارسال کن:" + CANCEL_HINT, None)


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
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=admin_menu_markup())
        else:
            await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=await main_menu())
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
            await update.message.reply_text("❌ لطفاً یک عکس ارسال کن.")
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
            await update.message.reply_text("⚠️ حداکثر ۵ عکس مجاز است. برای اتمام بنویس «تمام»."); return
        images.append(update.message.photo[-1].file_id)
        await update.message.reply_text(f"✅ عکس {len(images)} دریافت شد.\nعکس بعدی را بفرست یا بنویس «تمام».")
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
                await update.message.reply_text("❌ ظرفیت ۵ عکس تکمیل شده است."); return
            next_pos = (await conn.fetchval("SELECT COALESCE(MAX(position),0) FROM product_images WHERE product_id=$1", product_id)) + 1
            await conn.execute("INSERT INTO product_images(product_id,file_id,position) VALUES($1,$2,$3)",
                                product_id, update.message.photo[-1].file_id, next_pos)
        context.user_data["state"] = None
        await update.message.reply_text("✅ عکس اضافه شد.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🖼 مدیریت عکس‌ها", callback_data=f"adm_pimages:{product_id}")]]))
        return
    if state and state.startswith("receipt:"):
        await receive_receipt(update, context)


async def error_handler(update, context):
    print("❌ ERROR:", repr(context.error))
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ خطایی رخ داد. لطفاً دوباره تلاش کن یا /start را بزن.",
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

print("🚀 BOT STARTED")
app.run_polling()
