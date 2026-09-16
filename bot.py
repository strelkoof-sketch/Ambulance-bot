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

ORENBURG_TZ = timezone(timedelta(hours=5))

def now_orenburg():
    return datetime.now(ORENBURG_TZ)

DEFAULT_SETTINGS = {
    "fuel_consumption": 13.5,
    "fuel_price": 62.0,
    "norm_minutes": 20
}

class CallForm(StatesGroup):
    odometer_start = State()
    fuel_start = State()
    number = State()
    from_place = State()
    address = State()
    arrived = State()
    km_to = State()
    patient_taken = State()
    hospital = State()
    km_from = State()
    odometer_fact = State()
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
            "odometer_fact": None,
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
    data["odometer_fact"] = None
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
    data = load_data()
    if not data["calls"]:
        return await msg.answer("За смену ещё нет вызовов.")
    await CallForm.odometer_fact.set()
    calc_end = (data.get("odometer_start") or 0) + sum(c["total_km"] for c in data["calls"])
    await msg.answer(
        f"📊 Расчётный одометр на конец: {calc_end:.0f} км\n\n"
        f"🛢 Введите фактическое показание спидометра (км):"
    )

@dp.message_handler(state=CallForm.odometer_fact)
async def shift_odometer_fact(msg: types.Message, state: FSMContext):
    text = msg.text.replace(" ", "").replace(",", ".")
    try:
        odo_fact = float(text)
    except ValueError:
        return await msg.answer("Введите число, например 125512")
    data = load_data()
    data["odometer_fact"] = odo_fact
    save_data(data)
    await state.finish()
    await show_summary(msg)

# ========== НОВЫЙ ВЫЗОВ ==========
@dp.message_handler(lambda m: m.text == "🚑 Новый вызов")
async def new_call(msg: types.Message):
    data = load_data()
    accepted = now_orenburg().strftime("%H:%M")
    last_point = ""
    if data["calls"]:
        last = data["calls"][-1]
        last_point = last.get("hospital") or last.get("address") or ""
    data["current_call"] = {"accepted": accepted}
    save_data(data)
    await CallForm.number.set()
    await msg.answer(f"🕐 Время принятия: {accepted}\n\nВведите номер вызова:")

@dp.message_handler(state=CallForm.number)
async def call_number(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["number"] = msg.text
    save_data(data)
    await CallForm.from_place.set()
    await msg.answer("🚗 Откуда выезжаете?")

@dp.message_handler(state=CallForm.from_place)
async def call_from(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["from_place"] = msg.text
    save_data(data)
    await CallForm.address.set()
    await msg.answer("📍 Куда едете? (адрес вызова):")

@dp.message_handler(state=CallForm.address)
async def call_address(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["address"] = msg.text
    save_data(data)
    await CallForm.arrived.set()
    await msg.answer("🕐 Время прибытия на адрес? (ЧЧ:ММ) или «-»:")

@dp.message_handler(state=CallForm.arrived)
async def call_arrived(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["arrived"] = msg.text if msg.text != "-" else None
    save_data(data)
    addr = data["current_call"]["address"]
    yandex_link = f"https://yandex.ru/maps/?text={addr}, Оренбург"
    await CallForm.km_to.set()
    await msg.answer(
        f"🗺️ Маршрут: {yandex_link}\n\n"
        f"📏 Сколько км до адреса? (по картам):"
    )

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
    await msg.answer("👤 Пациента взяли? (Да / Нет)", reply_markup=yesno_kb())

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
        await msg.answer("🏥 Куда везёте пациента? (название больницы):")
    else:
        await finish_call(msg, state, data)

@dp.message_handler(state=CallForm.hospital)
async def call_hospital(msg: types.Message, state: FSMContext):
    data = load_data()
    data["current_call"]["hospital"] = msg.text
    save_data(data)
    await CallForm.km_from.set()
    await msg.answer("📏 Сколько км до больницы? (число):")

@dp.message_handler(state=CallForm.km_from)
async def call_km_from(msg: types.Message, state: FSMContext):
    try:
        km = float(msg.text.replace(",", "."))
    except ValueError:
        return await msg.answer("Введите число, например 5.4")
    data = load_data()
    data["current_call"]["km_from"] = km
    save_data(data)
    await finish_call(msg, state, data)

async def finish_call(msg: types.Message, state: FSMContext, data):
    c = data["current_call"]
    km_from = c.get("km_from", 0)
    total_km = c["km_to"] + km_from
    spent = calc_fuel(total_km, data)
    data["fuel_left"] -= spent
    c["total_km"] = total_km
    c["fuel_spent"] = spent
    c["adjusted_km"] = total_km
    data["calls"].append(c)
    data["current_call"] = None
    save_data(data)
    await state.finish()

    route = c.get("from_place", "—") + " → " + c["address"]
    if c.get("hospital"):
        route += " → " + c["hospital"]
    else:
        route += " (без доставки)"
    odo_now = (data.get("odometer_start") or 0) + sum(x["adjusted_km"] for x in data["calls"])
    norm = data["settings"]["fuel_consumption"]

    await msg.answer(
        f"✅ Вызов №{c['number']} закрыт\n"
        f"📍 {route}\n"
        f"🕐 Принят: {c.get('accepted','—')} | На адресе: {c.get('arrived') or '—'}\n"
        f"📏 Пробег: {total_km:.1f} км\n"
        f"🛢 Спидометр (расчёт): {odo_now:.0f} км\n"
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
        t = now_orenburg().strftime("%H:%M")
        data["current_call"]["arrived"] = t
        save_data(data)
        await msg.answer(f"🏥 Время прибытия: {t} (Оренбург)")
    else:
        await msg.answer("Нет активного вызова.")

# ========== ИТОГ СМЕНЫ С ПОДГОНКОЙ ==========
async def show_summary(msg: types.Message):
    data = load_data()
    calls = data["calls"]
    if not calls:
        return await msg.answer("За смену ещё нет вызовов.")

    norm = data["settings"]["fuel_consumption"]
    odo_start = data.get("odometer_start")
    odo_fact = data.get("odometer_fact")
    fuel_start = data.get("fuel_start", 0.0)
    refueled = data.get("refueled", 0.0)

    calc_total_km = sum(c["total_km"] for c in calls)
    calc_end = (odo_start or 0) + calc_total_km

    # Подгонка, если введён фактический одометр
    diff_km = 0.0
    fact_total_km = calc_total_km
    if odo_fact is not None and odo_start is not None:
        fact_total_km = odo_fact - odo_start
        diff_km = fact_total_km - calc_total_km
        if calc_total_km > 0 and abs(diff_km) > 0.01:
            # пропорциональная подгонка
            for c in calls:
                k = c["total_km"] / calc_total_km
                c["adjusted_km"] = c["total_km"] + diff_km * k
        else:
            for c in calls:
                c["adjusted_km"] = c["total_km"]

    # пересчёт топлива от скорректированного пробега
    for c in calls:
        c["adjusted_fuel"] = c["adjusted_km"] * norm / 100
    adj_norm_fuel = sum(c["adjusted_fuel"] for c in calls)
    fact_fuel = (fuel_start + refueled) - (fuel_start + refueled - adj_norm_fuel)  # = adj_norm_fuel
    # фактический остаток = старт + заправки - расход
    fuel_end_calc = fuel_start + refueled - adj_norm_fuel

    text = (
        f"📊 <b>ИТОГ СМЕНЫ (Оренбург)</b>\n"
        f"🌅 Начало: {data['shift_start'] or '—'}\n\n"
        f"🛢 <b>ОДОМЕТР:</b>\n"
    )
    if odo_start is not None:
        text += f"• Начало: {odo_start:.0f} км\n"
    text += f"• Расчёт (по вызовам): {calc_end:.0f} км\n"
    if odo_fact is not None:
        text += f"• Факт (введено): {odo_fact:.0f} км\n"
        sign = "+" if diff_km >= 0 else ""
        text += f"• Разница: {sign}{diff_km:.1f} км (распределена)\n"
        text += f"• Пробег по спидометру: {fact_total_km:.1f} км\n"
    text += f"• Пробег по вызовам (расчёт): {calc_total_km:.1f} км\n\n"

    text += (
        f"⛽ <b>ТОПЛИВО:</b>\n"
        f"• На старте: {fuel_start:.1f} л\n"
        f"• Заправок: +{refueled:.1f} л\n"
        f"• По норме ({norm} л/100км): {adj_norm_fuel:.2f} л\n"
        f"• Остаток (расчёт): {fuel_end_calc:.1f} л\n\n"
        f"🚑 Вызовов: {len(calls)}\n\n"
    )

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>ДЛЯ ПУТЕВОГО ЛИСТА:</b>\n"
    )
    if odo_start is not None:
        text += f"• Одометр начало: {odo_start:.0f} км\n"
    if odo_fact is not None:
        text += f"• Одометр конец: {odo_fact:.0f} км\n"
        text += f"• Пробег: {fact_total_km:.1f} км\n"
    else:
        text += f"• Одометр конец (расчёт): {calc_end:.0f} км\n"
        text += f"• Пробег (расчёт): {calc_total_km:.1f} км\n"
    text += (
        f"• Остаток при выезде: {fuel_start:.1f} л\n"
        f"• Заправок: +{refueled:.1f} л\n"
        f"• Расход по норме: {adj_norm_fuel:.2f} л\n"
        f"• Остаток (расчёт): {fuel_end_calc:.1f} л\n"
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
        route = c.get("from_place", "—") + " → " + c["address"]
        if c.get("hospital"):
            route += " → " + c["hospital"]
        else:
            route += " (без доставки)"
        adj = c.get("adjusted_km", c["total_km"])
        adj_f = c.get("adjusted_fuel", c.get("fuel_spent", 0))
        text += f"• №{c['number']} — {route}\n"
        text += f"   Принят: {accepted} | На адресе: {arrived}{delivery}\n"
        if abs(adj - c["total_km"]) > 0.01:
            text += f"   {c['total_km']:.1f} км → {adj:.1f} км, {adj_f:.2f} л\n"
        else:
            text += f"   {adj:.1f} км, {adj_f:.2f} л\n"
    await msg.answer(text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "📊 Итог смены")
async def summary(msg: types.Message):
    await show_summary(msg)

if __name__ == "__main__":
    print("Bot started")
    executor.start_polling(dp, skip_updates=True)
