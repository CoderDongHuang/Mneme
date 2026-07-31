package com.mneme.controller;

import com.mneme.dto.Result;
import com.mneme.service.MemoryService;
import com.mneme.service.PendingMemoryService;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import com.mneme.dto.internal.MemoryContracts;

@RestController
@RequestMapping("/api/v1/memory")
public class MemoryController {
    private final MemoryService memoryService;
    private final PendingMemoryService pendingMemoryService;

    public MemoryController(MemoryService memoryService, PendingMemoryService pendingMemoryService) {
        this.memoryService = memoryService;
        this.pendingMemoryService = pendingMemoryService;
    }

    @GetMapping
    public Result<MemoryContracts.ReadResult> readMemory(@RequestAttribute("userId") Long userId) {
        return Result.success(memoryService.readMemory(
            userId.toString(), List.of("preference", "weak_point", "progress")
        ));
    }

    @PostMapping("/write")
    public Result<MemoryContracts.OperationResult> writeMemory(
        @RequestAttribute("userId") Long userId,
        @RequestBody Map<String, String> request
    ) {
        return Result.success(memoryService.writeMemory(
            userId.toString(), request.get("category"), request.get("content"), request.get("topic")
        ));
    }

    @PostMapping("/confirm")
    public Result<MemoryContracts.OperationResult> confirmMemory(
        @RequestAttribute("userId") Long userId,
        @RequestBody Map<String, Object> request
    ) {
        return Result.success(pendingMemoryService.resolve(
            userId,
            String.valueOf(request.get("temp_id")),
            String.valueOf(request.get("action"))
        ));
    }
}
