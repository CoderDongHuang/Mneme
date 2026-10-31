package com.mneme.controller;

import com.mneme.service.EmailVerificationService;
import com.mneme.service.ProfileService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;

class EmailVerificationControllerTest {
    @Test void validationDoesNotEchoCredentialsAndCooldownRetainsHttpStatus() throws Exception {
        var verification = mock(EmailVerificationService.class);
        var profiles = mock(ProfileService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new ProfileController(profiles, verification))
            .setControllerAdvice(new GlobalExceptionHandler()).build();
        mvc.perform(post("/api/v1/profile/email-verification/confirm").requestAttr("userId", 7L)
            .contentType("application/json").content("{\"token\":\"private-invalid-code\"}"))
            .andExpect(status().isBadRequest()).andExpect(content().string(not(containsString("private-invalid-code"))));
        mvc.perform(post("/api/v1/profile/email-verification/request").requestAttr("userId", 7L)
            .contentType("application/json").content("{\"email\":\"invalid\"}"))
            .andExpect(status().isBadRequest());
        verifyNoInteractions(verification);
        doThrow(new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "请在 60 秒后重新发送验证码"))
            .when(verification).request(7L, "qa@example.test");
        mvc.perform(post("/api/v1/profile/email-verification/request").requestAttr("userId", 7L)
            .contentType("application/json").content("{\"email\":\"qa@example.test\"}"))
            .andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After", "60"))
            .andExpect(jsonPath("$.code").value(429));
        when(profiles.profile(7L)).thenReturn(Map.of("emailVerified", true));
        mvc.perform(post("/api/v1/profile/email-verification/confirm").requestAttr("userId", 7L)
            .contentType("application/json").content("{\"token\":\"" + "a".repeat(64) + "\"}"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data.emailVerified").value(true));
        verify(verification).confirm(7L, "a".repeat(64));
    }
}
