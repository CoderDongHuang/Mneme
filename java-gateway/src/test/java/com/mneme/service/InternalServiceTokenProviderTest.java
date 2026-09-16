package com.mneme.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class InternalServiceTokenProviderTest {
    @Test
    void rotatesWithoutExposingSecret() {
        InternalServiceTokenProvider provider = new InternalServiceTokenProvider("a".repeat(32), "");

        provider.rotate("b".repeat(32));

        assertEquals("b".repeat(32), provider.current());
        assertEquals(true, provider.status().get("previous_configured"));
        assertFalse(provider.status().toString().contains("b".repeat(16)));
    }

    @Test
    void rejectsWeakToken() {
        assertThrows(IllegalArgumentException.class, () -> new InternalServiceTokenProvider("short", ""));
    }
}
