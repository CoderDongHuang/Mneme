package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.mneme.controller.ProfileController;
import com.mneme.service.EmailVerificationService;
import com.mneme.service.ProfileService;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.AbstractMockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ProfileContractTest {
    private final ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/profile.schema.json").toFile()).get("$defs");
    }

    private void assertContract(String name, JsonNode value) throws Exception {
        var definitions = definitions();
        assertTrue(SchemaContract.matches(definitions.get(name), value, definitions), name + " contract mismatch");
    }

    @Test
    void browserAndJavaAgreeOnSharedPositiveAndNegativeCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/profile.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void profileEndpointsSerializeBusinessDataThroughActualHttpEntryPoints() throws Exception {
        var profiles = mock(ProfileService.class);
        var verification = mock(EmailVerificationService.class);
        var profile = mapper.readTree("""
            {"userId":7,"username":"alice","nickname":"Alice","email":"alice@example.test",
             "role":"user","emailVerified":true,"hasAvatar":false}
            """);
        List<Map<String, Object>> sessions = List.of(Map.<String, Object>of(
            "session_id", "session-1", "remembered", true,
            "created_at", "2026-11-28T01:00:00Z", "last_seen_at", "2026-11-28T02:00:00Z",
            "expires_at", "2026-12-28T01:00:00Z"));
        when(profiles.profile(7L)).thenReturn(mapper.convertValue(profile, Map.class));
        when(profiles.sessions(7L)).thenReturn(sessions);
        when(profiles.update(eq(7L), any(ProfileUpdateRequest.class))).thenReturn(mapper.convertValue(profile, Map.class));
        when(profiles.uploadAvatar(eq(7L), any(MultipartFile.class))).thenReturn(mapper.convertValue(profile, Map.class));
        when(profiles.deleteAccount(7L)).thenReturn("delete-7");
        var mvc = mvc(profiles, verification);

        assertContract("Profile", response(mvc, get("/api/v1/profile")));
        assertContract("AuthSessionList", response(mvc, get("/api/v1/profile/sessions")));
        assertContract("Profile", response(mvc, patch("/api/v1/profile").contentType("application/json")
            .content("{\"nickname\":\"Alice\",\"email\":\"alice@example.test\"}")));
        assertContract("EmailVerificationReceipt", response(mvc, post("/api/v1/profile/email-verification/request")
            .contentType("application/json").content("{\"email\":\"alice@example.test\"}")));
        assertContract("Profile", response(mvc, post("/api/v1/profile/email-verification/confirm")
            .contentType("application/json").content("{\"token\":\"abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789\"}")));
        assertContract("Profile", response(mvc, multipart("/api/v1/profile/avatar")
            .file(new MockMultipartFile("file", "avatar.png", "image/png", new byte[]{1}))));
        assertContract("VoidReceipt", response(mvc, post("/api/v1/profile/password")
            .contentType("application/json").content("{\"currentPassword\":\"old-password\",\"newPassword\":\"new-password\"}")));
        assertContract("VoidReceipt", response(mvc, delete("/api/v1/profile/sessions/session-1")));
        assertContract("AccountDeletionReceipt", response(mvc, delete("/api/v1/profile/account")));

        verify(profiles, org.mockito.Mockito.times(2)).profile(7L);
        verify(profiles).sessions(7L);
        verify(profiles).update(eq(7L), any(ProfileUpdateRequest.class));
        verify(verification).request(eq(7L), eq("alice@example.test"));
        verify(verification).confirm(eq(7L), eq("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"));
        verify(profiles).uploadAvatar(eq(7L), any(MultipartFile.class));
        verify(profiles).changePassword(eq(7L), any(PasswordChangeRequest.class));
        verify(profiles).revokeSession(7L, "session-1");
        verify(profiles).deleteAccount(7L);
        verifyNoMoreInteractions(profiles, verification);
    }

    private MockMvc mvc(ProfileService profiles, EmailVerificationService verification) {
        return MockMvcBuilders.standaloneSetup(new ProfileController(profiles, verification))
            .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();
    }

    private JsonNode response(MockMvc mvc, AbstractMockHttpServletRequestBuilder<?> request) throws Exception {
        var response = mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isOk())
            .andReturn().getResponse().getContentAsByteArray();
        var result = mapper.readTree(response);
        var envelope = mapper.readTree(Path.of("../contracts/gateway-result.schema.json").toFile());
        assertTrue(SchemaContract.matches(envelope, result, mapper.createObjectNode()));
        return result.get("data");
    }
}
