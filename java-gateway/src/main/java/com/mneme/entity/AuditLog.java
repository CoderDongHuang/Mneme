package com.mneme.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

@TableName("audit_log")
public class AuditLog {
    @TableId(type = IdType.AUTO) private Long id;
    private Long userId;
    private String action;
    private String resource;
    private Integer statusCode;
    private String clientIp;
    private String traceId;
    private LocalDateTime createdAt;
    public Long getId() { return id; } public void setId(Long id) { this.id = id; }
    public Long getUserId() { return userId; } public void setUserId(Long userId) { this.userId = userId; }
    public String getAction() { return action; } public void setAction(String action) { this.action = action; }
    public String getResource() { return resource; } public void setResource(String resource) { this.resource = resource; }
    public Integer getStatusCode() { return statusCode; } public void setStatusCode(Integer statusCode) { this.statusCode = statusCode; }
    public String getClientIp() { return clientIp; } public void setClientIp(String clientIp) { this.clientIp = clientIp; }
    public String getTraceId() { return traceId; } public void setTraceId(String traceId) { this.traceId = traceId; }
    public LocalDateTime getCreatedAt() { return createdAt; } public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
