package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.service.KnowledgeService;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/knowledge")
public class KnowledgeController {
    private final KnowledgeService knowledgeService;

    public KnowledgeController(KnowledgeService knowledgeService) {
        this.knowledgeService = knowledgeService;
    }

    @PostMapping("/base")
    public Result<KnowledgeBase> createKb(
        @RequestAttribute("userId") Long userId,
        @RequestBody Map<String, String> request
    ) {
        return Result.success(knowledgeService.createKb(
            userId, request.get("name"), request.get("description")
        ));
    }

    @GetMapping("/base/list")
    public Result<List<KnowledgeBase>> listKb(@RequestAttribute("userId") Long userId) {
        return Result.success(knowledgeService.listKb(userId));
    }

    @DeleteMapping("/base/{kbId}")
    public Result<Map<String, Boolean>> deleteKb(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long kbId
    ) {
        knowledgeService.deleteKb(userId, kbId);
        return Result.success(Map.of("deleted", true));
    }

    @PostMapping("/document/upload")
    public Result<KnowledgeDocument> uploadDocument(
        @RequestAttribute("userId") Long userId,
        @RequestParam("kbId") Long kbId,
        @RequestParam("file") MultipartFile file
    ) {
        return Result.success(knowledgeService.uploadDocument(userId, kbId, file));
    }

    @GetMapping("/base/{kbId}/documents")
    public Result<List<KnowledgeDocument>> documents(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long kbId
    ) {
        return Result.success(knowledgeService.listDocuments(userId, kbId));
    }

    @GetMapping("/document/{documentId}/status")
    public Result<KnowledgeDocument> documentStatus(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long documentId
    ) {
        return Result.success(knowledgeService.refreshDocumentStatus(userId, documentId));
    }

    @DeleteMapping("/document/{documentId}")
    public Result<Map<String, Boolean>> deleteDocument(@RequestAttribute("userId") Long userId, @PathVariable Long documentId) {
        knowledgeService.deleteDocument(userId, documentId);
        return Result.success(Map.of("accepted", true));
    }

    @PostMapping("/document/{documentId}/reparse")
    public Result<Map<String, Boolean>> reparseDocument(@RequestAttribute("userId") Long userId, @PathVariable Long documentId) {
        knowledgeService.reparseDocument(userId, documentId);
        return Result.success(Map.of("accepted", true));
    }

    @PostMapping("/document/{documentId}/replace")
    public Result<KnowledgeDocument> replaceDocument(
        @RequestAttribute("userId") Long userId,
        @PathVariable Long documentId,
        @RequestParam("file") MultipartFile file
    ) { return Result.success(knowledgeService.replaceDocument(userId, documentId, file)); }

    @GetMapping("/document/{documentId}/versions")
    public Result<List<Map<String, Object>>> documentVersions(
        @RequestAttribute("userId") Long userId, @PathVariable Long documentId
    ) { return Result.success(knowledgeService.documentVersions(userId, documentId)); }

    @PostMapping("/document/{documentId}/versions/{version}/restore")
    public Result<KnowledgeDocument> restoreDocumentVersion(
        @RequestAttribute("userId") Long userId, @PathVariable Long documentId, @PathVariable int version
    ) { return Result.success(knowledgeService.restoreDocumentVersion(userId, documentId, version)); }
}
