package com.mneme.contract;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.dto.ChatRequest;
import com.mneme.dto.internal.IngestionRequest;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class InternalContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void serializesPythonIngestionContract() throws Exception {
        String json = mapper.writeValueAsString(new IngestionRequest("1", "2", "/data/a.pdf", "doc_3"));
        assertThat(json).contains("\"user_id\":\"1\"");
        assertThat(json).contains("\"kb_id\":\"2\"");
        assertThat(json).contains("\"file_path\":\"/data/a.pdf\"");
        assertThat(json).contains("\"document_id\":\"doc_3\"");
    }

    @Test
    void deserializesVersionedChatRequest() throws Exception {
        ChatRequest request = mapper.readValue("""
            {"request_id":"req-1","user_id":"9","session_id":"7","message":"hello","knowledge_base_ids":["2"]}
            """, ChatRequest.class);
        assertThat(request.getRequestId()).isEqualTo("req-1");
        assertThat(request.getKnowledgeBaseIds()).containsExactly("2");
    }
}
