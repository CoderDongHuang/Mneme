package com.mneme.dto;

import java.util.List;

public class ChatRequest {
    @com.fasterxml.jackson.annotation.JsonProperty("user_id")
    private String userId;
    @com.fasterxml.jackson.annotation.JsonProperty("session_id")
    private String sessionId;
    private String message;
    @com.fasterxml.jackson.annotation.JsonProperty("knowledge_base_ids")
    private List<String> knowledgeBaseIds;

    // getters and setters
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public List<String> getKnowledgeBaseIds() { return knowledgeBaseIds; }
    public void setKnowledgeBaseIds(List<String> knowledgeBaseIds) { this.knowledgeBaseIds = knowledgeBaseIds; }
}