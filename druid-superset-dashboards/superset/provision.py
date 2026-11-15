"""Create the Superset dashboard as code, through Superset's REST API.

Runs inside the Superset container (it has Python and requests):
    docker compose exec superset python /app/provision.py

Creates (or recreates) the Druid database connection, a dataset on clicks_hourly, five charts,
and the "Clickstream" dashboard. Safe to run again: it replaces what it created before.
"""

import json
import os
import sys

import requests

BASE = "http://localhost:8088"
DRUID_URI = "druid://router:8888/druid/v2/sql/"  # the router, inside the Docker network
DATABASE_NAME = "Druid"
TABLE = "clicks_hourly"
DASHBOARD_SLUG = "clickstream"

# Metrics are SQL expressions over the rolled-up table
VIEWS = {"expressionType": "SQL", "sqlExpression": "SUM(views)", "label": "Views"}
USERS = {"expressionType": "SQL", "sqlExpression": "APPROX_COUNT_DISTINCT_DS_HLL(users_sketch)", "label": "Unique users"}


def chart_specs(datasource):
    common = {"datasource": datasource, "time_range": "No filter", "adhoc_filters": []}
    return [
        # (name, viz_type, params, width out of 12, height)
        ("Page views", "big_number_total",
         {**common, "metric": VIEWS, "subheader": "October 2026", "y_axis_format": "SMART_NUMBER"}, 3, 40),
        ("Unique users", "big_number_total",
         {**common, "metric": USERS, "subheader": "HLL estimate from the rollup", "y_axis_format": "SMART_NUMBER"}, 3, 40),
        ("Views per day by device", "echarts_timeseries_line",
         {**common, "x_axis": "__time", "time_grain_sqla": "P1D", "metrics": [VIEWS], "groupby": ["device"],
          "row_limit": 10000, "show_legend": True, "rich_tooltip": True, "y_axis_format": "SMART_NUMBER"}, 6, 40),
        ("Top pages", "echarts_timeseries_bar",
         {**common, "x_axis": "page", "metrics": [VIEWS], "groupby": [], "row_limit": 10,
          "x_axis_sort": "Views", "x_axis_sort_asc": True, "orientation": "horizontal",  # ascending draws the largest bar on top
          "show_value": True, "y_axis_format": "SMART_NUMBER"}, 6, 50),
        ("Views by country", "pie",
         {**common, "groupby": ["country"], "metric": VIEWS, "row_limit": 10, "show_legend": True,
          "label_type": "key_percent", "number_format": "SMART_NUMBER"}, 6, 50),
    ]


class Superset:
    def __init__(self, username, password):
        self.s = requests.Session()
        token = self.s.post(f"{BASE}/api/v1/security/login",
                            json={"username": username, "password": password, "provider": "db", "refresh": True})
        token.raise_for_status()
        self.s.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        csrf = self.s.get(f"{BASE}/api/v1/security/csrf_token/")
        csrf.raise_for_status()
        self.s.headers.update({"X-CSRFToken": csrf.json()["result"], "Referer": BASE})

    def call(self, method, path, **kwargs):
        res = self.s.request(method, f"{BASE}/api/v1/{path}", **kwargs)
        if not res.ok:
            sys.exit(f"{method} {path} -> {res.status_code}: {res.text[:500]}")
        return res.json() if res.content else None

    def find(self, resource, column, value):
        query = f"(filters:!((col:{column},opr:eq,value:'{value}')),page_size:100)"
        return self.call("GET", f"{resource}/", params={"q": query})["result"]


def main():
    api = Superset("admin", os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"))

    # 1. Database connection (reused if it exists)
    found = api.find("database", "database_name", DATABASE_NAME)
    if found:
        database_id = found[0]["id"]
    else:
        database_id = api.call("POST", "database/", json={
            "database_name": DATABASE_NAME, "sqlalchemy_uri": DRUID_URI, "expose_in_sqllab": True})["id"]
    print(f"Database '{DATABASE_NAME}' -> {DRUID_URI} (id {database_id})")

    # 2. Remove what an earlier run created, then the dataset, so it picks up the current columns
    for dashboard in api.find("dashboard", "slug", DASHBOARD_SLUG):
        for chart in api.call("GET", f"dashboard/{dashboard['id']}/charts")["result"]:
            api.call("DELETE", f"chart/{chart['id']}")
        api.call("DELETE", f"dashboard/{dashboard['id']}")
    for dataset in api.find("dataset", "table_name", TABLE):
        api.call("DELETE", f"dataset/{dataset['id']}")
    dataset_id = api.call("POST", "dataset/", json={"database": database_id, "schema": "druid", "table_name": TABLE})["id"]
    api.call("PUT", f"dataset/{dataset_id}", json={"main_dttm_col": "__time"})
    print(f"Dataset druid.{TABLE} (id {dataset_id})")

    # 3. Dashboard, then the charts attached to it, then the layout
    dashboard_id = api.call("POST", "dashboard/", json={
        "dashboard_title": "Clickstream", "slug": DASHBOARD_SLUG, "published": True})["id"]

    layout = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": "Clickstream"}},
    }
    row, row_width = None, 12
    for n, (name, viz_type, params, width, height) in enumerate(chart_specs(f"{dataset_id}__table"), start=1):
        chart_id = api.call("POST", "chart/", json={
            "slice_name": name, "viz_type": viz_type, "datasource_id": dataset_id, "datasource_type": "table",
            "params": json.dumps({**params, "viz_type": viz_type}), "dashboards": [dashboard_id]})["id"]
        if row_width + width > 12:  # start a new row
            row, row_width = f"ROW-{n}", 0
            layout[row] = {"type": "ROW", "id": row, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                           "meta": {"background": "BACKGROUND_TRANSPARENT"}}
            layout["GRID_ID"]["children"].append(row)
        key = f"CHART-{n}"
        layout[key] = {"type": "CHART", "id": key, "children": [], "parents": ["ROOT_ID", "GRID_ID", row],
                       "meta": {"chartId": chart_id, "width": width, "height": height, "sliceName": name}}
        layout[row]["children"].append(key)
        row_width += width
        print(f"Chart '{name}' ({viz_type}, id {chart_id})")

    api.call("PUT", f"dashboard/{dashboard_id}", json={
        "position_json": json.dumps(layout),
        "json_metadata": json.dumps({"color_scheme": "supersetColors", "refresh_frequency": 0}),
    })
    print(f"Dashboard: {BASE}/superset/dashboard/{DASHBOARD_SLUG}/")


if __name__ == "__main__":
    main()
