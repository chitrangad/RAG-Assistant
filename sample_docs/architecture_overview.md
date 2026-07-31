# Payment Gateway Migration — Architecture Overview

**Project:** Payment Gateway Migration
**Version:** 2.1.0
**Last updated:** 2024-01-15

## Summary

This document describes the architecture for migrating from the legacy payment processor
to the new Stripe-based gateway. See also REQ-101, REQ-205, and REQ-310 for detailed
functional requirements.

## Architecture Decisions

### ADR-001: Use Stripe as primary payment processor

The team evaluated Stripe, Adyen, and Braintree. Stripe was selected because of its
extensive API documentation, webhook reliability, and strong developer ecosystem.

Implements: REQ-101
Related change requests: CR-0891, CR-1234

### ADR-002: Event-driven refund processing

Refunds will be processed asynchronously through a message queue (RabbitMQ) to avoid
blocking the main API thread during peak traffic.

Implements: REQ-205

## Component Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Checkout   │────▶│ Payment Svc  │────▶│   Stripe    │
│     UI       │     │              │     │    API      │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────▼───────┐
                    │  RabbitMQ    │
                    │  (refunds)   │
                    └──────────────┘
```

## Repositories

- Backend: https://github.com/org/payment-service
- Frontend: https://github.com/org/checkout-ui
- Infrastructure: https://dev.azure.com/org/project/_git/infra

## Security Considerations

All card data is tokenized via Stripe Elements. No raw PAN data touches our servers.
PCI-DSS compliance is maintained at SAQ-A level.
