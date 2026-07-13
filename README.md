# yolo-retail-ai-agent

An AI Agent-driven inventory audit system combining YOLO object detection with LLM reasoning to detect phantom inventory, misplaced items, and automate stock replenishment.

## Instruction and Goal

See [instruction](doc/instruction.md).

## Develop

> Contents below are for developers only. Read them carefully before you do the actual work and make a git push.
>
> ![miku_for_developers](./doc/images/banner/miku_for_developers.png)

- [DEVELOPING RULES](./doc/developing_rules.md)

### Dataset

The dataset has been ignored to the git repository because of its giant size. Download the dataset and place it as the following file structure:

```text
dataset/
├── rp2k_dataset/
│   └── all/
│       ├── test/
│       └── train/
└── meta.csv
```
