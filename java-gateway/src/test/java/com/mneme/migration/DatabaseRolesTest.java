package com.mneme.migration;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration;
import org.springframework.boot.flyway.autoconfigure.FlywayAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.MountableFile;

import javax.sql.DataSource;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@Testcontainers(disabledWithoutDocker = true)
class DatabaseRolesTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.0")
        .withDatabaseName("mneme").withUsername("root").withPassword("isolated-root-password");
    // Exercise quoting of passwords as data, not SQL (including a SQL-looking suffix).
    static final String GATEWAY_PASSWORD = "gw'\\\n; GRANT ALL ON *.* TO evil; --";
    static final String AGENT_PASSWORD = "agent'\\\n密码";
    static final String MIGRATION_PASSWORD = "migration'\\password";

    static JdbcTemplate jdbc(String user, String password) {
        return new JdbcTemplate(new DriverManagerDataSource(MYSQL.getJdbcUrl(), user, password));
    }

    static void provision() throws Exception {
        var result = MYSQL.execInContainer("env", "MYSQL_HOST=127.0.0.1",
            "MYSQL_ROOT_PASSWORD=" + MYSQL.getPassword(), "MYSQL_GATEWAY_PASSWORD=" + GATEWAY_PASSWORD,
            "MYSQL_AGENT_PASSWORD=" + AGENT_PASSWORD, "MYSQL_MIGRATION_PASSWORD=" + MIGRATION_PASSWORD,
            "sh", "/tmp/provision-users.sh");
        assertThat(result.getExitCode()).withFailMessage("Database provisioning must succeed without logging SQL").isZero();
        assertThat(result.getStdout()).isEqualTo("Database migration and DML runtime accounts are ready.\n");
        assertThat(result.getStderr()).isEmpty();
    }

    @BeforeAll static void migrateWithSeparateSpringFlywayConnection() throws Exception {
        MYSQL.copyFileToContainer(MountableFile.forHostPath(Path.of("../docker/mysql/provision-users.sh")), "/tmp/provision-users.sh");
        provision();
        // Actual Boot auto-configuration: if Flyway accidentally uses the DML connection, DDL fails.
        new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(DataSourceAutoConfiguration.class, FlywayAutoConfiguration.class))
            .withPropertyValues("spring.datasource.url=" + MYSQL.getJdbcUrl(),
                "spring.datasource.username=mneme_gateway", "spring.datasource.password=" + GATEWAY_PASSWORD,
                "spring.flyway.user=mneme_migrator", "spring.flyway.password=" + MIGRATION_PASSWORD)
            .run(context -> {
                assertThat(context).hasNotFailed();
                var business = new JdbcTemplate(context.getBean(DataSource.class));
                assertThat(business.queryForObject("SELECT CURRENT_USER()", String.class)).startsWith("mneme_gateway@");
                assertThat(business.queryForObject("SELECT MAX(CAST(version AS UNSIGNED)) FROM flyway_schema_history WHERE success=1", Integer.class)).isEqualTo(27);
            });
    }

    @Test void runtimeDmlSucceedsButDdlAndGlobalPrivilegesAreDenied() {
        var root = jdbc("root", MYSQL.getPassword());
        root.execute("CREATE DATABASE unrelated_roles");
        root.execute("CREATE TABLE unrelated_roles.secret(value INT)");
        try {
            for (var role : new String[][]{{"mneme_gateway", GATEWAY_PASSWORD}, {"mneme_agent", AGENT_PASSWORD}}) {
                var business = jdbc(role[0], role[1]);
                business.update("INSERT INTO agent_tool_usage(user_id,usage_date,used_units) VALUES (?,CURRENT_DATE,1)", role[0]);
                assertThat(business.update("UPDATE agent_tool_usage SET used_units=2 WHERE user_id=?", role[0])).isEqualTo(1);
                assertThat(business.queryForObject("SELECT used_units FROM agent_tool_usage WHERE user_id=?", Integer.class, role[0])).isEqualTo(2);
                assertThat(business.update("DELETE FROM agent_tool_usage WHERE user_id=?", role[0])).isEqualTo(1);
                for (String sql : new String[]{"CREATE TABLE mneme.must_not_exist(id INT)", "DROP DATABASE mneme",
                    "CREATE USER 'must_not_exist'@'%' IDENTIFIED BY 'dummy'", "SELECT * FROM unrelated_roles.secret",
                    "GRANT SELECT ON mneme.* TO 'mneme_gateway'@'%'"}) {
                    assertThatThrownBy(() -> business.execute(sql)).isInstanceOf(org.springframework.dao.DataAccessException.class);
                }
            }
        } finally { root.execute("DROP DATABASE unrelated_roles"); }
    }

    @Test void rerunRevokesLegacyGlobalGrantsAndPreservesData() throws Exception {
        var root = jdbc("root", MYSQL.getPassword());
        root.execute("GRANT CREATE, DROP ON *.* TO 'mneme_agent'@'%'");
        root.update("INSERT INTO agent_tool_usage(user_id,usage_date,used_units) VALUES ('roles-preserved',CURRENT_DATE,3)");
        provision();
        var agent = jdbc("mneme_agent", AGENT_PASSWORD);
        assertThat(agent.queryForObject("SELECT used_units FROM agent_tool_usage WHERE user_id='roles-preserved'", Integer.class)).isEqualTo(3);
        assertThatThrownBy(() -> agent.execute("CREATE DATABASE roles_forbidden")).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(agent.queryForList("SHOW GRANTS", String.class)).allMatch(grant -> !grant.contains("ON *.*") || grant.startsWith("GRANT USAGE"));
        var migrator = jdbc("mneme_migrator", MIGRATION_PASSWORD);
        migrator.execute("CREATE TABLE mneme.roles_ddl_check(id INT)");
        migrator.execute("ALTER TABLE mneme.roles_ddl_check ADD COLUMN value INT");
        migrator.execute("DROP TABLE mneme.roles_ddl_check");
        assertThatThrownBy(() -> migrator.execute("CREATE USER 'migration_forbidden'@'%' IDENTIFIED BY 'dummy'"))
            .isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
}
