package com.mneme.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.mneme.controller.ChatSessionController;
import com.mneme.entity.ChatMessage;
import com.mneme.entity.ChatSession;
import com.mneme.mapper.ChatMessageMapper;
import com.mneme.mapper.ChatSessionMapper;
import com.mneme.service.ChatSessionService;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ChatSessionContractTest {
    private final ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/chat-session.schema.json").toFile()).get("$defs");
    }

    private void assertContract(String name, JsonNode value) throws Exception {
        var definitions = definitions();
        assertTrue(SchemaContract.matches(definitions.get(name), value, definitions), name + " contract mismatch");
    }

    @Test
    void browserAndJavaAgreeOnSharedPositiveAndNegativeCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/chat-session.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void entityPropertyNamesStayAlignedWithGeneratedBrowserTypes() throws Exception {
        for (var entry : Map.of("ChatSession", ChatSession.class, "ChatHistoryMessage", ChatMessage.class).entrySet()) {
            var actual = mapper.getSerializationConfig().introspect(mapper.constructType(entry.getValue()))
                .findProperties().stream().map(property -> property.getName()).collect(Collectors.toSet());
            var expected = new HashSet<String>();
            definitions().get(entry.getKey()).get("properties").fieldNames().forEachRemaining(expected::add);
            assertEquals(expected, actual, entry.getKey());
        }
    }

    @Test
    void createListAndRenameSerializeActualEntitiesThroughHttpEntryPoints() throws Exception {
        var service = mock(ChatSessionService.class);
        var session = mapper.treeToValue(mapper.readTree("""
            {"id":9,"userId":7,"title":"学习","deletionStatus":"active",
             "createdAt":"2026-11-27T10:00:00","updatedAt":"2026-11-27T10:00:01"}
            """), ChatSession.class);
        when(service.createSession(7L, "学习")).thenReturn(session);
        when(service.listSessions(7L)).thenReturn(List.of(session));
        when(service.renameSession(7L, 9L, "学习")).thenReturn(session);
        var mvc = mvc(service);
        var created = response(mvc, post("/api/v1/sessions").contentType("application/json").content("{\"title\":\"学习\"}"));
        assertContract("ChatSession", created);
        assertEquals("2026-11-27T10:00:00", created.path("createdAt").asText());
        assertEquals(7, created.path("userId").asLong());
        assertEquals(created, response(mvc, patch("/api/v1/sessions/9").contentType("application/json").content("{\"title\":\"学习\"}")));
        var listed = response(mvc, get("/api/v1/sessions"));
        assertContract("ChatSessionList", listed);
        assertEquals(created, listed.get(0));
        verify(service).createSession(7L, "学习");
        verify(service).renameSession(7L, 9L, "学习");
        verify(service).listSessions(7L);
        verifyNoMoreInteractions(service);
    }

    @Test
    void messageHistoryPreservesCurrentStatesLegacyNullsAndSerializedCitations() throws Exception {
        var service = mock(ChatSessionService.class);
        var examples = new java.util.ArrayList<ChatMessage>();
        for (String state : new String[]{"processing", "completed", "failed", "stopped", "legacy_state", null}) {
            var message = new ChatMessage();
            message.setId((long) examples.size() + 1);
            message.setSessionId(9L);
            message.setRole("assistant");
            message.setContent("partial answer");
            message.setStatus(state);
            message.setRequestId("request-1");
            message.setErrorCode("failed".equals(state) ? "MODEL_TIMEOUT" : null);
            message.setSourcesJson("[{\"document_name\":\"old.txt\",\"chunk_content\":\"evidence\"}]");
            message.setCreatedAt(LocalDateTime.of(2026, 11, 27, 10, 0));
            examples.add(message);
        }
        when(service.getMessages(7L, 9L)).thenReturn(examples);
        var history = response(mvc(service), get("/api/v1/sessions/9/messages"));
        assertContract("ChatHistory", history);
        assertEquals("evidence", mapper.readTree(history.get(0).path("sourcesJson").asText()).get(0).path("chunk_content").asText());
        assertTrue(history.get(5).get("status").isNull());
        assertEquals("MODEL_TIMEOUT", history.get(2).path("errorCode").asText());
        verify(service).getMessages(7L, 9L);
    }

    @Test
    void optionalNullFieldsCanBePresentOrOmittedBySerializerPolicy() throws Exception {
        var session = new ChatSession();
        session.setId(9L);
        var message = new ChatMessage();
        message.setId(11L); message.setSessionId(9L); message.setRole("user"); message.setContent("");
        for (var inclusion : List.of(JsonInclude.Include.ALWAYS, JsonInclude.Include.NON_NULL)) {
            var json = mapper.copy().setSerializationInclusion(inclusion);
            assertContract("ChatSession", json.valueToTree(session));
            assertContract("ChatHistoryMessage", json.valueToTree(message));
        }
    }

    @Test
    void deletionSerializesActualServiceReceiptsIncludingDurableReplays() throws Exception {
        var jdbc = mock(JdbcTemplate.class);
        var service = new ChatSessionService(mock(ChatSessionMapper.class), mock(ChatMessageMapper.class), jdbc, mapper);
        when(jdbc.queryForList(contains("SELECT id FROM user"), eq(Long.class), eq(7L))).thenReturn(List.of(7L));
        when(jdbc.queryForList(contains("SELECT id FROM chat_session"), eq(Long.class), eq(9L), eq(7L))).thenReturn(List.of(9L));
        var mvc = mvc(service);
        var accepted = response(mvc, delete("/api/v1/sessions/9"));
        assertContract("ChatSessionDeletionReceipt", accepted);
        assertEquals("pending", accepted.path("status").asText());
        String taskId = accepted.path("task_id").asText();
        assertTrue(taskId.startsWith("task_"));
        for (var state : definitions().get("ChatSessionDeletionReceipt").path("properties").path("status").path("enum")) {
            when(jdbc.queryForList(contains("SELECT task_id,status"), eq(7L), eq(9L)))
                .thenReturn(List.of(Map.of("task_id", taskId, "status", state.asText())));
            var replay = response(mvc, delete("/api/v1/sessions/9"));
            assertContract("ChatSessionDeletionReceipt", replay);
            assertEquals(taskId, replay.path("task_id").asText());
            assertEquals(state, replay.get("status"));
        }
        verify(jdbc, times(1)).update(contains("INSERT INTO processing_task"), any(), any(), any(), any());
    }

    private MockMvc mvc(ChatSessionService service) {
        return MockMvcBuilders.standaloneSetup(new ChatSessionController(service))
            .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();
    }

    private JsonNode response(MockMvc mvc, MockHttpServletRequestBuilder request) throws Exception {
        var response = mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isOk())
            .andReturn().getResponse().getContentAsByteArray();
        var result = mapper.readTree(response);
        var envelope = mapper.readTree(Path.of("../contracts/gateway-result.schema.json").toFile());
        assertTrue(SchemaContract.matches(envelope, result, mapper.createObjectNode()));
        return result.get("data");
    }
}
