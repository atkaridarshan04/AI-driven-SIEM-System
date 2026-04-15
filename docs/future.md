# Future Roadmap — V3.0 and Beyond

This document covers planned capabilities beyond the V2.0 improvements described in
[improvements.md](./improvements.md). These are forward-looking — do not start until
V2.0 is validated in production.

---

## V3.0 — Cross-System Attack Chain Reconstruction

### Goal

Detect attacks that span multiple systems and reconstruct the full attack chain.
This is the capability that separates a SIEM from a log anomaly detector — it is what
a Tier 2 SOC analyst does manually today.

### Why V2.0 enables this

By V2.0 the foundation is in place:
- `SemanticLogTransformer` embeds heterogeneous log text into a shared vector space.
  Adding a new log source requires only: write a parser → normalize → embed.
  No model retraining needed.
- Kafka pipeline accepts any log source.
- Cross-source time-window joining is already built for LANL multi-source fusion.

### Example attack chain

```
t=0    Linux SSH brute force (T1110)           ← auth anomaly
t=43   Successful SSH logon from same IP       ← baseline deviation
t=51   Unusual process spawned on Linux host   ← proc anomaly
t=120  Lateral move to Windows host (T1021)    ← cross-system correlation
t=305  AWS CloudTrail: IAM key created (T1136) ← cloud pivot
```

V2.0 detects each anomaly independently. V3.0 links them into a single incident.

### New log sources (V3.0 ingestion targets)

| Source | Format | Attack signal |
|--------|--------|--------------|
| Linux syslog + auditd | Syslog (already partial via BRAIN) | SSH brute force, privilege escalation |
| AWS CloudTrail | JSON, one API call per line | IAM abuse, S3 exfiltration, unusual region |
| Azure AD sign-in logs | JSON | Password spray, impossible travel, MFA bypass |
| Palo Alto / Cisco firewall | Syslog CEF format | Port scans, blocked lateral movement, C2 |
| Nginx / Apache | Combined log format | Web attacks, credential stuffing |

### V3.0 architecture additions

**Incident correlator service**
- Sliding time-window graph: nodes = anomalies, edges = shared entity (user/host/IP) within window
- Connected subgraphs = incident candidates

**Tactic sequencer**
- Validates that the MITRE tactic sequence of a candidate incident is plausible
- Reconnaissance → Initial Access → Lateral Movement is valid; random ordering is noise

**Incident store**
- Elasticsearch index for incidents (grouped anomalies) separate from raw anomaly index

**Grafana incident timeline panel**
- Visualizes the attack chain as a timeline with MITRE tactic labels

**Case management**
- Acknowledge, escalate, close incidents via the Next.js console

### Evaluation datasets for V3.0

| Dataset | Covers |
|---------|--------|
| OTRF Security Datasets | Multi-stage attack simulations with cross-system logs |
| BRAWL / APT29 simulation (MITRE) | Full APT campaign logs across Windows + network |
| AWS CloudTrail anomaly dataset (Kaggle) | Cloud-specific attack patterns |

---

## V4.0 — Autonomous Response (SOAR Integration)

Stop detecting and alerting. Start acting.

When a confirmed attack is detected, automatically trigger a response: block an IP via
firewall API, isolate a host from the network, revoke a compromised credential, kill a
malicious process.

**The hard problem:** False-positive cost. A wrong block takes down a production server.
Requires very high confidence thresholds and a human-in-the-loop approval workflow before
any destructive action.

**Commercial equivalents:** Palo Alto XSOAR, Splunk SOAR, Microsoft Sentinel Playbooks.

**Key additions:**
- Response playbook engine: `if anomaly_type=lateral_movement AND confidence>0.95 → isolate host`
- Firewall API integration (Palo Alto, AWS Security Groups, Azure NSG)
- Approval queue in the dashboard for high-impact actions
- Rollback capability — undo a response action if confirmed false positive

---

## V5.0 — Threat Intelligence Fusion

Enrich every anomaly with external context.

Cross-reference detected anomalies against global threat intelligence: is this IP in a
known botnet? Is this domain on a threat feed? Is this file hash known malware?

**Commercial equivalents:** Recorded Future, ThreatConnect, MISP.

**Key additions:**
- MISP integration for community threat feeds
- VirusTotal API enrichment for file hashes and IPs
- Shodan enrichment for exposed infrastructure
- STIX/TAXII feed ingestion (industry standard threat intel format)
- Threat score overlay on Grafana anomaly panels

---

## V6.0 — Multi-Tenant SaaS SIEM

One deployment, multiple organizations, full data isolation.

Monitor multiple customer environments from a single platform with strict per-tenant
data isolation, separate model fine-tuning per tenant, and a billing/access control layer.

**Commercial equivalents:** Microsoft Sentinel, Sumo Logic, Devo.

**Why it's hard:** Per-tenant Elasticsearch indices, per-tenant model fine-tuning without
cross-contamination, RBAC at every layer, compliance requirements (SOC 2, GDPR).

---

## Research-Grade Extensions

These are open problems in the academic literature. Implementing any one of these is
a conference paper contribution.

### Online / Continual Learning

The V2.0 `SemanticLogTransformer` is static after training. Real enterprise environments
drift — new software gets deployed, user behavior changes, new normal patterns emerge.
A model that adapts to new normal behavior without full retraining (and without
catastrophic forgetting of old patterns) is an unsolved problem for log anomaly detection.

### Explainability

Current output: "this sequence is anomalous, confidence 0.87."

What SOC analysts actually need: "these 3 specific events in this sequence are anomalous
because they deviate from this user's historical pattern in these ways."

Attention visualization gets partway there but is not human-interpretable at scale.
Proper explainability for transformer-based anomaly detection on logs is an active
research gap.

### Adversarial Robustness

Attackers who know an ML-based SIEM is running can craft log entries designed to evade
detection — adversarial examples for log data. Analogous to adversarial images for vision
models but largely unsolved for the log domain.

### LLM-Based Alert Triage (Most Timely)

Feed anomaly context + correlated logs to an LLM, get back a natural language incident
report with recommended response steps, severity justification, and MITRE tactic explanation.

This is where the industry is moving: Microsoft Copilot for Security, Google SecOps Gemini,
Elastic AI Assistant are all doing this commercially. An open-source implementation on top
of this project's detection pipeline would be highly relevant.

**Rough implementation:**
1. Anomaly detected
2. Retrieve top-k correlated log sequences
3. Prompt an open-source LLM (Mistral, LLaMA) with context
4. Return structured incident report
5. Display in dashboard

---

## Progression Summary

| Version | Capability | Territory |
|---------|-----------|-----------|
| V1.5 (current) | Single-source Linux log anomaly detection | Student project |
| V2.0 | Multi-source enterprise fusion, semantic transformer model | Strong portfolio |
| V3.0 | Cross-system attack chain reconstruction | Exceptional portfolio / early research |
| V4.0 | Autonomous response (SOAR) | Research / startup |
| V5.0 | Threat intelligence fusion | Research / startup |
| V6.0 | Multi-tenant SaaS SIEM | Startup |
| Research | Online learning, explainability, adversarial robustness, LLM triage | Conference paper |

---

## Training Data Strategy (V2.0+)

### Primary: LANL Comprehensive Multi-Source Dataset

58 days, 1.648 billion events. Five correlated sources with unified de-identification
(`U1` is the same user across all files), enabling cross-source correlation.

| File | Schema | Security relevance |
|------|--------|-------------------|
| `auth.txt` | `time, src_user, dst_user, src_computer, dst_computer, auth_type, logon_type, success/fail` | Maps to Windows EventID 4624/4625 |
| `proc.txt` | `time, user, computer, process_name, start/end` | Maps to EventID 4688/4689 |
| `flows.txt` | `time, duration, src_computer, src_port, dst_computer, dst_port, protocol, bytes` | Network flow from core routers |
| `dns.txt` | `time, src_computer, resolved_computer` | DNS lookups |
| `redteam.txt` | `time, user, src_computer, dst_computer` | **Labeled ground truth** |

Train/test split: everything before the first redteam timestamp (`t=151648`) is clean
normal behavior. Everything after is evaluation. Zero leakage.

### MITRE ATT&CK coverage from LANL red team activity

| Technique | LANL signal | MITRE ID |
|-----------|-------------|----------|
| Credential brute force | Auth failure bursts in `auth.txt` | T1110 |
| Lateral movement | User authenticating to unusual hosts | T1021 |
| Privilege escalation | Auth type changes (Batch→Interactive) | T1078 |
| Process execution | Anomalous entries in `proc.txt` | T1059 |
| C2 / exfiltration | Unusual flows to rare destinations | T1071 |
| Reconnaissance | DNS lookups to unusual hosts | T1018 |

### Why not LogHub Windows CBS logs

The LogHub "Windows" 2k sample is CBS (Component Based Servicing) logs — Windows Update
internals. These have zero security relevance (no auth, no process execution, no network).
Training on them and testing on attack samples would compare completely different log
distributions.

### Scale considerations (1.6B+ events)

- Stream in chunks: `pd.read_csv(chunksize=100_000)` — never load full dataset into RAM
- Pre-compute embeddings offline, cache to HDF5 / memory-mapped numpy before training
- Join sources in time windows (e.g. 60s) before embedding to create multi-source context vectors
- Keep a held-out normal validation split (~5%) to tune the anomaly threshold percentile
