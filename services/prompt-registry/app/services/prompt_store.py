PROMPTS = {
    "tz": {
        "type": "tz",
        "title": "Technical specification (TZ)",
        "prompt": (
            "You are an expert in technical documentation. Extract structured technical "
            "characteristics from the provided document. Return ONLY valid JSON that "
            "matches the given JSON Schema. If a field is not present, use null. "
            "If multiple values are present, use an array. Do not add extra keys. "
            "IMPORTANT: every characteristic MUST include its name. For every field "
            "that represents a characteristic, return an object with: "
            "{name, value, references}. The name must be the human-readable title "
            "of the characteristic (e.g., 'Flow rate', 'Head', 'Power', 'Material')."
        ),
        "schema": {
            "type": "object",
            "required": ["product", "technical", "source_pages"],
            "properties": {
                "product": {
                    "type": "object",
                    "required": ["name", "model"],
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "model": {"type": ["string", "null"]},
                        "manufacturer": {"type": ["string", "null"]},
                        "purpose": {"type": ["string", "null"]},
                    },
                },
                "technical": {
                    "type": "object",
                    "properties": {
                        "performance": {
                            "type": "object",
                            "properties": {
                                "flow_rate": {"type": ["string", "null"]},
                                "head": {"type": ["string", "null"]},
                                "power": {"type": ["string", "null"]},
                                "efficiency": {"type": ["string", "null"]},
                                "speed_rpm": {"type": ["string", "null"]},
                            },
                        },
                        "dimensions": {
                            "type": "object",
                            "properties": {
                                "length": {"type": ["string", "null"]},
                                "width": {"type": ["string", "null"]},
                                "height": {"type": ["string", "null"]},
                                "weight": {"type": ["string", "null"]},
                            },
                        },
                        "materials": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                        "temperature_range": {"type": ["string", "null"]},
                        "pressure": {"type": ["string", "null"]},
                        "voltage": {"type": ["string", "null"]},
                        "ingress_protection": {"type": ["string", "null"]},
                        "standards": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                        "operating_conditions": {"type": ["string", "null"]},
                    },
                },
                "source_pages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "pages"],
                        "properties": {
                            "field": {"type": "string"},
                            "pages": {"type": "array", "items": {"type": "integer"}},
                        },
                    },
                },
                "notes": {"type": ["string", "null"]},
            },
        },
    },
    "passport": {
        "type": "passport",
        "title": "Product passport",
        "prompt": (
            "You are an expert in product passports. Extract structured data from the "
            "document. Return ONLY valid JSON that matches the given JSON Schema. "
            "If a field is not present, use null. If multiple values are present, use "
            "an array. Do not add extra keys. "
            "IMPORTANT: every characteristic MUST include its name. For every field "
            "that represents a characteristic, return an object with: "
            "{name, value, references}. The name must be the human-readable title "
            "of the characteristic."
        ),
        "schema": {
            "type": "object",
            "required": ["product", "identification", "technical", "source_pages"],
            "properties": {
                "product": {
                    "type": "object",
                    "required": ["name", "model"],
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "model": {"type": ["string", "null"]},
                        "manufacturer": {"type": ["string", "null"]},
                        "serial_number": {"type": ["string", "null"]},
                        "production_date": {"type": ["string", "null"]},
                    },
                },
                "identification": {
                    "type": "object",
                    "properties": {
                        "document_number": {"type": ["string", "null"]},
                        "document_date": {"type": ["string", "null"]},
                        "certificate_numbers": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                    },
                },
                "technical": {
                    "type": "object",
                    "properties": {
                        "performance": {
                            "type": "object",
                            "properties": {
                                "flow_rate": {"type": ["string", "null"]},
                                "head": {"type": ["string", "null"]},
                                "power": {"type": ["string", "null"]},
                                "efficiency": {"type": ["string", "null"]},
                                "speed_rpm": {"type": ["string", "null"]},
                            },
                        },
                        "dimensions": {
                            "type": "object",
                            "properties": {
                                "length": {"type": ["string", "null"]},
                                "width": {"type": ["string", "null"]},
                                "height": {"type": ["string", "null"]},
                                "weight": {"type": ["string", "null"]},
                            },
                        },
                        "materials": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                        "temperature_range": {"type": ["string", "null"]},
                        "pressure": {"type": ["string", "null"]},
                        "voltage": {"type": ["string", "null"]},
                        "ingress_protection": {"type": ["string", "null"]},
                        "standards": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ]
                        },
                        "completeness": {"type": ["string", "null"]},
                        "warranty": {"type": ["string", "null"]},
                        "storage_conditions": {"type": ["string", "null"]},
                    },
                },
                "source_pages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "pages"],
                        "properties": {
                            "field": {"type": "string"},
                            "pages": {"type": "array", "items": {"type": "integer"}},
                        },
                    },
                },
                "notes": {"type": ["string", "null"]},
            },
        },
    },
    "comparison": {
        "type": "comparison",
        "title": "Compare TZ vs Passport",
        "prompt": (
            "You are a technical expert. Compare the technical characteristics in the "
            "TZ JSON with the Passport JSON. Use a flexible, human-like comparison: "
            "allow minor wording differences, unit variations, rounding, and synonyms. "
            "Decide if the passport matches the TZ. Return ONLY valid JSON matching the "
            "schema. Do not wrap the JSON in markdown or code fences. If a field cannot "
            "be compared, mark it as 'unknown'."
        ),
        "schema": {
            "type": "object",
            "required": ["match", "confidence", "summary", "mismatches"],
            "properties": {
                "match": {"type": "boolean"},
                "confidence": {"type": "number"},
                "summary": {"type": "string"},
                "mismatches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "tz_value", "passport_value", "severity"],
                        "properties": {
                            "field": {"type": "string"},
                            "tz_value": {"type": "string"},
                            "passport_value": {"type": "string"},
                            "severity": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                },
                "unknowns": {
                    "type": "array",
                    "items": {"type": "string"},
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
