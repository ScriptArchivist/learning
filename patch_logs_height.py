from pathlib import Path
import json
import yaml

path = Path("deploy/k8s/base/monitoring/grafana.yaml")

with path.open("r", encoding="utf-8") as f:
    docs = list(yaml.safe_load_all(f))

changed = 0

for doc in docs:
    if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
        continue

    name = (doc.get("metadata") or {}).get("name")
    data = doc.get("data") or {}

    if name == "grafana-dashboard-overview":
        key = "video-platform-k8s-overview.json"
        dashboard = json.loads(data[key])
        for panel in dashboard.get("panels", []):
            if panel.get("title") == "Platform Logs":
                panel["gridPos"] = {"h": 14, "w": 24, "x": 0, "y": 14}
                changed += 1
        data[key] = json.dumps(dashboard, ensure_ascii=False, indent=2)

    elif name == "grafana-dashboard-api":
        key = "video-platform-k8s-api.json"
        dashboard = json.loads(data[key])
        for panel in dashboard.get("panels", []):
            if panel.get("title") == "API Service Logs":
                panel["gridPos"] = {"h": 14, "w": 24, "x": 0, "y": 12}
                changed += 1
        data[key] = json.dumps(dashboard, ensure_ascii=False, indent=2)

    elif name == "grafana-dashboard-pipeline":
        key = "video-platform-k8s-pipeline.json"
        dashboard = json.loads(data[key])
        for panel in dashboard.get("panels", []):
            if panel.get("title") == "Pipeline Service Logs":
                panel["gridPos"] = {"h": 14, "w": 24, "x": 0, "y": 11}
                changed += 1
        data[key] = json.dumps(dashboard, ensure_ascii=False, indent=2)

with path.open("w", encoding="utf-8") as f:
    yaml.safe_dump_all(docs, f, allow_unicode=True, sort_keys=False)

print(f"Готово. Обновлено лог-панелей: {changed}")