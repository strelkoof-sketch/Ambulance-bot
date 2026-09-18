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
    "fuel_consumption": 17.74,
    "fuel_price": 62.0,
    "norm_minutes": 20
}

class CallForm(StatesGroup):
    odometer_start = State()
    fuel_start = State()
    number = State()
    from_place = State()
    address = State()
    km_to = State()
    patient_taken = State()
    hospital = State()
    km_from = State()
    odometer_fact = State()
    refuel = State()
    cancel_km = State()

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "settings": DEFAULT_SETTINGS.copy(),
            "fuel_left": 0.0,
            "fuel_start": 0.0,
            "refueled": 0.0,
            "shift_start": None,
            "odometer_start": None,
            "odometer_fact": None,
            "calls": [],
            "cancelled": [],
            "pending_km": 0,
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
    kb.add("❌ Отмена вызова", "⛽ Заправился")
    kb.add("📊 Итог смены")
    kb.add("🌅 Старт смены", "🌙 Конец смены")
    return kb

def yesno_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Да", "Нет")
    return kb

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
    pending = data.get("pending_km", 0)
    text = (
        f"⛽ Топливо: {fuel_status(data['fuel_left'])}\n"
        f"📏 Норма расхода: {s['fuel_consumption']} л/100км\n"
        f"🛢 Спидометр на старте: {odo}\n"
        f"📋 Вызовов: {len(data['calls'])}\n"
        f"❌ Отменённых: {len(data.get('cancelled', []))}"
    )
    if pending > 0:
        text += f"\n⏳ Отложенных км: {pending}"
    await msg.answer(text)

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
    data["cancelled"] = []
    data["pending_km"] = 0
    data["odometer_fact"] = None
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
    if not data["calls"] and not data.get("cancelled"):
        return await msg.answer("За смену ещё нет вызовов.")
    await CallForm.odometer_fact.set()
    calls_km = sum(c["total_km"] for c in data["calls"])
    cancelled_km = sum(c["km"] for c in data.get("cancelled", []))
    total_km = calls_km + cancelled_km + data.get("pending_km", 0)
    calc_end = (data.get("odometer_start") or 0) + total_km
    await msg.answer(
        f"📊 Расчётный одометр на конец: {calc_end} км\n\n"
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
    data["current_call"] = {"accepted": accepted}
    save_data(data)
    await CallForm.number.set()
    pending = data.get("pending_km", 0)
    if pending > 0:
        await msg.answer(
            f"🕐 Время принятия: {accepted}\n"
            f"⏳ Отложенных км с отмены: {pending}\n\n"
            f"Введите номер вызова:"
        )
    else:
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
    await state.finish()
    await msg.answer(
        "🚑 Едете на вызов.\n"
        "Когда прибудете — нажмите «🏥 На адресе».\n"
        "Если отменят — нажмите «❌ Отмена вызова».",
        reply_markup=main_kb()
    )

@dp.message_handler(lambda m: m.text == "🏥 На адресе")
async def on_scene(msg: types.Message):
    data = load_data()
    if not data.get("current_call"):
        return await msg.answer("Нет активного вызова.")
    t = now_orenburg().strftime("%H:%M")
    data["current_call"]["arrived"] = t
    save_data(data)
    await CallForm.km_to.set()
    await msg.answer(
        f"🏥 Время прибытия: {t} (Оренбург)\n\n"
        f"📏 Сколько км от точки А до точки Б? (по картам):"
    )

@dp.message_handler(state=CallForm.km_to)
async def call_km_to(msg: types.Message, state: FSMContext):
    try:
        km = round(float(msg.text.replace(",", ".")))
    except ValueError:
        return await msg.answer("Введите число, например 8")
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
        await msg.answer("🏥 Куда везёте пациента? (название больницы):", reply_markup=main_kb())
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
        km = round(float(msg.text.replace(",", ".")))
    except ValueError:
        return await msg.answer("Введите число, например 5")
    data = load_data()
    data["current_call"]["km_from"] = km
    save_data(data)
    await finish_call(msg, state, data)

async def finish_call(msg: types.Message, state: FSMContext, data):
    c = data["current_call"]
    km_from = c.get("km_from", 0)
    pending = data.get("pending_km", 0)
    own_km = c["km_to"] + km_from
    total_km = own_km + pending
    spent = round(total_km * data["settings"]["fuel_consumption"] / 100, 2)
    data["fuel_left"] -= spent
    c["total_km"] = total_km
    c["own_km"] = own_km
    c["pending_used"] = pending
    c["fuel_spent"] = spent
    c["adjusted_km"] = total_km
    data["pending_km"] = 0
    data["calls"].append(c)
    data["current_call"] = None
    save_data(data)
    await state.finish()

    route = c.get("from_place", "—") + " → " + c["address"]
    if c.get("hospital"):
        route += " → " + c["hospital"]
    else:
        route += " (без доставки)"
    odo_now = (data.get("odometer_start") or 0) + sum(x["adjusted_km"] for x in data["calls"]) + sum(x["km"] for x in data.get("cancelled", []))
    norm = data["settings"]["fuel_consumption"]

    pending_info = ""
    if pending > 0:
        pending_info = f"\n⏳ Включено с отмены: {pending} км\n"

    await msg.answer(
        f"✅ Вызов №{c['number']} закрыт\n"
        f"📍 {route}\n"
        f"🕐 Принят: {c.get('accepted','—')} | На адресе: {c.get('arrived') or '—'}\n"
        f"📏 Пробег: {total_km} км{pending_info}\n"
        f"🛢 Спидометр (расчёт): {odo_now:.0f} км\n"
        f"⛽ Расход по норме ({norm} л/100км): {spent:.2f} л\n"
        f"🛢 Остаток: {fuel_status(data['fuel_left'])}",
        reply_markup=main_kb()
    )

# ========== ОТМЕНА ВЫЗОВА ==========
@dp.message_handler(lambda m: m.text == "❌ Отмена вызова")
async def cancel_start(msg: types.Message):
    data = load_data()
    if not data.get("current_call"):
        return await msg.answer("Нет активного вызова.")
    await CallForm.cancel_km.set()
    await msg.answer("❌ Сколько км проехали до отмены?")

@dp.message_handler(state=CallForm.cancel_km)
async def cancel_save(msg: types.Message, state: FSMContext):
    try:
        km = round(float(msg.text.replace(",", ".")))
    except ValueError:
        return await msg.answer("Введите число, например 5")
    data = load_data()
    c = data["current_call"]
    spent = round(km * data["settings"]["fuel_consumption"] / 100, 2)
    data["fuel_left"] -= spent
    cancelled = {
        "number": c.get("number", "—"),
        "address": c.get("address", "—"),
        "from_place": c.get("from_place", "—"),
        "accepted": c.get("accepted", "—"),
        "km": km,
        "fuel_spent": spent
    }
    data["cancelled"].append(cancelled)
    data["pending_km"] = data.get("pending_km", 0) + km
    data["current_call"] = None
    save_data(data)
    await state.finish()
    await msg.answer(
        f"❌ Вызов №{cancelled['number']} отменён\n"
        f"📍 {cancelled['from_place']} → {cancelled['address']}\n"
        f"📏 Пробег: {km} км (пойдёт в следующий вызов)\n"
        f"⛽ Расход: {spent:.2f} л\n"
        f"🛢 Остаток: {fuel_status(data['fuel_left'])}\n\n"
        f"⏳ Отложено для следующего вызова: {data['pending_km']} км",
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

# ========== ИТОГ СМЕНЫ ==========
async def show_summary(msg: types.Message):
    data = load_data()
    calls = data["calls"]
    cancelled = data.get("cancelled", [])
    if not calls and not cancelled:
        return await msg.answer("За смену ещё нет вызовов.")

    norm = data["settings"]["fuel_consumption"]
    odo_start = data.get("odometer_start")
    odo_fact = data.get("odometer_fact")
    fuel_start = data.get("fuel_start", 0.0)
    refueled = data.get("refueled", 0.0)
    pending = data.get("pending_km", 0)

    calls_km = sum(c["total_km"] for c in calls)
    cancelled_km = sum(c["km"] for c in cancelled)
    calc_total_km = calls_km + cancelled_km + pending
    calc_end = (odo_start or 0) + calc_total_km

    diff_km = 0
    fact_total_km = calc_total_km
    if odo_fact is not None and odo_start is not None:
        fact_total_km = round(odo_fact - odo_start)
        diff_km = fact_total_km - calc_total_km
        if calls_km > 0 and diff_km != 0:
            accumulated = cancelled_km + pending
            for i, c in enumerate(calls):
                if i == len(calls) - 1:
                    new_km = fact_total_km - accumulated
                else:
                    k = c["total_km"] / calls_km
                    new_km = round(c["total_km"] + diff_km * k)
                c["adjusted_km"] = new_km
                accumulated += new_km
        else:
            for c in calls:
                c["adjusted_km"] = c["total_km"]

    for c in calls:
        c["adjusted_fuel"] = round(c["adjusted_km"] * norm / 100, 2)
    adj_norm_fuel = round(sum(c["adjusted_fuel"] for c in calls) + sum(c["fuel_spent"] for c in cancelled), 2)
    fuel_end_calc = round(fuel_start + refueled - adj_norm_fuel, 2)

    text = (
        f"📊 <b>ИТОГ СМЕНЫ (Оренбург)</b>\n"
        f"🌅 Начало: {data['shift_start'] or '—'}\n\n"
        f"🛢 <b>ОДОМЕТР:</b>\n"
    )
    if odo_start is not None:
        text += f"• Начало: {odo_start:.0f} км\n"
    text += f"• Расчёт (по вызовам): {calc_end} км\n"
    if odo_fact is not None:
        text += f"• Факт (введено): {odo_fact:.0f} км\n"
        sign = "+" if diff_km >= 0 else ""
        text += f"• Разница: {sign}{diff_km} км (распределена)\n"
        text += f"• Пробег по спидометру: {fact_total_km} км\n"
    text += f"• Пробег по вызовам: {calls_km} км\n"
    if cancelled_km > 0:
        text += f"• Пробег по отменённым: {cancelled_km} км\n"
    if pending > 0:
        text += f"• Отложено км: {pending}\n"
    text += "\n"

    text += (
        f"⛽ <b>ТОПЛИВО:</b>\n"
        f"• На старте: {fuel_start:.1f} л\n"
        f"• Заправок: +{refueled:.1f} л\n"
        f"• По норме ({norm} л/100км): {adj_norm_fuel:.2f} л\n"
        f"• Остаток (расчёт): {fuel_end_calc:.2f} л\n\n"
        f"🚑 Вызовов: {len(calls)}\n"
    )
    if cancelled:
        text += f"❌ Отменённых: {len(cancelled)}\n"
    text += "\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>ДЛЯ ПУТЕВОГО ЛИСТА:</b>\n"
    )
    if odo_start is not None:
        text += f"• Одометр начало: {odo_start:.0f} км\n"
    if odo_fact is not None:
        text += f"• Одометр конец: {odo_fact:.0f} км\n"
        text += f"• Пробег: {fact_total_km} км\n"
    else:
        text += f"• Одометр конец (расчёт): {calc_end} км\n"
        text += f"• Пробег (расчёт): {calc_total_km} км\n"
    text += (
        f"• Остаток при выезде: {fuel_start:.1f} л\n"
        f"• Заправок: +{refueled:.1f} л\n"
        f"• Расход по норме: {adj_norm_fuel:.2f} л\n"
        f"• Остаток (расчёт): {fuel_end_calc:.2f} л\n"
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
        pend_used = c.get("pending_used", 0)
        text += f"• №{c['number']} — {route}\n"
        text += f"   Принят: {accepted} | На адресе: {arrived}{delivery}\n"
        if pend_used > 0:
            text += f"   Свои: {c.get('own_km', 0)} км + отмена: {pend_used} км = {adj} км, {adj_f:.2f} л\n"
        elif adj != c["total_km"]:
            text += f"   {c['total_km']} км → {adj} км, {adj_f:.2f} л\n"
        else:
            text += f"   {adj} км, {adj_f:.2f} л\n"

    if cancelled:
        text += f"\n❌ <b>ОТМЕНЁННЫЕ ВЫЗОВЫ (км ушли в следующий вызов):</b>\n"
        for c in cancelled:
            text += f"• №{c['number']} — {c['from_place']} → {c['address']}\n"
            text += f"   Принят: {c['accepted']} | Отменён\n"
            text += f"   {c['km']} км, {c['fuel_spent']:.2f} л\n"

    await msg.answer(text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "📊 Итог смены")
async def summary(msg: types.Message):
    await show_summary(msg)

if __name__ == "__main__":
    print("Bot started")
    executor.start_polling(dp, skip_updates=True)
