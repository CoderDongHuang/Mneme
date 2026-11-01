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
        @com.fasterxml.jackson.annotation.JsonProperty("retrieval_ranks")
        private java.util.Map<String, Integer> retrievalRanks = java.util.Map.of();
        @com.fasterxml.jackson.annotation.JsonProperty("content_sha256")
        private String contentSha256 = "";
        @com.fasterxml.jackson.annotation.JsonProperty("indexed_at")
        private String indexedAt = "";
        @com.fasterxml.jackson.annotation.JsonProperty("parser_version")
        private String parserVersion = "";
        public java.util.Map<String, Integer> getRetrievalRanks() { return retrievalRanks; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setRetrievalRanks(java.util.Map<String, Integer> value) { retrievalRanks = value; }
        public String getContentSha256() { return contentSha256; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setContentSha256(String value) { contentSha256 = value; }
        public String getIndexedAt() { return indexedAt; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setIndexedAt(String value) { indexedAt = value; }
        public String getParserVersion() { return parserVersion; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setParserVersion(String value) { parserVersion = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("document_id")
        private String documentId = "";
        public String getDocumentId() { return documentId; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setDocumentId(String value) { this.documentId = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("visual_page")
        private Integer visualPage;
        public Integer getVisualPage() { return visualPage; }
        public void setVisualPage(Integer value) { this.visualPage = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("visual_region")
        @com.fasterxml.jackson.databind.annotation.JsonDeserialize(using = VisualRegionDeserializer.class)
        private List<Double> visualRegion;
        public List<Double> getVisualRegion() { return visualRegion; }
        public void setVisualRegion(List<Double> value) { this.visualRegion = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("ocr_confidence")
        private Double ocrConfidence;
        public Double getOcrConfidence() { return ocrConfidence; }
        public void setOcrConfidence(Double value) { this.ocrConfidence = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("evidence_type")
        private String evidenceType = "text";
        public String getEvidenceType() { return evidenceType; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setEvidenceType(String value) { this.evidenceType = value; }
        @com.fasterxml.jackson.annotation.JsonProperty("document_name")
        private String documentName = "未知文档";
        @com.fasterxml.jackson.annotation.JsonProperty("chunk_content")
        private String chunkContent = "";
        private Integer page;
        private Double score = 0.0;
        private String section = "";
        @com.fasterxml.jackson.annotation.JsonProperty("chunk_type")
        private String chunkType = "text";

        public String getDocumentName() { return documentName; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setDocumentName(String documentName) { this.documentName = documentName; }
        public String getChunkContent() { return chunkContent; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setChunkContent(String chunkContent) { this.chunkContent = chunkContent; }
        public Integer getPage() { return page; }
        public void setPage(Integer page) { this.page = page; }
        public Double getScore() { return score; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setScore(Double score) { this.score = score; }
        public String getSection() { return section; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
        public void setSection(String section) { this.section = section; }
        public String getChunkType() { return chunkType; }
        @com.fasterxml.jackson.annotation.JsonSetter(nulls = com.fasterxml.jackson.annotation.Nulls.SKIP)
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
