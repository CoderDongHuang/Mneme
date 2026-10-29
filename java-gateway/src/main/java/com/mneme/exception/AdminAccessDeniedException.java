package com.mneme.exception;

/** A valid login can lack administration privileges without losing its session. */
public class AdminAccessDeniedException extends SecurityException {
    public AdminAccessDeniedException(String message) { super(message); }
}
