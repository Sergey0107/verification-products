"""Выбор целевого изделия паспорта, когда документ описывает несколько.

Паспорт нередко приходит каталогом на 2+ изделия (например КМХ (В 6,45) 50-50
и КМХ (В 3,00) 12,5-50 в одном PDF), а ТЗ заказывает одно конкретное. Если имя
из ТЗ не сопоставляется ни с одним изделием паспорта, автоматика раньше молча
брала «самое наполненное» — фактически первое попавшееся, и в сравнение уходили
характеристики чужого изделия (инцидент 2026-08-13, анализ aca90496).

Здесь — только определение ситуации «выбор неоднозначен». Само сопоставление
кодов моделей повторяет _models_match из domain-analyze/compare_service.py:
сервисы разные, общего пакета нет, поэтому логика продублирована намеренно —
она должна отвечать на вопрос «совпали ли модели» одинаково по обе стороны,
иначе гейт спросит пользователя там, где сравнение справилось бы само.
"""

import re
from typing import Any


def _normalize_model(value: Any) -> str:
    """Нижний регистр без пробелов и разделителей: ГП-1500 / ГП 1500 → 'гп1500'."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s\-_.]+", "", value.strip().lower().replace("ё", "е"))


def _model_size_cores(value: Any) -> set[str]:
    """Числовое ядро типоразмера — самая стабильная часть кода между
    документами: 'КС 50-110/4' → {'50-110/4', '50-110'}."""
    if not isinstance(value, str):
        return set()
    norm = (
        value.lower()
        .replace("ё", "е")
        .replace("–", "-")
        .replace("—", "-")
        .replace("х", "x")
    )
    cores: set[str] = set()
    for match in re.findall(r"\d+(?:[-/x]\d+)+", norm):
        cores.add(match)
        base = match.split("/", 1)[0]
        if "-" in base:
            cores.add(base)
    return cores


def models_match(tz_model: Any, passport_model: Any) -> bool:
    """Модели совпадают, если нормализованные строки равны/вложены либо есть
    общее числовое ядро типоразмера."""
    norm_tz = _normalize_model(tz_model)
    norm_pp = _normalize_model(passport_model)
    if norm_tz and norm_pp and (
        norm_tz == norm_pp or norm_tz in norm_pp or norm_pp in norm_tz
    ):
        return True
    return bool(_model_size_cores(tz_model) & _model_size_cores(passport_model))


def _products_of(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    products = result.get("products") if isinstance(result, dict) else None
    return [p for p in products if isinstance(p, dict)] if isinstance(products, list) else []


def _product_label(product: dict) -> str | None:
    for key in ("product_name", "product_model"):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _count_filled(product: dict) -> int:
    characteristics = product.get("characteristics")
    if not isinstance(characteristics, list):
        return 0
    return sum(1 for c in characteristics if isinstance(c, dict) and c.get("value"))


# Минимум характеристик, ниже которого «изделие» считается мусорной меткой, а
# не реальной моделью. Настоящее изделие паспорта описано десятками строк.
_MIN_CHARACTERISTICS = 3


def _looks_like_product(label: str, filled: int) -> bool:
    """Отсеивает мусор, попавший в variant вместо названия модели.

    На реальных паспортах в variant изредка утекают коды исполнения и
    маркировки — например '0ExiaIICT4GaX' (класс взрывозащиты) оказывался
    третьим "изделием" рядом с двумя настоящими насосами. Показывать такое
    пользователю нельзя. Признак настоящей модели тот же, что использует
    промпт structuring: числовое обозначение типоразмера ('50-50', '6,45')
    плюс осмысленный объём характеристик."""
    if filled < _MIN_CHARACTERISTICS:
        return False
    return bool(re.search(r"\d+[.,\-/x]\d+", label.lower().replace("х", "x")))


def passport_product_options(passport_payload: Any) -> list[dict]:
    """Изделия паспорта в виде, пригодном для показа пользователю."""
    options: list[dict] = []
    for product in _products_of(passport_payload):
        label = _product_label(product)
        if not label:
            continue
        filled = _count_filled(product)
        if not _looks_like_product(label, filled):
            continue
        options.append({"name": label, "characteristics_count": filled})
    return options


def resolve_target_product(
    tz_payload: Any,
    passport_payload: Any,
    user_choice: str | None,
) -> tuple[str | None, list[dict]]:
    """Определяет, нужен ли выбор изделия пользователем.

    Возвращает (product_model, options_requiring_choice):

    * (значение, []) — выбор не нужен: пользователь уже выбрал, изделие в
      паспорте одно, либо имя из ТЗ уверенно совпало ровно с одним изделием.
      Значение уходит в Analysis.product_model и дальше в сравнение;
      None здесь означает «сравнение разберётся само» (единственное изделие).
    * (None, [варианты]) — выбор неоднозначен, нужно спросить пользователя.

    Спрашиваем только при реальной неоднозначности: если ТЗ прямо называет
    изделие, которое есть в паспорте, дёргать пользователя незачем.
    """
    options = passport_product_options(passport_payload)
    if user_choice:
        return user_choice, []
    if len(options) <= 1:
        return None, []

    tz_products = _products_of(tz_payload)
    tz_labels = [label for label in (_product_label(p) for p in tz_products) if label]

    matched = [
        option
        for option in options
        if any(models_match(tz_label, option["name"]) for tz_label in tz_labels)
    ]
    if len(matched) == 1:
        return matched[0]["name"], []

    return None, options
