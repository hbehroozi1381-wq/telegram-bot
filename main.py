import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🛍 محصولات", callback_data="products"),
            InlineKeyboardButton("🛒 سبد خرید", callback_data="cart"),
        ],
        [
            InlineKeyboardButton("📦 سفارش‌های من", callback_data="orders"),
            InlineKeyboardButton("📞 پشتیبانی", callback_data="support"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👟 به فروشگاه کفش و کتونی خوش آمدید!\n\n"
        "از منوی زیر انتخاب کنید:",
        reply_markup=reply_markup
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "products":
        await query.edit_message_text(
            "🛍 بخش محصولات\n\n"
            "به‌زودی محصولات اینجا نمایش داده می‌شوند."
        )

    elif query.data == "cart":
        await query.edit_message_text("🛒 سبد خرید شما خالی است.")

    elif query.data == "orders":
        await query.edit_message_text("📦 هنوز سفارشی ثبت نکرده‌اید.")

    elif query.data == "support":
        await query.edit_message_text("📞 برای پشتیبانی با ما در ارتباط باشید.")


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))

print("👟 فروشگاه آنلاین شد...")
app.run_polling()
