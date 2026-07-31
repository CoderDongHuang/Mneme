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

@RestControllerAdvice
public class GlobalExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler({SecurityException.class, JwtException.class})
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public Result<Void> unauthorized(Exception exception) {
        return Result.error(401, exception.getMessage());
    }

    @ExceptionHandler({IllegalArgumentException.class, MethodArgumentNotValidException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<Void> badRequest(Exception exception) {
        return Result.error(400, exception.getMessage());
    }

    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public Result<Void> internalError(Exception exception) {
        log.error("未处理异常", exception);
        return Result.error(500, "服务暂时无法处理该请求");
    }
}
