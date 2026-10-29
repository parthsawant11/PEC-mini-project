# Dataset — Sample Inventory Files

This folder contains sample CSV and PDF files for use with the **Stockwise Inventory Assistant**.

## CSV Files

| File | Description | Items | Columns |
|------|-------------|-------|---------|
| `electronics_inventory.csv` | Electronics & peripherals store | 25 | sku, item, category, stock, reorder_level, unit_price |
| `grocery_store_inventory.csv` | Grocery / supermarket stock | 30 | product_id, product_name, department, quantity, minimum_stock, cost |
| `pharmacy_inventory.csv` | Pharmacy / medical supplies | 20 | item_id, item_name, category, on_hand, reorder_point, unit_cost |
| `bookstore_inventory.csv` | College bookstore items | 20 | code, name, type, stock, reorder_level, price |
| `warehouse_inventory.csv` | Hardware / construction warehouse | 20 | sku, product, group, current_stock, min_stock, unit_price |

> **Note:** Each CSV uses slightly different column names (e.g., `stock` vs `on_hand` vs `quantity`). The assistant auto-detects the correct columns.

## PDF Files

| File | Description |
|------|-------------|
| `inventory_management_guide.pdf` | Best practices for reorder points, safety stock, EOQ, and ABC analysis |
| `reorder_policy.pdf` | Company reorder policy with approval workflows and supplier rules |
| `stock_audit_report_Q3_2025.pdf` | Sample quarterly audit report with discrepancy findings |

## How to Use

1. Start the Inventory Assistant (`python server.py` or double-click the `.bat` file)
2. Open http://127.0.0.1:8003 in your browser
3. Upload any CSV from this folder using the **Choose CSV** button or drag-and-drop
4. Ask the agent questions like:
   - *"Which items are low on stock?"*
   - *"Prepare a reorder list"*
   - *"Which products are out of stock?"*
