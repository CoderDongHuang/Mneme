package com.mneme.service;

import com.mneme.entity.User;
import com.mneme.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AdminAuthorizationServiceTest {
    @Test
    void requiresActiveAdminUserAndConfiguredToken() {
        UserMapper users = mock(UserMapper.class);
        User user = new User();
        user.setId(1L);
        user.setRole("user");
        user.setStatus("active");
        when(users.selectById(1L)).thenReturn(user);
        AdminAuthorizationService service = new AdminAuthorizationService(users);
        ReflectionTestUtils.setField(service, "adminToken", "01234567890123456789012345678901");

        assertThatThrownBy(() -> service.requireAdmin(1L, "01234567890123456789012345678901"))
            .isInstanceOf(SecurityException.class)
            .hasMessageContaining("管理员权限");
    }

    @Test
    void rejectsWrongAdminToken() {
        UserMapper users = mock(UserMapper.class);
        User user = new User();
        user.setId(1L);
        user.setRole("admin");
        user.setStatus("active");
        when(users.selectById(1L)).thenReturn(user);
        AdminAuthorizationService service = new AdminAuthorizationService(users);
        ReflectionTestUtils.setField(service, "adminToken", "01234567890123456789012345678901");

        assertThatThrownBy(() -> service.requireAdmin(1L, "wrong"))
            .isInstanceOf(SecurityException.class)
            .hasMessageContaining("凭证");
    }
}
