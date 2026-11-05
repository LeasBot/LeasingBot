# -*- coding: utf-8 -*-
"""Правила и настройки — в одном месте."""
import os

# ── Три состояния источника ─────────────────────────────────
STATUS_OK = "ok"
STATUS_EMPTY = "пусто"
STATUS_UNCHECKED = "не проверено"

# ── Checko API ──────────────────────────────────────────────
# Ключ берём из переменной окружения (задаётся на Render в разделе Environment)
CHECKO_API_KEY = os.environ.get("CHECKO_API_KEY", "")
CHECKO_BASE = "https://api.checko.ru/v2"
HTTP_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── Максимум персон для графа связей (экономия лимита) ──────
MAX_PERSONS_FOR_LINKS = 2

# ── Максимум страниц Федресурса для запроса ─────────────────
MAX_FEDRESURS_PAGES = 15

# ── Стоп-сигналы (deal-killers) ─────────────────────────────
LIQUIDATED_STATUSES = ["ликвидирована", "ликвидация", "прекращен", "прекращено"]
BANKRUPTCY_PROCEDURE_KEYWORDS = [
    "введена процедура", "признан банкротом", "конкурсное производство",
    "наблюдение", "внешнее управление",
]
ENFORCEMENT_DEAL_KILLER_RUB = 10_000_000

# ── Финансовые пороги ───────────────────────────────────────
THRESHOLDS = {
    "current_liquidity_min": 1.0,
    "autonomy_min": 0.1,
    "revenue_drop_pct": 50,
}

# ── Порог «не проверено» для выдачи null ────────────────────
MAX_UNCHECKED_RATIO = 0.5

# ── Вердикты ────────────────────────────────────────────────
VERDICT = {
    "red": "🔴 ВЫСОКИЙ РИСК",
    "yellow": "🟡 СРЕДНИЙ РИСК",
    "green": "🟢 НИЗКИЙ РИСК",
    "null": "⚪ ПРОВЕРКА НЕ СОСТОЯЛАСЬ",
}

# ── Все источники (для подсчёта полноты) ────────────────────
ALL_SOURCES = [
    "company", "finances", "contracts", "fedresurs",
    "bankruptcy", "enforcements", "legal_cases",
]
STOP_SOURCES = ["company", "bankruptcy", "enforcements"]
