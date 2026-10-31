package com.mneme.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;

public record EmailVerificationConfirmRequest(@NotBlank @Pattern(regexp = "[0-9a-f]{64}") String token) {}
