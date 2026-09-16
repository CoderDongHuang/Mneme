package com.mneme.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class OperationLogServiceTest {
    @Test
    void recordsOperationStepsAsJsonPayload() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        OperationLogService service = new OperationLogService(jdbc, new ObjectMapper());

        service.record(
            "op-1",
            7L,
            "account_delete",
            "7",
            "memory_cleanup",
            "completed",
            Map.of("attempts", 2),
            null
        );

        verify(jdbc).update(
            any(String.class),
            eq("op-1"),
            eq(7L),
            eq("account_delete"),
            eq("7"),
            eq("memory_cleanup"),
            eq("completed"),
            eq("{\"attempts\":2}"),
            eq(null),
            eq(2)
        );
    }
}
