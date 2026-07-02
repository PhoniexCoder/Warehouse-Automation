from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_warehouses: int
    total_cameras: int
    total_boxes: int
    total_inventory_items: int
    total_count_logs: int
    total_alerts: int
    entry_count: int
    exit_count: int
