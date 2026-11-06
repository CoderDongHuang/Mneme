package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import com.fasterxml.jackson.databind.DeserializationFeature;

/** Generated schema is shared with Agent and browser; errors never echo payloads. */
public final class ChatStreamContract {
    private ChatStreamContract() { }
    private static final ObjectReader JSON = new ObjectMapper().reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
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
        if (!agent) for (JsonNode name : CONTRACT.path("agent_only_events")) if (name.asText().equals(event)) allowed = false;
        if (agent) for (JsonNode name : CONTRACT.path("agent_events")) if (name.asText().equals(event)) allowed = true;
        if (!allowed || schema == null || payload == null || !SchemaContract.matches(schema, payload, CONTRACT.path("$defs")))
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

}
