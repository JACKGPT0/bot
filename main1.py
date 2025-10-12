import telebot
import subprocess
import os
import requests
import re
import logging
import time
from telebot import types

TOKEN = '8297719212:AAF15B9gC-uDwtxR5d7R7jUIZSVbVDQ7zUQ'
ADMIN_ID = 7065772273
CHANNEL = '@so_LO_LO'

bot = telebot.TeleBot(TOKEN)
uploaded_files_dir = 'uploaded_bots'
pending_approvals = {}

if not os.path.exists(uploaded_files_dir):
    os.makedirs(uploaded_files_dir)

# --- دالة التحقق من الاشتراك ---
def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

# --- طلب الاشتراك ---
def ask_for_subscription(chat_id):
    markup = types.InlineKeyboardMarkup()
    join_btn = types.InlineKeyboardButton("📢 اشترك بالقناة", url=f"https://t.me/{CHANNEL[1:]}")
    markup.add(join_btn)
    bot.send_message(chat_id, f"📢 لازم تشترك في {CHANNEL} قبل الاستخدام.", reply_markup=markup)

# --- رسالة الترحيب ---
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if not check_subscription(user_id):
        ask_for_subscription(message.chat.id)
        return

    markup = types.InlineKeyboardMarkup()
    upload_button = types.InlineKeyboardButton('⛈️ رفع ملف', callback_data='upload')
    speed_button = types.InlineKeyboardButton('⚡ سرعة البوت', callback_data='speed')
    dev_button = types.InlineKeyboardButton('💈 قناة المطور', url='https://t.me/so_LO_LO')
    markup.add(upload_button)
    markup.add(speed_button, dev_button)

    caption = f"مرحباً {message.from_user.first_name}! 👋\n✨ استخدم الأزرار أدناه:"
    # رابط صورة أو فيديو من تلغرام
    media_url = "https://t.me/so_LO_LO/6"

    # إرسال الصورة أو الفيديو تلقائيًا حسب الرابط
    if media_url.endswith((".mp4", ".mov")) or "/video/" in media_url:
        bot.send_video(message.chat.id, media_url, caption=caption, reply_markup=markup)
    else:
        bot.send_photo(message.chat.id, media_url, caption=caption, reply_markup=markup)

# --- سرعة البوت ---
@bot.callback_query_handler(func=lambda call: call.data == 'speed')
def bot_speed(call):
    start_time = time.time()
    try:
        requests.get(f'https://api.telegram.org/bot{TOKEN}/getMe')
        latency = time.time() - start_time
        bot.send_message(call.message.chat.id, f"⚡ سرعة الاستجابة: {latency:.2f} ثانية")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ خطأ: {e}")

# --- طلب رفع ملف ---
@bot.callback_query_handler(func=lambda call: call.data == 'upload')
def ask_upload(call):
    bot.send_message(call.message.chat.id, "📁 أرسل الملف المراد رفعه.")

# --- استقبال الملف ---
@bot.message_handler(content_types=['document'])
def handle_file(message):
    user_id = message.from_user.id
    if not check_subscription(user_id):
        ask_for_subscription(message.chat.id)
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        file_name = message.document.file_name
        file_path = os.path.join(uploaded_files_dir, f"{user_id}_{file_name}")

        with open(file_path, 'wb') as f:
            f.write(file_data)

        markup = types.InlineKeyboardMarkup()
        approve = types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_{user_id}_{file_name}")
        reject = types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_{user_id}_{file_name}")
        markup.add(approve, reject)

        user_tag = f"@{message.from_user.username}" if message.from_user.username else f"ID:{user_id}"
        caption = f"📦 رفع {user_tag} ملف:\n📁 {file_name}\nهل توافق؟"

        bot.send_document(ADMIN_ID, open(file_path, 'rb'), caption=caption, reply_markup=markup)
        pending_approvals[f"{user_id}_{file_name}"] = {'chat_id': message.chat.id, 'path': file_path}
        bot.send_message(message.chat.id, "⏳ تم إرسال الملف للإدارة...")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خطأ أثناء رفع الملف: {e}")

# --- معالجة قرار الأدمن ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')))
def handle_admin(call):
    try:
        parts = call.data.split('_')
        action, user_id, file_name = parts[0], parts[1], "_".join(parts[2:])
        key = f"{user_id}_{file_name}"

        if key not in pending_approvals:
            bot.answer_callback_query(call.id, "⚠️ الملف غير موجود.")
            return

        chat_id = pending_approvals[key]['chat_id']
        path = pending_approvals[key]['path']

        if action == 'approve':
            bot.send_message(chat_id, f"✅ تمت الموافقة! تشغيل {file_name}...")
            run_script(path, chat_id, file_name)
        else:
            bot.send_message(chat_id, "🚫 تم الرفض.")
            os.remove(path)

        del pending_approvals[key]
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ خطأ: {e}")

# --- تشغيل السكربت وإرسال الـ Logs ---
def run_script(path, chat_id, file_name):
    try:
        bot.send_message(chat_id, "⚙️ جاري تشغيل الملف ومتابعة المخرجات...")

        process = subprocess.Popen(
            ['python3', path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        log_buffer = ""
        for line in iter(process.stdout.readline, ''):
            log_buffer += line
            if len(log_buffer) > 2000:
                bot.send_message(chat_id, f"🪵 Log:\n```\n{log_buffer}```", parse_mode='Markdown')
                log_buffer = ""
            print(line.strip())  # يعرض اللوج في التيرمنال كمان
            time.sleep(1)

        if log_buffer:
            bot.send_message(chat_id, f"🪵 Log (النهاية):\n```\n{log_buffer}```", parse_mode='Markdown')

        process.wait()
        bot.send_message(chat_id, f"✅ تم إنهاء تشغيل {file_name}.")

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ أثناء التشغيل: {e}")

print("🔹 Bot running...")
bot.infinity_polling(timeout=30, long_polling_timeout=10)