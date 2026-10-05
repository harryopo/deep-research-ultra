# .zcode/skills 与 .agents/skills 是同一存储（junction）

**生效**: 2026-10-04
**记录**: 2026-10-04
**置信度**: [F]（os.path.realpath 实测）
**Related**: git-gate-explicit-staging

## 事实

`C:\Users\Administrator\.zcode\skills` 是指向 `C:\Users\Administrator\.agents\skills`
的 junction（`os.path.realpath` 实测：`.zcode\skills\deep-research-ultra` 解析到
`.agents\skills\deep-research-ultra`）。

后果：
- 所谓"双安装位"是**同一份存储的两个路径视图**；`git -C ~/.agents fetch ~/.zcode/...`
  是同库自拉取的空操作；
- pytest 从 `.zcode` 工作区跑时，`import ledger` 等模块经 realpath 解析仍落在同一
  份文件——不存在"改了 dev 忘了同步安装位"这类问题，也没有这类同步工作。

## How to apply

- 只管一个 git 仓库（分支 `plan-a/plugin-shell`，远端
  `git@github.com:harryopo/deep-research-ultra`）；
- 排查"两处不一致"类问题前先意识到只有一处存储，别造同步脚本。
