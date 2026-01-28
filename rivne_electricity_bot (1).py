import asyncio
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import logging
import os

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен вашого Telegram бота (з змінних оточення або прямо)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Глобальні змінні
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словник для зберігання запланованих нагадувань
scheduled_reminders = {}

class RivneElectricityParser:
    """Парсер графіків відключень з сайту Рівнеобленерго"""
    
    SITE_URL = "https://www.roe.vsei.ua/disconnections"
    
    @staticmethod
    async def fetch_schedule():
        """Завантажує та парсить графік відключень"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RivneElectricityParser.SITE_URL) as response:
                    html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Знаходимо таблицю з графіками
            table = soup.find('table')
            if not table:
                return None
            
            # Отримуємо дату сьогодні
            today = datetime.now().strftime("%d.%m.%Y")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
            
            schedule = {}
            
            # Парсимо таблицю
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) > 0:
                    # Перша комірка містить дату
                    cell_text = cells[0].get_text(strip=True)
                    
                    if cell_text == today or cell_text == tomorrow:
                        # Черга 6.2 знаходиться в позиції для чергу 6
                        # Шукаємо дані для підчергу 6.2
                        if len(cells) >= 12:
                            # Позиція 11 - це черга 6, підчерга 6.2
                            time_text = cells[11].get_text(strip=True)
                            if time_text and time_text != "Очікується":
                                schedule[cell_text] = time_text
            
            return schedule
            
        except Exception as e:
            logger.error(f"Помилка при завантаженні графіку: {e}")
            return None

class ReminderManager:
    """Менеджер нагадувань про відключення"""
    
    @staticmethod
    def parse_time_slots(time_string):
        """
        Парсить час відключень з рядка типу "03:00 - 07:00  15:00 - 19:00"
        Повертає список кортежів (start_time, end_time)
        """
        slots = []
        try:
            # Розділяємо на окремі інтервали (розділені подвійними пробілами)
            intervals = time_string.split('  ')
            
            for interval in intervals:
                if '-' in interval:
                    parts = interval.split('-')
                    start = parts[0].strip()
                    end = parts[1].strip()
                    slots.append((start, end))
            
            return slots
        except Exception as e:
            logger.error(f"Помилка при парсингу часу: {e}")
            return []
    
    @staticmethod
    async def schedule_reminder(user_id, chat_id, start_time_str, date_str):
        """
        Планує нагадування за годину до відключення
        """
        try:
            # Конвертуємо дату та час в об'єкт datetime
            date_time_str = f"{date_str} {start_time_str}"
            cutoff_time = datetime.strptime(date_time_str, "%d.%m.%Y %H:%M")
            
            # Нагадування за годину до
            reminder_time = cutoff_time - timedelta(hours=1)
            
            # Якщо час вже минув, не плануємо
            if reminder_time < datetime.now():
                return False
            
            # Розраховуємо затримку
            delay = (reminder_time - datetime.now()).total_seconds()
            
            if delay > 0:
                # Створюємо уніквальний ID для нагадування
                reminder_id = f"{chat_id}_{date_str}_{start_time_str}"
                
                # Зберігаємо завдання для скасування при необхідності
                task = asyncio.create_task(
                    ReminderManager._send_reminder_after_delay(
                        chat_id, 
                        cutoff_time,
                        delay
                    )
                )
                scheduled_reminders[reminder_id] = task
                
                logger.info(f"Нагадування заплановано на {reminder_time} для чату {chat_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Помилка при плануванні нагадування: {e}")
            return False
    
    @staticmethod
    async def _send_reminder_after_delay(chat_id, cutoff_time, delay):
        """
        Чекає затримку та відправляє нагадування
        """
        try:
            await asyncio.sleep(delay)
            
            message = (
                f"⚠️ <b>Нагадування про відключення світла!</b>\n\n"
                f"<b>Черга 6.2</b>\n"
                f"Відключення через <b>1 годину</b>\n"
                f"Час: <b>{cutoff_time.strftime('%H:%M')}</b>\n\n"
                f"Підготуйтеся заздалегідь!"
            )
            
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"
            )
            
            logger.info(f"Нагадування відправлено для чату {chat_id}")
            
        except Exception as e:
            logger.error(f"Помилка при відправці нагадування: {e}")

# Обробники команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обробляє команду /start"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Графік на сьогодні")],
            [KeyboardButton(text="📅 Графік на завтра")],
            [KeyboardButton(text="🔔 Увімкнути нагадування")],
            [KeyboardButton(text="❌ Вимкнути нагадування")],
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "👋 Привіт! Я бот для відслідкування графіків відключення світла.\n\n"
        "<b>Черга 6.2</b> Рівнеобленерго\n\n"
        "Виберіть дію:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обробляє команду /help"""
    await message.answer(
        "<b>Доступні команди:</b>\n\n"
        "/start - Головне меню\n"
        "/today - Графік на сьогодні\n"
        "/tomorrow - Графік на завтра\n"
        "/help - Справка\n\n"
        "Або використовуйте кнопки нижче.",
        parse_mode="HTML"
    )

@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    """Показує графік на сьогодні"""
    await show_schedule(message, "today")

@dp.message(Command("tomorrow"))
async def cmd_tomorrow(message: types.Message):
    """Показує графік на завтра"""
    await show_schedule(message, "tomorrow")

async def show_schedule(message: types.Message, day: str):
    """Показує графік відключень"""
    
    loading_msg = await message.answer("⏳ Завантажую графік...")
    
    try:
        schedule = await RivneElectricityParser.fetch_schedule()
        
        if not schedule:
            await loading_msg.edit_text("❌ Не можу завантажити графік. Спробуйте пізніше.")
            return
        
        if day == "today":
            target_date = datetime.now().strftime("%d.%m.%Y")
            day_name = "сьогодні"
        else:
            target_date = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
            day_name = "завтра"
        
        if target_date in schedule:
            times = schedule[target_date]
            slots = ReminderManager.parse_time_slots(times)
            
            text = f"📅 <b>Графік чергу 6.2 на {day_name}</b>\n"
            text += f"Дата: <b>{target_date}</b>\n\n"
            
            if slots:
                text += "<b>Часи відключення:</b>\n"
                for i, (start, end) in enumerate(slots, 1):
                    text += f"{i}. <b>{start}</b> - <b>{end}</b>\n"
                
                # Плануємо нагадування
                for start, end in slots:
                    await ReminderManager.schedule_reminder(
                        message.from_user.id,
                        message.chat.id,
                        start,
                        target_date
                    )
                
                text += "\n✅ Нагадування активовані!"
            else:
                text += "❌ Дані не доступні (очікується оновлення)"
            
            await loading_msg.edit_text(text, parse_mode="HTML")
        else:
            await loading_msg.edit_text(
                f"❌ Дані для {day_name} ще недоступні.",
                parse_mode="HTML"
            )
    
    except Exception as e:
        logger.error(f"Помилка: {e}")
        await loading_msg.edit_text(
            "❌ Помилка при завантаженні графіку.\nСпробуйте пізніше.",
            parse_mode="HTML"
        )

@dp.message(lambda message: message.text in ["📅 Графік на сьогодні", "/today"])
async def button_today(message: types.Message):
    await show_schedule(message, "today")

@dp.message(lambda message: message.text in ["📅 Графік на завтра", "/tomorrow"])
async def button_tomorrow(message: types.Message):
    await show_schedule(message, "tomorrow")

@dp.message(lambda message: message.text in ["🔔 Увімкнути нагадування"])
async def button_enable_reminder(message: types.Message):
    await show_schedule(message, "today")

@dp.message(lambda message: message.text in ["❌ Вимкнути нагадування"])
async def button_disable_reminder(message: types.Message):
    # Скасовуємо все нагадування для цього чату
    cancelled = 0
    for reminder_id, task in list(scheduled_reminders.items()):
        if str(message.chat.id) in reminder_id:
            task.cancel()
            del scheduled_reminders[reminder_id]
            cancelled += 1
    
    await message.answer(
        f"✅ Нагадування вимкнені.\n"
        f"Скасовано нагадувань: {cancelled}",
        parse_mode="HTML"
    )

# Основна функція
async def main():
    """Запускає бот"""
    logger.info("Бот запускається...")
    
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Помилка при запуску: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
