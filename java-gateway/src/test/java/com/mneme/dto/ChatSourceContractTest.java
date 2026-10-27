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
             "ocr_confidence":0.76,"evidence_type":"visual"}
            """, ChatResponse.Source.class);
        var json = mapper.readTree(mapper.writeValueAsString(source));
        assertEquals("doc_42", json.path("document_id").asText());
        assertEquals(4, json.path("visual_region").size());
        assertEquals(0.76, json.path("ocr_confidence").asDouble());
        assertEquals("visual", json.path("evidence_type").asText());
    }
}
