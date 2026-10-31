#!/bin/sh
# Management-only job. Never enable shell tracing or print the generated SQL.
set -eu
: "${MYSQL_ROOT_PASSWORD:?Database administrator password is required}"
: "${MYSQL_GATEWAY_PASSWORD:?Gateway password is required}"
: "${MYSQL_AGENT_PASSWORD:?Agent password is required}"
: "${MYSQL_MIGRATION_PASSWORD:?Migration password is required}"

password_sql() {
    account="$1"
    # Hex encoding makes quotes, backslashes and line breaks data, never SQL.
    encoded=$(printf '%s' "$2" | od -An -v -tx1 | tr -d ' \n')
    printf "SET @pwd=CONVERT(0x%s USING utf8mb4);\n" "$encoded"
    printf "SET @stmt=CONCAT('CREATE USER IF NOT EXISTS ''%s''@''%%'' IDENTIFIED BY ',QUOTE(@pwd));\n" "$account"
    printf 'PREPARE p FROM @stmt; EXECUTE p; DEALLOCATE PREPARE p;\n'
    printf "SET @stmt=CONCAT('ALTER USER ''%s''@''%%'' IDENTIFIED BY ',QUOTE(@pwd));\n" "$account"
    printf 'PREPARE p FROM @stmt; EXECUTE p; DEALLOCATE PREPARE p;\n'
    printf "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '%s'@'%%';\n" "$account"
}

{
    printf "SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION';\n"
    password_sql mneme_gateway "$MYSQL_GATEWAY_PASSWORD"
    password_sql mneme_agent "$MYSQL_AGENT_PASSWORD"
    password_sql mneme_migrator "$MYSQL_MIGRATION_PASSWORD"
    printf "GRANT SELECT,INSERT,UPDATE,DELETE ON mneme.* TO 'mneme_gateway'@'%%';\n"
    printf "GRANT SELECT,INSERT,UPDATE,DELETE ON mneme.* TO 'mneme_agent'@'%%';\n"
    printf "GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,DROP,INDEX,REFERENCES ON mneme.* TO 'mneme_migrator'@'%%';\n"
} | MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 --protocol=TCP -h "${MYSQL_HOST:-mysql}" -uroot --batch 2>/dev/null || {
    printf '%s\n' 'Database role provisioning failed; check administrator access and configuration.' >&2
    exit 1
}
printf '%s\n' 'Database migration and DML runtime accounts are ready.'
