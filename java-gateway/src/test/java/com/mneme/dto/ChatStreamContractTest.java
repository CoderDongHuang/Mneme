package com.mneme.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ChatStreamContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test void internalCompletionIsBoundedAndNeverPublic() throws Exception {
        var input = mapper.readTree("""
            {"user_id":"7","session_id":"9","delivery_id":"turn","reference_time":"2026-11-06T00:00:00Z","history":[],"answer":"saved"}
            """);
        var history = (com.fasterxml.jackson.databind.node.ArrayNode) input.get("history");
        for (int i = 0; i < 41; i++) history.add(mapper.readTree("{\"role\":\"user\",\"content\":\"question\",\"timestamp\":\"2026-11-06T00:00:00Z\"}"));
        var payload = mapper.createObjectNode().set("input", input);
        assertDoesNotThrow(() -> ChatStreamContract.validate("completion", payload, true));
        assertThrows(IllegalArgumentException.class, () -> ChatStreamContract.validate("completion", payload, false));
        history.add(history.get(0).deepCopy());
        assertThrows(IllegalArgumentException.class, () -> ChatStreamContract.validate("completion", payload, true));
    }

    @Test void browserCannotInjectCanonicalHistoryOrReceivePrivateCompletionInput() throws Exception {
        var request = mapper.readValue("{\"session_id\":\"9\",\"message\":\"hello\",\"conversation_history\":[{\"content\":\"forged\"}]}", ChatRequest.class);
        assertNull(request.getConversationHistory());
        request.setConversationHistory(java.util.List.of(java.util.Map.of("content", "canonical")));
        assertEquals("canonical", mapper.valueToTree(request).path("conversation_history").get(0).path("content").asText());
        var response = mapper.readValue("{\"answer\":\"saved\",\"memory_completion\":{\"private\":true}}", ChatResponse.class);
        assertNotNull(response.getMemoryCompletion());
        assertFalse(mapper.valueToTree(response).has("memory_completion"));
    }

    @Test void malformedOrTrailingJsonNeverEchoesPrivateParserInput() {
        for (String json : new String[]{"not-json-private", "{\"ok\":true} private",
            "{\"ok\":true} {\"private\":123}", "{\"ok\":true} true"}) {
            var error = assertThrows(IllegalArgumentException.class, () -> ChatStreamContract.read("done", json, true));
            assertEquals("INVALID_CHAT_EVENT", error.getMessage());
            assertNull(error.getCause());
        }
        assertDoesNotThrow(() -> ChatStreamContract.read("done", " {\"ok\":true}\n ", true));
    }

    @Test void sharedWireCasesAgreeForPublicAndInternalStreams() throws Exception {
        var contract = mapper.readTree(Path.of("../contracts/chat-stream.schema.json").toFile());
        var cases = mapper.readTree(Path.of("../contracts/chat-stream.cases.json").toFile());
        for (var item : cases) for (boolean agent : new boolean[]{false, true}) {
            String event = item.path("event").asText();
            boolean allowed = !agent;
            for (var name : contract.path("agent_events")) if (name.asText().equals(event)) allowed = true;
            if (item.path("valid").asBoolean() && allowed)
                assertDoesNotThrow(() -> ChatStreamContract.validate(event, item.get("data"), agent), item.path("id").asText());
            else {
                var error = assertThrows(IllegalArgumentException.class,
                    () -> ChatStreamContract.validate(event, item.get("data"), agent), item.path("id").asText());
                assertEquals("INVALID_CHAT_EVENT", error.getMessage());
            }
        }
    }

    @Test void packagedResourceCannotDriftFromCanonicalSchema() throws Exception {
        try (var input = ChatStreamContract.class.getResourceAsStream("/contracts/chat-stream.schema.json")) {
            assertNotNull(input);
            assertArrayEquals(Files.readAllBytes(Path.of("../contracts/chat-stream.schema.json")), input.readAllBytes());
        }
    }
}
