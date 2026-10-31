package com.mneme.service;

import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.Set;

/** Watches persisted ownership even while the provider has sent no headers/tokens. */
@Component
public class ChatStreamMonitor {
    private final ChatSessionService sessions;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(4, task -> {
        Thread thread = new Thread(task, "chat-stream-watch"); thread.setDaemon(true); return thread;
    });
    private final Semaphore slots = new Semaphore(64);
    private final Set<Control> active = ConcurrentHashMap.newKeySet();
    // Socket writes must never occupy the scheduler which cancels silent upstreams.
    private final ExecutorService heartbeats = new ThreadPoolExecutor(0, 64, 30, TimeUnit.SECONDS,
        new SynchronousQueue<>(), task -> {
            Thread thread = new Thread(task, "chat-stream-heartbeat"); thread.setDaemon(true); return thread;
        });
    @Value("${mneme.chat-stream-timeout-ms:180000}") private long timeoutMillis = 180_000;

    public ChatStreamMonitor(ChatSessionService sessions) { this.sessions = sessions; }

    public synchronized Control watch(Long messageId, long generation, OutputStream output) {
        if (!slots.tryAcquire()) throw new IllegalStateException("STREAM_CAPACITY_EXCEEDED");
        Control control = new Control(messageId, generation, output);
        active.add(control);
        try { control.task = scheduler.scheduleWithFixedDelay(control::tick, 500, 500, TimeUnit.MILLISECONDS); }
        catch (RejectedExecutionException error) { control.close(); throw error; }
        return control;
    }

    @PreDestroy public synchronized void close() {
        scheduler.shutdownNow();
        for (Control control : active) { control.cancel("GATEWAY_SHUTDOWN"); control.close(); }
        heartbeats.shutdownNow();
    }

    public final class Control implements AutoCloseable {
        private final Long messageId;
        private final long generation;
        private final OutputStream output;
        private final long started = System.nanoTime();
        private final AtomicReference<String> reason = new AtomicReference<>();
        private final AtomicBoolean closed = new AtomicBoolean();
        private final AtomicBoolean heartbeatPending = new AtomicBoolean();
        private volatile Future<?> response;
        private volatile InputStream body;
        private ScheduledFuture<?> task;
        private int ticks;

        private Control(Long messageId, long generation, OutputStream output) {
            this.messageId = messageId; this.generation = generation; this.output = output;
        }

        public void response(Future<?> value) { response = value; if (reason.get() != null) value.cancel(true); }
        public void body(InputStream value) throws IOException {
            body = value;
            if (reason.get() != null) { value.close(); check(); }
        }
        public String reason() { return reason.get(); }
        public void check() throws IOException { if (reason.get() != null) throw new IOException(reason.get()); }

        public synchronized void frame(String type, String json) throws IOException {
            if (!closed.get()) check();
            try {
                output.write(("event: " + type + "\ndata: " + json + "\n\n").getBytes(StandardCharsets.UTF_8));
                output.flush();
            } catch (IOException error) { cancel("CLIENT_DISCONNECTED"); throw error; }
        }

        private void tick() {
            if (closed.get()) return;
            try {
                var state = sessions.answerState(messageId);
                if (state == null || state.generation() != generation || "failed".equals(state.status())) cancel("ANSWER_SUPERSEDED");
                else if ("stopped".equals(state.status())) cancel("USER_STOPPED");
                else if ("completed".equals(state.status())) return;
                else if (TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) >= timeoutMillis) cancel("MODEL_TIMEOUT");
                else if (++ticks % 2 == 0 && heartbeatPending.compareAndSet(false, true)) {
                    try { heartbeats.execute(() -> { try { heartbeat(); } finally { heartbeatPending.set(false); } }); }
                    catch (RejectedExecutionException error) { heartbeatPending.set(false); cancel("STREAM_CAPACITY_EXCEEDED"); }
                }
            } catch (Exception error) { cancel("STREAM_STATE_UNAVAILABLE"); }
        }

        private synchronized void heartbeat() {
            if (closed.get() || reason.get() != null) return;
            try { output.write(": heartbeat\n\n".getBytes(StandardCharsets.UTF_8)); output.flush(); }
            catch (IOException error) { cancel("CLIENT_DISCONNECTED"); }
        }

        private void cancel(String code) {
            if (closed.get() || !reason.compareAndSet(null, code)) return;
            Future<?> pending = response;
            if (pending != null) pending.cancel(true);
            InputStream upstream = body;
            if (upstream != null) try { upstream.close(); } catch (IOException ignored) { }
        }

        @Override public void close() {
            if (!closed.compareAndSet(false, true)) return;
            if (task != null) task.cancel(false);
            if (response != null && !response.isDone()) response.cancel(true);
            if (body != null) try { body.close(); } catch (IOException ignored) { }
            slots.release();
            active.remove(this);
        }
    }
}
