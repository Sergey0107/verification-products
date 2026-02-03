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
            "Ты — аналитик технической документации. Сравни техническое задание (ТЗ) и паспорт изделия. "
            "Представь результат строго в формате JSON без использования markdown или форматирования. "
            "Сравнивай следующие параметры: наименование продукции, характеристики, значения и ссылки на источники. "
            "Выполняй сравнение по КАЖДОЙ характеристике. "
            "Если данные отсутствуют или их невозможно сопоставить — укажи match=false. Не добавляй лишнего текста.\n\n"

            "Формат результата: массив comparison_items. Каждый элемент должен содержать поля: "
            "product_name, characteristic, tz_value, passport_value, tz_references, passport_references. "
            "Дополнительно допускается массив comparisons, который может содержать несколько comparison_items. "
            "Структура должна быть строго валидным JSON.\n\n"

            "Правила формирования:\n"
            "1) characteristic должен иметь формат: \"<product_name> - <characteristic>\".\n"
            "2) tz_value и passport_value заполняй только при наличии данных, иначе указывай null.\n"
            "3) tz_references и passport_references должны содержать точные цитаты из документов. "
            "Если данные отсутствуют — добавь пояснение в поле note.\n"
            "4) Устанавливай is_match=false, если значения не совпадают, отсутствуют "
            "или невозможно определить соответствие.\n"
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
