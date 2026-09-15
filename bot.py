import os
import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "shift_data.json"

# Оренбург = UTC+5
ORENBURG_TZ = timezone(timedelta(hours=5))

def now_orenburg():
    return datetime.now(ORENBURG_TZ)

# НОРМА РАСХОДА — меняйте здесь (л/100 км)
DEFAULT_SETTINGS = {
    "fuel_consumption": 13.5,
    "fuel_price": 62.0,
    "norm_minutes": 20
}

class CallForm(StatesGroup):
    odometer_start = State()
    fuel_start = State()
    number = State()
    address = State()
    km_to = State()
    patient_taken = State()
    hospital = State()
    km_from = State()
    time_on_scene = State()
    odometer_end = State()
    fuel_end = State()
    refuel = State()

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "settings": DEFAULT_SETTINGS.copy(),
            "fuel_left": 0.0,
            "fuel_start": 0.0,
            "fuel_end": 0.0,
            "refueled": 0.0,
            "shift_start": None,
            "odometer_start": None,
            "odometer_end": None,
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

def yesno_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Да", "Нет")
    return kb

def calc_fuel(km, data):
    return km * data["settings"]["fuel_consumption"] / 100

def fuel_status(left):
    if left < 10:
        flag = "🔴 СРОЧНО ЗАПРАВИТЬСЯ"
    elif left < 20:
        flag = "🟡 низкий уровень"
    else:
        flag = "🟢 ок"
    return f"{left:.1f} л {flag}"

@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    s = DEFAULT_SETTINGS
    await msg.answer(
        "🚑 <b>Помощник водителя скорой</b>\n\n"
        f"📏 Норма расхода: {s['fuel_consumption']} л/100 км\n"
        f"⏱ Норматив подачи: {s['norm_minutes']} мин\n\n"
        "Начните со «🌅 Старт смены».",
        parse_mode="HTML",
        reply_markup=main_kb()
    )

@dp.message_handler(commands=["status"])
async def status(msg: types.Message):
    data = load_data()
    s = data["settings"]
    odo = data.get("odometer_start") or "—"
    await msg.answer(
        f"⛽ Топливо: {fuel_status(data['fuel_left'])}\n"
        f"📏 Норма расхода: {s['fuel_consumption']} л/100км\n"
        f"🛢 Спидометр на старте: {odo}\n"
        f"📋 Вызовов: {len(data['calls'])}"
    )

# ========== СТАРТ СМЕНЫ ==========
@dp.message_handler(lambda m: m.text == "🌅 Старт смены")
async def shift_start(msg: types.Message):
    await CallForm.odometer_start.set()
    await msg.answer("🛢 Введите показание спидометра на начало смены (км):")

@dp.message_handler(state=CallForm.odometer_start)
async def shift_odometer(msg: types.Message, state: FSMContext):
    text = msg.text.replace(" ", "").replace(",", ".")
    try:
        odo = float(text)
    except ValueError:
        return await msg.answer("Введите число, например 125430")
    data = load_data()
    data["odometer_start"] = odo
    save_data(data)
    await CallForm.fuel_start.set()
    await msg.answer("⛽ Сколько сейчас топлива в баке? (л):")

@dp.message_handler(state=CallForm.fuel_start)
async def shift_fuel(msg: types.Message, state: FSMContext):
    text = msg.text.replace(" ", "").replace(",", ".")
    try:
        fuel = float(text)
    except ValueError:
        return await msg.answer("Введите число, например 52.5")
    data = load_data()
    s = data["settings"]
    data["shift_start"] = now_orenburg().strftime("%d.%m %H:%M")
    data["fuel_start"] = fuel
    data["fuel_left"] = fuel
    data["refueled"] = 0.0
    data["calls"] = []
    data["odometer_end"] = None
    data["fuel_end"] = None
    save_data(data)
    await state.finish()
    await msg.answer(
        f"🌅 Смена начата: {data['shift_start']} (Оренбург)\n"
        f"🛢 Спидометр: {data['odometer_start']:.0f} км\n"
        f"⛽ Остаток топлива: {fuel:.1f} л\n"
        f"📏 Норма расхода: {s['fuel_consumption']} л/100 км\n\n"
        f"Жду первый вызов.",
        reply_markup=main_kb()
    )

# ========== КОНЕЦ СМЕНЫ ==========
@dp.message_handler(lambda m: m.text == "🌙 Конец смены")
async def shift_end(msg: types.Message):
    await CallForm.odometer_end.set()
    await msg.answer("🛢 Введите показание спидометра на конец смены (км):")

@dp.message_handler(state=CallForm.odometer_end)
async def shift_odometer_end(msg: types.Message, state: FSMContext):
    text = msg.text.replace(" ", "").replace(",", ".")
    try:
        odo_end = float(text)
    except ValueError:
        return await msg.answer("Введите число, например 125512")
    data = load_data()
    odo_start = data.get("odometer_start")
    if odo_start is not None and odo_end < odo_start:
        return await msg.answer("Спидометр на конец меньше, чем на начало. Проверьте число.")
    data["odometer_end"] = odo_end
    save_data(data)
    await CallForm.fuel_end.set()
    await msg.answer("⛽ Сколько топлива осталось в баке? (л):")

@dp.message_handler(state=CallForm.fuel_end)
async def shift_fuel_end(msg: types.Message, state: FSMContext):
    text = msg.text.replace(" ", "").replace(",", ".")
    try:
        fuel_end = float(text)
    except ValueError:
        return await msg.answer("Введите число, например 40.0")
    data = load_data()
    data["fuel_end"] = fuel_end
    data["fuel_left"] = fuel_end
    save_data(data)
    await state.finish()
    await show_summary(msg)
    data = load_data()
    data["shift_start"] = None
    save_data(data)

# ========== НОВЫЙ ВЫЗОВ ==========
@dp.message_handler(lambda m: m.text == "🚑 Новый вызов")
async def new_call(msg: types.Message):
    data = load_data()
    data["current_call"] = {"accepted": now_orenburg().strftime("%H:%M")}
    save_data(data)
    await CallForm.number.set()
    await msg.answer("Введите номер вызова:")

@dp.message_handler(state=CallForm.number)
async def call_number(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["number"] = msg.text
    save_data(data)
    await CallForm.address.set()
    await msg.answer("Введите адрес вызова (откуда):")

@dp.message_handler(state=CallForm.address)
async def call_address(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["address"] = msg.text
    save_data(data)
    yandex_link = f"https://yandex.ru/maps/?text={msg.text}, Оренбург"
    await msg.answer(
        f"🗺️ Маршрут: {yandex_link}\n\n"
        f"Сколько км до адреса? (число)"
    )
    await CallForm.km_to.set()

@dp.message_handler(state=CallForm.km_to)
async def call_km_to(msg: types.Message, state: FSMContext):
    try:
        km = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("Введите число, например 8.2")
    data = load_data()
    data["current_call"]["km_to"] = km
    save_data(data)
    await CallForm.patient_taken.set()
    await msg.answer("Пациента взяли? (Да / Нет)", reply_markup=yesno_kb())

@dp.message_handler(state=CallForm.patient_taken)
async def call_patient(msg: types.Message, state: FSMContext):
    ans = msg.text.strip().lower()
    if ans not in ("да", "нет"):
        return await msg.answer("Ответьте «Да» или «Нет»", reply_markup=yesno_kb())
    data = load_data()
    data["current_call"]["patient_taken"] = (ans == "да")
    save_data(data)
    if ans == "да":
        await CallForm.hospital.set()
        await msg.answer("Куда везёте пациента? (название больницы):")
    else:
        await CallForm.time_on_scene.set()
        await msg.answer("Время прибытия на адрес? (ЧЧ:ММ) или «-»", reply_markup=types.ReplyKeyboardRemove())

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
    km_from = c.get("km_from", 0)
    total_km = c["km_to"] + km_from
    spent = calc_fuel(total_km, data)
    data["fuel_left"] -= spent
    c["total_km"] = total_km
    c["fuel_spent"] = spent
    data["calls"].append(c)
    data["current_call"] = None
    save_data(data)
    await state.finish()

    route = c["address"] + (" → " + c["hospital"] if c.get("hospital") else " (без доставки)")
    odo_now = (data.get("odometer_start") or 0) + sum(x["total_km"] for x in data["calls"])
    norm = data["settings"]["fuel_consumption"]

    await msg.answer(
        f"✅ Вызов №{c['number']} закрыт\n"
        f"📍 {route}\n"
        f"📏 Пробег: {total_km:.1f} км\n"
        f"🛢 Спидометр: {odo_now:.0f} км\n"
        f"⛽ Расход по норме ({norm} л/100км): {spent:.2f} л\n"
        f"🛢 Остаток: {fuel_status(data['fuel_left'])}",
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
    data["refueled"] = data.get("refueled", 0.0) + liters
    save_data(data)
    await state.finish()
    await msg.answer(f"⛽ Заправлено: {liters} л\n🛢 В баке: {fuel_status(data['fuel_left'])}", reply_markup=main_kb())

@dp.message_handler(lambda m: m.text == "🏥 На адресе")
async def on_scene(msg: types.Message):
    data = load_data()
    if data.get("current_call"):
        data["current_call"]["arrived"] = now_orenburg().strftime("%H:%M")
        save_data(data)
        await msg.answer(f"🏥 Время прибытия: {data['current_call']['arrived']} (Оренбург)")
    else:
        await msg.answer("Нет активного вызова.")

# ========== ИТОГ СМЕНЫ ==========
async def show_summary(msg: types.Message):
    data = load_data()
    calls = data["calls"]
    if not calls:
        return await msg.answer("За смену ещё нет вызовов.")

    total_km = sum(c["total_km"] for c in calls)
    norm_fuel = sum(c["fuel_spent"] for c in calls)
    norm = data["settings"]["fuel_consumption"]

    odo_start = data.get("odometer_start")
    odo_end = data.get("odometer_end")
    real_km = (odo_end - odo_start) if (odo_start is not None and odo_end is not None) else None

    fuel_start = data.get("fuel_start", 0.0)
    fuel_end = data.get("fuel_end", 0.0)
    refueled = data.get("refueled", 0.0)
    fact_fuel = (fuel_start + refueled) - fuel_end

    text = (
        f"📊 <b>ИТОГ СМЕНЫ (Оренбург)</b>\n"
        f"🌅 Начало: {data['shift_start'] or '—'}\n\n"
        f"🛢 <b>ОДОМЕТР:</b>\n"
    )
    if odo_start is not None:
        text += f"• Начало: {odo_start:.0f} км\n"
    if odo_end is not None:
        text += f"• Конец: {odo_end:.0f} км\n"
    if real_km is not None:
        text += f"• Пробег по спидометру: {real_km:.1f} км\n"
    text += f"• Пробег по вызовам: {total_km:.1f} км\n\n"

    text += (
        f"⛽ <b>ТОПЛИВО:</b>\n"
        f"• На старте: {fuel_start:.1f} л\n"
        f"• Заправок: +{refueled:.1f} л\n"
        f"• На конце: {fuel_end:.1f} л\n"
        f"• По норме ({norm} л/100км): {norm_fuel:.2f} л\n"
        f"• Фактический расход: {fact_fuel:.2f} л\n\n"
        f"🚑 Вызовов: {len(calls)}\n\n"
    )

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>ДЛЯ ПУТЕВОГО ЛИСТА:</b>\n"
    )
    if real_km is not None:
        text += f"• Пробег: {real_km:.1f} км\n"
    else:
        text += f"• Пробег: {total_km:.1f} км\n"
    text += (
        f"• Расход по норме: {norm_fuel:.2f} л\n"
        f"• Фактический расход: {fact_fuel:.2f} л\n"
        f"• Остаток в баке: {fuel_end:.1f} л\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for c in calls:
        accepted = c.get("accepted", "—")
        arrived = c.get("arrived") or "—"
        delivery = ""
        try:
            t1 = datetime.strptime(accepted, "%H:%M")
            t2 = datetime.strptime(arrived, "%H:%M")
            minutes = (t2 - t1).seconds // 60
            mark = "⚠️" if minutes > data["settings"]["norm_minutes"] else "✅"
            delivery = f" | Подача: {minutes} мин {mark}"
        except Exception:
            pass
        route = c["address"] + (" → " + c["hospital"] if c.get("hospital") else " (без доставки)")
        text += f"• №{c['number']} — {route}\n"
        text += f"   Принят: {accepted} | На адресе: {arrived}{delivery}\n"
        text += f"   {c['total_km']:.1f} км, {c['fuel_spent']:.2f} л\n"
    await msg.answer(text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "📊 Итог смены")
async def summary(msg: types.Message):
    await show_summary(msg)

if __name__ == "__main__":
    print("Bot started")
    executor.start_polling(dp, skip_updates=True)
