package com.mneme.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.mneme.entity.KnowledgeDocument;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface KnowledgeDocumentMapper extends BaseMapper<KnowledgeDocument> {
    @Select("SELECT * FROM knowledge_document WHERE id=#{id} FOR UPDATE")
    KnowledgeDocument selectForUpdate(Long id);

    @Update("UPDATE knowledge_document SET index_generation=index_generation+1 WHERE id=#{id} AND index_generation=#{expected}")
    int advanceGeneration(@Param("id") Long id, @Param("expected") long expected);
}
