package com.mneme.migration;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.spring.MybatisSqlSessionFactoryBean;
import com.mneme.mapper.KnowledgeDocumentMapper;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.concurrent.*;
import java.util.stream.LongStream;

import static org.assertj.core.api.Assertions.*;

@Testcontainers(disabledWithoutDocker = true)
class IndexGenerationConcurrencyTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("mneme").withPassword("generation-test-password");
    static JdbcTemplate jdbc;
    static TransactionTemplate transaction;
    static KnowledgeDocumentMapper documents;

    @BeforeAll static void database() throws Exception {
        var source = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        jdbc = new JdbcTemplate(source);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(source));
        Flyway.configure().dataSource(source).locations("classpath:db/migration").target("29").load().migrate();
        jdbc.update("INSERT INTO user(id,username,password_hash) VALUES(1,'generation','hash')");
        jdbc.update("INSERT INTO knowledge_base(id,user_id,name) VALUES(1,1,'generation')");
        jdbc.update("INSERT INTO knowledge_document(id,kb_id,file_name,file_path,status) VALUES(1,1,'old.txt','old.txt','ready')");
        Flyway.configure().dataSource(source).locations("classpath:db/migration").load().migrate();
        assertThat(jdbc.queryForObject("SELECT index_generation FROM knowledge_document WHERE id=1", Long.class)).isZero();
        var config = new MybatisConfiguration(); config.setMapUnderscoreToCamelCase(true);
        config.addMapper(KnowledgeDocumentMapper.class);
        var factory = new MybatisSqlSessionFactoryBean(); factory.setDataSource(source); factory.setConfiguration(config);
        documents = new SqlSessionTemplate(factory.getObject()).getMapper(KnowledgeDocumentMapper.class);
    }

    @Test void competingTransactionsAllocateUniqueMonotonicGenerationsAndOldEntitiesCannotResetThem() throws Exception {
        var stale = documents.selectById(1L);
        var start = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        var allocated = new ConcurrentLinkedQueue<Long>();
        try {
            var futures = java.util.stream.IntStream.range(0, 2).mapToObj(worker -> pool.submit(() -> {
                assertThat(start.await(5, TimeUnit.SECONDS)).isTrue();
                for (int i = 0; i < 10; i++) {
                    allocated.add(transaction.execute(status -> {
                        var document = documents.selectForUpdate(1L);
                        assertThat(documents.advanceGeneration(1L, document.getIndexGeneration())).isEqualTo(1);
                        return document.getIndexGeneration() + 1;
                    }));
                }
                return true;
            })).toList();
            start.countDown();
            for (var future : futures) assertThat(future.get(20, TimeUnit.SECONDS)).isTrue();
        } finally { pool.shutdownNow(); }
        assertThat(allocated).containsExactlyInAnyOrderElementsOf(LongStream.rangeClosed(1, 20).boxed().toList());
        assertThat(documents.advanceGeneration(1L, 0L)).isZero();
        jdbc.update("UPDATE knowledge_document SET error_message='prior generation rejected' WHERE id=1");
        var recovered = documents.selectById(1L);
        assertThat(recovered.getErrorMessage()).isNotNull();
        recovered.setStatus("ready"); recovered.setErrorMessage(null);
        documents.updateById(recovered);
        assertThat(documents.selectById(1L).getErrorMessage()).isNull();
        stale.setFileName("renamed.txt"); documents.updateById(stale);
        assertThat(documents.selectById(1L).getIndexGeneration()).isEqualTo(20L);
        assertThatThrownBy(() -> transaction.execute(status -> {
            assertThat(documents.advanceGeneration(1L, 20L)).isEqualTo(1);
            throw new IllegalStateException("rollback");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(documents.selectById(1L).getIndexGeneration()).isEqualTo(20L);
    }
}
