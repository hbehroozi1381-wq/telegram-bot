import os
import hashlib
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# =========================================================
# DATABASE
# =========================================================
async def db():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return DB_POOL


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
        defaults = {
            "card_number": "",
            "shipping_cost": "0",
            "support_text": "📞 برای پشتیبانی با ما در ارتباط باشید.",
            "admin_password": hashlib.sha256(DEFAULT_ADMIN_PASSWORD.encode()).hexdigest(),
        }
        for key, value in defaults.items():
            await conn.execute("""
                INSERT INTO settings(key,value) VALUES($1,$2)
                ON CONFLICT(key) DO NOTHING
            """, key, value)

    print("✅ DATABASE READY")


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


def admin_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="adm_products")],
        [InlineKeyboardButton("🏷 مدیریت برندها", callback_data="adm_brands")],
        [InlineKeyboardButton("🧾 سفارش‌ها", callback_data="adm_orders")],
        [InlineKeyboardButton("👥 اعضای ربات", callback_data="adm_members")],
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
    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\nاز منوی زیر انتخاب کنید:",
        reply_markup=await main_menu()
    )


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
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="home")])
    await query.edit_message_text("🛍 محصولات فروشگاه\n\n🔥 حراج\n🏷 برند موردنظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))


async def brand_products(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        brand = await conn.fetchrow("SELECT name FROM brands WHERE id=$1 AND active=TRUE", brand_id)
        products = await conn.fetch("""
            SELECT id,name,price,sale_price FROM products
            WHERE brand_id=$1 AND active=TRUE AND stock>0 ORDER BY id DESC
        """, brand_id)
    if not brand:
        await query.edit_message_text("❌ برند پیدا نشد.", reply_markup=back_button("products")); return
    if not products:
        await query.edit_message_text(f"🏷 {brand['name']}\n\nفعلاً محصول موجودی ندارد.", reply_markup=back_button("products")); return
    keyboard = []
    for p in products:
        price = p['sale_price'] if 0 < p['sale_price'] < p['price'] else p['price']
        prefix = "🔥" if price != p['price'] else "👟"
        keyboard.append([InlineKeyboardButton(f"{prefix} {p['name']} | {price:,} تومان", callback_data=f"product:{p['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 برندها", callback_data="products")])
    await query.edit_message_text(f"🏷 {brand['name']}\n\nمدل موردنظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))


async def sale_products(query):
    pool = await db()
    async with pool.acquire() as conn:
        products = await conn.fetch("""
            SELECT id,name,sale_price FROM products
            WHERE active=TRUE AND stock>0 AND sale_price>0 AND sale_price<price ORDER BY id DESC
        """)
    if not products:
        await query.edit_message_text("🔥 حراج\n\nفعلاً محصولی در حراج نیست.", reply_markup=back_button("products")); return
    keyboard = [[InlineKeyboardButton(f"🔥 {p['name']} | {p['sale_price']:,} تومان", callback_data=f"product:{p['id']}")] for p in products]
    keyboard.append([InlineKeyboardButton("🔙 محصولات", callback_data="products")])
    await query.edit_message_text("🔥 محصولات حراج:", reply_markup=InlineKeyboardMarkup(keyboard))


async def product_details(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("""
            SELECT p.*,b.name AS brand_name FROM products p
            LEFT JOIN brands b ON b.id=p.brand_id
            WHERE p.id=$1 AND p.active=TRUE
        """, product_id)
        images = await conn.fetch("SELECT file_id FROM product_images WHERE product_id=$1 ORDER BY position LIMIT 5", product_id)
    if not product:
        await query.edit_message_text("❌ محصول پیدا نشد یا غیرفعال است.", reply_markup=back_button("products")); return
    price = product['sale_price'] if 0 < product['sale_price'] < product['price'] else product['price']
    price_text = f"💰 قیمت: {price:,} تومان"
    if price != product['price']:
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
                await query.message.chat.send_photo(photo=image['file_id'], caption=text if i == 0 else None, reply_markup=markup if i == 0 else None)
            return
        except Exception as e:
            print("PHOTO ERROR:", e)
    await query.edit_message_text(text, reply_markup=markup)


# =========================================================
# CART / CHECKOUT
# =========================================================
async def add_to_cart(update, product_id):
    query = update.callback_query
    pool = await db()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("SELECT * FROM products WHERE id=$1 AND active=TRUE", product_id)
    if not product:
        await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
    if product['stock'] <= 0:
        await query.answer("❌ این محصول ناموجود است.", show_alert=True); return
    sizes = [x.strip() for x in (product['sizes'] or '').split(',') if x.strip()]
    if len(sizes) > 1:
        keyboard = [[InlineKeyboardButton(f"📏 سایز {s}", callback_data=f"addsize:{product_id}:{s}")] for s in sizes]
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"product:{product_id}")])
        await query.edit_message_text("📏 سایز موردنظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)); return
    await insert_cart(update, product_id, sizes[0] if sizes else '')


async def insert_cart(update, product_id, size):
    telegram_id = update.effective_user.id
    query = update.callback_query
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            product = await conn.fetchrow("SELECT name,stock FROM products WHERE id=$1 AND active=TRUE", product_id)
            if not product:
                await query.answer("❌ محصول پیدا نشد.", show_alert=True); return
            current = await conn.fetchval("SELECT quantity FROM cart_items WHERE telegram_id=$1 AND product_id=$2 AND size=$3", telegram_id, product_id, size) or 0
            if current >= product['stock']:
                await query.answer("❌ بیشتر از موجودی نمی‌توانی اضافه کنی.", show_alert=True); return
            await conn.execute("""
                INSERT INTO cart_items(telegram_id,product_id,size,quantity) VALUES($1,$2,$3,1)
                ON CONFLICT(telegram_id,product_id,size) DO UPDATE SET quantity=cart_items.quantity+1
            """, telegram_id, product_id, size)
    await query.edit_message_text(f"✅ {product['name']}\n\nبه سبد خرید اضافه شد.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 سبد خرید", callback_data="cart")],
        [InlineKeyboardButton("🛍 ادامه خرید", callback_data="products")],
    ]))


async def show_cart(query):
    pool = await db()
    async with pool.acquire() as conn:
        items = await conn.fetch("""
            SELECT c.id,c.product_id,c.size,c.quantity,p.name,p.price,p.sale_price,p.stock,p.active
            FROM cart_items c JOIN products p ON p.id=c.product_id
            WHERE c.telegram_id=$1 ORDER BY c.id
        """, query.from_user.id)
    if not items:
        await query.edit_message_text("🛒 سبد خرید خالی است.", reply_markup=back_button("home")); return
    total = 0; text = "🛒 سبد خرید شما:\n\n"; valid_count = 0
    for item in items:
        if not item['active'] or item['stock'] <= 0:
            continue
        qty = min(item['quantity'], item['stock'])
        price = item['sale_price'] if 0 < item['sale_price'] < item['price'] else item['price']
        subtotal = price * qty; total += subtotal; valid_count += 1
        text += f"👟 {item['name']}\n📏 سایز: {item['size'] or '---'}\n🔢 تعداد: {qty}\n💰 {subtotal:,} تومان\n\n"
    if valid_count == 0:
        await query.edit_message_text("🛒 سبد خرید خالی است یا محصولات آن دیگر موجود نیستند.", reply_markup=back_button("home")); return
    shipping = int(await setting('shipping_cost') or 0); final_total = total + shipping
    text += f"🛍 جمع کالاها: {total:,} تومان\n🚚 ارسال: {shipping:,} تومان\n💵 مبلغ نهایی: {final_total:,} تومان"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 ثبت سفارش", callback_data="checkout")],
        [InlineKeyboardButton("🛍 ادامه خرید", callback_data="products")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="home")],
    ]))


async def checkout_start(query, context):
    pool = await db()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM cart_items WHERE telegram_id=$1", query.from_user.id)
    if not count:
        await query.edit_message_text("🛒 سبد خرید خالی است.", reply_markup=back_button("home")); return
    context.user_data['state'] = 'customer_name'
    await query.edit_message_text("👤 نام و نام خانوادگی را ارسال کنید:")


async def checkout_message(update, context):
    state = context.user_data.get('state'); text = update.message.text.strip()
    if state == 'customer_name':
        if len(text) < 3: await update.message.reply_text("❌ نام را کامل وارد کنید."); return
        context.user_data['customer_name'] = text; context.user_data['state'] = 'phone'; await update.message.reply_text("📱 شماره موبایل را ارسال کنید:"); return
    if state == 'phone':
        if len(text) < 7: await update.message.reply_text("❌ شماره موبایل معتبر وارد کنید."); return
        context.user_data['phone'] = text; context.user_data['state'] = 'address'; await update.message.reply_text("📍 آدرس کامل را ارسال کنید:"); return
    if state == 'address':
        if len(text) < 10: await update.message.reply_text("❌ آدرس را کامل‌تر وارد کنید."); return
        context.user_data['address'] = text; context.user_data['state'] = 'postal'; await update.message.reply_text("📮 کد پستی ۱۰ رقمی را ارسال کنید:"); return
    if state == 'postal':
        postal = ''.join(x for x in text if x.isdigit())
        if len(postal) != 10: await update.message.reply_text("❌ کد پستی باید ۱۰ رقم باشد."); return
        context.user_data['postal_code'] = postal; context.user_data['state'] = None; await create_order(update, context)


async def create_order(update, context):
    telegram_id = update.effective_user.id
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            items = await conn.fetch("""
                SELECT c.product_id,c.size,c.quantity,p.name,p.price,p.sale_price,p.stock,p.active
                FROM cart_items c JOIN products p ON p.id=c.product_id
                WHERE c.telegram_id=$1 FOR UPDATE
            """, telegram_id)
            if not items:
                await update.message.reply_text("❌ سبد خرید خالی است."); return
            total = 0
            for item in items:
                if not item['active'] or item['stock'] < item['quantity']:
                    await update.message.reply_text(f"❌ موجودی «{item['name']}» کافی نیست."); return
                price = item['sale_price'] if 0 < item['sale_price'] < item['price'] else item['price']
                total += price * item['quantity']
            shipping = int(await conn.fetchval("SELECT value FROM settings WHERE key='shipping_cost'") or 0)
            final_total = total + shipping
            order_id = await conn.fetchval("""
                INSERT INTO orders(telegram_id,customer_name,phone,address,postal_code,shipping_cost,total,status)
                VALUES($1,$2,$3,$4,$5,$6,$7,'waiting_payment') RETURNING id
            """, telegram_id, context.user_data['customer_name'], context.user_data['phone'], context.user_data['address'], context.user_data['postal_code'], shipping, final_total)
            for item in items:
                price = item['sale_price'] if 0 < item['sale_price'] < item['price'] else item['price']
                await conn.execute("""
                    INSERT INTO order_items(order_id,product_id,product_name,size,quantity,price)
                    VALUES($1,$2,$3,$4,$5,$6)
                """, order_id, item['product_id'], item['name'], item['size'], item['quantity'], price)
                await conn.execute("UPDATE products SET stock=stock-$1 WHERE id=$2", item['quantity'], item['product_id'])
            await conn.execute("DELETE FROM cart_items WHERE telegram_id=$1", telegram_id)
    card = await setting('card_number')
    payment = f"💳 شماره کارت:\n`{card}`\n\n" if card else "⚠️ شماره کارت هنوز ثبت نشده.\n\n"
    await update.message.reply_text(f"✅ سفارش شما ثبت شد.\n\n🧾 شماره سفارش: #{order_id}\n💰 مبلغ نهایی: {final_total:,} تومان\n\n{payment}بعد از پرداخت، عکس رسید را همینجا ارسال کنید.", parse_mode='Markdown')
    context.user_data['state'] = f'receipt:{order_id}'


# =========================================================
# RECEIPT / ORDERS
# =========================================================
async def receive_receipt(update, context):
    state = context.user_data.get('state', '')
    if not state.startswith('receipt:'): return
    if not update.message.photo:
        await update.message.reply_text("❌ لطفاً عکس رسید را ارسال کنید."); return
    order_id = int(state.split(':')[1]); file_id = update.message.photo[-1].file_id
    pool = await db()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1 AND telegram_id=$2", order_id, update.effective_user.id)
        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد."); return
        await conn.execute("UPDATE orders SET receipt_file_id=$1,status='waiting_admin' WHERE id=$2", file_id, order_id)
    context.user_data['state'] = None
    await update.message.reply_text("🧾 رسید دریافت شد.\n\n⏳ بعد از بررسی پرداخت، نتیجه برای شما ارسال می‌شود.")
    try:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=(f"🧾 رسید جدید\n\n🧾 سفارش: #{order_id}\n💰 مبلغ: {order['total']:,} تومان\n👤 مشتری: {order['customer_name']}\n📱 تلفن: {order['phone']}\n📍 آدرس: {order['address']}\n📮 کد پستی: {order['postal_code']}"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ تأیید پرداخت', callback_data=f'approve:{order_id}'), InlineKeyboardButton('❌ رد پرداخت', callback_data=f'reject:{order_id}')]]))
    except Exception as e: print('ADMIN RECEIPT ERROR:', e)


async def customer_orders(query):
    pool = await db()
    async with pool.acquire() as conn:
        orders = await conn.fetch("SELECT id,total,status,created_at FROM orders WHERE telegram_id=$1 ORDER BY id DESC LIMIT 20", query.from_user.id)
    if not orders:
        await query.edit_message_text("📦 هنوز سفارشی ثبت نکرده‌اید.", reply_markup=back_button('home')); return
    statuses = {'waiting_payment':'⏳ منتظر پرداخت','waiting_admin':'🔎 در انتظار بررسی','paid':'✅ پرداخت تأیید شد','rejected':'❌ پرداخت رد شد','shipped':'🚚 ارسال شد','completed':'🏁 تکمیل شد'}
    text = '📦 سفارش‌های شما:\n\n'
    for o in orders: text += f"🧾 سفارش #{o['id']}\n💰 {o['total']:,} تومان\n📌 {statuses.get(o['status'],o['status'])}\n\n"
    await query.edit_message_text(text, reply_markup=back_button('home'))


# =========================================================
# ADMIN LOGIN/PANEL
# =========================================================
async def admin_command(update, context):
    if not is_admin(update.effective_user.id): await update.message.reply_text('❌ شما دسترسی مدیریت ندارید.'); return
    context.user_data.clear(); context.user_data['admin_id'] = ADMIN_ID; context.user_data['state'] = 'admin_password'
    await update.message.reply_text('🔐 رمز پنل مدیریت را وارد کنید:')


async def admin_password(update, context):
    if not is_admin(update.effective_user.id) or context.user_data.get('state') != 'admin_password': return
    hashed = hashlib.sha256(update.message.text.strip().encode()).hexdigest()
    if hashed != await setting('admin_password'):
        await update.message.reply_text('❌ رمز اشتباه است.'); return
    context.user_data['admin_logged'] = True; context.user_data['admin_id'] = ADMIN_ID; context.user_data['state'] = None
    await update.message.reply_text('👑 پنل مدیریت فروشگاه\n\nاز منوی زیر مدیریت کن:', reply_markup=admin_menu_markup())


async def admin_panel_callback(query, context):
    await query.edit_message_text('👑 پنل مدیریت', reply_markup=admin_menu_markup())


# =========================================================
# ADMIN BRANDS - FIXED
# =========================================================
async def admin_brands(query):
    pool = await db()
    async with pool.acquire() as conn:
        brands = await conn.fetch("""
            SELECT b.id,b.name,b.active,COUNT(p.id) AS product_count
            FROM brands b LEFT JOIN products p ON p.brand_id=b.id
            GROUP BY b.id ORDER BY b.id DESC
        """)
    keyboard = [[InlineKeyboardButton('➕ افزودن برند', callback_data='adm_add_brand')]]
    for b in brands:
        icon = '🟢' if b['active'] else '🔴'
        keyboard.append([InlineKeyboardButton(f"{icon} {b['name']} | {b['product_count']} محصول", callback_data=f"adm_brand:{b['id']}")])
    keyboard.append([InlineKeyboardButton('🔙 پنل', callback_data='adm_panel')])
    await query.edit_message_text('🏷 مدیریت برندها:', reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_brand_details(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT id,name,active FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await query.edit_message_text('❌ برند پیدا نشد.', reply_markup=back_button('adm_brands')); return
    status = '🟢 فعال' if b['active'] else '🔴 غیرفعال'
    keyboard = [
        [InlineKeyboardButton('🔴 غیرفعال‌سازی' if b['active'] else '🟢 فعال‌سازی', callback_data=f"brandtoggle:{brand_id}")],
        [InlineKeyboardButton('🗑 حذف کامل برند', callback_data=f"branddelete:{brand_id}")],
        [InlineKeyboardButton('🔙 برندها', callback_data='adm_brands')],
    ]
    await query.edit_message_text(f"🏷 برند: {b['name']}\n\n📌 وضعیت: {status}\n📦 تعداد محصولات: {count}\n\n⚠️ غیرفعال‌سازی امن است و محصولات را حذف نمی‌کند.\n🗑 حذف کامل فقط وقتی ممکن است که هیچ محصولی به برند متصل نباشد.", reply_markup=InlineKeyboardMarkup(keyboard))


async def toggle_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE brands SET active=NOT active WHERE id=$1 RETURNING name,active", brand_id)
    if not row:
        await query.answer('❌ برند پیدا نشد.', show_alert=True); return
    await query.answer('✅ وضعیت برند تغییر کرد.')
    await admin_brand_details(query, brand_id)


async def confirm_brand_delete(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        b = await conn.fetchrow("SELECT name FROM brands WHERE id=$1", brand_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id) if b else 0
    if not b:
        await query.answer('❌ برند پیدا نشد.', show_alert=True); return
    if count:
        await query.answer('❌ اول برند را غیرفعال کن یا محصولاتش را مدیریت کن؛ تا وقتی محصول متصل دارد حذف نمی‌شود.', show_alert=True)
        return
    await query.edit_message_text(f"⚠️ حذف برند «{b['name']}» قطعی است. ادامه می‌دهی؟", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ بله، حذف شود', callback_data=f'branddeleteconfirm:{brand_id}')],
        [InlineKeyboardButton('❌ لغو', callback_data=f'adm_brand:{brand_id}')],
    ]))


async def delete_brand(query, brand_id):
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            count = await conn.fetchval('SELECT COUNT(*) FROM products WHERE brand_id=$1', brand_id)
            if count:
                await query.answer('❌ این برند هنوز محصول متصل دارد.', show_alert=True); return
            deleted = await conn.fetchval('DELETE FROM brands WHERE id=$1 RETURNING name', brand_id)
    if not deleted:
        await query.answer('❌ برند پیدا نشد.', show_alert=True); return
    await query.answer('✅ برند حذف شد.')
    await admin_brands(query)


async def add_brand_start(query, context):
    context.user_data['state'] = 'add_brand'; await query.edit_message_text('🏷 نام برند جدید را ارسال کن:')


async def add_brand(update, context):
    name = update.message.text.strip()
    if not name: return
    pool = await db()
    async with pool.acquire() as conn:
        exists = await conn.fetchval('SELECT id FROM brands WHERE LOWER(name)=LOWER($1)', name)
        if exists:
            await update.message.reply_text('❌ این برند قبلاً وجود دارد.'); return
        await conn.execute('INSERT INTO brands(name) VALUES($1)', name)
    context.user_data['state'] = None
    await update.message.reply_text(f'✅ برند «{name}» اضافه شد.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🏷 مدیریت برندها', callback_data='adm_brands')]]))


# =========================================================
# ADMIN PRODUCTS
# =========================================================
async def admin_products(query):
    pool = await db()
    async with pool.acquire() as conn:
        products = await conn.fetch("""
            SELECT p.id,p.name,p.price,p.sale_price,p.active,p.stock,b.name AS brand
            FROM products p LEFT JOIN brands b ON b.id=p.brand_id ORDER BY p.id DESC LIMIT 100
        """)
    keyboard = [[InlineKeyboardButton('➕ افزودن محصول', callback_data='adm_add_product')]]
    for p in products:
        icon = '🟢' if p['active'] else '🔴'
        keyboard.append([InlineKeyboardButton(f"{icon} {p['name']} | {p['stock']} عدد", callback_data=f'adm_product:{p["id"]}')])
    keyboard.append([InlineKeyboardButton('🔙 پنل', callback_data='adm_panel')])
    await query.edit_message_text('📦 مدیریت محصولات:', reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_product_details(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow('''SELECT p.*,b.name AS brand FROM products p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.id=$1''', product_id)
        image_count = await conn.fetchval('SELECT COUNT(*) FROM product_images WHERE product_id=$1', product_id) if p else 0
    if not p:
        await query.edit_message_text('❌ محصول پیدا نشد.', reply_markup=back_button('adm_products')); return
    status = '🟢 فعال' if p['active'] else '🔴 غیرفعال'
    price = p['sale_price'] if 0 < p['sale_price'] < p['price'] else p['price']
    text = (f"📦 {p['name']}\n\n🏷 برند: {p['brand'] or '---'}\n📌 وضعیت: {status}\n💰 قیمت: {price:,} تومان\n"
            f"📏 سایز: {p['sizes'] or '---'}\n📦 موجودی: {p['stock']}\n🖼 عکس: {image_count}\n👟 دسته: {p['category'] or '---'}\n🔎 کلمات: {p['keywords'] or '---'}")
    keyboard = [
        [InlineKeyboardButton('🔴 غیرفعال‌سازی' if p['active'] else '🟢 فعال‌سازی', callback_data=f'producttoggle:{product_id}')],
        [InlineKeyboardButton('✏️ ویرایش محصول', callback_data=f'prodedit:{product_id}')],
        [InlineKeyboardButton('🗑 حذف کامل محصول', callback_data=f'proddelete:{product_id}')],
        [InlineKeyboardButton('🔙 محصولات', callback_data='adm_products')],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def toggle_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow('UPDATE products SET active=NOT active WHERE id=$1 RETURNING active', product_id)
    if not p: await query.answer('❌ محصول پیدا نشد.', show_alert=True); return
    await query.answer('✅ وضعیت محصول تغییر کرد.')
    await admin_product_details(query, product_id)


async def confirm_product_delete(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        p = await conn.fetchrow('SELECT name FROM products WHERE id=$1', product_id)
    if not p: await query.answer('❌ محصول پیدا نشد.', show_alert=True); return
    await query.edit_message_text(f"⚠️ حذف «{p['name']}» و عکس‌هایش قطعی است. ادامه؟", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ بله، حذف شود', callback_data=f'proddeleteconfirm:{product_id}')],
        [InlineKeyboardButton('❌ لغو', callback_data=f'adm_product:{product_id}')],
    ]))


async def delete_product(query, product_id):
    pool = await db()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval('DELETE FROM products WHERE id=$1 RETURNING name', product_id)
    if not deleted: await query.answer('❌ محصول پیدا نشد.', show_alert=True); return
    await query.answer('✅ محصول حذف شد.')
    await admin_products(query)


# =========================================================
# PRODUCT ADD
# =========================================================
async def add_product_start(query, context):
    context.user_data['product'] = {}; context.user_data['state'] = 'product_name'; await query.edit_message_text('👟 نام مدل را ارسال کن:')


async def product_add_message(update, context):
    state = context.user_data.get('state'); data = context.user_data.setdefault('product', {})
    if state == 'product_name':
        name = update.message.text.strip()
        if len(name) < 2: await update.message.reply_text('❌ نام محصول کوتاه است.'); return
        data['name'] = name; context.user_data['state'] = 'product_brand'
        pool = await db()
        async with pool.acquire() as conn: brands = await conn.fetch('SELECT id,name FROM brands WHERE active=TRUE ORDER BY name')
        if not brands: context.user_data['state']=None; await update.message.reply_text('❌ اول حداقل یک برند بساز.'); return
        await update.message.reply_text('🏷 برند محصول را انتخاب کن:', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(b['name'], callback_data=f'choosebrand:{b["id"]}')] for b in brands])); return
    if state == 'product_description':
        data['description'] = '' if update.message.text.strip() == 'ندارد' else update.message.text.strip(); context.user_data['state']='product_price'; await update.message.reply_text('💰 قیمت اصلی را فقط عدد وارد کن:'); return
    if state == 'product_price':
        try: data['price']=int(update.message.text.replace(',','')); assert data['price']>=0
        except: await update.message.reply_text('❌ فقط عدد صحیح نامنفی وارد کن.'); return
        context.user_data['state']='product_sale'; await update.message.reply_text('🔥 قیمت حراج را وارد کن؛ اگر ندارد 0:'); return
    if state == 'product_sale':
        try: data['sale_price']=int(update.message.text.replace(',','')); assert data['sale_price']>=0
        except: await update.message.reply_text('❌ فقط عدد صحیح نامنفی وارد کن.'); return
        if data['sale_price'] and data['sale_price'] >= data['price']:
            await update.message.reply_text('❌ قیمت حراج باید از قیمت اصلی کمتر باشد یا 0 باشد.'); return
        context.user_data['state']='product_sizes'; await update.message.reply_text('📏 سایزها را با کاما جدا کن؛ مثال 40,41,42,43,44,45:'); return
    if state == 'product_sizes':
        data['sizes']=update.message.text.strip(); context.user_data['state']='product_stock'; await update.message.reply_text('📦 تعداد موجودی کل را وارد کن:'); return
    if state == 'product_stock':
        try: data['stock']=int(update.message.text); assert data['stock']>=0
        except: await update.message.reply_text('❌ فقط عدد صحیح نامنفی وارد کن.'); return
        context.user_data['state']='product_category'; await update.message.reply_text('👟 دسته‌بندی/کاربرد محصول را بنویس:'); return
    if state == 'product_category':
        data['category']=update.message.text.strip(); context.user_data['state']='product_keywords'; await update.message.reply_text('🔎 کلمات جستجو را با کاما بنویس:'); return
    if state == 'product_keywords':
        data['keywords']=update.message.text.strip(); data['images']=[]; context.user_data['state']='product_images'; await update.message.reply_text('🖼 عکس‌ها را یکی‌یکی بفرست؛ حداکثر ۵ عکس. وقتی تمام شد بنویس «تمام».'); return
    if state == 'product_images' and update.message.text and update.message.text.strip() == 'تمام': await save_product(update, context); return


async def save_product(update, context):
    data = context.user_data.get('product', {})
    if not data.get('images'): await update.message.reply_text('❌ حداقل یک عکس برای محصول بفرست.'); return
    pool = await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            product_id = await conn.fetchval('''INSERT INTO products(brand_id,name,description,price,sale_price,sizes,stock,category,keywords) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id''', data['brand_id'],data['name'],data.get('description',''),data['price'],data['sale_price'],data['sizes'],data['stock'],data.get('category',''),data.get('keywords',''))
            for pos,file_id in enumerate(data['images'][:5],1): await conn.execute('INSERT INTO product_images(product_id,file_id,position) VALUES($1,$2,$3)', product_id,file_id,pos)
    name=data['name']; context.user_data.clear()
    await update.message.reply_text(f'✅ محصول «{name}» اضافه شد.\n\n🆔 شماره محصول: {product_id}', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📦 مدیریت محصولات',callback_data='adm_products')],[InlineKeyboardButton('👑 پنل',callback_data='adm_panel')]]))


# =========================================================
# ADMIN ORDERS/MEMBERS/SETTINGS
# =========================================================
async def admin_members(query):
    pool=await db()
    async with pool.acquire() as conn:
        count=await conn.fetchval('SELECT COUNT(*) FROM users'); members=await conn.fetch('SELECT telegram_id,username,first_name,created_at FROM users ORDER BY created_at DESC LIMIT 100')
    text=f'👥 اعضای ربات\n\n👤 تعداد کل اعضا: {count}\n\n'
    for m in members: text += f"👤 {m['first_name'] or 'بدون نام'}\n🆔 {m['telegram_id']}\n📱 @{m['username'] if m['username'] else '---'}\n📅 {m['created_at']}\n━━━━━━━━━━━━\n"
    if not members: text+='هنوز عضوی ثبت نشده.'
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔄 بروزرسانی',callback_data='adm_members')],[InlineKeyboardButton('🔙 پنل',callback_data='adm_panel')]]))


async def admin_orders(query):
    pool=await db()
    async with pool.acquire() as conn: orders=await conn.fetch('SELECT id,customer_name,total,status FROM orders ORDER BY id DESC LIMIT 50')
    names={'waiting_payment':'⏳ پرداخت','waiting_admin':'🔎 بررسی','paid':'✅ تأیید','rejected':'❌ رد','shipped':'🚚 ارسال','completed':'🏁 تکمیل'}
    keyboard=[[InlineKeyboardButton(f"#{o['id']} | {o['customer_name']} | {o['total']:,} | {names.get(o['status'],o['status'])}",callback_data=f'adm_order:{o["id"]}')] for o in orders]
    keyboard.append([InlineKeyboardButton('🔙 پنل',callback_data='adm_panel')]); await query.edit_message_text('🧾 سفارش‌های فروشگاه:',reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_order_details(query, order_id):
    pool=await db()
    async with pool.acquire() as conn:
        order=await conn.fetchrow('SELECT * FROM orders WHERE id=$1',order_id); items=await conn.fetch('SELECT * FROM order_items WHERE order_id=$1',order_id)
    if not order: await query.edit_message_text('❌ سفارش پیدا نشد.',reply_markup=back_button('adm_orders')); return
    text=f"🧾 سفارش #{order_id}\n\n👤 {order['customer_name']}\n📱 {order['phone']}\n📍 {order['address']}\n📮 {order['postal_code']}\n\n"
    for i in items: text+=f"👟 {i['product_name']}\n📏 سایز: {i['size'] or '---'}\n🔢 تعداد: {i['quantity']}\n💰 قیمت واحد: {i['price']:,}\n\n"
    text+=f"🚚 ارسال: {order['shipping_cost']:,}\n💵 مجموع: {order['total']:,}\n📌 وضعیت: {order['status']}"
    keyboard=[]
    if order['status']=='waiting_admin': keyboard.append([InlineKeyboardButton('✅ تأیید پرداخت',callback_data=f'approve:{order_id}'),InlineKeyboardButton('❌ رد پرداخت',callback_data=f'reject:{order_id}')])
    keyboard.append([InlineKeyboardButton('🔙 سفارش‌ها',callback_data='adm_orders')]); await query.edit_message_text(text,reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_settings(query):
    card=await setting('card_number'); shipping=await setting('shipping_cost'); support=await setting('support_text')
    await query.edit_message_text(f"⚙️ تنظیمات فروشگاه\n\n💳 کارت: {card or 'ثبت نشده'}\n🚚 ارسال: {shipping or '0'} تومان\n📞 پشتیبانی: {support[:100]}",reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('💳 تغییر شماره کارت',callback_data='set_card')],[InlineKeyboardButton('🚚 تغییر هزینه ارسال',callback_data='set_shipping')],[InlineKeyboardButton('📞 تغییر پشتیبانی',callback_data='set_support')],[InlineKeyboardButton('🔙 پنل',callback_data='adm_panel')]]))


async def change_password_start(query,context): context.user_data['state']='new_password'; await query.edit_message_text('🔑 رمز جدید را ارسال کن:')

async def change_password(update,context):
    password=update.message.text.strip()
    if len(password)<4: await update.message.reply_text('❌ رمز باید حداقل ۶ کاراکتر باشد.'); return
    await set_setting('admin_password',hashlib.sha256(password.encode()).hexdigest()); context.user_data['state']=None; await update.message.reply_text('✅ رمز با موفقیت تغییر کرد.')

async def admin_setting_message(update,context):
    state=context.user_data.get('state'); text=update.message.text.strip()
    if state=='set_card': await set_setting('card_number',text)
    elif state=='set_shipping':
        try: value=int(text.replace(',','')); assert value>=0
        except: await update.message.reply_text('❌ فقط عدد نامنفی وارد کن.'); return
        await set_setting('shipping_cost',str(value))
    elif state=='set_support': await set_setting('support_text',update.message.text)
    else: return
    context.user_data['state']=None; await update.message.reply_text('✅ تنظیمات ذخیره شد.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚙️ تنظیمات',callback_data='adm_settings')]]))


# =========================================================
# ADMIN CALLBACK ROUTER
# =========================================================
async def admin_callback(query,context):
    if not is_admin(query.from_user.id): await query.answer('❌ دسترسی ندارید.',show_alert=True); return
    if not is_logged(context): await query.answer('❌ ابتدا /admin را بزن و وارد پنل شو.',show_alert=True); return
    data=query.data
    if data=='adm_panel': await admin_panel_callback(query,context)
    elif data=='adm_products': await admin_products(query)
    elif data=='adm_brands': await admin_brands(query)
    elif data=='adm_orders': await admin_orders(query)
    elif data=='adm_members': await admin_members(query)
    elif data=='adm_settings': await admin_settings(query)
    elif data=='adm_add_brand': await add_brand_start(query,context)
    elif data=='adm_add_product': await add_product_start(query,context)
    elif data.startswith('adm_brand:'): await admin_brand_details(query,int(data.split(':')[1]))
    elif data.startswith('brandtoggle:'): await toggle_brand(query,int(data.split(':')[1]))
    elif data.startswith('branddelete:'): await confirm_brand_delete(query,int(data.split(':')[1]))
    elif data.startswith('branddeleteconfirm:'): await delete_brand(query,int(data.split(':')[1]))
    elif data.startswith('adm_product:'): await admin_product_details(query,int(data.split(':')[1]))
    elif data.startswith('producttoggle:'): await toggle_product(query,int(data.split(':')[1]))
    elif data.startswith('proddelete:'): await confirm_product_delete(query,int(data.split(':')[1]))
    elif data.startswith('proddeleteconfirm:'): await delete_product(query,int(data.split(':')[1]))
    elif data.startswith('choosebrand:'):
        if 'product' not in context.user_data: await query.answer('❌ فرایند افزودن محصول منقضی شده.',show_alert=True); return
        context.user_data['product']['brand_id']=int(data.split(':')[1]); context.user_data['state']='product_description'; await query.edit_message_text('📝 توضیحات محصول را بنویس. اگر نداری بنویس: ندارد')
    elif data.startswith('adm_order:'): await admin_order_details(query,int(data.split(':')[1]))
    elif data=='adm_password': await change_password_start(query,context)
    elif data=='set_card': context.user_data['state']='set_card'; await query.edit_message_text('💳 شماره کارت جدید را ارسال کن:')
    elif data=='set_shipping': context.user_data['state']='set_shipping'; await query.edit_message_text('🚚 هزینه ارسال را به تومان وارد کن:')
    elif data=='set_support': context.user_data['state']='set_support'; await query.edit_message_text('📞 متن جدید پشتیبانی را ارسال کن:')
    elif data.startswith('approve:'): await set_order_status(query,context,int(data.split(':')[1]),'paid')
    elif data.startswith('reject:'): await set_order_status(query,context,int(data.split(':')[1]),'rejected')
    elif data=='adm_logout': context.user_data.clear(); await query.edit_message_text('🚪 از پنل مدیریت خارج شدید.')


async def set_order_status(query,context,order_id,status):
    pool=await db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order=await conn.fetchrow('SELECT * FROM orders WHERE id=$1 FOR UPDATE',order_id)
            if not order: await query.answer('❌ سفارش پیدا نشد.',show_alert=True); return
            if order['status']!='waiting_admin': await query.answer('⚠️ این سفارش قبلاً بررسی شده.',show_alert=True); return
            await conn.execute('UPDATE orders SET status=$1 WHERE id=$2',status,order_id)
    msg = f"✅ پرداخت سفارش #{order_id} تأیید شد.\n\n📦 سفارش شما برای ارسال آماده شد." if status=='paid' else f"❌ پرداخت سفارش #{order_id} تأیید نشد.\n\nلطفاً رسید پرداخت را بررسی و دوباره ارسال کنید."
    try: await context.bot.send_message(chat_id=order['telegram_id'],text=msg)
    except Exception as e: print('CUSTOMER MESSAGE ERROR:',e)
    await query.answer('✅ وضعیت سفارش ثبت شد.')
    await admin_order_details(query,order_id)


# =========================================================
# CUSTOMER CALLBACK / SEARCH
# =========================================================
async def start_search(query,context):
    context.user_data['state']='search'; await query.edit_message_text('🔎 جستجوی محصول\n\nاسم مدل، برند یا کاربرد را بنویس.',reply_markup=back_button('home'))

async def do_search(update,context):
    word=update.message.text.strip()
    if not word: await update.message.reply_text('❌ چیزی وارد نکردی.'); return
    context.user_data['state']=None; pool=await db()
    async with pool.acquire() as conn:
        products=await conn.fetch('''SELECT p.id,p.name,p.price,p.sale_price FROM products p LEFT JOIN brands b ON b.id=p.brand_id WHERE p.active=TRUE AND p.stock>0 AND (p.name ILIKE $1 OR p.description ILIKE $1 OR p.category ILIKE $1 OR p.keywords ILIKE $1 OR b.name ILIKE $1) ORDER BY p.id DESC''',f'%{word}%')
    if not products: await update.message.reply_text(f'❌ برای «{word}» محصولی پیدا نشد.',reply_markup=await main_menu()); return
    keyboard=[]
    for p in products:
        price=p['sale_price'] if 0<p['sale_price']<p['price'] else p['price']; keyboard.append([InlineKeyboardButton(f'👟 {p["name"]} | {price:,} تومان',callback_data=f'product:{p["id"]}')])
    keyboard.append([InlineKeyboardButton('🔙 منوی اصلی',callback_data='home')]); await update.message.reply_text(f'🔎 نتایج جستجو برای «{word}»:',reply_markup=InlineKeyboardMarkup(keyboard))

async def customer_callback(query,context):
    data=query.data
    if data=='home': await query.edit_message_text('👟 به فروشگاه کفش و کتونی خوش آمدید!\n\nاز منوی زیر انتخاب کنید:',reply_markup=await main_menu())
    elif data=='products': await products_menu(query)
    elif data=='sale': await sale_products(query)
    elif data.startswith('brand:'): await brand_products(query,int(data.split(':')[1]))
    elif data.startswith('product:'): await product_details(query,int(data.split(':')[1]))
    elif data.startswith('buy:'):
        class Obj: pass
        obj=Obj(); obj.callback_query=query; obj.effective_user=query.from_user; await add_to_cart(obj,int(data.split(':')[1]))
    elif data.startswith('addsize:'):
        parts=data.split(':',2)
        class Obj: pass
        obj=Obj(); obj.callback_query=query; obj.effective_user=query.from_user; await insert_cart(obj,int(parts[1]),parts[2])
    elif data=='cart': await show_cart(query)
    elif data=='checkout': await checkout_start(query,context)
    elif data=='orders': await customer_orders(query)
    elif data=='search': await start_search(query,context)
    elif data=='support': await query.edit_message_text(await setting('support_text'),reply_markup=back_button('home'))


# =========================================================
# ROUTERS / ERROR / STARTUP
# =========================================================
async def callback_handler(update,context):
    query=update.callback_query
    await query.answer()
    data=query.data
    admin_callbacks=(data.startswith('adm_') or data.startswith('approve:') or data.startswith('reject:') or data.startswith('set_') or data.startswith('choosebrand:') or data.startswith('brandtoggle:') or data.startswith('branddelete:') or data.startswith('branddeleteconfirm:') or data.startswith('producttoggle:') or data.startswith('proddelete:') or data.startswith('proddeleteconfirm:') or data.startswith('adm_product:'))
    if admin_callbacks: await admin_callback(query,context)
    else: await customer_callback(query,context)

async def text_handler(update,context):
    state=context.user_data.get('state')
    if state=='admin_password': await admin_password(update,context); return
    if state in ('set_card','set_shipping','set_support'):
        if is_admin(update.effective_user.id) and is_logged(context): await admin_setting_message(update,context)
        return
    if state=='new_password':
        if is_admin(update.effective_user.id) and is_logged(context): await change_password(update,context)
        return
    if state=='add_brand':
        if is_admin(update.effective_user.id) and is_logged(context): await add_brand(update,context)
        return
    if state and (state.startswith('product_')):
        if is_admin(update.effective_user.id) and is_logged(context): await product_add_message(update,context)
        return
    if state in ('customer_name','phone','address','postal'): await checkout_message(update,context); return
    if state=='search': await do_search(update,context)

async def photo_handler(update,context):
    state=context.user_data.get('state')
    if state=='product_images':
        if not (is_admin(update.effective_user.id) and is_logged(context)): return
        images=context.user_data.setdefault('product',{}).setdefault('images',[])
        if len(images)>=5: await update.message.reply_text('⚠️ حداکثر ۵ عکس مجاز است. بنویس «تمام».'); return
        images.append(update.message.photo[-1].file_id); await update.message.reply_text(f'✅ عکس {len(images)} دریافت شد.\nعکس بعدی یا «تمام».'); return
    if state and state.startswith('receipt:'): await receive_receipt(update,context)

async def error_handler(update,context): print('❌ ERROR:',repr(context.error))

async def post_init(application): await init_db()

app=(Application.builder().token(TOKEN).post_init(post_init).build())
app.add_handler(CommandHandler('start',start))
app.add_handler(CommandHandler('admin',admin_command))
app.add_handler(CallbackQueryHandler(callback_handler))
app.add_handler(MessageHandler(filters.PHOTO,photo_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
app.add_error_handler(error_handler)

print('🚀 BOT STARTED')
app.run_polling()
