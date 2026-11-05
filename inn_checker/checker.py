# -*- coding: utf-8 -*-
"""Загрузка источников Checko API и оркестратор проверки."""
import asyncio
import aiohttp
from . import config as C

HEADERS = {
    "User-Agent": C.USER_AGENT,
    "Accept": "application/json, text/plain, */*",
}


def _empty(reason):
    return {"status": C.STATUS_UNCHECKED, "reason": reason}


def _json_ok(ctype):
    return "application/json" in (ctype or "")


async def _get(session, path, params):
    """Базовый GET к Checko. Ключ всегда передаётся через params."""
    if not C.CHECKO_API_KEY:
        return _empty("нет CHECKO_API_KEY")
    url = f"{C.CHECKO_BASE}/{path}"
    full_params = {**(params or {}), "key": C.CHECKO_API_KEY.strip()}
    try:
        async with session.get(url, params=full_params, headers=HEADERS,
                               timeout=C.HTTP_TIMEOUT) as resp:
            if resp.status == 401:
                body = await resp.text()
                print(f"[Checko] 401 on {path}: {body[:300]}")
                return _empty("Checko: неверный ключ")
            if resp.status == 429:
                return _empty("Checko: превышен лимит")
            if resp.status != 200:
                body = await resp.text()
                print(f"[Checko] {resp.status} on {path}: {body[:300]}")
                return _empty(f"Checko HTTP {resp.status}")
            if not _json_ok(resp.headers.get("Content-Type")):
                return _empty("Checko: не JSON")
            j = await resp.json()
            if j.get("meta", {}).get("status") != "ok":
                return _empty(j.get("meta", {}).get("message", "ошибка Checko"))
            return {"status": C.STATUS_OK, "data": j.get("data", {})}
    except asyncio.TimeoutError:
        return _empty("Checko: таймаут")
    except Exception as e:
        return _empty(f"Checko: {type(e).__name__}: {e}")


# ── 1. ЕГРЮЛ / ЕГРИП ───────────────────────────────────────
async def fetch_company(session, inn):
    if len(inn) == 12:
        res = await _get(session, "entrepreneur", {"inn": inn})
        if res["status"] == C.STATUS_OK:
            return {"status": C.STATUS_OK, "kind": "ip", "data": res["data"]}
        return res
    res = await _get(session, "company", {"inn": inn})
    if res["status"] == C.STATUS_OK:
        return {"status": C.STATUS_OK, "kind": "ooo", "data": res["data"]}
    return res


# ── 2. Финансы ─────────────────────────────────────────────
async def fetch_finances(session, inn):
    return await _get(session, "finances", {"inn": inn})


# ── 3. Госзакупки (44 + 223) ───────────────────────────────
async def fetch_contracts(session, inn):
    results = {}
    for law in ("44", "223"):
        r = await _get(session, "contracts", {"inn": inn, "law": law})
        results[law] = r
    ok_laws = [r for r in results.values() if r["status"] == C.STATUS_OK]
    if not ok_laws:
        if all(r["status"] == C.STATUS_EMPTY for r in results.values()):
            return {"status": C.STATUS_EMPTY, "data": {}}
        reasons = [r.get("reason", "") for r in results.values()]
        return _empty("; ".join(filter(None, reasons)) or "Checko: контракты")
    merged = {}
    for law, r in results.items():
        if r["status"] == C.STATUS_OK:
            merged[law] = r["data"]
    return {"status": C.STATUS_OK, "data": merged}


# ── 4. Федресурс (с пагинацией) ────────────────────────────
async def fetch_fedresurs(session, inn):
    r1 = await _get(session, "fedresurs", {"inn": inn, "page": 1})
    if r1["status"] != C.STATUS_OK:
        return r1

    d1 = r1["data"]
    zaps = list(d1.get("Записи") or [])
    total_pages = min(int(d1.get("СтрВсего") or 1), C.MAX_FEDRESURS_PAGES)

    if total_pages > 1:
        tasks = [
            _get(session, "fedresurs", {"inn": inn, "page": p})
            for p in range(2, total_pages + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            if isinstance(r, dict) and r.get("status") == C.STATUS_OK:
                zaps.extend(r["data"].get("Записи") or [])

    return {
        "status": C.STATUS_OK,
        "data": {"Записи": zaps, "ЗапВсего": len(zaps)},
    }


# ── 5. ЕФРСБ (банкротство) ─────────────────────────────────
async def fetch_bankruptcy(session, inn):
    return await _get(session, "bankruptcy-messages", {"inn": inn})


# ── 6. ФССП ────────────────────────────────────────────────
async def fetch_enforcements(session, inn):
    return await _get(session, "enforcements", {"inn": inn})


# ── 7. Арбитраж ────────────────────────────────────────────
async def fetch_legal_cases(session, inn):
    return await _get(session, "legal-cases", {"inn": inn})


# ── 8. Связанные компании ──────────────────────────────────
async def fetch_person(session, person_inn):
    return await _get(session, "person", {"inn": person_inn})


async def collect_person_links(session, company_res):
    if company_res.get("status") != C.STATUS_OK:
        return _empty("нет данных company")

    d = company_res.get("data", {})
    person_inns = []

    ruk = d.get("Руковод")
    if isinstance(ruk, list) and ruk:
        first = ruk[0]
        if isinstance(first, dict) and first.get("ИНН"):
            person_inns.append(first["ИНН"])
    elif isinstance(ruk, dict) and ruk.get("ИНН"):
        person_inns.append(ruk["ИНН"])

    uchred = d.get("Учред") or {}
    if isinstance(uchred, dict):
        fl = uchred.get("ФЛ") or uchred.get("ФизЛица") or []
        for f in fl:
            if isinstance(f, dict) and f.get("ИНН"):
                person_inns.append(f["ИНН"])

    seen = []
    for x in person_inns:
        if x not in seen:
            seen.append(x)
    person_inns = seen[:C.MAX_PERSONS_FOR_LINKS]

    if not person_inns:
        return {"status": C.STATUS_EMPTY, "data": []}

    links = []
    for p_inn in person_inns:
        r = await fetch_person(session, p_inn)
        if r["status"] == C.STATUS_OK:
            links.append({"inn": p_inn, "data": r["data"]})

    if not links:
        return _empty("Checko: связи не получены")
    return {"status": C.STATUS_OK, "data": links}


# ── Оркестратор ────────────────────────────────────────────
async def check_inn(inn: str) -> dict:
    async with aiohttp.ClientSession() as session:
        (
            company,
            bankruptcy,
            enforcements,
            finances,
            contracts,
            fedresurs,
            legal_cases,
        ) = await asyncio.gather(
            fetch_company(session, inn),
            fetch_bankruptcy(session, inn),
            fetch_enforcements(session, inn),
            fetch_finances(session, inn),
            fetch_contracts(session, inn),
            fetch_fedresurs(session, inn),
            fetch_legal_cases(session, inn),
        )

        persons = await collect_person_links(session, company)

        return {
            "company": company,
            "bankruptcy": bankruptcy,
            "enforcements": enforcements,
            "finances": finances,
            "contracts": contracts,
            "fedresurs": fedresurs,
            "legal_cases": legal_cases,
            "persons": persons,
        }
