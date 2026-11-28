package com.mneme.dto;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mneme.controller.WorkspaceController;
import com.mneme.service.WorkspaceService;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.client.RestTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ReviewContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/review.schema.json").toFile()).get("$defs");
    }

    @Test
    void javaAndBrowserAgreeOnReviewAndPlanCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/review.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void reviewEndpointsSerializeActualGatewayResponses() throws Exception {
        var card = Map.<String, Object>of("id", 42, "prompt", "问题", "answer", "答案", "due_at", "2026-11-29 12:00:00", "review_count", 2, "last_rating", 5);
        var plan = Map.<String, Object>of("id", 7, "title", "复习计划", "goal", "掌握知识点", "status", "active");
        var rating = Map.<String, Object>of("rating", 5);
        var service = mock(WorkspaceService.class);
        when(service.reviews(7L)).thenReturn(List.of(card));
        when(service.plans(7L)).thenReturn(List.of(plan));
        when(service.createPlan(7L, Map.of("title", "复习计划", "goal", "掌握知识点"))).thenReturn(plan);
        when(service.review(7L, 42L, 5)).thenReturn(card);
        var mvc = MockMvcBuilders.standaloneSetup(new WorkspaceController(service, new RestTemplate()))
            .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();

        assertTrue(SchemaContract.matches(definitions().get("ReviewCard"), data(mvc, get("/api/v1/workspace/reviews" )).get(0), definitions()));
        assertTrue(SchemaContract.matches(definitions().get("LearningPlan"), data(mvc, get("/api/v1/workspace/plans")).get(0), definitions()));
        assertTrue(SchemaContract.matches(definitions().get("LearningPlan"), data(mvc, post("/api/v1/workspace/plans")
            .contentType("application/json").content("{\"title\":\"复习计划\",\"goal\":\"掌握知识点\"}")), definitions()));
        assertTrue(SchemaContract.matches(definitions().get("ReviewCard"), data(mvc, post("/api/v1/workspace/reviews/42")
            .contentType("application/json").content(mapper.writeValueAsBytes(rating))), definitions()));

        verify(service).reviews(7L);
        verify(service).plans(7L);
        verify(service).createPlan(7L, Map.of("title", "复习计划", "goal", "掌握知识点"));
        verify(service).review(7L, 42L, 5);
        verifyNoMoreInteractions(service);
    }

    private JsonNode data(MockMvc mvc, org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder request) throws Exception {
        var bytes = mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isOk())
            .andReturn().getResponse().getContentAsByteArray();
        return mapper.readTree(bytes).get("data");
    }
}
