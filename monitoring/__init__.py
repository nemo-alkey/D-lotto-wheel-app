"""Lotto Wheel App — monitoring and observability package.

Modules:
  health        — system health checks backing GET /health
  metrics       — Prometheus metrics backing GET /metrics
  alerting      — threshold evaluation + email/webhook dispatch
  logging_setup — structured JSON logging to data/logs/app.log

Config:
  prometheus.yml — scrape config for the docker-compose monitoring stack
  alerts.yml     — Prometheus alerting rules
"""
