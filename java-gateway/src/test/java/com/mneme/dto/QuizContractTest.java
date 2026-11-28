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
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class QuizContractTest {
    private final ObjectMapper mapper = new ObjectMapper();

    private JsonNode definitions() throws Exception {
        return mapper.readTree(Path.of("../contracts/quiz.schema.json").toFile()).get("$defs");
    }

    @Test
    void javaAndBrowserAgreeOnSharedQuizCases() throws Exception {
        var definitions = definitions();
        var cases = mapper.readTree(Path.of("../contracts/quiz.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(), SchemaContract.matches(
                definitions.get(item.path("schema").asText()), item.get("data"), definitions), item.path("id").asText());
        }
    }

    @Test
    void quizLifecycleEndpointsSerializeRequestsAndReceipts() throws Exception {
        var quiz = Map.<String, Object>of("id", 21, "title", "函数复习", "questions_json",
            "[{\"id\":1,\"type\":\"choice\",\"prompt\":\"选择答案\",\"options\":[\"甲\",\"乙\"]}]");
        var draft = Map.<String, Object>of("answers_json", "[\"甲\"]", "current_question", 0);
        var feedback = Map.<String, Object>of("question_id", 1, "correct", true, "expected", "甲", "evidence", "资料依据");
        var attempt = Map.<String, Object>of("id", 9, "answers_json", "[\"甲\"]", "score", 100,
            "raw_score", 100, "feedback_json", mapper.writeValueAsString(List.of(feedback)), "created_at", "2026-11-29 10:00:00");
        var submission = Map.<String, Object>of("score", 100, "raw_score", 100, "feedback", List.of(feedback));
        var report = Map.<String, Object>of("status", "recorded");
        var saveDraft = Map.<String, Object>of("answers", List.of("甲"), "current_question", 0);
        var reportRequest = Map.<String, Object>of("question", 0, "reason", "题目问题");
        var submitRequest = Map.<String, Object>of("answers", List.of("甲"), "request_id", "request_123");
        var service = mock(WorkspaceService.class);
        when(service.quizzes(7L)).thenReturn(List.of(quiz));
        when(service.quizDraft(7L, 21L)).thenReturn(draft);
        when(service.saveQuizDraft(7L, 21L, saveDraft)).thenReturn(draft);
        when(service.quizAttempts(7L, 21L)).thenReturn(List.of(attempt));
        when(service.reportQuestion(7L, 21L, reportRequest)).thenReturn(report);
        when(service.submitQuiz(7L, 21L, submitRequest)).thenReturn(submission);
        when(service.generateQuiz(7L, Map.of("kb_id", 5, "topic", "函数"))).thenReturn(quiz);
        var mvc = MockMvcBuilders.standaloneSetup(new WorkspaceController(service, new RestTemplate()))
            .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();
        var definitions = definitions();

        assertTrue(SchemaContract.matches(definitions.get("Quiz"), data(mvc, get("/api/v1/workspace/quizzes")).get(0), definitions));
        assertTrue(SchemaContract.matches(definitions.get("QuizDraft"), data(mvc, get("/api/v1/workspace/quizzes/21/draft")), definitions));
        assertTrue(SchemaContract.matches(definitions.get("QuizDraft"), data(mvc, put("/api/v1/workspace/quizzes/21/draft")
            .contentType("application/json").content(mapper.writeValueAsBytes(saveDraft))), definitions));
        assertTrue(SchemaContract.matches(definitions.get("QuizAttempt"), data(mvc, get("/api/v1/workspace/quizzes/21/attempts")).get(0), definitions));
        assertTrue(SchemaContract.matches(definitions.get("ReportQuestionReceipt"), data(mvc, post("/api/v1/workspace/quizzes/21/reports")
            .contentType("application/json").content(mapper.writeValueAsBytes(reportRequest))), definitions));
        assertTrue(SchemaContract.matches(definitions.get("QuizSubmissionReceipt"), data(mvc, post("/api/v1/workspace/quizzes/21/submit")
            .contentType("application/json").content(mapper.writeValueAsBytes(submitRequest))), definitions));
        assertTrue(SchemaContract.matches(definitions.get("Quiz"), data(mvc, post("/api/v1/workspace/quizzes/generate")
            .contentType("application/json").content("{\"kb_id\":5,\"topic\":\"函数\"}")), definitions));

        verify(service).quizzes(7L);
        verify(service).quizDraft(7L, 21L);
        verify(service).saveQuizDraft(7L, 21L, saveDraft);
        verify(service).quizAttempts(7L, 21L);
        verify(service).reportQuestion(7L, 21L, reportRequest);
        verify(service).submitQuiz(7L, 21L, submitRequest);
        verify(service).generateQuiz(7L, Map.of("kb_id", 5, "topic", "函数"));
        verifyNoMoreInteractions(service);
    }

    private JsonNode data(MockMvc mvc, MockHttpServletRequestBuilder request) throws Exception {
        var bytes = mvc.perform(request.requestAttr("userId", 7L)).andExpect(status().isOk())
            .andReturn().getResponse().getContentAsByteArray();
        return mapper.readTree(bytes).get("data");
    }
}
