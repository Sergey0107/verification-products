PROMPTS = {
    "tz": {
        "type": "tz",
        "title": "Technical specification (TZ)",
        "prompt": (
            "Вы — эксперт по технической документации. Извлеките структурированные "
            "технические характеристики из документа. Верните ТОЛЬКО валидный JSON, "
            "строго соответствующий схеме. Не добавляйте лишних ключей и ничего не "
            "выдумывайте. Извлекайте ВСЕ изделия и ВСЕ характеристики, которые есть "
            "в документе. Результаты должны быть на русском языке.\n\n"
            "ВАЖНО: каждая характеристика ДОЛЖНА иметь название. Для каждой "
            "характеристики возвращайте объект: {name, value, references}, где "
            "name — человекочитаемое название характеристики на русском "
            "(например: \"Расход\", \"Напор\", \"Мощность\", \"Материал\")."
        ),
        "schema": {
            "type": "object",
            "required": ["products"],
            "properties": {
                "products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["product_name", "characteristics"],
                        "properties": {
                            "product_name": {"type": "string"},
                            "product_model": {"type": ["string", "null"]},
                            "characteristics": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["name", "value", "references"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "value": {"type": ["string", "null"]},
                                        "references": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "passport": {
        "type": "passport",
        "title": "Product passport",
        "prompt": (
            "Вы — эксперт по паспортам изделий. Извлеките структурированные данные "
            "из документа. Верните ТОЛЬКО валидный JSON, строго соответствующий "
            "схеме. Не добавляйте лишних ключей и ничего не выдумывайте. "
            "Извлекайте ВСЕ изделия и ВСЕ характеристики, которые есть в документе. "
            "Результаты должны быть на русском языке.\n\n"
            "ВАЖНО: каждая характеристика ДОЛЖНА иметь название. Для каждой "
            "характеристики возвращайте объект: {name, value, references}, где "
            "name — человекочитаемое название характеристики на русском."
        ),
        "schema": {
            "type": "object",
            "required": ["products"],
            "properties": {
                "products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["product_name", "characteristics"],
                        "properties": {
                            "product_name": {"type": "string"},
                            "product_model": {"type": ["string", "null"]},
                            "characteristics": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["name", "value", "references"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "value": {"type": ["string", "null"]},
                                        "references": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "comparison": {
        "type": "comparison",
        "title": "Compare TZ vs Passport",
        "prompt": (
            "Вы — технический эксперт. Сравните характеристики из JSON ТЗ и JSON паспорта. "
            "Сравнение должно быть гибким: допускайте различия формулировок, единиц, "
            "округления и синонимы. НИЧЕГО не выдумывайте — только на основе данных. "
            "Верните ТОЛЬКО валидный JSON по схеме, без markdown/код‑фенсов. "
            "Если хотя бы одна характеристика не совпадает — match=false. "
            "Результат на русском языке.\n\n"
            "Для каждой сравниваемой характеристики верните: название, значение из паспорта, "
            "значение из ТЗ, цитаты из документов (две строки: из ТЗ и из паспорта)."
        ),
        "schema": {
            "type": "object",
            "required": ["match", "summary", "comparisons"],
            "properties": {
                "match": {"type": "boolean"},
                "summary": {"type": "string"},
                "comparisons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "characteristic",
                            "tz_value",
                            "passport_value",
                            "tz_quote",
                            "passport_quote",
                            "is_match",
                        ],
                        "properties": {
                            "characteristic": {"type": "string"},
                            "tz_value": {"type": ["string", "null"]},
                            "passport_value": {"type": ["string", "null"]},
                            "tz_quote": {"type": ["string", "null"]},
                            "passport_quote": {"type": ["string", "null"]},
                            "is_match": {"type": "boolean"},
                            "note": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
}


def list_prompt_summaries() -> list[dict]:
    return [
        {"type": value["type"], "title": value["title"]}
        for value in PROMPTS.values()
    ]


def resolve_prompt(file_type: str) -> dict:
    key = (file_type or "").strip().lower()
    if key not in PROMPTS:
        raise KeyError(key)
    return PROMPTS[key]
