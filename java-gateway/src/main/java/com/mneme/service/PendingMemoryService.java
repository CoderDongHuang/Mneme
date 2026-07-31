package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.mneme.dto.ChatResponse;
import com.mneme.entity.PendingMemory;
import com.mneme.mapper.PendingMemoryMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import com.mneme.dto.internal.MemoryContracts;

@Service
public class PendingMemoryService {
    private final PendingMemoryMapper mapper;
    private final MemoryService memoryService;

    public PendingMemoryService(PendingMemoryMapper mapper, MemoryService memoryService) {
        this.mapper = mapper;
        this.memoryService = memoryService;
    }

    public void store(Long userId, Long sessionId, Long sourceMessageId, List<ChatResponse.PendingMemory> candidates) {
        if (candidates == null) return;
        for (ChatResponse.PendingMemory candidate : candidates) {
            if (candidate.getTempId() == null || candidate.getTempId().isBlank()) continue;
            Long count = mapper.selectCount(new LambdaQueryWrapper<PendingMemory>()
                .eq(PendingMemory::getMemoryId, candidate.getTempId()));
            if (count > 0) continue;
            PendingMemory memory = new PendingMemory();
            memory.setMemoryId(candidate.getTempId());
            memory.setUserId(userId);
            memory.setSessionId(sessionId);
            memory.setSourceMessageId(sourceMessageId);
            memory.setCategory(candidate.getCategory());
            memory.setContent(candidate.getContent());
            memory.setTopic(candidate.getTopic() == null ? "" : candidate.getTopic());
            memory.setConfidence(candidate.getConfidence());
            memory.setStatus("pending");
            mapper.insert(memory);
        }
    }

    @Transactional
    public MemoryContracts.OperationResult resolve(Long userId, String memoryId, String action) {
        if (!List.of("confirm", "dismiss").contains(action)) {
            throw new IllegalArgumentException("未知记忆操作");
        }
        PendingMemory memory = mapper.selectOne(new LambdaQueryWrapper<PendingMemory>()
            .eq(PendingMemory::getMemoryId, memoryId)
            .eq(PendingMemory::getUserId, userId));
        if (memory == null) throw new IllegalArgumentException("待确认记忆不存在");
        if (!"pending".equals(memory.getStatus())) {
            return new MemoryContracts.OperationResult(memory.getStatus(), null, null);
        }
        MemoryContracts.OperationResult result = memoryService.confirmMemory(
            new MemoryContracts.ConfirmRequest(
                userId.toString(), memory.getMemoryId(), action, memory.getCategory(),
                memory.getContent(), memory.getTopic()
            )
        );
        memory.setStatus("confirm".equals(action) ? "confirmed" : "dismissed");
        memory.setResolvedAt(LocalDateTime.now());
        mapper.updateById(memory);
        return result;
    }
}
