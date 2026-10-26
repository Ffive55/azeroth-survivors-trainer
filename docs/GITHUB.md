# GitHub 上传指南

## 名称与介绍

- 仓库名：`azeroth-survivors-trainer`
- 展示名：`Azeroth Survivors Trainer`
- 中文介绍：`艾泽拉斯幸存者 Windows 修改器：36 项对局／天赋功能，全职业收藏、图鉴与成就永久解锁。`
- 英文介绍：`Windows trainer for Azeroth Survivors: 36 run and talent controls, plus permanent collection, codex and achievement unlocks.`
- 可选 Topics：`azeroth-survivors`、`trainer`、`windows`、`python`、`tkinter`。

发布目标：[Ffive55/azeroth-survivors-trainer](https://github.com/Ffive55/azeroth-survivors-trainer)，公开仓库，默认分支 `main`。当前版本标签与 Release 为 `v3.3.1`。

本文件同时保留从新副本发布和维护的命令。公开可见不等于授予开源许可证；源码许可证仍由维护者决定。

## 本地范围

Git 根目录应是 `azeroth-survivors-trainer/`，不要在父级游戏目录初始化仓库。

应纳入版本控制：Python 源码、两个生成模板、测试、`requirements-dev.txt`、`AzerothTrainer.spec`、`README.md`、`AGENTS.md`、`docs/`、`.gitignore` 和 `.gitattributes`。

游戏 EXE／Data、个人存档和配置、旧版本、第三方研究仓库、`.venv/`、`backups/`、`sessions/`、`logs/`、测试运行目录和打包 EXE 已从整理范围排除，并由 `.gitignore` 继续保护。不要使用 `git add -f` 加入这些文件。

## 首次发布

首次发布使用未预先生成 README 的空仓库。已有远端时不要重复创建；以下步骤可供其他维护者或新副本参考。

本地已初始化时无需重复 `git init`；在全新副本中可用：

```powershell
git init --initial-branch=main
git status --short --untracked-files=all
```

先审阅文件，使用明确文件清单暂存，避免把新产生的本机数据一起加入：

```powershell
git add -- .gitignore .gitattributes README.md AGENTS.md `
  app.py app_v2.py cli.py engine.py winmem.py talents.py `
  runtime_features.py native_v3.py native_templates_v3.py `
  progression_catalog.py progression_live.py progression_model.py `
  progression_rpc.py progression_template.py progression_ui.py save_codec.py `
  research.py build_native_v3.py build_progression_native.py `
  test_trainer.py test_runtime_features.py test_native_v3.py `
  test_progression.py test_build_compatibility.py requirements-dev.txt AzerothTrainer.spec `
  docs/CHANGELOG.md docs/GITHUB.md docs/VALIDATION.md docs/source-baseline.json
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m "Prepare Azeroth Survivors Trainer v3.3.1"
```

确认当前 GitHub 登录账号和目标仓库后，使用实际地址（已有 `origin` 时先核对，不重复添加）：

```powershell
git remote add origin https://github.com/Ffive55/azeroth-survivors-trainer.git
git remote -v
git push -u origin main
```

后续版本使用普通推送，避免重写已发布的版本标签。首次发布附带源码包、Windows 发行包及 `SHA256SUMS.txt`。

## 可选的二进制发行包

按 README 的命令构建，之后将 `AzerothTrainer.exe` 与 `README.md` 放在同一个 `azeroth-survivors-trainer/` 文件夹中再压缩。用户解压后应使这个文件夹直接位于游戏目录内。

EXE 适合附加到 GitHub Release，源码分支不保存生成后的 EXE。发行包仅包含修改器及使用说明，不包含游戏程序、游戏资源或任何存档、日志和备份。

打包后“打开使用说明”读取 EXE 旁边的 `README.md`，因此发行时需要一并附带该文件。

本次整理另在被 Git 忽略的 `release/` 目录生成了源码 ZIP 和 Windows 发行 ZIP。源码 ZIP 采用上述上传文件清单；Windows ZIP 仅含 EXE 和 README，并保留正确的修改器文件夹层级。
