package com.mneme.dto;

import java.util.List;

public class ChatResponse {
    private String answer;
    private List<Source> sources;

    public static class Source {
        @com.fasterxml.jackson.annotation.JsonProperty("document_name")
        private String documentName;
        @com.fasterxml.jackson.annotation.JsonProperty("chunk_content")
        private String chunkContent;
        private Integer page;
        private Double score;

        // getters and setters
        public String getDocumentName() { return documentName; }
        public void setDocumentName(String documentName) { this.documentName = documentName; }
        public String getChunkContent() { return chunkContent; }
        public void setChunkContent(String chunkContent) { this.chunkContent = chunkContent; }
        public Integer getPage() { return page; }
        public void setPage(Integer page) { this.page = page; }
        public Double getScore() { return score; }
        public void setScore(Double score) { this.score = score; }
    }

    // getters and setters
    public String getAnswer() { return answer; }
    public void setAnswer(String answer) { this.answer = answer; }
    public List<Source> getSources() { return sources; }
    public void setSources(List<Source> sources) { this.sources = sources; }
}