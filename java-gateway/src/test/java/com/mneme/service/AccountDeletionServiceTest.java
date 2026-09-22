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
            users, jdbc, mock(RestTemplate.class), operations, "http://agent", root.toString(), 8, storage);

        assertEquals("op-7", service.enqueue(7L));
        assertEquals("deleting", user.getStatus());
        verify(users).updateById(user);
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
            users, jdbc, mock(RestTemplate.class), operations, "http://agent", root.toString(), 8, storage);

        assertEquals("existing-op", service.enqueue(7L));

        verify(users, never()).updateById(any());
        verify(jdbc, never()).update(contains("INSERT INTO account_deletion_task"), any(), any());
        verify(operations, never()).newOperationId();
    }
}
