package com.mneme.service;

import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;

/** Database clock, unique attempt owner, and monotonic fence shared by durable workers. */
@Service
public class TaskLeaseService implements AutoCloseable {
    public enum Queue {
        PROCESSING("processing_task"), ACCOUNT_DELETION("account_deletion_task");
        final String table;
        Queue(String table) { this.table = table; }
    }

    public static final class LostLease extends RuntimeException {
        LostLease() { super("任务执行权已过期或已被接管"); }
    }

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final int seconds;
    private final ScheduledThreadPoolExecutor heartbeats;
    private final Semaphore slots = new Semaphore(16);

    public TaskLeaseService(JdbcTemplate jdbc, PlatformTransactionManager manager,
        @Value("${mneme.task-lease-seconds:300}") int seconds) {
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager);
        this.seconds = Math.max(3, seconds);
        heartbeats = new ScheduledThreadPoolExecutor(2, runnable -> {
            var thread = new Thread(runnable, "mneme-task-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
        heartbeats.setRemoveOnCancelPolicy(true);
        heartbeats.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
    }

    public Lease claim(Queue queue, long id, boolean cancellationCleanup) {
        if (!slots.tryAcquire()) return null;
        String owner = UUID.randomUUID().toString();
        String eligible = cancellationCleanup
            ? "status='cancelling' AND (owner_token IS NULL OR lease_until<=UTC_TIMESTAMP(6))"
            : "status IN ('pending','retry') AND next_attempt_at<=UTC_TIMESTAMP(6)";
        try {
            var lease = transaction.execute(status -> {
                int updated = jdbc.update("UPDATE " + queue.table + " SET status=?,owner_token=?,lease_fence=lease_fence+1,"
                    + "lease_until=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6)),locked_at=UTC_TIMESTAMP(6),locked_by=?"
                    + " WHERE id=? AND " + eligible,
                    cancellationCleanup ? "cancelling" : "processing", owner, seconds, owner, id);
                if (updated != 1) return null;
                long fence = jdbc.queryForObject("SELECT lease_fence FROM " + queue.table + " WHERE id=? AND owner_token=?",
                    Long.class, id, owner);
                return new Lease(queue, id, owner, fence);
            });
            if (lease == null) slots.release();
            return lease;
        } catch (RuntimeException error) { slots.release(); throw error; }
    }

    public void recover(Queue queue) {
        // Legacy workers must be stopped for the V27 upgrade. Never steal an unexpired lease.
        jdbc.update("UPDATE " + queue.table + " SET status='retry',next_attempt_at=UTC_TIMESTAMP(),"
            + "owner_token=NULL,lease_until=NULL,locked_at=NULL,locked_by=NULL"
            + " WHERE status='processing' AND ((owner_token IS NOT NULL AND lease_until<=UTC_TIMESTAMP(6))"
            + " OR (owner_token IS NULL AND locked_at<TIMESTAMPADD(SECOND,-300,UTC_TIMESTAMP(6))))");
    }

    public final class Lease implements AutoCloseable {
        private final Queue queue;
        private final long id;
        private final String owner;
        private final long fence;
        private final AtomicBoolean lost = new AtomicBoolean();
        private final AtomicBoolean closed = new AtomicBoolean();
        private ScheduledFuture<?> heartbeat;
        private final ThreadLocal<Boolean> writing = ThreadLocal.withInitial(() -> false);

        private Lease(Queue queue, long id, String owner, long fence) {
            this.queue = queue; this.id = id; this.owner = owner; this.fence = fence;
        }
        public long id() { return id; }
        public String owner() { return owner; }
        public long fence() { return fence; }

        public void startHeartbeat() {
            if (heartbeat != null || closed.get()) throw new IllegalStateException("Heartbeat already started or closed");
            heartbeat = heartbeats.scheduleWithFixedDelay(() -> {
                try { renew(); } catch (RuntimeException error) { lost.set(true); }
            }, Math.max(1, seconds / 3), Math.max(1, seconds / 3), TimeUnit.SECONDS);
        }

        public void renew() {
            if (lost.get() || closed.get()) throw new LostLease();
            if (jdbc.update("UPDATE " + queue.table + " SET lease_until=TIMESTAMPADD(SECOND,?,UTC_TIMESTAMP(6)),"
                + "locked_at=UTC_TIMESTAMP(6) WHERE id=? AND owner_token=? AND lease_fence=?"
                + " AND lease_until>UTC_TIMESTAMP(6) AND status IN ('processing','cancelling')",
                seconds, id, owner, fence) != 1) {
                lost.set(true);
                throw new LostLease();
            }
        }

        /** All business writes and terminal transitions run while holding this owner row lock. */
        public <T> T write(Function<Map<String, Object>, T> change) {
            if (lost.get() || closed.get()) throw new LostLease();
            return transaction.execute(status -> {
                var rows = jdbc.queryForList("SELECT * FROM " + queue.table
                    + " WHERE id=? AND owner_token=? AND lease_fence=? AND lease_until>UTC_TIMESTAMP(6)"
                    + " AND status IN ('processing','cancelling') FOR UPDATE", id, owner, fence);
                if (rows.isEmpty()) { lost.set(true); throw new LostLease(); }
                renew();
                writing.set(true);
                try { return change.apply(rows.get(0)); }
                finally { writing.remove(); }
            });
        }

        /** Only call inside write(), after dependent business updates. */
        public void finish(String state, String error) {
            if (!writing.get()) throw new IllegalStateException("Terminal transition requires lease.write()");
            if (lost.get() || closed.get()) throw new LostLease();
            if (!java.util.Set.of("completed", "cancelled", "failed", "retry").contains(state))
                throw new IllegalArgumentException("Invalid terminal transition");
            if (jdbc.update("UPDATE " + queue.table + " SET status=?,error_message=?,owner_token=NULL,"
                + "lease_until=NULL,locked_at=NULL,locked_by=NULL WHERE id=? AND owner_token=? AND lease_fence=?"
                + " AND lease_until>UTC_TIMESTAMP(6) AND status IN ('processing','cancelling')", state, error, id, owner, fence) != 1) throw new LostLease();
        }

        @Override public void close() {
            if (closed.compareAndSet(false, true)) {
                if (heartbeat != null) heartbeat.cancel(false);
                slots.release();
            }
        }
    }

    @PreDestroy public void close() { heartbeats.shutdownNow(); }
}
