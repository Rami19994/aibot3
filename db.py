import sqlite3
import asyncio
from datetime import datetime, timedelta

class Database:
    def __init__(self, db):
        self.connection = sqlite3.connect(db, check_same_thread=False)
        self.cursor = self.connection.cursor()
        self.create_tables()

    # ========================================================
    # 🧱 إنشاء الجداول
    # ========================================================
    def create_tables(self):
        # جدول المستخدمين
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                firstname TEXT,
                lastname TEXT,
                start_date TEXT,
                end_date TEXT,
                is_active INTEGER DEFAULT 0,
                balance INTEGER DEFAULT 10,
                reminder_sent INTEGER DEFAULT 0
            )
        ''')

        # جدول المدفوعات
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                date TEXT
            )
        ''')
        self.connection.commit()

    # ========================================================
    # 👤 إدارة المستخدمين
    # ========================================================
    def insert_user(self, user_id, username, firstname, lastname):
        """إضافة مستخدم جديد مع رصيد 10 رسائل مجانية"""
        self.cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, firstname, lastname, balance)
            VALUES (?, ?, ?, ?, 10)
        ''', (user_id, username, firstname, lastname))
        self.connection.commit()

    def get_user(self, user_id):
        """جلب بيانات مستخدم"""
        self.cursor.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
        return self.cursor.fetchone()

    def update_balance(self, user_id, amount):
        """تحديث الرصيد المجاني"""
        self.cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id=?', (amount, user_id))
        self.connection.commit()

    def get_balance(self, user_id):
        """جلب الرصيد المجاني"""
        self.cursor.execute('SELECT balance FROM users WHERE user_id=?', (user_id,))
        res = self.cursor.fetchone()
        return res[0] if res else 0

    # ========================================================
    # 💳 نظام الاشتراكات
    # ========================================================
    def activate_subscription(self, user_id, months=1):
        """تفعيل اشتراك المستخدم لمدة شهر"""
        start = datetime.now()
        end = start + timedelta(days=30 * months)
        self.cursor.execute('''
            UPDATE users
            SET start_date=?, end_date=?, is_active=1, reminder_sent=0
            WHERE user_id=?
        ''', (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), user_id))
        self.connection.commit()

    def deactivate_user(self, user_id):
        """إلغاء تفعيل المستخدم"""
        self.cursor.execute('UPDATE users SET is_active=0 WHERE user_id=?', (user_id,))
        self.connection.commit()

    def is_subscription_active(self, user_id):
        """التحقق من أن الاشتراك ما زال ساري المفعول"""
        self.cursor.execute('SELECT end_date, is_active FROM users WHERE user_id=?', (user_id,))
        result = self.cursor.fetchone()
        if not result:
            return False
        end_date_str, is_active = result
        if not end_date_str or not is_active:
            return False
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        return datetime.now() <= end_date

    # ========================================================
    # 💰 نظام المدفوعات
    # ========================================================
    def add_pending_payment(self, user_id, amount):
        """إضافة دفعة معلقة"""
        self.cursor.execute(
            "INSERT INTO payments (user_id, amount, date) VALUES (?, ?, ?)",
            (user_id, amount, datetime.now().strftime("%Y-%m-%d"))
        )
        self.connection.commit()

    def get_pending_payment_by_amount(self, amount):
        """جلب دفعة معلقة بالمبلغ المحدد"""
        self.cursor.execute(
            "SELECT user_id FROM payments WHERE amount=? AND status='pending' LIMIT 1", (amount,)
        )
        return self.cursor.fetchone()

    def confirm_payment(self, user_id):
        """تأكيد الدفع وتفعيل الاشتراك لمدة شهر"""
        start = datetime.now()
        end = start + timedelta(days=30)
        self.cursor.execute('''
            UPDATE users
            SET is_active=1, start_date=?, end_date=?, reminder_sent=0
            WHERE user_id=?
        ''', (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), user_id))
        self.cursor.execute('UPDATE payments SET status="done" WHERE user_id=?', (user_id,))
        self.connection.commit()

    def remove_pending_payment(self, user_id):
        """إزالة دفعة معلقة بعد معالجتها"""
        self.cursor.execute('DELETE FROM payments WHERE user_id=?', (user_id,))
        self.connection.commit()

    # ========================================================
    # 🕒 إدارة انتهاء الاشتراكات والتذكيرات
    # ========================================================
    def auto_deactivate_expired_users(self, app=None):
        """تعطيل الاشتراكات المنتهية تلقائيًا"""
        self.cursor.execute('SELECT user_id, end_date FROM users WHERE is_active=1')
        rows = self.cursor.fetchall()
        for user_id, end_date_str in rows:
            if not end_date_str:
                continue
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            if datetime.now() > end_date:
                self.cursor.execute('UPDATE users SET is_active=0 WHERE user_id=?', (user_id,))
                self.connection.commit()
                print(f"⛔ انتهاء اشتراك المستخدم {user_id}.")
                if app:
                    asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(chat_id=user_id,
                                             text="⏳ انتهى اشتراكك الشهري.\n💳 قم بالتجديد للاستمرار."),
                        app.bot.loop
                    )

    def send_expiry_reminders(self, app=None):
        """🔔 إرسال تذكير قبل يوم من انتهاء الاشتراك"""
        tomorrow = datetime.now() + timedelta(days=1)
        self.cursor.execute('''
            SELECT user_id, end_date FROM users
            WHERE is_active=1 AND reminder_sent=0
        ''')
        rows = self.cursor.fetchall()

        for user_id, end_date_str in rows:
            if not end_date_str:
                continue
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            if end_date.date() == tomorrow.date():
                self.cursor.execute('UPDATE users SET reminder_sent=1 WHERE user_id=?', (user_id,))
                self.connection.commit()
                print(f"📩 تذكير قبل انتهاء الاشتراك للمستخدم {user_id}")
                if app:
                    asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(
                            chat_id=user_id,
                            text=(
                                "⏰ تذكير مهم!\n"
                                "اشتراكك سينتهي غدًا 🗓️\n"
                                "💳 قم بالتجديد الآن لتواصل استخدام البوت بدون انقطاع ❤️"
                            )
                        ),
                        app.bot.loop
                    )

    # ========================================================
    # 🔚 إغلاق الاتصال
    # ========================================================
    def close(self):
        self.connection.close()
