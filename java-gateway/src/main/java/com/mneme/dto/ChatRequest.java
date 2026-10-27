package com.mneme.dto;

import java.util.List;
import java.util.ArrayList;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public class ChatRequest {
    @com.fasterxml.jackson.annotation.JsonProperty("request_id")
    @jakarta.validation.constraints.Size(max = 64)
    private String requestId;
    @com.fasterxml.jackson.annotation.JsonProperty("user_id")
    private String userId;
    @com.fasterxml.jackson.annotation.JsonProperty("session_id")
    @NotBlank
    @Size(max = 128)
    private String sessionId;
    @NotBlank
    @Size(max = 8000)
    private String message;
    @com.fasterxml.jackson.annotation.JsonProperty("knowledge_base_ids")
    @NotNull
    @Size(max = 20)
    private List<@Size(max = 128) String> knowledgeBaseIds = new ArrayList<>();

    @com.fasterxml.jackson.annotation.JsonProperty("selected_document_ids")
    @Size(max = 1000)
    private List<@Size(max = 128) String> selectedDocumentIds = new ArrayList<>();
    @Size(max = 20)
    private List<@Size(max = 80) String> tags = new ArrayList<>();
    @com.fasterxml.jackson.annotation.JsonProperty("date_from")
    @Size(max = 10)
    private String dateFrom;
    @com.fasterxml.jackson.annotation.JsonProperty("date_to")
    @Size(max = 10)
    private String dateTo;
    @com.fasterxml.jackson.annotation.JsonProperty(value = "document_ids", access = com.fasterxml.jackson.annotation.JsonProperty.Access.READ_ONLY)
    private List<String> documentIds;

    public List<String> getSelectedDocumentIds() { return selectedDocumentIds; }
    public void setSelectedDocumentIds(List<String> ids) { selectedDocumentIds = ids; }
    public List<String> getTags() { return tags; }
    public void setTags(List<String> values) { tags = values; }
    public String getDateFrom() { return dateFrom; }
    public void setDateFrom(String value) { dateFrom = value; }
    public String getDateTo() { return dateTo; }
    public void setDateTo(String value) { dateTo = value; }
    public List<String> getDocumentIds() { return documentIds; }
    public void setDocumentIds(List<String> ids) { documentIds = ids; }

    // getters and setters
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public List<String> getKnowledgeBaseIds() { return knowledgeBaseIds; }
    public void setKnowledgeBaseIds(List<String> knowledgeBaseIds) { this.knowledgeBaseIds = knowledgeBaseIds; }
    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }
}
