# Grafana Dashboards

## Accessing Grafana

URL: **http://localhost:3000**
Login: `admin` / `admin` (or value of `GRAFANA_PASSWORD` in `.env`)

---

## Datasources (auto-provisioned)

On first startup Grafana automatically configures datasources from
`infrastructure/grafana/provisioning/datasources/datasources.yml`.

| Name | Type | Index | Used for |
|---|---|---|---|
| Elasticsearch | Elasticsearch | `logs-*` | Raw logs, MITRE-tagged events |
| Elasticsearch-Anomalies | Elasticsearch | `anomalies-*` | ML-detected anomalies |
| Prometheus | Prometheus | — | System + pipeline metrics |

> The datasource YAML uses literal passwords (not `${ELASTIC_PASSWORD}`) because
> Grafana's provisioning does not resolve Docker env vars in `secureJsonData`.

### Verify datasource health
```bash
curl -s -u admin:admin \
  "http://localhost:3000/api/datasources/uid/P31C819B24CF3C3C7/health"
# Expected: {"status":"OK","message":"Elasticsearch data source is healthy."}
```

---

## SIEM Overview Dashboard

Pre-built dashboard at: **http://localhost:3000/d/siem-overview/siem-overview**

Loaded automatically from `infrastructure/grafana/dashboards/siem-overview.json`.

### Panels

| Panel | Type | Query | Shows |
|---|---|---|---|
| Total Log Events | Stat | `*` | Total indexed log count |
| MITRE Tagged Events | Stat | `mitre_tactic:*` | Events with a tactic assigned |
| Credential Access | Stat | `mitre_tactic:"Credential Access"` | Brute force / auth failures |
| Privilege Escalation | Stat | `mitre_tactic:"Privilege Escalation"` | sudo / escalation events |
| Log Events Over Time | Timeseries | `*` by `@timestamp` | All log volume over time |
| MITRE Tactics Breakdown | Pie chart | terms on `mitre_tactic.keyword` | Distribution of attack tactics |
| MITRE Events Over Time | Timeseries | grouped by tactic | Each tactic as a separate line |
| Recent Security Events | Logs panel | `mitre_tactic:*` | Expandable log entries with all fields |

### Inspecting a log entry

Click any row in the **Recent Security Events** panel to expand it:
```
@timestamp      when the event occurred on the host
ingest_time     when Logstash processed and indexed it
message         the raw syslog line
mitre_tactic    e.g. Credential Access
mitre_id        e.g. T1110
hostname        source host (siem-host)
```

---

## Explore (ad-hoc queries)

Go to **http://localhost:3000/explore** → select `Elasticsearch` datasource.

Useful queries:

```
# All MITRE-tagged events
mitre_tactic:*

# Specific tactic
mitre_tactic:"Credential Access"

# Search message content
message:"Failed password"

# Specific host
hostname:"siem-host"

# Combine filters
mitre_tactic:"Privilege Escalation" AND hostname:"siem-host"
```

Set time range to **Last 1 hour** or **Last 24 hours** to see recent events.

---

## Adding a New Dashboard

1. Build it in the Grafana UI
2. Export: **Dashboard menu → Share → Export → Save to file**
3. Place the JSON in `infrastructure/grafana/dashboards/`
4. Restart Grafana to load it:
```bash
docker compose restart grafana
```

---

## Alerting

Configure in **Alerting → Alert rules** in the Grafana UI.

### Recommended rules

**Brute force detected**
- Datasource: Elasticsearch
- Condition: count of `mitre_tactic:"Credential Access"` in last 5 min > 10
- Notification: Slack / email

**Critical anomaly detected**
- Datasource: Elasticsearch-Anomalies
- Condition: count of `severity:Critical` in last 5 min > 0
- Notification: immediate alert

**Kafka consumer lag too high**
- Datasource: Prometheus
- Condition: `kafka_consumergroup_lag{group="logstash-consumer"} > 1000`
- Notification: pipeline falling behind
