# Inventory Assistant — Mini Project Overview

## Problem

Small shops can run short on popular products if stock levels are not reviewed regularly. A spreadsheet may show current stock, but finding items below their reorder point and preparing a restock list takes manual work.

## Solution

The Inventory Assistant reads an inventory CSV, compares each product's current stock with its reorder level, highlights out-of-stock and low-stock items, and prepares suggested order quantities. A person reviews and approves the draft. The agent never places an order.

## Agent loop

1. **Observe:** Parse the uploaded CSV and identify item, stock, and reorder-level columns.
2. **Analyze:** Calculate low-stock, out-of-stock, healthy, and data-review counts.
3. **Plan:** Interpret a request such as “prepare a reorder list.” The optional AI planner is limited to analysis or preparing a draft.
4. **Confirm:** Show the impacted items and proposed quantity logic before editing the inventory.
5. **Act:** Add a suggested quantity and draft status for low-stock items using deterministic code.
6. **Review:** Show the updated data; support undo, restore-original, and CSV downloads.

## Reorder rule

For items at or below their reorder level:

`Suggested quantity = max(0, ceil(2 × reorder level − current stock))`

This is a simple demo policy. A real business should set target quantities using demand, supplier lead time, storage capacity, and budget.

## Architecture

- Browser interface: HTML, CSS, and JavaScript.
- Local API: Python standard-library HTTP server.
- Inventory logic: deterministic calculations and allowlisted local actions.
- Optional AI: OpenAI Responses API for interpreting requests; the model cannot execute code or submit orders.
- State: in-memory, single-user; no database or external inventory connection.

## Limitations and next steps

The app expects a CSV with item/product, stock, and reorder-level columns. It supports simple reorder planning and does not account for sales velocity, supplier lead times, pack sizes, budgets, or real purchase-order systems. Future versions could include demand forecasts, configurable targets, supplier comparisons, and an audited approval workflow.
