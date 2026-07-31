package com.mneme.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Size;

public record ProfileUpdateRequest(
    @Size(max = 50) String nickname,
    @Email @Size(max = 120) String email
) {}
