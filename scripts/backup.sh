#!/bin/bash
# Mneme 数据备份脚本
# 用法: ./scripts/backup.sh [backup|restore <file>]
set -e

BACKUP_DIR="./backups"
DATA_DIR="./data"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/mneme_backup_$TIMESTAMP.tar.gz"

backup() {
    echo "=== Mneme 数据备份 ==="
    mkdir -p "$BACKUP_DIR"

    # 1. MySQL 导出
    if docker compose ps mysql 2>/dev/null | grep -q "Up"; then
        echo "[MySQL] 导出中..."
        docker compose exec -T mysql mysqldump -uroot -proot mneme > "$BACKUP_DIR/mysql_$TIMESTAMP.sql"
        echo "[MySQL] 完成"
    else
        echo "[MySQL] 容器未运行，跳过"
    fi

    # 2. Chroma 数据
    if [ -d "$DATA_DIR/chroma" ]; then
        echo "[Chroma] 打包中..."
        # Chroma 在运行时可能锁文件，先 cp 再打包
        cp -r "$DATA_DIR/chroma" "$BACKUP_DIR/chroma_$TIMESTAMP"
        echo "[Chroma] 完成"
    else
        echo "[Chroma] 无数据，跳过"
    fi

    # 3. 会话数据
    if [ -d "$DATA_DIR/sessions" ]; then
        echo "[Sessions] 打包中..."
        cp -r "$DATA_DIR/sessions" "$BACKUP_DIR/sessions_$TIMESTAMP"
        echo "[Sessions] 完成"
    fi

    # 4. 打包
    tar -czf "$BACKUP_FILE" -C "$BACKUP_DIR" "mysql_$TIMESTAMP.sql" "chroma_$TIMESTAMP" "sessions_$TIMESTAMP" 2>/dev/null || true
    rm -rf "$BACKUP_DIR/mysql_$TIMESTAMP.sql" "$BACKUP_DIR/chroma_$TIMESTAMP" "$BACKUP_DIR/sessions_$TIMESTAMP"

    echo ""
    echo "备份完成: $BACKUP_FILE"
    ls -lh "$BACKUP_FILE"
}

restore() {
    RESTORE_FILE="$1"
    if [ ! -f "$RESTORE_FILE" ]; then
        echo "错误: 备份文件不存在: $RESTORE_FILE"
        exit 1
    fi

    echo "=== Mneme 数据恢复 ==="
    echo "警告: 将覆盖现有数据!"
    read -p "确认恢复? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "已取消"
        exit 0
    fi

    RESTORE_DIR="$BACKUP_DIR/restore_$TIMESTAMP"
    mkdir -p "$RESTORE_DIR"
    tar -xzf "$RESTORE_FILE" -C "$RESTORE_DIR"

    # MySQL 恢复
    SQL_FILE=$(ls "$RESTORE_DIR"/mysql_*.sql 2>/dev/null | head -1)
    if [ -n "$SQL_FILE" ] && docker compose ps mysql 2>/dev/null | grep -q "Up"; then
        echo "[MySQL] 恢复中..."
        docker compose exec -T mysql mysql -uroot -proot mneme < "$SQL_FILE"
        echo "[MySQL] 完成"
    fi

    # Chroma 恢复
    CHROMA_DIR=$(ls -d "$RESTORE_DIR"/chroma_* 2>/dev/null | head -1)
    if [ -n "$CHROMA_DIR" ]; then
        echo "[Chroma] 恢复中..."
        rm -rf "$DATA_DIR/chroma"
        cp -r "$CHROMA_DIR" "$DATA_DIR/chroma"
        echo "[Chroma] 完成"
    fi

    # Sessions 恢复
    SESSIONS_DIR=$(ls -d "$RESTORE_DIR"/sessions_* 2>/dev/null | head -1)
    if [ -n "$SESSIONS_DIR" ]; then
        echo "[Sessions] 恢复中..."
        rm -rf "$DATA_DIR/sessions"
        cp -r "$SESSIONS_DIR" "$DATA_DIR/sessions"
        echo "[Sessions] 完成"
    fi

    rm -rf "$RESTORE_DIR"
    echo "恢复完成，请重启服务"
}

case "${1:-backup}" in
    backup)  backup ;;
    restore) restore "${2:-}" ;;
    *)       echo "用法: $0 [backup|restore <file>]" ;;
esac
