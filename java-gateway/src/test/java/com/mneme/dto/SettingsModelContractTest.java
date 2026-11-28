package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.controller.UserSettingsController;
import com.mneme.service.InternalServiceTokenProvider;
import com.mneme.service.UserSettingsService;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class SettingsModelContractTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Map<String, Object> settingsResponse = Map.of(
        "provider", "openai", "model", "gpt-4.1-mini", "enabled", true,
        "hasKey", true, "keyMask", "••••cret", "baseUrl", "https://api.openai.com/v1");

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/settings-model.schema.json").toFile()).get("$defs");
    }

    @Test
    void javaAndBrowserAgreeOnModelSettingsRequestsAndReceipts() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/settings-model.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void modelSettingsEndpointsReturnOnlyTheMaskedActualHttpRepresentation() throws Exception {
        var service = mock(UserSettingsService.class);
        var request = Map.<String, Object>of(
            "provider", "openai", "model", "gpt-4.1-mini", "apiKey", "synthetic-test-secret", "enabled", true);
        when(service.models(7L)).thenReturn(settingsResponse);
        when(service.saveModels(7L, request)).thenReturn(settingsResponse);
        var mvc = mvc(service);

        var read = response(mvc, get("/api/v1/settings/models"));
        assertModelSettings(read);
        var saved = response(mvc, put("/api/v1/settings/models").contentType("application/json")
            .content(mapper.writeValueAsBytes(request)));
        assertModelSettings(saved);
        assertFalse(saved.has("apiKey"));

        verify(service).models(7L);
        verify(service).saveModels(7L, request);
        verifyNoMoreInteractions(service);
    }

    private void assertModelSettings(JsonNode value) throws Exception {
        var definitions = definitions();
        assertTrue(SchemaContract.matches(definitions.get("ModelSettings"), value, definitions));
    }

    private MockMvc mvc(UserSettingsService service) {
        return MockMvcBuilders.standaloneSetup(new UserSettingsController(
            service, mock(InternalServiceTokenProvider.class), mapper, "http://localhost:8001"))
            .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();
    }

    private JsonNode response(MockMvc mvc, MockHttpServletRequestBuilder request) throws Exception {
        var body = mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isOk())
            .andReturn().getResponse().getContentAsByteArray();
        var result = mapper.readTree(body);
        var envelope = mapper.readTree(Path.of("../contracts/gateway-result.schema.json").toFile());
        assertTrue(SchemaContract.matches(envelope, result, mapper.createObjectNode()));
        return result.get("data");
    }
}
