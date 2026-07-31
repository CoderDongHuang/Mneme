package com.mneme.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record PasswordChangeRequest(
    @NotBlank String currentPassword,
    @NotBlank @Size(min = 8, max = 100) String newPassword
) {}
