package com.mneme.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ChatSourceContractTest {
    @Test
    void syncResponsePreservesSourceLocations() throws Exception {
        var mapper = new ObjectMapper();
        var source = mapper.readValue("""
            {"document_id":"doc_42","document_name":"A.pdf","chunk_content":"evidence",
             "page":2,"visual_page":2,"visual_region":[0.1,0.2,0.9,0.8],
             "ocr_confidence":0.76,"evidence_type":"visual","retrieval_ranks":{"bm25":1},
             "content_sha256":"file-version","indexed_at":"2026-10-27T00:00:00Z","parser_version":"v2"}
            """, ChatResponse.Source.class);
        var json = mapper.readTree(mapper.writeValueAsString(source));
        assertEquals("doc_42", json.path("document_id").asText());
        assertEquals(4, json.path("visual_region").size());
        assertEquals(0.76, json.path("ocr_confidence").asDouble());
        assertEquals("visual", json.path("evidence_type").asText());
        assertEquals(1, json.path("retrieval_ranks").path("bm25").asInt());
        assertEquals("file-version", json.path("content_sha256").asText());
    }
}
