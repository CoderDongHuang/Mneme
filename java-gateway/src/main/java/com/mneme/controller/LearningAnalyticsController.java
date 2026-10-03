package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.LearningAnalyticsService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/analytics")
public class LearningAnalyticsController {
    private final LearningAnalyticsService analytics;
    public LearningAnalyticsController(LearningAnalyticsService analytics) { this.analytics = analytics; }
    public record Feedback(@Positive long message_id, @NotBlank String outcome, @NotBlank String citation_rating,
        @NotBlank String reason, @Size(max=1000) String note) {}
    @GetMapping public Result<Map<String, Object>> summary(@RequestAttribute("userId") Long user,
        @RequestParam(defaultValue="30") int days) { return Result.success(analytics.summary(user, days)); }
    @PutMapping("/feedback") public Result<Map<String, String>> feedback(@RequestAttribute("userId") Long user,
        @Valid @RequestBody Feedback body) {
        analytics.feedback(user, body.message_id(), body.outcome(), body.citation_rating(), body.reason(), body.note());
        return Result.success(Map.of("status", "saved"));
    }
    @DeleteMapping("/feedback/{id}") public Result<Map<String, String>> delete(@RequestAttribute("userId") Long user,
        @PathVariable long id) {
        analytics.deleteFeedback(user, id); return Result.success(Map.of("status", "deleted"));
    }
}
