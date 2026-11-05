# -*- coding: utf-8 -*-
"""Скоринг и вердикт — только правила, без моделей."""
from datetime import date
from . import config as C


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(" ", "").replace(",", "").strip()
        if cleaned in ("", "-"):
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _latest_year(data):
    if not isinstance(data, dict):
        return None, {}
    years = sorted([k for k in data if str(k).isdigit()], reverse=True)
    if not years:
        return None, {}
    return int(years[0]), data[years[0]]


def _status_text(raw):
    if isinstance(raw, dict):
        return str(raw.get("Наим", "")).lower()
    return str(raw or "").lower()


def compute_verdict(results: dict) -> dict:
    deal_killers = []
    warnings = []

    comp = results.get("company", {})
    if comp.get("status") == C.STATUS_OK:
        d = comp["data"]
        status = _status_text(d.get("Статус"))
        if any(k in status for k in C.LIQUIDATED_STATUSES):
            deal_killers.append(f"статус: {status}")
        if d.get("Санкции"):
            deal_killers.append("санкции (РФМ/OFAC/EU)")
        if d.get("СанкцУчр"):
            deal_killers.append("санкции у учредителей")
        if d.get("ДисквЛица"):
            deal_killers.append("дисквалификация директора")
        if d.get("НедобПост"):
            deal_killers.append("РНП: недобросовестный поставщик")

    bankr = results.get("bankruptcy", {})
    if bankr.get("status") == C.STATUS_OK:
        zaps = bankr["data"].get("Записи") or []
        for z in zaps:
            tip = str(z.get("ТипНаим", "")).lower()
            if any(k in tip for k in C.BANKRUPTCY_PROCEDURE_KEYWORDS):
                deal_killers.append(f"банкротство: {z.get('ТипНаим')}")
                break

    enf = results.get("enforcements", {})
    if enf.get("status") == C.STATUS_OK:
        total = 0.0
        for z in (enf["data"].get("Записи") or []):
            total += _to_number(z.get("СуммаДолга") or z.get("Сумма") or 0) or 0
        if total > C.ENFORCEMENT_DEAL_KILLER_RUB:
            deal_killers.append(f"ФССП: {total:,.0f} ₽".replace(",", " "))

    fin = results.get("finances", {})
    if fin.get("status") == C.STATUS_OK:
        data = fin["data"]
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        year, d = _latest_year(data)
        if d:
            revenue = _to_number(d.get("revenue") or d.get("2110"))
            profit = _to_number(d.get("net_profit") or d.get("2400"))
            equity = _to_number(d.get("equity") or d.get("1300"))
            assets = _to_number(d.get("assets") or d.get("1600"))
            short_liab = _to_number(d.get("liabilities_short") or d.get("1500"))

            if profit is not None and profit < 0:
                warnings.append(f"убыток за {year}")
            if equity is not None and equity < 0:
                warnings.append("отрицательные чистые активы")
            if assets and short_liab and short_liab > 0:
                liq = assets / short_liab
                if liq < C.THRESHOLDS["current_liquidity_min"]:
                    warnings.append(f"низкая ликвидность ({liq:.2f})")
            if equity is not None and assets and assets > 0:
                aut = equity / assets
                if aut < C.THRESHOLDS["autonomy_min"]:
                    warnings.append(f"низкая автономия ({aut:.2f})")

    lc = results.get("legal_cases", {})
    if lc.get("status") == C.STATUS_OK:
        total_claim = _to_number(lc["data"].get("ОбщСуммИск"))
        if total_claim and total_claim > 1_000_000:
            warnings.append(f"арбитраж: иски на {total_claim:,.0f} ₽".replace(",", " "))

    if comp.get("status") == C.STATUS_OK:
        d = comp["data"]
        nal = d.get("Налоги") or {}
        debt = _to_number(nal.get("СумНедоим"))
        if debt and debt > 0:
            warnings.append(f"налоговая недоимка {debt:,.0f} ₽".replace(",", " "))
        if d.get("МассРуковод"):
            warnings.append("массовый руководитель")
        if d.get("МассУчред"):
            warnings.append("массовый учредитель")

    checked = sum(
        1 for s in C.ALL_SOURCES
        if results.get(s, {}).get("status") in (C.STATUS_OK, C.STATUS_EMPTY)
    )
    unchecked = len(C.ALL_SOURCES) - checked
    unchecked_ratio = unchecked / len(C.ALL_SOURCES) if C.ALL_SOURCES else 1

    stop_unchecked = sum(
        1 for s in C.STOP_SOURCES
        if results.get(s, {}).get("status") == C.STATUS_UNCHECKED
    )
    stop_ratio = stop_unchecked / len(C.STOP_SOURCES) if C.STOP_SOURCES else 1

    if deal_killers:
        level = "red"
    elif warnings:
        level = "yellow"
    else:
        level = "green"

    if level == "green" and stop_ratio > C.MAX_UNCHECKED_RATIO:
        level = "null"
    if checked == 0:
        level = "null"

    return {
        "level": level,
        "deal_killers": deal_killers,
        "warnings": warnings,
        "checked_count": checked,
        "unchecked_ratio": unchecked_ratio,
    }


def business_age(reg_date_str):
    if not reg_date_str:
        return None
    try:
        y, m, d = map(int, str(reg_date_str)[:10].split("-"))
        reg = date(y, m, d)
        days = (date.today() - reg).days
        years = days // 365
        months = (days % 365) // 30
        return f"{years} г. {months} мес."
    except Exception:
        return None
