PROMPTS = {
    "tz": {
        "type": "tz",
        "title": "Technical specification (TZ)",
        "prompt": (
            "Ты — эксперт по извлечению данных из технической документации.\n"
            "Твоя задача — найти в документе ПЕРВУЮ ОСМЫСЛЕННУЮ МОДЕЛЬ ИЗДЕЛИЯ (строго по порядку появления в документе) и извлечь ВСЕ её характеристики без ограничений.\n"
            "Результат верни в виде JSON с полем products, которое содержит МАССИВ ИЗ ОДНОГО ОБЪЕКТА (только для первой найденной модели).\n\n"
            "ПРАВИЛА ПОИСКА МОДЕЛИ (строго по порядку, от начала документа):\n"
            "1. Просматривай документ последовательно, начиная с первого символа. Первое же вхождение, которое можно идентифицировать как изделие с моделью, считается целевым.\n"
            "2. Ищи паттерны: общее название изделия + следом или рядом код модели (например, \"Гидрант пожарный ГП-500\", \"Насос КМ 100-80-160\", \"Вентилятор ВР-80\"). Код модели обычно содержит буквы, цифры, дефисы.\n"
            "3. Если код модели явно указан (например, \"ГП-500\"), то:\n"
            "   - product_name = общее название (\"Гидрант пожарный\")\n"
            "   - product_model = код модели (\"ГП-500\")\n"
            "4. Если кода модели нет, но есть уникальное наименование (например, \"Клапан предохранительный\"), то product_name = это наименование, product_model = null.\n"
            "5. Если в документе нет ни одного изделия — верни {\"products\": [{\"product_name\": null, \"product_model\": null, \"characteristics\": []}]}.\n"
            "   НЕ ВЫДУМЫВАЙ МОДЕЛЬ, НЕ БЕРИ ИЗ ДРУГИХ ЧАСТЕЙ ДОКУМЕНТА.\n\n"
            "ИЗВЛЕЧЕНИЕ ХАРАКТЕРИСТИК:\n"
            "• Бери ВСЕ характеристики, относящиеся ТОЛЬКО к НАЙДЕННОЙ МОДЕЛИ. Игнорируй другие модели, общие спецификации, примечания.\n"
            "• Характеристика = пара «название → значение». Примеры: «Материал: сталь», «Условное давление: 10 кгс/см», «Высота: 500 мм».\n"
            "• Извлекай КАЖДУЮ явную характеристику этой модели. НЕ ОГРАНИЧИВАЙ по количеству.\n"
            "• НЕ создавай характеристики из служебных фраз («См. рис. 1»), если нет конкретного значения.\n"
            "• НЕ дублируй одинаковые name. Если одинаковое название встречается дважды — возьми первое или с большей confidence.\n\n"
            "ФОРМАТ ВЫВОДА (JSON):\n"
            "{\n"
            "  \"products\": [\n"
            "    {\n"
            "      \"product_name\": string | null,\n"
            "      \"product_model\": string | null,\n"
            "      \"characteristics\": [\n"
            "        {\n"
            "          \"name\": string,\n"
            "          \"value\": string | null,\n"
            "          \"references\": [\n"
            "            {\n"
            "              \"quote_text\": string | null,\n"
            "              \"anchor_text\": string | null,\n"
            "              \"page\": integer | null,\n"
            "              \"locator_strategy\": \"text\" | \"table\" | \"figure\" | null,\n"
            "              \"confidence\": number (0..1) | null,\n"
            "              \"bbox\": { ... } | null\n"
            "            }\n"
            "          ]\n"
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "ТРЕБОВАНИЯ К REFERENCES:\n"
            "• Всегда массив объектов (НЕ строки!).\n"
            "• quote_text — дословная цитата. Если таблица — строка таблицы или ячейка.\n"
            "• Если точная цитата невозможна → quote_text = null, confidence < 0.5.\n"
            "• confidence: 1.0 = идеально, 0.9–0.99 = прямая цитата, 0.7–0.89 = явно указано, 0.5–0.69 = косвенно, <0.5 = неуверенно.\n\n"
            "ЧЕГО НЕЛЬЗЯ (брак):\n"
            "❌ Не выдумывай модели и характеристики.\n"
            "❌ Не объединяй характеристики из разных моделей.\n"
            "❌ Не возвращай пустой массив characteristics, если модель найдена (хотя бы одна характеристика должна быть).\n"
            "❌ Не используй строки в references — только объекты.\n"
            "❌ Не добавляй лишних ключей.\n"
            "❌ Не пропускай характеристики из-за количества.\n"
            "❌ НЕ ПРИНИМАЙ ОБЩЕЕ НАЗВАНИЕ БЕЗ КОДА ЗА МОДЕЛЬ. Обязательно ищи буквенно-цифровой код модели.\n\n"
            "ПРИМЕР (few-shot):\n"
            "Документ (таблица):\n"
            "| № | Наименование | Технические характеристики |\n"
            "| 1 | Гидрант пожарный ГП-500 | Материал: сталь, Высота: 500 мм |\n"
            "| 2 | Гидрант пожарный ГП-750 | Материал: сталь, Высота: 750 мм |\n"
            "Вывод:\n"
            "{\n"
            "  \"products\": [\n"
            "    {\n"
            "      \"product_name\": \"Гидрант пожарный\",\n"
            "      \"product_model\": \"ГП-500\",\n"
            "      \"characteristics\": [\n"
            "        {\"name\": \"Материал\", \"value\": \"сталь\", \"references\": [{\"quote_text\": \"Материал: сталь\", \"anchor_text\": \"Технические характеристики\", \"page\": null, \"locator_strategy\": \"table\", \"confidence\": 1.0, \"bbox\": null}]},\n"
            "        {\"name\": \"Высота\", \"value\": \"500 мм\", \"references\": [{\"quote_text\": \"Высота: 500 мм\", \"anchor_text\": \"Технические характеристики\", \"page\": null, \"locator_strategy\": \"table\", \"confidence\": 1.0, \"bbox\": null}]}\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Теперь извлеки данные из предоставленного документа. Верни ТОЛЬКО JSON, без пояснений."
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
                            "product_name": {"type": ["string", "null"]},
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
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "quote_text": {"type": ["string", "null"]},
                                                    "anchor_text": {"type": ["string", "null"]},
                                                    "locator_text": {"type": ["string", "null"]},
                                                    "page": {"type": ["integer", "string", "null"]},
                                                    "locator_strategy": {"type": ["string", "null"]},
                                                    "confidence": {"type": ["number", "null"]},
                                                    "bbox": {
                                                        "type": ["object", "null"],
                                                        "properties": {
                                                            "x": {"type": ["number", "null"]},
                                                            "y": {"type": ["number", "null"]},
                                                            "width": {"type": ["number", "null"]},
                                                            "height": {"type": ["number", "null"]},
                                                            "x0": {"type": ["number", "null"]},
                                                            "y0": {"type": ["number", "null"]},
                                                            "x1": {"type": ["number", "null"]},
                                                            "y1": {"type": ["number", "null"]},
                                                            "left": {"type": ["number", "null"]},
                                                            "top": {"type": ["number", "null"]},
                                                            "right": {"type": ["number", "null"]},
                                                            "bottom": {"type": ["number", "null"]}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
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
            "name — человекочитаемое название характеристики на русском. "
            "Для references по возможности возвращайте структурированные объекты с "
            "полями quote_text, anchor_text, page, locator_strategy, confidence и bbox. "
            "quote_text должен быть дословной цитатой из документа, без пересказа и нормализации. "
            "Если характеристика находится в таблице, quote_text должен содержать строку таблицы или "
            "ячейку с реальным значением. anchor_text должен содержать ближайший заголовок, подпись "
            "или контекстный фрагмент. Если точная структура невозможна, допускается строковая цитата."
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
                                            "items": {
                                                "anyOf": [
                                                    {"type": "string"},
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "quote_text": {"type": ["string", "null"]},
                                                            "anchor_text": {"type": ["string", "null"]},
                                                            "locator_text": {"type": ["string", "null"]},
                                                            "page": {"type": ["integer", "string", "null"]},
                                                            "locator_strategy": {"type": ["string", "null"]},
                                                            "confidence": {"type": ["number", "null"]},
                                                            "bbox": {
                                                                "type": ["object", "null"],
                                                                "properties": {
                                                                    "x": {"type": ["number", "null"]},
                                                                    "y": {"type": ["number", "null"]},
                                                                    "width": {"type": ["number", "null"]},
                                                                    "height": {"type": ["number", "null"]},
                                                                    "x0": {"type": ["number", "null"]},
                                                                    "y0": {"type": ["number", "null"]},
                                                                    "x1": {"type": ["number", "null"]},
                                                                    "y1": {"type": ["number", "null"]},
                                                                    "left": {"type": ["number", "null"]},
                                                                    "top": {"type": ["number", "null"]},
                                                                    "right": {"type": ["number", "null"]},
                                                                    "bottom": {"type": ["number", "null"]}
                                                                }
                                                            }
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
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
                            "is_match"
                        ],
                        "properties": {
                            "characteristic": {"type": "string"},
                            "tz_value": {"type": ["string", "null"]},
                            "passport_value": {"type": ["string", "null"]},
                            "tz_quote": {"type": ["string", "null"]},
                            "passport_quote": {"type": ["string", "null"]},
                            "is_match": {"type": "boolean"},
                            "note": {"type": ["string", "null"]}
                        }
                    }
                }
            }
        }
    }
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
