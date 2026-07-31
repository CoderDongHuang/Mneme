package com.mneme.dto;

import java.util.List;

public class ChatResponse {
    private String answer;
    private String intent;
    private List<Source> sources;
    @com.fasterxml.jackson.annotation.JsonProperty("session_summary")
    private String sessionSummary;
    @com.fasterxml.jackson.annotation.JsonProperty("memory_insights")
    private List<String> memoryInsights;
    @com.fasterxml.jackson.annotation.JsonProperty("pending_memories")
    private List<PendingMemory> pendingMemories;

    public static class Source {
        @com.fasterxml.jackson.annotation.JsonProperty("document_name")
        private String documentName;
        @com.fasterxml.jackson.annotation.JsonProperty("chunk_content")
        private String chunkContent;
        private Integer page;
        private Double score;
        private String section;
        @com.fasterxml.jackson.annotation.JsonProperty("chunk_type")
        private String chunkType;

        public String getDocumentName() { return documentName; }
        public void setDocumentName(String documentName) { this.documentName = documentName; }
        public String getChunkContent() { return chunkContent; }
        public void setChunkContent(String chunkContent) { this.chunkContent = chunkContent; }
        public Integer getPage() { return page; }
        public void setPage(Integer page) { this.page = page; }
        public Double getScore() { return score; }
        public void setScore(Double score) { this.score = score; }
        public String getSection() { return section; }
        public void setSection(String section) { this.section = section; }
        public String getChunkType() { return chunkType; }
        public void setChunkType(String chunkType) { this.chunkType = chunkType; }
    }

    public static class PendingMemory {
        @com.fasterxml.jackson.annotation.JsonProperty("temp_id")
        private String tempId;
        private String category;
        private String content;
        private String topic;
        private Double confidence;

        public String getTempId() { return tempId; }
        public void setTempId(String tempId) { this.tempId = tempId; }
        public String getCategory() { return category; }
        public void setCategory(String category) { this.category = category; }
        public String getContent() { return content; }
        public void setContent(String content) { this.content = content; }
        public String getTopic() { return topic; }
        public void setTopic(String topic) { this.topic = topic; }
        public Double getConfidence() { return confidence; }
        public void setConfidence(Double confidence) { this.confidence = confidence; }
    }

    public String getAnswer() { return answer; }
    public void setAnswer(String answer) { this.answer = answer; }
    public String getIntent() { return intent; }
    public void setIntent(String intent) { this.intent = intent; }
    public List<Source> getSources() { return sources; }
    public void setSources(List<Source> sources) { this.sources = sources; }
    public String getSessionSummary() { return sessionSummary; }
    public void setSessionSummary(String sessionSummary) { this.sessionSummary = sessionSummary; }
    public List<String> getMemoryInsights() { return memoryInsights; }
    public void setMemoryInsights(List<String> memoryInsights) { this.memoryInsights = memoryInsights; }
    public List<PendingMemory> getPendingMemories() { return pendingMemories; }
    public void setPendingMemories(List<PendingMemory> pendingMemories) { this.pendingMemories = pendingMemories; }
}
