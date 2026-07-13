# 开发规范

本文档面向为本仓库做贡献的开发者。

请认真通读本指南，因为遵循这些规则有助于让协作过程更干净、更安全，也更便于审查。

## 前提：学习 Git 基础

每位贡献者都有责任掌握必要的 Git 和 GitHub 使用方式。

最低要求的知识包括：

- 克隆和拉取仓库
- 创建分支和切换分支
- 暂存并提交更改
- 推送分支并创建拉取请求
- 解决合并冲突
- 阅读提交历史

> **给新开发者的额外提醒**
>
> - 保持拉取请求尽量小，并且只聚焦一个目标。
> - 编写清晰的 PR 描述：改了什么、为什么改、如何测试。
> - 在推送之前先在本地测试你的更改。
> - 绝不要提交密钥、token 或私钥。
> - 除非明确要求，否则避免提交生成的构建产物。
> - 当行为、配置或命令发生变化时，更新文档。
> - 如果你被阻塞了，尽早请求审查。
> - 定期 rebase 或合并 `main`，以降低冲突风险。
> - 除非你的团队已批准，不要重写共享分支历史。
> - 认真阅读 CI 失败日志，并在请求审查前修复失败项。

### 快速入门工作流

#### Visual Studio Code（推荐）

1. 在合适的位置克隆此仓库：

 ```sh
 git clone https://github.com/oraoraoraaa/picking-up-optimization.git
 ```

1. 使用 Visual Studio Code 打开仓库文件夹。

2. 使用图形界面管理 Git 控件。

#### 命令行 Git（不推荐新手使用）

1. `git checkout main`
2. `git pull origin main`
3. `git checkout -b feat/your-change`
4. 进行修改
5. `git add .`
6. `git commit -m "feat: describe your change"`
7. `git push -u origin feat/your-change`
8. 打开 PR 并请求审查

---

## 1. 提交信息规范

所有提交都必须遵循 Conventional Commits 规范：
`https://www.conventionalcommits.org/en/v1.0.0/`

不符合该规范的拉取请求在审查时很可能会被直接拒绝。

在提交之前，请先学习并正确使用这种格式。

示例：

- `feat: add traffic congestion scoring`
- `fix: handle empty route result from amap client`
- `docs: update setup instructions`
- `refactor: simplify pickup candidate filtering`
- `test: add unit tests for route estimator`

## 2. 主分支保护

`main` 受 GitHub rulesets 保护。不要直接推送到 `main`，也不要尝试直接推送到 `main`。

始终按以下步骤操作：

1. 拉取最新的 `main`。
2. 创建并切换到功能分支。
3. 在功能分支上提交。
4. 将分支推送到远程。
5. 向 `main` 打开拉取请求。

分支命名示例：

- `feat/optimize-pickup-point`
- `fix/amap-timeout-handling`
- `docs/contributing-guide`

## 3. 遵循文档

每个文件夹及其子文件夹都配有对应的 `README.md`，其中包含详细的说明文档。

在进行任何贡献之前，请认真阅读这些文档。

同样地，如果你的改动不符合文档中给出的规范，在审查时也会被直接拒绝。

## 就这些，祝你编码愉快
