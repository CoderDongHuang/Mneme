package com.mneme.dto;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
public record PasswordResetStartRequest(@NotBlank String username, @NotBlank @Email String email) {}
