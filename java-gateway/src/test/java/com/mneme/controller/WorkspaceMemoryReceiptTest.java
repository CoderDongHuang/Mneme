package com.mneme.controller;

import com.mneme.service.WorkspaceService;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class WorkspaceMemoryReceiptTest {
    private WorkspaceController controller;
    private MockRestServiceServer server;

    @BeforeEach
    void setup() {
        var client = new RestTemplate();
        server = MockRestServiceServer.bindTo(client).build();
        controller = new WorkspaceController(mock(WorkspaceService.class), client);
        ReflectionTestUtils.setField(controller, "pythonAgentUrl", "http://agent");
    }

    @Test
    void updateReturnsCommittedRecordWithoutDependingOnAnotherReadAndOverridesForgedOwner() {
        server.expect(requestTo("http://agent/api/v1/memory/admin/mem_7"))
            .andExpect(method(HttpMethod.PATCH))
            .andExpect(content().json("{\"user_id\":\"7\",\"content\":\"已保存\"}"))
            .andRespond(withSuccess("{\"status\":\"updated\",\"memory\":{\"id\":\"mem_7\",\"content\":\"已保存\"}}", MediaType.APPLICATION_JSON));
        var result = controller.updateMemory(7L, "mem_7", new HashMap<>(Map.of("user_id", "99", "content", "已保存")));
        assertThat(((Map<?, ?>) result.getData()).get("memory")).isEqualTo(Map.of("id", "mem_7", "content", "已保存"));
        assertThat(((Map<?, ?>) result.getData()).get("status")).isEqualTo("updated");
        server.verify(); // Any extra list read fails this test, including a read returning 429.
    }

    @Test
    void restoreReturnsCommittedVersionAndUsesAuthenticatedOwner() {
        server.expect(requestTo("http://agent/api/v1/memory/admin/mem_7/restore"))
            .andExpect(method(HttpMethod.POST))
            .andExpect(content().json("{\"user_id\":\"7\",\"version\":1}"))
            .andRespond(withSuccess("{\"status\":\"restored\",\"version\":3,\"memory\":{\"id\":\"mem_7\",\"content\":\"历史内容\"}}", MediaType.APPLICATION_JSON));
        var result = controller.restoreMemory(7L, "mem_7", new HashMap<>(Map.of("user_id", "99", "version", 1)));
        assertThat(((Map<?, ?>) result.getData()).get("version")).isEqualTo(3);
        assertThat(((Map<?, ?>) result.getData()).get("memory")).isEqualTo(Map.of("id", "mem_7", "content", "历史内容"));
        server.verify();
    }

    @Test
    void deleteReturnsOnlyCommittedDeletionReceiptAndIncludesOwner() {
        server.expect(requestTo("http://agent/api/v1/memory/admin/mem_7?user_id=7"))
            .andExpect(method(HttpMethod.DELETE))
            .andRespond(withSuccess("{\"status\":\"deleted\",\"id\":\"mem_7\"}", MediaType.APPLICATION_JSON));
        var result = controller.deleteMemory(7L, "mem_7");
        assertThat(result.getData()).isEqualTo(Map.of("status", "deleted", "id", "mem_7"));
        server.verify();
    }

    @Test
    void failedWriteIsNotConvertedToSuccessOrFollowedByARead() {
        server.expect(requestTo("http://agent/api/v1/memory/admin/mem_7"))
            .andExpect(method(HttpMethod.PATCH))
            .andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS));
        assertThatThrownBy(() -> controller.updateMemory(7L, "mem_7", new HashMap<>(Map.of("content", "未保存"))))
            .isInstanceOf(HttpClientErrorException.TooManyRequests.class);
        server.verify();
    }
}
