package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Set;

/** Bounded shared JSON Schema validator; unknown constraints fail closed. */
public final class SchemaContract {
    private SchemaContract() { }
    private static final Set<String> VOCABULARY = Set.of("$ref", "title", "description", "default", "type",
        "properties", "required", "additionalProperties", "items", "anyOf", "const", "enum",
        "minimum", "maximum", "minLength", "maxLength", "maxItems");

    public static boolean matches(JsonNode schema, JsonNode value, JsonNode definitions) {
        if (schema == null || !schema.isObject() || value == null) return false;
        var names = schema.fieldNames();
        while (names.hasNext()) if (!VOCABULARY.contains(names.next())) return false;
        if (schema.has("$ref")) {
            String ref = schema.get("$ref").asText();
            return matches(definitions.get(ref.substring(ref.lastIndexOf('/') + 1)), value, definitions);
        }
        if (schema.has("anyOf")) {
            boolean found = false;
            for (JsonNode choice : schema.get("anyOf")) if (matches(choice, value, definitions)) found = true;
            if (!found) return false;
        }
        if (schema.has("const")) {
            JsonNode expected = schema.get("const");
            // JSON numbers compare by value: 200 and 200.0 are the same code.
            boolean equal = expected.isNumber() && value.isNumber()
                ? Double.isFinite(value.asDouble()) && expected.decimalValue().compareTo(value.decimalValue()) == 0
                : expected.equals(value);
            if (!equal) return false;
        }
        if (schema.has("enum")) {
            boolean found = false;
            for (JsonNode choice : schema.get("enum")) if (choice.equals(value)) found = true;
            if (!found) return false;
        }
        if (schema.has("type") && !switch (schema.get("type").asText()) {
            case "object" -> value.isObject(); case "array" -> value.isArray();
            case "string" -> value.isTextual(); case "boolean" -> value.isBoolean();
            case "number" -> value.isNumber() && Double.isFinite(value.asDouble());
            case "integer" -> value.isNumber() && Double.isFinite(value.asDouble()) && value.decimalValue().stripTrailingZeros().scale() <= 0;
            case "null" -> value.isNull(); default -> false;
        }) return false;
        if (value.isNumber()) {
            if (schema.has("minimum") && value.decimalValue().compareTo(schema.get("minimum").decimalValue()) < 0) return false;
            if (schema.has("maximum") && value.decimalValue().compareTo(schema.get("maximum").decimalValue()) > 0) return false;
        }
        if (value.isTextual()) {
            int length = value.asText().codePointCount(0, value.asText().length());
            if (schema.has("minLength") && length < schema.get("minLength").asInt()) return false;
            if (schema.has("maxLength") && length > schema.get("maxLength").asInt()) return false;
        }
        if (value.isArray() && schema.has("maxItems") && value.size() > schema.get("maxItems").asInt()) return false;
        if (value.isArray() && schema.has("items")) for (JsonNode item : value) if (!matches(schema.get("items"), item, definitions)) return false;
        if (value.isObject()) {
            for (JsonNode required : schema.path("required")) if (!value.has(required.asText())) return false;
            var fields = value.fields();
            while (fields.hasNext()) {
                var field = fields.next();
                JsonNode definition = schema.path("properties").get(field.getKey());
                if (definition != null) { if (!matches(definition, field.getValue(), definitions)) return false; }
                else {
                    JsonNode additional = schema.get("additionalProperties");
                    if (additional != null && (additional.isBoolean() ? !additional.asBoolean() : !matches(additional, field.getValue(), definitions))) return false;
                }
            }
        }
        return true;
    }
}
