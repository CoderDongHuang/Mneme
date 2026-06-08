package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.MemoryService;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/memory")
public class MemoryController {

    private final MemoryService memoryService;

    public MemoryController(MemoryService memoryService) {
        this.memoryService = memoryService;
    }

    @PostMapping("/read")
    public Result<Map<String, Object>> readMemory(@RequestHeader("userId") Long userId,
                                                  @RequestParam String[] memoryTypes) {
        return Result.success(memoryService.readMemory(userId.toString(), memoryTypes));
    }

    @PostMapping("/write")
    public Result<Map<String, Object>> writeMemory(@RequestHeader("userId") Long userId,
                                                   @RequestBody Map<String, String> request) {
        return Result.success(memoryService.writeMemory(
            userId.toString(),
            request.get("category"),
            request.get("content")
        ));
    }
}
