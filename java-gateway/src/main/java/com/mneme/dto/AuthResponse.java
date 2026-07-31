package com.mneme.dto;

public record AuthResponse(@com.fasterxml.jackson.annotation.JsonIgnore String token, Long userId, String username) {
}
