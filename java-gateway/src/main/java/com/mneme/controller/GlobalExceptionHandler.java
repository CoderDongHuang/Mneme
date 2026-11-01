package com.mneme.controller;

import com.mneme.dto.Result;
import io.jsonwebtoken.JwtException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import com.mneme.exception.RequestInProgressException;
import com.mneme.exception.AdminAccessDeniedException;

@RestControllerAdvice
public class GlobalExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(org.springframework.web.client.HttpClientErrorException.TooManyRequests.class)
    public org.springframework.http.ResponseEntity<Result<Void>> upstreamRateLimit(
            org.springframework.web.client.HttpClientErrorException.TooManyRequests exception) {
        // Preserve backpressure without forwarding private upstream bodies or headers.
        String retry = exception.getResponseHeaders() == null ? null
            : exception.getResponseHeaders().getFirst("Retry-After");
        if (retry == null || !retry.matches("[1-9][0-9]{0,2}")) retry = "1";
        return org.springframework.http.ResponseEntity.status(429)
            .header("Retry-After", retry)
            .body(Result.error(429, "请求过于频繁，请稍后再试"));
    }

    @ExceptionHandler(org.springframework.web.server.ResponseStatusException.class)
    public org.springframework.http.ResponseEntity<Result<Void>> statusError(org.springframework.web.server.ResponseStatusException exception) {
        var response = org.springframework.http.ResponseEntity.status(exception.getStatusCode());
        if (exception.getStatusCode().value() == 429) response.header("Retry-After", "60");
        return response.body(Result.error(exception.getStatusCode().value(), exception.getReason()));
    }

    @ExceptionHandler(com.mneme.exception.MailDeliveryException.class)
    @ResponseStatus(HttpStatus.SERVICE_UNAVAILABLE)
    public Result<Void> mailUnavailable(com.mneme.exception.MailDeliveryException exception) {
        return Result.error(503, exception.getMessage());
    }

    @ExceptionHandler(AdminAccessDeniedException.class)
    @ResponseStatus(HttpStatus.FORBIDDEN)
    public Result<Void> forbidden(AdminAccessDeniedException exception) {
        return Result.error(403, exception.getMessage());
    }

    @ExceptionHandler({SecurityException.class, JwtException.class})
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public Result<Void> unauthorized(Exception exception) {
        return Result.error(401, exception.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<Void> invalidInput(MethodArgumentNotValidException exception) {
        // Validation exceptions include rejected values, including credentials and tokens.
        return Result.error(400, "请求参数格式不正确");
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<Void> badRequest(Exception exception) {
        return Result.error(400, exception.getMessage());
    }

    @ExceptionHandler(RequestInProgressException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public Result<Void> conflict(RequestInProgressException exception) {
        return Result.error(409, exception.getMessage());
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public Result<Void> internalError(Exception exception) {
        log.error("未处理异常", exception);
        return Result.error(500, "服务暂时无法处理该请求");
    }
}
