# -*- coding: utf-8 -*-
"""Telegram-обработчик ИНН + формат карточки."""
import re
import html
from datetime import datetime
from aiogram import Router, types
from .checker import check_inn
from .scoring import compute_verdict, _to_number, business_age
from . import config as C

router = Router(name="inn_checker")
INN_RE = re.compile(r"^\d{10}$|^\d{12}$")


def _esc(s):
    return html.escape(str(s)) if s is not None else "—"


def _money(n):
    n = _to_number(n)
    if n is None:
        return "—"
    return f"{n:,.0f} ₽".replace(",", " ")


def _status_mark(st):
    return {"ok": "✅", "пусто": "▫️", "не проверено": "⚠️"}.get(st, "?")


def _pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", {}, [], 0):
            return v
    return None


def _nested(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _stat_naim(status):
    if isinstance(status, dict):
        return status.get("Наим") or status.get("Код")
    return status


def _support_total(support):
    total = 0.0
    for s in support:
        sz = str(s.get("Размер", ""))
        if "руб" in sz:
            try:
                total += float(sz.replace("руб.", "").replace("руб", "").strip())
            except ValueError:
                pass
    return total


def _render_company(comp):
    d = comp["data"]
    lines = []

    name = _pick(d, "НаимСокр", "НаимПолн") or d.get("ФИО")
    status = _stat_naim(d.get("Статус"))
    reg = d.get("ДатаРег")

    lines.append(f"🏢 <b>{_esc(name)}</b>")
    if status:
        lines.append(f"📌 Статус: {_esc(status)}")
    if reg:
        age = business_age(reg)
        lines.append(f"📅 Регистрация: {_esc(reg)}" + (f" ({age})" if age else ""))

    addr = _nested(d, "ЮрАдрес", "АдресРФ")
    if addr:
        lines.append(f"📍 {_esc(addr)}")

    okv_kod = _nested(d, "ОКВЭД", "Код")
    okv_naim = _nested(d, "ОКВЭД", "Наим")
    if okv_kod:
        lines.append(f"🔧 ОКВЭД: {_esc(okv_kod)} — {_esc(okv_naim)}")

    capital = _nested(d, "УстКап", "Сумма")
    if capital is not None:
        lines.append(f"💰 Уставный капитал: {_money(capital)}")

    ruk = d.get("Руковод")
    director = None
    if isinstance(ruk, list) and ruk:
        director = ruk[0].get("ФИО")
    elif isinstance(ruk, dict):
        director = ruk.get("ФИО")
    if director:
        lines.append(f"👤 Руководитель: {_esc(director)}")

    fl = _nested(d, "Учред", "ФЛ") or []
    founders = []
    for f in fl if isinstance(fl, list) else []:
        fio = f.get("ФИО")
        pct = _nested(f, "Доля", "Процент")
        if fio:
            founders.append(f"{fio}" + (f" ({pct:g}%)" if pct else ""))
    if founders:
        lines.append(f"👥 Учредители: {_esc('; '.join(founders))}")

    schr = d.get("СЧР")
    schr_year = d.get("СЧРГод")
    if schr is not None:
        lines.append(f"🧮 Численность: {_esc(schr)} чел."
                     + (f" ({schr_year})" if schr_year else ""))

    debt = _nested(d, "Налоги", "СумНедоим")
    debt_date = _nested(d, "Налоги", "НедоимДата")
    if debt is not None:
        suffix = f" (на {debt_date})" if debt_date else ""
        lines.append(f"💸 Налоговая задолженность: {_money(debt)}{suffix}")

    support = d.get("ПоддержМСП") or []
    if support:
        total_sup = _support_total(support)
        extra = f", {_money(total_sup)}" if total_sup else ""
        lines.append(f"🎁 Меры поддержки МСП: {len(support)} записей{extra}")

    return lines


def format_card(inn, results, verdict):
    level = verdict["level"]
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [f"<b>{C.VERDICT[level]}</b> — ИНН <code>{inn}</code> — на {now}", ""]

    comp = results.get("company", {})
    if comp.get("status") == C.STATUS_OK:
        lines.extend(_render_company(comp))
        lines.append("")
    elif comp.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"🏢 ЕГРЮЛ/ЕГРИП: <i>не проверено</i> ({_esc(comp.get('reason'))})")
        lines.append("")

    fin = results.get("finances", {})
    if fin.get("status") == C.STATUS_OK:
        data = fin["data"]
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        year_keys = [k for k in data if str(k).isdigit()] if isinstance(data, dict) else []
        if year_keys:
            years = sorted(year_keys, reverse=True)[:5]
            lines.append("📊 <b>Выручка / прибыль по годам</b>")
            for y in years:
                d = data[y]
                rev = _money(d.get("revenue") or d.get("2110"))
                prof = _money(d.get("net_profit") or d.get("2400"))
                lines.append(f"   • {y}: {rev} / прибыль {prof}")
            lines.append("")
        else:
            lines.append("📊 Финансы: <i>пустой ответ</i>")
            lines.append("")
    elif fin.get("status") == C.STATUS_EMPTY:
        lines.append("📊 Финансы: <i>отчётности нет</i>")
        lines.append("")
    elif fin.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"📊 Финансы: <i>не проверено</i> ({_esc(fin.get('reason'))})")
        lines.append("")

    con = results.get("contracts", {})
    if con.get("status") == C.STATUS_OK:
        lines.append("🏛️ <b>Госзакупки</b>")
        for law, d in con.get("data", {}).items():
            total = d.get("ЗапВсего") or 0
            zaps = d.get("Записи") or []
            summa = sum(_to_number(z.get("Цена")) or 0 for z in zaps)
            lines.append(f"   • {law}-ФЗ: {total} контрактов, сумма {_money(summa)}")
        lines.append("")
    elif con.get("status") == C.STATUS_EMPTY:
        lines.append("🏛️ Госзакупки: <i>контрактов не найдено</i>")
        lines.append("")
    elif con.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"🏛️ Госзакупки: <i>не проверено</i> ({_esc(con.get('reason'))})")
        lines.append("")

    fr = results.get("fedresurs", {})
    if fr.get("status") == C.STATUS_OK:
        zaps = fr["data"].get("Записи") or []
        opened = sum(1 for z in zaps if z.get("Тип") == "FinancialLeaseContract")
        closed = sum(1 for z in zaps if z.get("Тип") == "StopFinancialLeaseContract")
        lines.append("📑 <b>Лизинг / договоры с сохранением права собственности</b>")
        lines.append(f"   • Заключено договоров: {opened}")
        lines.append(f"   • Завершено договоров: {closed}")
        lines.append("")
    elif fr.get("status") == C.STATUS_EMPTY:
        lines.append("📑 Лизинг: <i>сообщений не найдено</i>")
        lines.append("")
    elif fr.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"📑 Лизинг: <i>не проверено</i> ({_esc(fr.get('reason'))})")
        lines.append("")

    bankr = results.get("bankruptcy", {})
    if bankr.get("status") == C.STATUS_OK:
        total = bankr["data"].get("ЗапВсего", 0)
        lines.append(f"🏦 Банкротство (ЕФРСБ): {total} записей")
        lines.append("")
    elif bankr.get("status") == C.STATUS_EMPTY:
        lines.append("🏦 Банкротство: <i>записей нет</i>")
        lines.append("")
    elif bankr.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"🏦 Банкротство: <i>не проверено</i> ({_esc(bankr.get('reason'))})")
        lines.append("")

    enf = results.get("enforcements", {})
    if enf.get("status") == C.STATUS_OK:
        zaps = enf["data"].get("Записи") or []
        total = sum(
            _to_number(
                z.get("ОстатокДолга")
                or z.get("СуммаДолга")
                or z.get("Сумма")
                or 0
            ) or 0
            for z in zaps
        )
        lines.append(f"⚖️ ФССП: {len(zaps)} производств, на {_money(total)}")
        lines.append("")
    elif enf.get("status") == C.STATUS_EMPTY:
        lines.append("⚖️ ФССП: <i>производств нет</i>")
        lines.append("")
    elif enf.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"⚖️ ФССП: <i>не проверено</i> ({_esc(enf.get('reason'))})")
        lines.append("")

    lc = results.get("legal_cases", {})
    if lc.get("status") == C.STATUS_OK:
        total = lc["data"].get("ЗапВсего", 0)
        claim = _money(lc["data"].get("ОбщСуммИск"))
        lines.append(f"📋 Арбитраж: {total} дел, сумма исков {claim}")
        lines.append("")
    elif lc.get("status") == C.STATUS_EMPTY:
        lines.append("📋 Арбитраж: <i>дел нет</i>")
        lines.append("")
    elif lc.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"📋 Арбитраж: <i>не проверено</i> ({_esc(lc.get('reason'))})")
        lines.append("")

    persons = results.get("persons", {})
    if persons.get("status") == C.STATUS_OK:
        lines.append("🔗 <b>Связанные компании</b>")
        for p in persons["data"]:
            pd = p.get("data", {})
            fio = pd.get("ФИО") or p.get("inn")

            orgs = []
            for key in ("Руковод", "Учред"):
                arr = pd.get(key) or []
                if isinstance(arr, list):
                    orgs.extend(arr)

            if not orgs:
                lines.append(f"   • {_esc(fio)}: связей не найдено")
                continue

            names = []
            seen = set()
            for o in orgs[:5]:
                nm = o.get("НаимСокр") or o.get("Наим") or o.get("ИНН")
                if nm and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
            lines.append(f"   • {_esc(fio)}: {_esc('; '.join(names))}")
        lines.append("")
    elif persons.get("status") == C.STATUS_EMPTY:
        lines.append("🔗 Связанные компании: <i>нет данных о персонах</i>")
        lines.append("")
    elif persons.get("status") == C.STATUS_UNCHECKED:
        lines.append(f"🔗 Связанные компании: <i>не проверено</i> ({_esc(persons.get('reason'))})")
        lines.append("")

    if verdict.get("deal_killers"):
        lines.append("🔴 <b>Стоп-сигналы:</b>")
        for k in verdict["deal_killers"]:
            lines.append(f"   • {_esc(k)}")
        lines.append("")
    if verdict.get("warnings"):
        lines.append("⚠️ <b>Предупреждения:</b>")
        for w in verdict["warnings"]:
            lines.append(f"   • {_esc(w)}")
        lines.append("")

    labels = {
        "company": "ЕГРЮЛ/ЕГРИП", "finances": "Финансы",
        "contracts": "Госзакупки", "fedresurs": "Федресурс (лизинг)",
        "bankruptcy": "Банкротство", "enforcements": "ФССП",
        "legal_cases": "Арбитраж", "persons": "Связи",
    }
    lines.append("✅ <b>Что проверено:</b>")
    for src in C.ALL_SOURCES:
        s = results.get(src, {})
        st = s.get("status", "?")
        lines.append(f"   {_status_mark(st)} {labels[src]}: {st}")

    unchecked = []
    for src in list(C.ALL_SOURCES) + ["persons"]:
        s = results.get(src, {})
        if s.get("status") == C.STATUS_UNCHECKED:
            unchecked.append(f"   ⚠️ {labels.get(src, src)}: {_esc(s.get('reason', ''))}")
    if unchecked:
        lines.append("")
        lines.append("🔍 <b>Что НЕ проверено:</b>")
        lines.extend(unchecked)

    lines.append("")
    lines.append("<i>Данные Checko API. Не является юридическим заключением.</i>")
    return "\n".join(lines)


@router.message()
async def handle_inn(message: types.Message):
    text = (message.text or "").strip()
    if not INN_RE.match(text):
        return
    await message.answer("⏳ Проверяю по 8 источникам…")
    try:
        results = await check_inn(text)
        verdict = compute_verdict(results)
        card = format_card(text, results, verdict)
        if len(card) > 4000:
            card = card[:3990] + "\n… (сокращено)"
        await message.answer(card, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка проверки: {_esc(str(e))}")
