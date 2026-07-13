# yolo-retail-ai-agent

An AI Agent-driven inventory audit system combining YOLO object detection with LLM reasoning to detect phantom inventory, misplaced items, and automate stock replenishment.

## Instruction and Goal

See [instruction](doc/instruction.md).

## Develop

> Contents below are for developers only. Read them carefully before you do the actual work and make a git push.
>
> ![miku_for_developers](./doc/images/banner/miku_for_developers.png)

- [DEVELOPING RULES](./doc/developing_rules.md)

## Roboflow API Key

You would need the Roboflow API key to download the dataset using the scripts inside the `dataset` folder:

- [sku-1kimg-yolov8.py](dataset/sku-1kimg-yolov8.py)
- [sku-gap-700img-yolov8.py](dataset/sku-gap-700img-yolov8.py)

To find your API, navigate to the [Roboflow Docs: Find Your Roboflow API Key](https://docs.roboflow.com/developer/authentication/find-your-roboflow-api-key).
