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
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PreferencesContractTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Map<String, Object> preferences = Map.of(
        "language", "en", "timezone", "Europe/Amsterdam", "notifications", false, "theme", "dark");

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/preferences.schema.json").toFile()).get("$defs");
    }

    @Test
    void browserAndJavaAgreeOnSharedPositiveAndNegativeCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/preferences.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void preferenceEndpointsSerializeBusinessDataThroughActualHttpEntryPoints() throws Exception {
        var settings = mock(UserSettingsService.class);
        when(settings.preferences(7L)).thenReturn(preferences);
        when(settings.savePreferences(7L, preferences)).thenReturn(preferences);
        var mvc = mvc(settings);

        assertPreferences(response(mvc, get("/api/v1/settings/preferences")));
        assertPreferences(response(mvc, put("/api/v1/settings/preferences").contentType("application/json")
            .content("{\"language\":\"en\",\"timezone\":\"Europe/Amsterdam\",\"notifications\":false,\"theme\":\"dark\"}")));

        verify(settings).preferences(7L);
        verify(settings).savePreferences(7L, preferences);
        verifyNoMoreInteractions(settings);
    }

    private void assertPreferences(JsonNode value) throws Exception {
        var definitions = definitions();
        assertTrue(SchemaContract.matches(definitions.get("Preferences"), value, definitions));
    }

    private MockMvc mvc(UserSettingsService settings) {
        return MockMvcBuilders.standaloneSetup(new UserSettingsController(
            settings, mock(InternalServiceTokenProvider.class), mapper, "http://localhost:8001"))
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
