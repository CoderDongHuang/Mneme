package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import com.fasterxml.jackson.databind.DeserializationFeature;
import java.util.Set;

/** Generated schema is shared with Agent and browser; errors never echo payloads. */
public final class ChatStreamContract {
    private ChatStreamContract() { }
    private static final ObjectReader JSON = new ObjectMapper().reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    private static final Set<String> VOCABULARY = Set.of("$ref", "title", "description", "default", "type",
        "properties", "required", "additionalProperties", "items", "anyOf", "const", "enum",
        "minimum", "maximum", "minLength", "maxLength");
    private static final JsonNode CONTRACT = load();

    private static JsonNode load() {
        try (var input = ChatStreamContract.class.getResourceAsStream("/contracts/chat-stream.schema.json")) {
            if (input == null) throw new IllegalStateException("Missing chat stream contract");
            return new ObjectMapper().readTree(input);
        } catch (java.io.IOException error) { throw new ExceptionInInitializerError(error); }
    }

    public static void validate(String event, JsonNode payload, boolean agent) {
        JsonNode schema = CONTRACT.path("events").get(event);
        boolean allowed = !agent;
        if (agent) for (JsonNode name : CONTRACT.path("agent_events")) if (name.asText().equals(event)) allowed = true;
        if (!allowed || schema == null || payload == null || !matches(schema, payload))
            throw new IllegalArgumentException("INVALID_CHAT_EVENT");
    }

    public static JsonNode read(String event, String json, boolean agent) {
        try {
            JsonNode payload = JSON.readTree(json);
            validate(event, payload, agent);
            return payload;
        } catch (java.io.IOException error) {
            throw new IllegalArgumentException("INVALID_CHAT_EVENT");
        }
    }

    private static boolean matches(JsonNode schema, JsonNode value) {
        if (schema == null) return false;
        var names = schema.fieldNames();
        while (names.hasNext()) if (!VOCABULARY.contains(names.next())) return false;
        if (schema.has("$ref")) {
            String ref = schema.get("$ref").asText();
            return matches(CONTRACT.path("$defs").get(ref.substring(ref.lastIndexOf('/') + 1)), value);
        }
        if (schema.has("anyOf")) {
            boolean found = false;
            for (JsonNode choice : schema.get("anyOf")) if (matches(choice, value)) found = true;
            if (!found) return false;
        }
        if (schema.has("const") && !schema.get("const").equals(value)) return false;
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
        if (value.isArray() && schema.has("items")) for (JsonNode item : value) if (!matches(schema.get("items"), item)) return false;
        if (value.isObject()) {
            for (JsonNode required : schema.path("required")) if (!value.has(required.asText())) return false;
            var fields = value.fields();
            while (fields.hasNext()) {
                var field = fields.next();
                JsonNode definition = schema.path("properties").get(field.getKey());
                if (definition != null) { if (!matches(definition, field.getValue())) return false; }
                else {
                    JsonNode additional = schema.get("additionalProperties");
                    if (additional != null && (additional.isBoolean() ? !additional.asBoolean() : !matches(additional, field.getValue()))) return false;
                }
            }
        }
        return true;
    }
}
