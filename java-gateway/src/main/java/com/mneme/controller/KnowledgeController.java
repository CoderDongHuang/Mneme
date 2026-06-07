package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.service.KnowledgeService;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
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
    public Result<KnowledgeBase> createKb(@RequestHeader("userId") Long userId,
                                          @RequestBody Map<String, String> request) {
        KnowledgeBase kb = knowledgeService.createKb(userId, request.get("name"), request.get("description"));
        return Result.success(kb);
    }

    @GetMapping("/base/list")
    public Result<List<KnowledgeBase>> listKb(@RequestHeader("userId") Long userId) {
        return Result.success(knowledgeService.listKb(userId));
    }

    @PostMapping("/document/upload")
    public Result<KnowledgeDocument> uploadDocument(@RequestParam("kbId") Long kbId,
                                                    @RequestParam("file") MultipartFile file) throws Exception {
        File tempFile = File.createTempFile("upload_", file.getOriginalFilename());
        file.transferTo(tempFile);
        KnowledgeDocument doc = knowledgeService.uploadDocument(kbId, file.getOriginalFilename(), tempFile);
        return Result.success(doc);
    }
}