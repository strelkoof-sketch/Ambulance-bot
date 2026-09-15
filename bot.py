import os
import json
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "shift_data.json"

DEFAULT_SETTINGS = {
    "fuel_consumption": 13.5,
    "tank_volume": 60,
    "fuel_price": 62.0,
    "norm_minutes": 20
}

class CallForm(StatesGroup):
    number = State()
    address = State()
    km_to = State()
    hospital = State()
    km_from = State()
    time_on_scene = State()
    refuel = State()

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "settings": DEFAULT_SETTINGS.copy(),
            "fuel_left": DEFAULT_SETTINGS["tank_volume"] * 0.75,
            "shift_start": None,
            "calls": [],
            "current_call": None
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🚑 Новый вызов", "🏥 На адресе")
    kb.add("⛽ Заправился", "📊 Итог смены")
    kb.add("🌅 Старт смены", "🌙 Конец смены")
    return kb

def calc_fuel(km, data):
    return km * data["settings"]["fuel_consumption"] / 100

def fuel_status(data):
    left = data["fuel_left"]
    tank = data["settings"]["tank_volume"]
    percent = left / tank * 100
    if left < 10:
        flag = "🔴 СРОЧНО ЗАПРАВИТЬСЯ"
    elif left < 20:
        flag = "🟡 низкий уровень"
    else:
        flag = "🟢 ок"
    return f"{left:.1f} л ({percent:.0f}%) {flag}"

@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    await msg.answer(
        "🚑 <b>Помощник водителя скорой</b>\n\n"
        "Кнопки снизу — управление сменой.\n"
        "Начните со «🌅 Старт смены».",
        parse_mode="HTML",
        reply_markup=main_kb()
    )

@dp.message_handler(commands=["status"])
async def status(msg: types.Message):
    data = load_data()
    s = data["settings"]
    await msg.answer(
        f"⛽ Топливо: {fuel_status(data)}\n"
        f"📏 Расход: {s['fuel_consumption']} л/100км\n"
        f"📋 Вызовов: {len(data['calls'])}"
    )

@dp.message_handler(lambda m: m.text == "🌅 Старт смены")
async def shift_start(msg: types.Message):
    data = load_data()
    data["shift_start"] = datetime.now().strftime("%d.%m %H:%M")
    data["calls"] = []
    save_data(data)
    await msg.answer(f"🌅 Смена начата: {data['shift_start']}\n⛽ Топливо: {fuel_status(data)}")

@dp.message_handler(lambda m: m.text == "🌙 Конец смены")
async def shift_end(msg: types.Message):
    data = load_data()
    data["shift_start"] = None
    save_data(data)
    await msg.answer("🌙 Смена завершена.")

@dp.message_handler(lambda m: m.text == "🚑 Новый вызов")
async def new_call(msg: types.Message):
    data = load_data()
    data["current_call"] = {"accepted": datetime.now().strftime("%H:%M")}
    save_data(data)
    await CallForm.number.set()
    await msg.answer("Введите номер вызова:")

@dp.message_handler(state=CallForm.number)
async def call_number(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["number"] = msg.text
    save_data(data)
    await CallForm.address.set()
    await msg.answer("Введите адрес вызова:")

@dp.message_handler(state=CallForm.address)
async def call_address(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["address"] = msg.text
    save_data(data)
    await CallForm.km_to.set()
    await msg.answer("Сколько км до адреса? (число)")

@dp.message_handler(state=CallForm.km_to)
async def call_km_to(msg: types.Message, state: FSMContext):
    try:
        km = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("Введите число, например 8.2")
    data = load_data()
    data["current_call"]["km_to"] = km
    save_data(data)
    await CallForm.hospital.set()
    await msg.answer("Введите название больницы:")

@dp.message_handler(state=CallForm.hospital)
async def call_hospital(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["hospital"] = msg.text
    save_data(data)
    await CallForm.km_from.set()
    await msg.answer("Сколько км до больницы? (число)")

@dp.message_handler(state=CallForm.km_from)
async def call_km_from(msg: types.Message, state: FSMContext):
    try:
        km = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("Введите число, например 5.4")
    data = load_data()
    data["current_call"]["km_from"] = km
    save_data(data)
    await CallForm.time_on_scene.set()
    await msg.answer("Время прибытия на адрес? (ЧЧ:ММ) или «-»")

@dp.message_handler(state=CallForm.time_on_scene)
async def call_finish(msg: types.Message, state: FSMContext):
    data = load_data()
    c = data["current_call"]
    c["arrived"] = msg.text if msg.text != "-" else None
    total_km = c["km_to"] + c["km_from"]
    spent = calc_fuel(total_km, data)
    data["fuel_left"] -= spent
    c["total_km"] = total_km
    c["fuel_spent"] = spent
    data["calls"].append(c)
    data["current_call"] = None
    save_data(data)
    await state.finish()
    await msg.answer(
        f"✅ Вызов №{c['number']} закрыт\n"
        f"📍 {c['address']} → {c['hospital']}\n"
        f"📏 Пробег: {total_km:.1f} км\n"
        f"⛽ Расход: {spent:.2f} л\n"
        f"🛢 Остаток: {fuel_status(data)}",
        reply_markup=main_kb()
    )

@dp.message_handler(lambda m: m.text == "⛽ Заправился")
async def refuel_start(msg: types.Message):
    await CallForm.refuel.set()
    await msg.answer("Сколько литров залили?")

@dp.message_handler(state=CallForm.refuel)
async def refuel_save(msg: types.Message, state: FSMContext):
    try:
        liters = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("Введите число, например 40")
    data = load_data()
    data["fuel_left"] += liters
    if data["fuel_left"] > data["settings"]["tank_volume"]:
        data["fuel_left"] = data["settings"]["tank_volume"]
    save_data(data)
    await state.finish()
    await msg.answer(f"⛽ Заправлено: {liters} л\n🛢 В баке: {fuel_status(data)}", reply_markup=main_kb())

@dp.message_handler(lambda m: m.text == "🏥 На адресе")
async def on_scene(msg: types.Message):
    await msg.answer("🏥 Отметьте время прибытия и продолжите ввод вызова.")

@dp.message_handler(lambda m: m.text == "📊 Итог смены")
async def summary(msg: types.Message):
    data = load_data()
    calls = data["calls"]
    if not calls:
        return await msg.answer("За смену ещё нет вызовов.")
    total_km = sum(c["total_km"] for c in calls)
    total_fuel = sum(c["fuel_spent"] for c in calls)
    text = (
        f"📊 <b>ИТОГ СМЕНЫ</b>\n"
        f"🌅 Начало: {data['shift_start'] or '—'}\n"
        f"🚑 Вызовов: {len(calls)}\n"
        f"📏 Пробег: {total_km:.1f} км\n"
        f"⛽ Расход: {total_fuel:.2f} л\n"
        f"🛢 Остаток: {fuel_status(data)}\n\n"
    )
    for c in calls:
        text += f"• №{c['number']} — {c['address']} → {c['hospital']}\n"
        text += f"   {c['total_km']:.1f} км, {c['fuel_spent']:.2f} л\n"
    await msg.answer(text, parse_mode="HTML")

if __name__ == "__main__":
    print("Bot started")
    executor.start_polling(dp, skip_updates=True)
