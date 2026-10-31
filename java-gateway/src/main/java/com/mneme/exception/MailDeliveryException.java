package com.mneme.exception;

/** Deliberately carries no SMTP cause: mail exceptions may contain recipients and message bodies. */
public class MailDeliveryException extends RuntimeException {
    public MailDeliveryException(String message) { super(message); }
}
