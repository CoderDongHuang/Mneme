package com.mneme.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.mneme.entity.KnowledgeBase;
import com.mneme.entity.KnowledgeDocument;
import com.mneme.mapper.KnowledgeBaseMapper;
import com.mneme.mapper.KnowledgeDocumentMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.io.File;
import java.util.List;
import java.util.Map;

@Service
public class KnowledgeService {

    private final KnowledgeBaseMapper kbMapper;
    private final KnowledgeDocumentMapper docMapper;
    private final RestTemplate restTemplate;

    @Value("${mneme.python-agent-url}")
    private String pythonAgentUrl;

    @Value("${mneme.file-storage-path:./data/files}")
    private String fileStoragePath;

    public KnowledgeService(KnowledgeBaseMapper kbMapper, KnowledgeDocumentMapper docMapper, RestTemplate restTemplate) {
        this.kbMapper = kbMapper;
        this.docMapper = docMapper;
        this.restTemplate = restTemplate;
    }

    public KnowledgeBase createKb(Long userId, String name, String description) {
        KnowledgeBase kb = new KnowledgeBase();
        kb.setUserId(userId);
        kb.setName(name);
        kb.setDescription(description);
        kbMapper.insert(kb);
        kb.setChromaCollectionId("user_" + userId + "_kb_" + kb.getId());
        kbMapper.updateById(kb);
        return kb;
    }

    public List<KnowledgeBase> listKb(Long userId) {
        return kbMapper.selectList(new QueryWrapper<KnowledgeBase>().eq("user_id", userId));
    }

    public KnowledgeDocument uploadDocument(Long kbId, String fileName, File tempFile) {
        KnowledgeBase kb = kbMapper.selectById(kbId);
        if (kb == null) throw new RuntimeException("知识库不存在");

        String targetDir = fileStoragePath + "/" + kb.getUserId() + "/" + kbId;
        new File(targetDir).mkdirs();
        String filePath = targetDir + "/" + fileName;

        // 将临时文件复制到共享存储路径
        try {
            java.nio.file.Files.copy(tempFile.toPath(), java.nio.file.Paths.get(filePath),
                java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception e) {
            throw new RuntimeException("文件存储失败", e);
        }

        KnowledgeDocument doc = new KnowledgeDocument();
        doc.setKbId(kbId);
        doc.setFileName(fileName);
        doc.setFilePath(filePath);
        doc.setStatus("parsing");
        docMapper.insert(doc);

        try {
            Map<String, Object> request = Map.of(
                "user_id", kb.getUserId().toString(),
                "kb_id", kbId.toString(),
                "file_path", filePath
            );
            int maxRetries = 2;
            for (int i = 0; i <= maxRetries; i++) {
                try {
                    restTemplate.postForObject(pythonAgentUrl + "/api/v1/knowledge/ingest", request, Map.class);
                    doc.setStatus("ready");
                    break;
                } catch (Exception e) {
                    if (i == maxRetries) throw e;
                    try { Thread.sleep(1000 * (i + 1)); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
                }
            }
        } catch (Exception e) {
            doc.setStatus("failed");
        }
        docMapper.updateById(doc);
        return doc;
    }
}