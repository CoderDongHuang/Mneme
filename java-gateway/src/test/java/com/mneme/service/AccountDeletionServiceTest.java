package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AccountDeletionServiceTest {
    @TempDir Path root;

    @Test void throttledAccountCleanupKeepsBudgetAndReleasesLeaseForLaterRetry() {
        var users = mock(UserMapper.class);
        var jdbc = mock(JdbcTemplate.class);
        var http = mock(RestTemplate.class);
        var operations = mock(OperationLogService.class);
        var lease = mock(TaskLeaseService.Lease.class);
        var row = java.util.Map.<String, Object>of("operation_id", "op", "user_id", 7L,
            "attempt_count", 7, "current_step", "queued");
        when(lease.id()).thenReturn(9L); when(lease.owner()).thenReturn("owner"); when(lease.fence()).thenReturn(3L);
        when(lease.write(any())).thenAnswer(invocation -> {
            java.util.function.Function<java.util.Map<String, Object>, Object> change = invocation.getArgument(0);
            return change.apply(row);
        });
        var user = new User(); user.setId(7L); when(users.selectById(7L)).thenReturn(user);
        doThrow(TaskRetryPolicyTest.limited("120")).when(http).delete("http://agent/api/v1/knowledge/admin/user/7");
        when(http.getForObject(anyString(), eq(java.util.Map.class))).thenReturn(AccountCleanupVerificationTest.healthyAgent());
        var service = new AccountDeletionService(users, jdbc, http, operations, "http://agent", root.toString(),
            8, mock(ObjectStorageService.class), mock(TaskLeaseService.class));
        service.execute(lease);
        verify(jdbc).update(contains("attempt_count=?"), eq(7), eq(120L), eq(9L), eq("owner"), eq(3L));
        verify(jdbc).update(contains("UPDATE user SET status=?"), eq("deleting"), eq(7L));
        verify(lease).finish("retry", TaskRetryPolicy.RATE_LIMIT_MESSAGE);
        verify(users, never()).deleteById(anyLong());
    }

    @Test
    void enqueueFreezesUserAndCreatesRecoverableTask() {
        UserMapper users = mock(UserMapper.class);
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        OperationLogService operations = mock(OperationLogService.class);
        User user = new User(); user.setId(7L); user.setStatus("active");
        when(jdbc.queryForList(contains("FROM user"), eq(Long.class), eq(7L))).thenReturn(List.of(7L));
        when(users.selectById(7L)).thenReturn(user);
        when(jdbc.queryForList(anyString(), eq(7L))).thenReturn(List.of());
        when(operations.newOperationId()).thenReturn("op-7");
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        AccountDeletionService service = new AccountDeletionService(
            users, jdbc, mock(RestTemplate.class), operations, "http://agent", root.toString(), 8, storage, mock(TaskLeaseService.class));

        assertEquals("op-7", service.enqueue(7L));
        verify(jdbc).update("UPDATE user SET status='deleting' WHERE id=?", 7L);
        verify(users, never()).updateById(any(User.class));
        verify(jdbc).update(contains("INSERT INTO account_deletion_task"), eq("op-7"), eq(7L));
    }

    @Test
    void enqueueReturnsExistingTaskWithoutMutatingUser() {
        UserMapper users = mock(UserMapper.class);
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        OperationLogService operations = mock(OperationLogService.class);
        User user = new User(); user.setId(7L); user.setStatus("deleting");
        when(jdbc.queryForList(contains("FROM user"), eq(Long.class), eq(7L))).thenReturn(List.of(7L));
        when(users.selectById(7L)).thenReturn(user);
        when(jdbc.queryForList(contains("account_deletion_task"), eq(7L)))
            .thenReturn(List.of(java.util.Map.of("operation_id", "existing-op")));
        ObjectStorageService storage = new ObjectStorageService(
            "local", root.toString(), "", "", "", "mneme");
        AccountDeletionService service = new AccountDeletionService(
            users, jdbc, mock(RestTemplate.class), operations, "http://agent", root.toString(), 8, storage, mock(TaskLeaseService.class));

        assertEquals("existing-op", service.enqueue(7L));

        verify(users, never()).updateById(any(User.class));
        verify(jdbc, never()).update(contains("INSERT INTO account_deletion_task"), any(), any());
        verify(operations, never()).newOperationId();
    }
}
