import asyncio
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

TOKEN = "8812842875:AAGh1x9kqngQtkgfs7K_jIknbB0mYICk310"

bot = Bot(token=TOKEN)
dp = Dispatcher()

MAX_SETS = 4

WORKOUT_SCHEDULES = {
    "mon": {
        "title": "День верха (Понедельник) — Грудь & Трицепс",
        "exercises": [
            {"name": "Жим на наклоне", "is_superset": False},
            {"name": "Тяга вертикального блока к груди", "is_superset": False},
            {"name": "Бабочки (грудь) / Кроссовер", "is_superset": False},
            {"name": "Махи в стороны (средняя дельта)", "is_superset": False},
            {"name": "Трицепс на блоке", "is_superset": False}
        ]
    },
    "tue": {
        "title": "День ног (Вторник)",
        "exercises": [
            {"name": "Жим ногами", "is_superset": False},
            {"name": "Становая тяга", "is_superset": False},
            {"name": "Разгибание ног", "is_superset": False},
            {"name": "Сгибание ног", "is_superset": False},
            {"name": "Икры", "is_superset": False}
        ]
    },
    "thu": {
        "title": "День верха (Четверг) — Спина & Плечи & Бицепс",
        "exercises": [
            {"name": "Тяга Т-грифа / Горизонтального блока", "is_superset": False},
            {"name": "Жим лежа", "is_superset": False},
            {"name": "Жим гантелей сидя (плечи)", "is_superset": False},
            {"name": "Задняя дельта", "is_superset": False},
            {"name": "Сгибания на бицепс", "is_superset": False}
        ]
    },
    "fri": {
        "title": "День ног (Пятница)",
        "exercises": [
            {"name": "Присед со штангой", "is_superset": False},
            {"name": "Становая тяга", "is_superset": False},
            {"name": "Разгибание ног", "is_superset": False},
            {"name": "Сгибание ног", "is_superset": False},
            {"name": "Икры", "is_superset": False}
        ]
    }
}

user_data = {}
user_tasks = {}

def get_today_schedule_key():
    weekday = datetime.now().weekday()
    if weekday == 0: return "mon"
    elif weekday == 1: return "tue"
    elif weekday == 3: return "thu"
    elif weekday == 4: return "fri"
    else: return "mon"

def get_current_exercise(user_id):
    sched_key = user_data[user_id]["day_key"]
    ex_idx = user_data[user_id]["exercise_idx"]
    exercises = WORKOUT_SCHEDULES[sched_key]["exercises"]
    if ex_idx < len(exercises):
        return exercises[ex_idx]
    return {"name": "Тренировка окончена 🎉", "is_superset": False}

def get_workout_keyboard(user_id):
    ex = get_current_exercise(user_id)
    buttons = []
    
    if ex.get("is_superset"):
        stage = user_data[user_id].get("superset_stage", 1)
        if stage == 1:
            buttons.append([InlineKeyboardButton(text="✅ Сделал Махи (1 часть)", callback_data="done_superset_part1")])
        elif stage == 2:
            buttons.append([InlineKeyboardButton(text="✅ Сделал Жим (2 часть)", callback_data="done_superset_part2")])
    else:
        buttons.append([InlineKeyboardButton(text="✅ Уже сделал подход", callback_data="done_set")])
        
    buttons.append([InlineKeyboardButton(text="⏳ +30 сек отдыха", callback_data="add_30sec")])
    buttons.append([InlineKeyboardButton(text="🛒 Магазин (10 мин)", callback_data="go_shop")])
    buttons.append([InlineKeyboardButton(text="⚙️ Настройки / Выбор дня", callback_data="open_settings")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_settings_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить +1 подход", callback_data="add_manual_set")],
            [InlineKeyboardButton(text="⏭ Следующее упражнение", callback_data="next_exercise")],
            [InlineKeyboardButton(text="📅 Выбрать Понедельник", callback_data="set_day_mon")],
            [InlineKeyboardButton(text="📅 Выбрать Вторник", callback_data="set_day_tue")],
            [InlineKeyboardButton(text="📅 Выбрать Четверг", callback_data="set_day_thu")],
            [InlineKeyboardButton(text="📅 Выбрать Пятницу", callback_data="set_day_fri")],
            [InlineKeyboardButton(text="◀️ Назад к тренировке", callback_data="back_to_workout")]
        ]
    )

def get_shop_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏁 Вернулся из магазина", callback_data="back_from_shop")]
        ]
    )

def track_message(user_id: int, message_id: int):
    if user_id not in user_data:
        return
    if "tracked_messages" not in user_data[user_id]:
        user_data[user_id]["tracked_messages"] = list()
    if message_id not in user_data[user_id]["tracked_messages"]:
        user_data[user_id]["tracked_messages"].append(message_id)

async def cleanup_all_messages(user_id: int):
    if user_id not in user_data or "tracked_messages" not in user_data[user_id]:
        return
    
    for msg_id in list(user_data[user_id]["tracked_messages"]):
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass
    user_data[user_id]["tracked_messages"] = list()

def cancel_user_timer(user_id):
    if user_id in user_tasks and not user_tasks[user_id].done():
        user_tasks[user_id].cancel()

def format_time(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

async def live_timer(message: types.Message, user_id: int, total_seconds: int, base_text: str, finish_text: str, keyboard=None):
    try:
        user_data[user_id]["remaining_seconds"] = total_seconds
        while user_data[user_id]["remaining_seconds"] > 0:
            rem = user_data[user_id]["remaining_seconds"]
            time_str = format_time(rem)
            text_to_show = f"{base_text}\n\n⏱ Ост. отдыха: **{time_str}**"
            try:
                await message.edit_text(text_to_show, reply_markup=keyboard, parse_mode="Markdown")
            except TelegramBadRequest:
                pass
            await asyncio.sleep(1)
            user_data[user_id]["remaining_seconds"] -= 1

        await cleanup_all_messages(user_id)

        finish_msg = await bot.send_message(
            user_id,
            finish_text,
            reply_markup=get_workout_keyboard(user_id),
            parse_mode="Markdown"
        )
        track_message(user_id, finish_msg.message_id)
        
        nag_count = 0
        last_nag_id = None
        while True:
            await asyncio.sleep(15)
            nag_count += 1
            
            if last_nag_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=last_nag_id)
                except Exception:
                    pass
            
            nag_msg = await bot.send_message(
                user_id,
                f"🔔 **Эй, не отвлекайся!** Пора делать подход! (прошло уже +{nag_count * 15} сек)\n"
                f"☝️ Нажми кнопку в сообщении выше.",
                parse_mode="Markdown"
            )
            last_nag_id = nag_msg.message_id
            track_message(user_id, nag_msg.message_id)

    except asyncio.CancelledError:
        pass

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    day_key = get_today_schedule_key()
    
    cancel_user_timer(user_id)
    user_data[user_id] = {
        "sets": 0, 
        "exercise_idx": 0, 
        "day_key": day_key, 
        "superset_stage": 1, 
        "remaining_seconds": 0,
        "tracked_messages": []
    }
    
    try:
        await message.delete()
    except Exception:
        pass
        
    await cleanup_all_messages(user_id)
    
    ex = get_current_exercise(user_id)
    day_title = WORKOUT_SCHEDULES[day_key]["title"]
    
    msg = await message.answer(
        f"🏋️‍♂️ **Тренировка начата!**\n\n"
        f"📅 Сегодня: **{day_title}**\n"
        f"1️⃣ Первое упражнение: **{ex['name']}**\n"
        f"Подход: **1 из {MAX_SETS}**\n\n"
        f"Сделай подход и нажми кнопку ниже.",
        reply_markup=get_workout_keyboard(user_id),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)

@dp.message(F.text.lower().contains("магазин"))
async def shop_command(message: types.Message):
    user_id = message.from_user.id
    cancel_user_timer(user_id)
    if user_id not in user_data:
        user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": get_today_schedule_key(), "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}
    
    try:
        await message.delete()
    except Exception:
        pass
        
    await cleanup_all_messages(user_id)
    
    msg = await message.answer("🛒 **Пошел в магазин!** У тебя есть 10 минут.", reply_markup=get_shop_keyboard())
    track_message(user_id, msg.message_id)
    
    ex = get_current_exercise(user_id)
    current_set = user_data[user_id]["sets"] + 1
    base_txt = "🛒 **Режим «Магазин»**"
    finish_txt = f"🛒 **10 минут прошло!** Время возвращаться!\n\n🏋️‍♂️ Упражнение: **{ex['name']}**\nПора делать **{current_set}-й подход**!"
    
    task = asyncio.create_task(live_timer(msg, user_id, 600, base_txt, finish_txt, keyboard=get_shop_keyboard()))
    user_tasks[user_id] = task

@dp.callback_query(F.data == "done_set")
async def process_done_set(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)

    if user_id not in user_data:
        user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": get_today_schedule_key(), "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}

    user_data[user_id]["sets"] += 1
    current_set = user_data[user_id]["sets"]
    ex = get_current_exercise(user_id)

    if current_set >= MAX_SETS:
        user_data[user_id]["sets"] = 0
        user_data[user_id]["exercise_idx"] += 1
        user_data[user_id]["superset_stage"] = 1
        next_ex = get_current_exercise(user_id)
        
        base_txt = f"🎉 **Завершено {MAX_SETS} подхода в «{ex['name']}»!**\n\n➡️ Следующее упражнение: **{next_ex['name']}**"
        finish_txt = f"⏰ **Время отдыха вышло!**\n\n🏋️‍♂️ Начинай делать 1-й подход упражнения: **{next_ex['name']}**!"
    else:
        base_txt = f"💪 **Упражнение:** {ex['name']}\nПодход **№{current_set} из {MAX_SETS}** засчитан!"
        finish_txt = f"⏰ **Время отдыха вышло!**\n\n🏋️‍♂️ Упражнение: **{ex['name']}**\nПора делать **{current_set + 1}-й подход** из {MAX_SETS}!"

    msg = await callback.message.answer("⏱ Запуск таймера...", parse_mode="Markdown")
    track_message(user_id, msg.message_id)

    task = asyncio.create_task(live_timer(msg, user_id, 150, base_txt, finish_txt))
    user_tasks[user_id] = task
    await callback.answer()

@dp.callback_query(F.data == "add_30sec")
async def process_add_30sec(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    current_rem = user_data[user_id].get("remaining_seconds", 0)
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)
    
    new_sec = current_rem + 30 if current_rem > 0 else 30
    ex = get_current_exercise(user_id)
    current_set = user_data[user_id]["sets"] + 1
    
    base_txt = f"⏳ **Добавлено 30 секунд отдыха.**\n🏋️‍♂️ Упражнение: **{ex['name']}**"
    finish_txt = f"⏰ **Дополнительный отдых окончен!** Пора делать **{current_set}-й подход**!"
    
    msg = await callback.message.answer("⏱ Обновление таймера...", parse_mode="Markdown")
    track_message(user_id, msg.message_id)

    task = asyncio.create_task(live_timer(msg, user_id, new_sec, base_txt, finish_txt))
    user_tasks[user_id] = task
    await callback.answer()

@dp.callback_query(F.data == "open_settings")
async def process_open_settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)

    if user_id not in user_data:
        user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": get_today_schedule_key(), "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}
        
    ex = get_current_exercise(user_id)
    current_set = user_data[user_id]["sets"]
    day_title = WORKOUT_SCHEDULES[user_data[user_id]["day_key"]]["title"]
    
    msg = await callback.message.answer(
        f"⚙️ **Настройки тренировки**\n\n"
        f"📅 Программа: **{day_title}**\n"
        f"🏋️‍♂️ Упражнение: **{ex['name']}**\n"
        f"Подходов сделано: **{current_set} из {MAX_SETS}**\n\n"
        f"Выбери действие или смени день:",
        reply_markup=get_settings_keyboard(),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_day_"))
async def process_change_day(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    day_key = callback.data.replace("set_day_", "")
    
    cancel_user_timer(user_id)
    user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": day_key, "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}
    await cleanup_all_messages(user_id)
    
    ex = get_current_exercise(user_id)
    day_title = WORKOUT_SCHEDULES[day_key]["title"]
    
    msg = await callback.message.answer(
        f"🔄 **Программа изменена на: {day_title}**\n\n"
        f"1️⃣ Первое упражнение: **{ex['name']}**\n"
        f"Счетчик подходов сброшен (0/{MAX_SETS}).",
        reply_markup=get_workout_keyboard(user_id),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)
    await callback.answer()

@dp.callback_query(F.data == "add_manual_set")
async def process_add_manual_set(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)

    if user_id not in user_data:
        user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": get_today_schedule_key(), "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}
        
    user_data[user_id]["sets"] += 1
    current_set = user_data[user_id]["sets"]
    ex = get_current_exercise(user_id)

    if current_set >= MAX_SETS:
        user_data[user_id]["sets"] = 0
        user_data[user_id]["exercise_idx"] += 1
        user_data[user_id]["superset_stage"] = 1
        next_ex = get_current_exercise(user_id)
        
        msg = await callback.message.answer(
            f"➕ Добавлен подход! Достигнут лимит в {MAX_SETS} подхода.\n\n"
            f"Переключаемся на новое упражнение: **{next_ex['name']}**!",
            reply_markup=get_workout_keyboard(user_id),
            parse_mode="Markdown"
        )
    else:
        msg = await callback.message.answer(
            f"➕ **Подход добавлен вручную!**\n\n"
            f"Упражнение: **{ex['name']}**\n"
            f"Теперь засчитано подходов: **{current_set} из {MAX_SETS}**",
            reply_markup=get_workout_keyboard(user_id),
            parse_mode="Markdown"
        )
    track_message(user_id, msg.message_id)
    await callback.answer()

@dp.callback_query(F.data == "next_exercise")
async def process_next_exercise(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)

    if user_id not in user_data:
        user_data[user_id] = {"sets": 0, "exercise_idx": 0, "day_key": get_today_schedule_key(), "superset_stage": 1, "remaining_seconds": 0, "tracked_messages": []}
        
    user_data[user_id]["sets"] = 0
    user_data[user_id]["exercise_idx"] += 1
    user_data[user_id]["superset_stage"] = 1
    ex = get_current_exercise(user_id)

    msg = await callback.message.answer(
        f"⏭ Переключено на следующее упражнение: **{ex['name']}**!\n"
        f"Счетчик подходов сброшен (0/{MAX_SETS}).",
        reply_markup=get_workout_keyboard(user_id),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)
    await callback.answer()

@dp.callback_query(F.data == "back_to_workout")
async def process_back_to_workout(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await cleanup_all_messages(user_id)

    ex = get_current_exercise(user_id)
    current_set = user_data[user_id]["sets"]
    
    msg = await callback.message.answer(
        f"🏋️‍♂️ **Продолжаем тренировку!**\n\n"
        f"Упражнение: **{ex['name']}**\n"
        f"Подход: **{current_set + 1} из {MAX_SETS}**",
        reply_markup=get_workout_keyboard(user_id),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)
    await callback.answer()

@dp.callback_query(F.data == "go_shop")
async def process_go_shop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)
    
    ex = get_current_exercise(user_id)
    current_set = user_data[user_id]["sets"] + 1
    base_txt = "🛒 **Режим «Магазин»**"
    finish_txt = f"🛒 **10 минут прошло!** Время возвращаться!\n\n🏋️‍♂️ Упражнение: **{ex['name']}**\nПора делать **{current_set}-й подход**!"
    
    msg = await callback.message.answer("🛒 Режим магазин запущен...", reply_markup=get_shop_keyboard())
    track_message(user_id, msg.message_id)

    task = asyncio.create_task(live_timer(msg, user_id, 600, base_txt, finish_txt, keyboard=get_shop_keyboard()))
    user_tasks[user_id] = task
    await callback.answer()

@dp.callback_query(F.data == "back_from_shop")
async def process_back_from_shop(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cancel_user_timer(user_id)
    await cleanup_all_messages(user_id)

    ex = get_current_exercise(user_id)
    current_set = user_data.get(user_id, {}).get("sets", 0) + 1
    msg = await callback.message.answer(
        f"👍 С возвращением! Пора делать **{current_set}-й подход** в упражнении «{ex['name']}»!",
        reply_markup=get_workout_keyboard(user_id),
        parse_mode="Markdown"
    )
    track_message(user_id, msg.message_id)
    await callback.answer()

# Микро веб-сервер для того, чтобы Render считал сервис активным
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    print("Запуск веб-сервера...")
    await start_web_server()
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
