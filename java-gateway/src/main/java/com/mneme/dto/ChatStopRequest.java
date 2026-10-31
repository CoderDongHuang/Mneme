package com.mneme.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/** The generation comes from the stream's start handshake, never from a guess. */
public record ChatStopRequest(
    @JsonProperty("session_id") @NotNull @Positive Long sessionId,
    @JsonProperty("request_id") @NotBlank @Size(max = 64) String requestId,
    @JsonProperty("answer_generation") @Positive long answerGeneration
) { }
