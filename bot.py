import asyncio
import nest_asyncio
import requests
import time
import os
import threading
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from db import Database

nest_asyncio.apply()

# ========== الإعداد ==========
db = Database("db.db")
TOKEN = "8344417182:AAHDfjagQdiKF8mu5ARgU15w9Ic5UWYOQhw"

# 🧠 مفاتيح OpenRouter
OPENROUTER_KEY = "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"
PRIMARY_MODEL = "deepseek/deepseek-chat-v3.1:free"
BACKUP_MODEL = "mistralai/mistral-7b-instruct:free"

# محفظة USDT
WALLET_ADDRESS = "TD7BeQyvkanpJS9R5LevtyC5F2zr7WE4Fh"
BOT_USERNAME = "sadekee_bot"

# ========== دالة الذكاء الصناعي ==========
async def chat_with_ai(prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    def send_request(model_name):
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": f"https://t.me/{BOT_USERNAME}",
            "X-Title": "AI Telegram Chatbot"
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "أنت مساعد ذكي يتحدث العربية، ودود ومفيد."},
                {"role": "user", "content": prompt},
            ]
        }
        return requests.post(url, headers=headers, json=payload, timeout=40)
    try:
        response = send_request(PRIMARY_MODEL)
        data = response.json()
        if "error" in data and data["error"].get("code") == 429:
            response = send_request(BACKUP_MODEL)
            data = response.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        else:
            return "حدث خطأ أثناء معالجة الرد 😕"
    except Exception as e:
        print("❌ خطأ أثناء الاتصال بـ OpenRouter:", e)
        return "حدث خطأ أثناء الاتصال بالذكاء الصناعي 😔"

# ========== أمر /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.insert_user(user.id, user.username or "unknown", user.first_name or "N/A", user.last_name or "N/A")

    # الأزرار
    buttons = [
        [InlineKeyboardButton("🔗 رابط إحالتي", callback_data="referral")],
        [InlineKeyboardButton("💳 الاشتراك الشهري", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ معلومات عن البوت", callback_data="info")]
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n"
        "أنا بوت الدردشة الذكي 🤖.\n\n"
        "🎁 لديك 10 رسائل مجانية لتجربتي.\n"
        "بعدها يمكنك الاشتراك الشهري لتواصل الدردشة بدون حدود 💬.\n\n"
        "اختر أحد الخيارات 👇",
        reply_markup=keyboard
    )

# ========== الأزرار التفاعلية ==========
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "referral":
        link = f"https://t.me/{BOT_USERNAME}?start={user.id}"
        await query.message.reply_text(f"🔗 رابط إحالتك الخاص:\n{link}\nشارك أصدقاءك!")

    elif query.data == "buy":
        await query.message.reply_text(
            f"💵 أرسل *5 USDT* إلى العنوان التالي لتفعيل اشتراكك الشهري:\n\n"
            f"`{WALLET_ADDRESS}`\n\n"
            "⏳ سيتم التحقق تلقائيًا من المعاملة وتفعيل الاشتراك خلال دقيقة واحدة ✅",
            parse_mode="Markdown"
        )
        db.add_pending_payment(user.id, 5)

    elif query.data == "info":
        await query.message.reply_text(
            "🤖 *معلومات عن البوت:*\n\n"
            "بوت دردشة ذكي يعتمد على GPT.\n"
            "🎁 10 رسائل مجانية عند التسجيل.\n"
            "💳 بعدها يمكنك الاشتراك الشهري واستخدام البوت بحرية طوال الشهر.",
            parse_mode="Markdown"
        )

# ========== التعامل مع الرسائل ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # 🔍 تحقق من حالة المستخدم
    if db.is_subscription_active(user.id):
        # الاشتراك نشط → استخدم بدون خصم
        reply = await chat_with_ai(text)
        await update.message.reply_text(reply)
        return

    # المستخدم غير مشترك → تحقق من الرصيد المجاني
    balance = db.get_balance(user.id)
    if balance > 0:
        db.update_balance(user.id, -1)
        reply = await chat_with_ai(text)
        await update.message.reply_text(f"{reply}\n\n💬 تبقّى لك {balance - 1} من الرسائل المجانية.")
    else:
        await update.message.reply_text(
            "⏳ انتهت رسائلك المجانية أو انتهى اشتراكك.\n💳 اشترك الآن لتفعيل الشهر الجديد عبر الزر في /start."
        )

# ========== فحص المدفوعات (TronScan) ==========
def check_payments(app):
    print("🔍 جاري التحقق من معاملات TRON...")
    try:
        url = f"https://apilist.tronscanapi.com/api/transaction?address={WALLET_ADDRESS}&limit=20"
        data = requests.get(url, timeout=10).json()
        if "data" not in data:
            return

        for tx in data["data"]:
            if tx.get("contractRet") != "SUCCESS":
                continue

            amount = float(tx.get("amount", 0)) / 1_000_000
            pending = db.get_pending_payment_by_amount(amount)
            if pending:
                user_id = pending[0]
                db.confirm_payment(user_id)  # ✅ تفعيل الاشتراك الشهري
                print(f"✅ تم تفعيل اشتراك المستخدم {user_id} لمدة شهر.")
                asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(
                        chat_id=user_id,
                        text="✅ تم استلام دفعتك بنجاح!\nتم تفعيل اشتراكك لمدة شهر 🎉"
                    ),
                    app.bot.loop
                )

    except Exception as e:
        print("⚠️ خطأ أثناء التحقق من المدفوعات:", e)

# ========== تشغيل المراقبة التلقائية ==========
def start_auto_checker(app):
    def loop():
        while True:
            check_payments(app)
            db.auto_deactivate_expired_users(app)  # ⏰ تعطيل من انتهى اشتراكه
            time.sleep(60)
    threading.Thread(target=loop, daemon=True).start()

# ========== تشغيل البوت ==========
def main():
   
    

    if os.name == "nt":  # يعمل فقط على Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print("🚀 البوت يعمل الآن...")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    start_auto_checker(app)
    app.run_polling(timeout=100, poll_interval=2.0)

if __name__ == "__main__":
    main()





