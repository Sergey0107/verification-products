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
            "?? ? ??????????? ???????. ???????? ?????????????? ?? JSON ?? ? JSON ????????. "
            "????????? ?????? ???? ??????: ?????????? ???????? ????????????, ??????, ?????????? ? ????????. "
            "?????? ?? ??????????? ? ?????? ?? ?????? ??????. ??????? ?????? ???????? JSON ?? ?????, ??? markdown/?????. "
            "???? ???? ?? ???? ?????????????? ?? ????????? ? match=false. ????????? ?? ??????? ?????.\n\n"
            "????: ?????? comparison_items. ?????? ??????? ???????? product_name, characteristic, tz_value, passport_value, tz_references, passport_references. "
            "???????????: ??????? comparisons ????? ??? ?? ????? ? ? ??? ?? ???????, ??? comparison_items. "
            "??????? ?????????????? ?????? ??????????.\n\n"
            "??? ??????? ????????: "
            "1) characteristic: "<product_name> ? <characteristic>". "
            "2) tz_value ? passport_value ?????? ?? ?????, ?? ??????? ????? ? ???????. "
            "3) tz_quote ? passport_quote ? ???????? ?????? ?? ??????????; ???? ?????? ?????? ???, ??????????? ??????? ?????????????? ? ??????? ??? ? note. "
            "4) is_match=false, ???? ???????? ???????????, ????????????, ??? ???? ?? ???????? ??????????? (null)."
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
