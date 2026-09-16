package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class OperationLogService {
    private static final Logger log = LoggerFactory.getLogger(OperationLogService.class);
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public OperationLogService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public String newOperationId() {
        return UUID.randomUUID().toString();
    }

    public void record(
        String operationId,
        Long userId,
        String operationType,
        String aggregateId,
        String step,
        String status,
        Map<String, ?> payload,
        Exception error
    ) {
        try {
            jdbc.update("""
                INSERT INTO operation_log(
                    operation_id,user_id,operation_type,aggregate_id,step,status,payload_json,error_message,attempts
                ) VALUES(?,?,?,?,?,?,CAST(? AS JSON),?,?)
                """,
                operationId,
                userId,
                operationType,
                aggregateId,
                step,
                status,
                mapper.writeValueAsString(payload == null ? Map.of() : payload),
                error == null ? null : error.getMessage(),
                integer(payload == null ? null : payload.get("attempts"))
            );
        } catch (Exception loggingError) {
            log.warn("操作日志写入失败: operationId={}, step={}", operationId, step, loggingError);
        }
    }

    public List<Map<String, Object>> list(Long userId, int limit) {
        return jdbc.queryForList("""
            SELECT operation_id,operation_type,aggregate_id,step,status,error_message,attempts,created_at,updated_at
            FROM operation_log WHERE user_id=? ORDER BY id DESC LIMIT ?
            """, userId, Math.max(1, Math.min(limit, 500)));
    }

    private int integer(Object value) {
        try {
            return value == null ? 0 : Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return 0;
        }
    }
}
