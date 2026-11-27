package com.mneme.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.mneme.controller.KnowledgeController;
import com.mneme.entity.KnowledgeBase;
import com.mneme.service.KnowledgeService;
import com.mneme.service.UploadSubmissionService;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class KnowledgeBaseContractTest {
    private final ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/knowledge-base.schema.json").toFile()).get("$defs");
    }

    private void assertContract(String name, JsonNode value) throws Exception {
        var definitions = definitions();
        assertTrue(SchemaContract.matches(definitions.get(name), value, definitions), name + " contract mismatch");
    }

    @Test
    void browserAndJavaAgreeOnSharedPositiveAndNegativeCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/knowledge-base.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void entityPropertyNamesStayAlignedWithGeneratedBrowserTypes() throws Exception {
        var actual = mapper.getSerializationConfig().introspect(mapper.constructType(KnowledgeBase.class))
            .findProperties().stream().map(property -> property.getName()).collect(Collectors.toSet());
        var expected = new HashSet<String>();
        definitions().get("KnowledgeBase").get("properties").fieldNames().forEachRemaining(expected::add);
        assertEquals(expected, actual);
    }

    @Test
    void createAndListSerializeEntitiesThroughActualHttpEntryPoints() throws Exception {
        var service = mock(KnowledgeService.class);
        var base = mapper.treeToValue(mapper.readTree("""
            {"id":9,"userId":7,"name":"学习","description":"笔记","chromaCollectionId":"user_7_kb_9",
             "status":"active","createdAt":"2026-11-27T10:00:00","updatedAt":"2026-11-27T10:00:01"}
            """), KnowledgeBase.class);
        when(service.createKb(7L, "学习", "笔记")).thenReturn(base);
        when(service.listKb(7L)).thenReturn(List.of(base));
        var mvc = mvc(service);
        var created = response(mvc, post("/api/v1/knowledge/base").contentType("application/json")
            .content("{\"name\":\"学习\",\"description\":\"笔记\"}"));
        assertContract("KnowledgeBase", created);
        assertEquals("user_7_kb_9", created.path("chromaCollectionId").asText());
        assertEquals("2026-11-27T10:00:00", created.path("createdAt").asText());
        var listed = response(mvc, get("/api/v1/knowledge/base/list"));
        assertContract("KnowledgeBaseList", listed);
        assertEquals(created, listed.get(0));
        verify(service).createKb(7L, "学习", "笔记");
        verify(service).listKb(7L);
        verifyNoMoreInteractions(service);
    }

    @Test
    void optionalFieldsPreserveNullOmissionAndImportedLegacyStatus() throws Exception {
        var base = new KnowledgeBase();
        base.setId(9L);
        base.setName("旧资料库");
        for (var inclusion : List.of(JsonInclude.Include.ALWAYS, JsonInclude.Include.NON_NULL)) {
            for (String state : new String[]{null, "active", "deleting", "legacy_state"}) {
                base.setStatus(state);
                assertContract("KnowledgeBase", mapper.copy().setSerializationInclusion(inclusion).valueToTree(base));
            }
        }
    }

    @Test
    void deletionSerializesTheExistingAcceptanceReceiptThroughHttp() throws Exception {
        var service = mock(KnowledgeService.class);
        var accepted = response(mvc(service), delete("/api/v1/knowledge/base/9"));
        assertContract("KnowledgeBaseDeletionReceipt", accepted);
        assertTrue(accepted.path("deleted").booleanValue());
        verify(service).deleteKb(7L, 9L);
        verifyNoMoreInteractions(service);
    }

    private MockMvc mvc(KnowledgeService service) {
        return MockMvcBuilders.standaloneSetup(new KnowledgeController(service, mock(UploadSubmissionService.class)))
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
