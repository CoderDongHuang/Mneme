package com.mneme.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.nio.file.Path;
import static org.junit.jupiter.api.Assertions.*;

class ChatSourceContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void pythonGeneratedCitationsRoundTripWithoutFieldOrTypeDrift() throws Exception {
        var examples = mapper.readTree(Path.of("../contracts/chat-source.examples.json").toFile());
        var schema = mapper.readTree(Path.of("../contracts/chat-source.schema.json").toFile());
        var properties = mapper.getSerializationConfig().introspect(mapper.constructType(ChatResponse.Source.class)).findProperties();
        assertEquals(schema.path("properties").size(), properties.size());
        for (var property : properties) {
            assertTrue(schema.path("properties").has(property.getName()), property.getName());
            assertWireType(schema.path("properties").get(property.getName()), property.getPrimaryType(), property.getName());
        }
        for (var example : examples) {
            var source = mapper.treeToValue(example, ChatResponse.Source.class);
            assertEquals(example, mapper.valueToTree(source));
        }
    }

    private void assertWireType(com.fasterxml.jackson.databind.JsonNode schema, com.fasterxml.jackson.databind.JavaType type, String name) {
        if (schema.has("anyOf")) {
            for (var branch : schema.get("anyOf")) {
                if (!"null".equals(branch.path("type").asText())) assertWireType(branch, type, name);
            }
            return;
        }
        switch (schema.path("type").asText()) {
            case "string" -> assertEquals(String.class, type.getRawClass(), name);
            case "integer" -> assertTrue(java.util.Set.of(Integer.class, Long.class).contains(type.getRawClass()), name);
            case "number" -> assertTrue(java.util.Set.of(Double.class, Float.class).contains(type.getRawClass()), name);
            case "array" -> {
                assertTrue(type.isCollectionLikeType(), name);
                assertWireType(schema.get("items"), type.getContentType(), name + "[]");
            }
            case "object" -> {
                assertTrue(type.isMapLikeType(), name);
                assertEquals(String.class, type.getKeyType().getRawClass(), name);
                assertWireType(schema.get("additionalProperties"), type.getContentType(), name + "{}");
            }
            default -> fail("Unsupported source schema type: " + schema);
        }
    }

    @Test
    void historicalCsvAndMalformedRegionsDoNotLoseOtherCitationMetadata() throws Exception {
        var cases = mapper.readTree(Path.of("../contracts/citation-regions.json").toFile());
        for (var item : cases) {
            var input = mapper.createObjectNode().put("document_name", "legacy.pdf").put("chunk_content", "evidence");
            input.set("visual_region", item.get("input"));
            var source = mapper.treeToValue(input, ChatResponse.Source.class);
            var output = mapper.valueToTree(source);
            var expected = mapper.convertValue(item.get("expected"), mapper.getTypeFactory().constructCollectionType(java.util.List.class, Double.class));
            assertEquals(expected, source.getVisualRegion(), item.toString());
            assertEquals("evidence", output.path("chunk_content").asText());
            assertEquals("legacy.pdf", output.path("document_name").asText());
        }
    }

    @Test
    void nullLegacyOptionalStringsKeepWireDefaults() throws Exception {
        var source = mapper.readValue("{\"document_id\":null,\"chunk_type\":null,\"score\":null,\"retrieval_ranks\":null}", ChatResponse.Source.class);
        assertEquals("", source.getDocumentId());
        assertEquals("text", source.getChunkType());
        assertEquals(0.0, source.getScore());
        assertEquals(java.util.Map.of(), source.getRetrievalRanks());
    }

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
