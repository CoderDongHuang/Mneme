package com.mneme.service;

import java.time.Instant;
import java.util.Map;
import java.util.stream.Stream;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.entity.ProcessingTask;
import com.mneme.mapper.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class TaskRetryPolicyTest {
    private static final Instant NOW = Instant.parse("2026-11-05T00:00:00Z");

    static HttpClientErrorException limited(String retryAfter) {
        var headers = new HttpHeaders();
        if (retryAfter != null) headers.set("Retry-After", retryAfter);
        return HttpClientErrorException.create(HttpStatus.TOO_MANY_REQUESTS, "limited", headers,
            "private upstream response".getBytes(java.nio.charset.StandardCharsets.UTF_8), null);
    }

    static Stream<Arguments> headers() {
        return Stream.of(Arguments.of(null, 60L), Arguments.of("invalid", 60L), Arguments.of("1", 30L),
            Arguments.of("120", 120L), Arguments.of("-1", 30L), Arguments.of("999999999", 86400L),
            Arguments.of("Thu, 5 Nov 2026 00:02:00 GMT", 120L),
            Arguments.of("Thu, 5 Nov 2026 00:00:00 GMT", 30L));
    }

    @ParameterizedTest @MethodSource("headers")
    void rateLimitsPreserveFaultBudgetAndRespectBoundedRetryAfter(String header, long seconds) {
        var result = TaskRetryPolicy.decide(new IllegalStateException("verification", limited(header)), 4, 5, 300, NOW);
        assertThat(result.attempts()).isEqualTo(4);
        assertThat(result.exhausted()).isFalse();
        assertThat(result.rateLimited()).isTrue();
        assertThat(result.delaySeconds()).isEqualTo(seconds);
    }

    @Test void actualFaultsStillExhaustAndDoNotInspectSuppressedUnrelatedErrors() {
        var failure = new IllegalStateException("residue");
        failure.addSuppressed(limited("1"));
        var result = TaskRetryPolicy.decide(failure, 4, 5, 300, NOW);
        assertThat(result.attempts()).isEqualTo(5);
        assertThat(result.exhausted()).isTrue();
        assertThat(result.rateLimited()).isFalse();
        assertThat(result.delaySeconds()).isEqualTo(32);
    }

    @Test void workerPersistsRateLimitWithoutLeakingBodyAndStillFailsRealFaults() {
        var jdbc = mock(JdbcTemplate.class);
        var service = new ProcessingTaskService(mock(ProcessingTaskMapper.class), mock(KnowledgeDocumentMapper.class),
            mock(KnowledgeBaseMapper.class), new ObjectMapper(), mock(RestTemplate.class), new SimpleMeterRegistry(),
            mock(NotificationService.class), jdbc, mock(ObjectStorageService.class), mock(TaskLeaseService.class), mock(PendingMemoryService.class));
        var lease = mock(TaskLeaseService.Lease.class);
        when(lease.owner()).thenReturn("owner");
        when(lease.fence()).thenReturn(2L);
        var task = new ProcessingTask(); task.setId(7L); task.setTaskId("task"); task.setTaskType("session_delete");
        task.setAttemptCount(4); task.setMaxAttempts(5);
        ReflectionTestUtils.invokeMethod(service, "retryOrFailLocked", task, lease, limited("120"));
        assertThat(task.getStatus()).isEqualTo("retry");
        assertThat(task.getAttemptCount()).isEqualTo(4);
        assertThat(task.getErrorCode()).isEqualTo("RATE_LIMITED");
        assertThat(task.getErrorMessage()).isEqualTo(TaskRetryPolicy.RATE_LIMIT_MESSAGE);
        verify(jdbc).update(contains("attempt_count=?"), eq(4), eq(120L), eq("RATE_LIMITED"), eq(7L), eq("owner"), eq(2L));
        verify(lease).finish("retry", TaskRetryPolicy.RATE_LIMIT_MESSAGE);
        ReflectionTestUtils.invokeMethod(service, "retryOrFailLocked", task, lease, new IllegalStateException("real fault"));
        assertThat(task.getStatus()).isEqualTo("failed");
        assertThat(task.getAttemptCount()).isEqualTo(5);
        verify(lease).finish("failed", "会话清理未完成，请修复服务后重试任务");
    }

    @Test void realResidueAndOtherUnreadableStoreCannotBeMaskedByThrottledRead() {
        for (boolean unreadable : new boolean[] {false, true}) {
            var report = new CleanupReport();
            var http = mock(RestTemplate.class);
            when(http.getForObject("report", Map.class)).thenThrow(limited("1"));
            report.agent(http, "report", java.util.List.of("fts"));
            report.read("files", () -> { if (unreadable) throw new IllegalStateException("disk unavailable"); return 1; });
            var failure = catchThrowableOfType(() -> report.requireZeroExcept(null), IllegalStateException.class);
            assertThat(TaskRetryPolicy.decide(failure, 4, 5, 300, NOW).exhausted()).isTrue();
        }
    }
}
