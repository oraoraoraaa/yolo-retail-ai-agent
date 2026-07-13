# Automated Inventory & Smart Retail Agent

> [中文](./instruction_cn.md)

---

## 1. Project Objectives

The goal of this project is to build an autonomous retail Agent that uses computer vision technology to audit physical shelves in real time. By detecting products, gaps, and misplacements, this Agent eliminates the discrepancy between digital database records and the actual physical reality of the store.

### "Phantom Inventory"

Relying solely on sales data in traditional databases creates three primary blind spots:

* **Product Misplacement:** When customers leave a product on the wrong shelf, that item becomes invisible to other customers who actually want to buy it. The database still lists it as in-stock, but its actual sales drop to zero. The Agent identifies misplaced items and alerts staff to return them to their proper location.
* **Theft and Shrinkage:** Stolen or damaged items bypass the checkout scanner. Because these items remain "in-stock" in the database, automated reorder triggers are never tripped. The Agent detects that the physical shelf is empty, flags the anomaly, and sends a reorder notification.
* **Restocking Delays:** A database might show ample inventory, but the items are actually sitting forgotten in the backroom. The project's frontend can display the empty shelf state; when the Agent detects a gap, it cross-references backroom inventory data and alerts employees to move stock to the sales floor.

---

## 2. AI Agent Workflow

The system operates in a continuous, three-step cycle:

1. **Perception:** An object detection model processes video streams or photos of the shelves to localize products and empty spaces.
2. **Reasoning:** The AI Agent cross-references the visual detections against a real-time database or a digital store planogram.
3. **Action:** The Agent automatically executes appropriate operations, such as generating supplier purchase orders, dispatching notifications to store staff, or dynamically adjusting prices based on supply and demand.

---

## 3. Implementation

Due to the vast variety of products, this project inherently faces an extreme many-class classification problem. Training a model to directly distinguish between thousands of specific brands is highly challenging. Instead, this project adopts an efficient, coordinate-based "Gap Detection" approach.

### I. Dataset: RP2K

The project utilizes RP2K, a high-quality, clean, open-source retail dataset, applying transfer learning to avoid training a model entirely from scratch.

### II. Training a Binary "Gap Detection" Model

Instead of forcing the model to differentiate between hundreds of different brands (e.g., Coke vs. Pepsi), a lightweight object detection architecture like **YOLOv8** is trained to detect only two states:

1. `Product`
2. `Empty Shelf Space (Gap)`

### III. Establishing a Digital Planogram

A digital map of the store layout (the planogram) is created. This database maps specific physical shelf coordinates directly to the products designated for those slots.

* *Example:* `Coordinates (X: 12, Y: 45) = Brand Y Soda`

### IV. Coordinate-Based Logical Reasoning

AI Agent code is implemented to merge the visual model's outputs with the planogram coordinates to infer missing inventory:

1. The computer vision model detects an `Empty Shelf Space (Gap)` at a specific coordinate.
2. The AI Agent queries that exact coordinate within the digital planogram.
3. The Agent deduces: *"There is a gap at coordinates (X:12, Y:45). According to the planogram, Brand Y Soda belongs here. Therefore, Brand Y Soda is currently out of stock."*
