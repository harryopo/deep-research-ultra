# 取证 U2：插件 `mcp.json` 里的命令路径到底怎么写

- 任务：计划 A / Task 1（`task-1-brief.md`）
- 取证时间：2026-09-20
- 取证方式：只读扫描本机已安装的 **26 个 marketplace 插件目录 + 1 个第一方 bundler 插件（`qoder-context`，内含 3 个历史版本目录）**，以及宿主运行日志 `C:\Users\Administrator\.qoder\logs\runs\`。**未做任何写操作**，未修改任何插件。
- 结论行：见文末 `DECISION:`（Task 4 只需读那一行 + 「交给 Task 4 的硬性写法」一节）

---

## 证据

以下每一段都是**我真实跑过的命令 + 原样贴回的 stdout**。命令本身也贴出来了，便于复验。

### E1 — brief Step 1 第一条（marketplace 插件 mcp 清单）

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
grep -rn --include="mcp.json" --include=".mcp.json" -e '"command"' -e 'PLUGIN' -e '\${' . | head -40
```

Output（原样）:

```
./ard-kit/0.19.6/bench/portable/corpus/.mcp.json:4:      "command": "weather-mcp",
./ard-kit/0.19.6/bench/portable/corpus/.mcp.json:10:      "command": "units-mcp",
./ard-kit/0.19.6/bench/portable/corpus/.mcp.json:16:      "command": "calendar-mcp",
./chrome-devtools-mcp/1.9.0/.mcp.json:4:      "command": "npx",
./chrome-devtools-mcp/1.9.0/mcp.json:5:      "command": "npx",
./chrome-devtools-mcp/1.9.0/mcp.json:8:        "${PLUGIN_DATA}",
./playwright/1.0.0/mcp.json:4:      "command": "npx",
./Presentations/0.1.1/.mcp.json:4:      "command": "${QODER_NODE_RUNTIME}",
./Presentations/0.1.1/.mcp.json:6:        "${QODER_PLUGIN_ROOT}/runtime/server.cjs"
./project-explorer/1.0.5/mcp.json:4:      "command": "npx",
```

### E2 — brief Step 1 第二条（hooks.json，作对照）

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
grep -rn --include="hooks.json" -e '"command"' . | head -20
```

Output（原样）:

```
./impeccable/4.3.1/.codex/hooks.json:8:            "type": "command",
./impeccable/4.3.1/.codex/hooks.json:9:            "command": "[ ! -f \".codex/skills/impeccable/scripts/impeccable\" ] || \".codex/skills/impeccable/scripts/impeccable\" hook",
./impeccable/4.3.1/.codex/hooks.json:21:            "type": "command",
./impeccable/4.3.1/.codex/hooks.json:22:            "command": "[ ! -f \".codex/skills/impeccable/scripts/impeccable\" ] || \".codex/skills/impeccable/scripts/impeccable\" hook",
./impeccable/4.3.1/.cursor/hooks.json:6:        "command": "[ ! -f \".cursor/skills/impeccable/scripts/impeccable\" ] || \".cursor/skills/impeccable/scripts/impeccable\" hook-before-edit",
./impeccable/4.3.1/cursor-plugin/hooks/hooks.json:6:        "command": "[ ! -f \"${CURSOR_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" ] || \"${CURSOR_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" hook-before-edit",
./impeccable/4.3.1/plugin/hooks/hooks.json:8:            "type": "command",
./impeccable/4.3.1/plugin/hooks/hooks.json:9:            "command": "[ ! -f \"${QODER_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" ] || \"${QODER_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" hook",
./impeccable/4.3.1/plugin/hooks/hooks.json:20:            "type": "command",
./impeccable/4.3.1/plugin/hooks/hooks.json:21:            "command": "[ ! -f \"${QODER_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" ] || \"${QODER_PLUGIN_ROOT}/skills/impeccable/scripts/impeccable\" hook",
./quality-guardian/1.0.0/hooks/hooks.json:8:            "type": "command",
./quality-guardian/1.0.0/hooks/hooks.json:9:            "command": "node hooks/check-ui-anti-patterns.js"
./quality-guardian/1.0.0/hooks/hooks.json:19:            "type": "command",
./quality-guardian/1.0.0/hooks/hooks.json:20:            "command": "node hooks/post-task-reminder.js"
./superpowers/6.3.0/hooks/hooks.json:8:            "type": "command",
./superpowers/6.3.0/hooks/hooks.json:9:            "command": "\"${QODER_PLUGIN_ROOT}/hooks/run-hook.cmd\" session-start",
./superun-creation/0.8.5/hooks/hooks.json:7:            "type": "command",
./superun-creation/0.8.5/hooks/hooks.json:8:            "command": "sh \"${QODER_PLUGIN_ROOT}/scripts/prepare-cli.sh\" --hook",
./superun-creation/0.8.5/hooks/hooks.json:19:            "type": "command",
./superun-creation/0.8.5/hooks/hooks.json:20:            "command": "sh \"${QODER_PLUGIN_ROOT}/scripts/mode-gate.sh\"",
```

### E3 — 穷举：全部 mcp 类清单文件（两个 vendor 都扫）

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
find . -iname "*mcp*.json" -not -path "*/node_modules/*" | sort
cd "C:/Users/Administrator/.qoder/plugins/cache/qoderapp-bundler"
find . -iname "*mcp*.json" -not -path "*/node_modules/*" | sort
```

Output（原样）:

```
./Presentations/0.1.1/.mcp.json
./apollographql-skills/1.2.9/.mcp.json
./ard-kit/0.19.6/bench/portable/corpus/.mcp.ard.json
./ard-kit/0.19.6/bench/portable/corpus/.mcp.json
./chrome-devtools-mcp/1.9.0/.mcp.json
./chrome-devtools-mcp/1.9.0/mcp.json
./playwright/1.0.0/mcp.json
./postman/1.3.1/.mcp.json
./postman/1.3.1/mcp.json
./product-management/1.1.1/.mcp.json
./project-explorer/1.0.5/mcp.json
./vercel/0.49.1/.mcp.json
```

```
./qoder-context/1.0.36.52b05a7/mcp.json
./qoder-context/1.0.42.c363cdb/mcp.json
./qoder-context/1.0.51.fa026ec3/mcp.json
./qoder-context/mcp.json
```

marketplace 下 26 个插件目录（`ls -1d */ | wc -l` = 26），**只有上面这些**带 mcp 清单；其余插件不声明 MCP。

### E4 — 全量盘点：15 个清单里每个 server 的 type / command / args[0]

Run（逐字，脚本口径：`glob('**/mcp.json')` + `glob('**/.mcp.json')`，排除 node_modules，解析 JSON 后逐 server 打印）:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache" && python -c "
import json, io, os, glob
rows=[]
files=[]
for pat in ['**/mcp.json','**/.mcp.json']:
    files += glob.glob(pat, recursive=True)
files=sorted(set(f for f in files if 'node_modules' not in f))
for f in files:
    try:
        d=json.load(io.open(f, encoding='utf-8'))
    except Exception as e:
        rows.append((f,'PARSE-ERR '+str(e),'','',''));continue
    srv=d.get('mcpServers',{})
    if not srv: rows.append((f,'(no mcpServers)','','',''))
    for name,c in srv.items():
        args=c.get('args') or []
        rows.append((f,name,c.get('type','(default stdio)'),c.get('command','(none)'), (args[0] if args else '(none)')))
print('%-62s %-22s %-16s %-26s %s' % ('FILE','SERVER','TYPE','COMMAND','ARGS[0]'))
for r in rows:
    print('%-62s %-22s %-16s %-26s %s' % (r[0][:62], str(r[1])[:22], str(r[2])[:16], str(r[3])[:26], str(r[4])[:60]))
print()
print('total manifest files:', len(files))
"
```

Output（原样，列宽截断处保留原样）:

```
FILE                                                           SERVER                 TYPE             COMMAND                      ARGS[0]
qoder-marketplace\Presentations\0.1.1\.mcp.json                office                 (default stdio)  ${QODER_NODE_RUNTIME}        ${QODER_PLUGIN_ROOT}/runtime/server.cjs
qoder-marketplace\apollographql-skills\1.2.9\.mcp.json         graphos-tools          http             (none)                       (none)
qoder-marketplace\ard-kit\0.19.6\bench\portable\corpus\.mcp.js weather-lookup         (default stdio)  weather-mcp                  --stdio
qoder-marketplace\ard-kit\0.19.6\bench\portable\corpus\.mcp.js unit-converter         (default stdio)  units-mcp                    --stdio
qoder-marketplace\ard-kit\0.19.6\bench\portable\corpus\.mcp.js calendar-events        (default stdio)  calendar-mcp                 --stdio
qoder-marketplace\chrome-devtools-mcp\1.9.0\.mcp.json          chrome-devtools        (default stdio)  npx                          chrome-devtools-mcp@1.9.0
qoder-marketplace\chrome-devtools-mcp\1.9.0\mcp.json           chrome-devtools        stdio            npx                          --prefix
qoder-marketplace\playwright\1.0.0\mcp.json                    playwright             (default stdio)  npx                          -y
qoder-marketplace\postman\1.3.1\.mcp.json                      postman                http             (none)                       (none)
qoder-marketplace\postman\1.3.1\mcp.json                       postman                http             (none)                       (none)
qoder-marketplace\product-management\1.1.1\.mcp.json           notion                 http             (none)                       (none)
qoder-marketplace\product-management\1.1.1\.mcp.json           linear                 http             (none)                       (none)
qoder-marketplace\product-management\1.1.1\.mcp.json           figma                  http             (none)                       (none)
qoder-marketplace\project-explorer\1.0.5\mcp.json              project-explorer       (default stdio)  npx                          -y
qoder-marketplace\vercel\0.49.1\.mcp.json                      vercel                 http             (none)                       (none)
qoderapp-bundler\qoder-context\1.0.36.52b05a7\mcp.json         qoder-context          (default stdio)  ${QODER_NODE_RUNTIME}        ${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs
qoderapp-bundler\qoder-context\1.0.42.c363cdb\mcp.json         qoder-context          (default stdio)  ${QODER_NODE_RUNTIME}        ${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs
qoderapp-bundler\qoder-context\1.0.51.fa026ec3\mcp.json        qoder-context          (default stdio)  ${QODER_NODE_RUNTIME}        ${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs
qoderapp-bundler\qoder-context\mcp.json                        qoder-context          (default stdio)  ${QODER_NODE_RUNTIME}        ${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs

total manifest files: 15
```

分类计数（对上面这张表做的算术，不是新证据）：

| 类别 | server 条目 | 是否算路径证据 |
|---|---|---|
| `type: http` + URL，无本地文件（graphos-tools / postman×2 / notion / linear / figma / vercel） | 7 | **不算，两头都不证明**。按要求显式排除 |
| ard-kit `bench/portable/corpus/` 下的 fixture（不在 `.qoder-plugin/plugin.json` 里声明，是插件自带的评测数据集） | 3 | **不算**，它不是插件清单 |
| `npx <registry 包名>`（chrome-devtools 两变体 / playwright / project-explorer） | 4 | 只证明「裸 PATH 命令可用」，**不证明插件内相对路径可用** |
| 指向**插件目录内文件**的 stdio server（Presentations `office`、qoder-context） | 2 | **这才是本题证据。2 例，2 例全用 `${QODER_PLUGIN_ROOT}`，0 例用相对路径** |

### E5 — 变量名普查：这些清单里到底出现过哪些 `${...}`

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
grep -rhoE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' --include="mcp.json" --include=".mcp.json" --include="hooks.json" . | sort | uniq -c | sort -rn
cd "C:/Users/Administrator/.qoder/plugins/cache"   # 放宽到 *.json + *.md
grep -rhoE '\$\{(QODER|PLUGIN|CURSOR)[A-Z_]*\}' . --include="*.json" --include="*.md" | sort | uniq -c | sort -rn
```

Output（原样，第一条）:

```
     14 ${QODER_PLUGIN_ROOT}
      2 ${CURSOR_PLUGIN_ROOT}
      1 ${QODER_NODE_RUNTIME}
      1 ${PLUGIN_DATA}
```

Output（原样，第二条，含 `*.md`）:

```
     45 ${QODER_PLUGIN_ROOT}
      5 ${QODER_NODE_RUNTIME}
      3 ${PLUGIN_ROOT}
      2 ${CURSOR_PLUGIN_ROOT}
      1 ${PLUGIN_DATA}
```

`${PLUGIN_ROOT}`（不带 `QODER_`）那 3 处的**出处原文**，用于排除它：

```
./qoder-marketplace/ard-kit/0.19.6/README.md:295:must be a bare executable or `./`-relative: `${PLUGIN_ROOT}` expands in
./qoder-marketplace/impeccable/4.3.1/docs/CLI-CONTRACT.md:1068: ... OpenAI plugin bundle (`dist/openai/impeccable/hooks/hooks.json`) uses `${PLUGIN_ROOT}/skills/impeccable/scripts/hook.mjs`.
./qoder-marketplace/impeccable/4.3.1/docs/CLI-CONTRACT.md:1248:| Codex | ... | OpenAI plugin `hooks/hooks.json` (`${PLUGIN_ROOT}`) | ...
```

→ 三处全在 README/契约文档里，讲的是 **Hermes / OpenAI-Codex 宿主**，**没有一处出现在 Qoder 读的配置文件中**。

ard-kit README 同段原文（第三方对**别的宿主**的说法，仅作警示，不是 Qoder 证据）:

```
Mounted as a plugin (Hermes reads `mcp.json` from the plugin root), `command`
must be a bare executable or `./`-relative: `${PLUGIN_ROOT}` expands in
`args`/`cwd`/`env`, never in `command`. The form that resolves from the plugin
root is `./bin/ard-mcp`.
```

### E6 — 两条「插件内文件」用例的配置原文

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"; cat Presentations/0.1.1/.mcp.json
cd "C:/Users/Administrator/.qoder/plugins/cache/qoderapp-bundler";  cat qoder-context/1.0.51.fa026ec3/mcp.json
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace/chrome-devtools-mcp/1.9.0"; cat .mcp.json mcp.json
```

Output（原样，`####` 是我加的分割标记）:

```
#### Presentations/0.1.1/.mcp.json
{
  "mcpServers": {
    "office": {
      "command": "${QODER_NODE_RUNTIME}",
      "args": [
        "${QODER_PLUGIN_ROOT}/runtime/server.cjs"
      ],
      "timeout": 120000
    }
  }
}

#### qoderapp-bundler/qoder-context/1.0.51.fa026ec3/mcp.json
{
  "mcpServers": {
    "qoder-context": {
      "command": "${QODER_NODE_RUNTIME}",
      "args": [
        "${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs",
        "mcp-bridge"
      ],
      "env_vars": [
        "QODER_HOME",
        "QODER_ENV",
        "QODER_BIG_MODEL_ENDPOINT",
        "QODER_OPENAPI_ENDPOINT"
      ],
      "env": {
        "QODER_PRODUCT_ID": "qoder",
        "QODER_SEARCH_PRODUCT_FORM": "qoder",
        "QODER_MTREE_NATIVE": "${QODER_PLUGIN_ROOT}/runtime/native/mtree/index.cjs",
        "QODER_SEARCH_RIPGREP_PATH": "${QODER_PLUGIN_ROOT}/bin/rg.exe",
        "QODER_SEARCH_BUILD_ID": "1.0.51.fa026ec3-win32-x64"
      },
      "qoderAuthState": true,
      "startup": "application",
      "timeout": 600000,
      "alwaysAllow": [
        "SearchWorkspace",
        "SearchKnowledge"
      ],
      "toolOverrides": {
        "SearchWorkspace": {
          "exposedName": "SearchWorkspace",
          "alwaysLoad": true
        },
        "SearchKnowledge": {
          "exposedName": "SearchKnowledge",
          "alwaysLoad": true
        }
      }
    }
  }
}

#### chrome-devtools-mcp/1.9.0/.mcp.json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@1.9.0"
      ]
    }
  }
}

#### chrome-devtools-mcp/1.9.0/mcp.json
{
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "--prefix",
        "${PLUGIN_DATA}",
        "chrome-devtools-mcp@1.9.0"
      ]
    }
  }
}
```

关键点：第一方 `qoder-context` 在 **`args`、`env` 两处**都用了 `${QODER_PLUGIN_ROOT}`，且指向的是插件里的**真实可执行文件**（`bin/rg.exe`）。这是和「`server.py` 放在插件目录里」完全同构的场景。

`${QODER_PLUGIN_ROOT}` 展开后指向的文件真实存在（证明变量确实解析到插件根）：

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache/qoder-marketplace"
ls -la Presentations/0.1.1/runtime/server.cjs
ls -la quality-guardian/1.0.0/hooks/
ls -la superpowers/6.3.0/hooks/
```

```
-rw-r--r-- 1 Administrator 197121 1087789 Sep 19 23:16 Presentations/0.1.1/runtime/server.cjs

total 13
drwxr-xr-x 1 Administrator 197121    0 Sep 19 23:17 .
drwxr-xr-x 1 Administrator 197121    0 Sep 19 23:17 ..
-rwxr-xr-x 1 Administrator 197121 3719 Sep 19 23:17 check-ui-anti-patterns.js
-rw-r--r-- 1 Administrator 197121  479 Sep 19 23:17 hooks.json
-rwxr-xr-x 1 Administrator 197121 1986 Sep 19 23:17 post-task-reminder.js

total 19
drwxr-xr-x 1 Administrator 197121    0 Sep 18 14:04 .
drwxr-xr-x 1 Administrator 197121    0 Sep 18 14:04 ..
-rw-r--r-- 1 Administrator 197121  137 Sep 18 14:04 hooks-cursor.json
-rw-r--r-- 1 Administrator 197121  340 Sep 18 14:04 hooks.json
-rw-r--r-- 1 Administrator 197121 1460 Sep 18 14:04 run-hook.cmd
-rwxr-xr-x 1 Administrator 197121  201 Sep 18 14:04 session-start
-rwxr-xr-x 1 Administrator 197121  970 Sep 18 14:04 session-start.cjs
```

### E7 — 清单文件名与 plugin.json 声明（`mcp.json` 还是 `.mcp.json`？）

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins/cache"
grep -rn -e 'mcpServers' -e '"hooks"' --include="plugin.json" .
```

Output（原样，只贴 Qoder 侧 `.qoder-plugin/plugin.json` 命中行；其它宿主目录 `.claude-plugin` / `.cursor-plugin` / `.kimi-plugin` / `.github` 一并贴出以便区分）:

```
./qoder-marketplace/apollographql-skills/1.2.9/.qoder-plugin/plugin.json:3:  "mcpServers": "./.mcp.json",
./qoder-marketplace/chrome-devtools-mcp/1.9.0/.claude-plugin/plugin.json:5:  "mcpServers": {
./qoder-marketplace/chrome-devtools-mcp/1.9.0/.cursor-plugin/plugin.json:11:  "mcpServers": {
./qoder-marketplace/chrome-devtools-mcp/1.9.0/.github/plugin/plugin.json:5:  "mcpServers": {
./qoder-marketplace/chrome-devtools-mcp/1.9.0/.qoder-plugin/plugin.json:24:  "mcpServers": "./.mcp.json",
./qoder-marketplace/impeccable/4.3.1/cursor-plugin/.cursor-plugin/plugin.json:21:  "hooks": "./hooks/hooks.json"
./qoder-marketplace/impeccable/4.3.1/plugin/.grok-plugin/plugin.json:18:    "hooks"
./qoder-marketplace/playwright/1.0.0/.qoder-plugin/plugin.json:29:  "mcpServers": "./mcp.json"
./qoder-marketplace/postman/1.3.1/.qoder-plugin/plugin.json:95:  "mcpServers": "./mcp.json"
./qoder-marketplace/Presentations/0.1.1/.qoder-plugin/plugin.json:11:  "mcpServers": "./.mcp.json"
./qoder-marketplace/project-explorer/1.0.5/.qoder-plugin/plugin.json:26:  "mcpServers": "./mcp.json"
./qoder-marketplace/superpowers/6.3.0/.qoder-plugin/plugin.json:32:  "hooks": "./hooks/hooks.json"
./qoder-marketplace/superun-creation/0.8.5/.qoder-plugin/plugin.json:11:  "hooks": "./hooks/hooks.json",
./qoder-marketplace/vercel/0.49.1/.kimi-plugin/plugin.json:25:  "mcpServers": {
./qoder-marketplace/vercel/0.49.1/.qoder-plugin/plugin.json:49:  "hooks": "./.qoder-plugin/qoder-hooks.json",
./qoder-marketplace/vercel/0.49.1/.qoder-plugin/plugin.json:50:  "mcpServers": "./.mcp.json",
```

两个要点：

1. `plugin.json` **内部**的 `"./.mcp.json"` / `"./mcp.json"` 确实是**相对插件根**的——所以「相对插件根」这个语义在 Qoder 里存在，但它存在的层面是 **plugin.json 的清单指针**，不是 mcp.json 的 `command`/`args`。这两个是不同的解析器，不能拿前者替后者背书。
2. chrome-devtools 同时有 `.mcp.json` 和 `mcp.json`，而 plugin.json 只声明了 `./.mcp.json` → 带 `${PLUGIN_DATA}` 的那个 `mcp.json` **根本没被 Qoder 加载**（旁证见 E11）。所以「`${PLUGIN_DATA}` 在 args 里能用」这条本机证据其实**没被验证过**，不能当依据。

Presentations 的声明原文（作者写的是 `Qoder`，第一方）:

```json
{
  "name": "Presentations",
  "displayName": "Presentations",
  "version": "0.1.1",
  "author": {
    "name": "Qoder"
  },
  "skills": "./skills/",
  "mcpServers": "./.mcp.json"
}
```

### E8 — 运行时证据：用 `${QODER_PLUGIN_ROOT}` 的 mcp server **真的连上了**

Run:

```bash
cd "C:/Users/Administrator/.qoder/logs/runs"
grep -rn -iE "mcp.*(office|Presentations|server\.cjs)" 2026-09-19*/*.log 2026-09-2*/*.log | head -25
grep -rhoE "\[MCP\] Server '[^']*'[^\"]{0,80}" 2026-09-2*/*.log | sort -u
```

Output（原样，节选）:

```
79:2026-09-19T23:16:35.021+08:00 INFO  debug.message [MCP] Server 'plugin:Presentations:office' connected — no instructions provided.
113:2026-09-19T23:16:35.047+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__load_guide
114:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__begin_deck
115:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__read_context
116:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__set_plan
117:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__put_page
118:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__read_slide
119:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__put_image
120:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__apply_ops
121:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__execute_slide_script
122:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__check_deck
123:2026-09-19T23:16:35.048+08:00 INFO  debug.message [mcp-check-sync] checker installed for mcp__plugin_Presentations_office__save_document
```

（去重后的全量 `[MCP] Server ...` 连接行，证明插件 MCP 通道整体可用）:

```
[MCP] Server 'arxiv' connected — no instructions provided.
[MCP] Server 'context7' provided instructions (632 chars): 
[MCP] Server 'mysql' connected — no instructions provided.
[MCP] Server 'open-websearch' connected — no instructions provided.
[MCP] Server 'paper-search' connected — no instructions provided.
[MCP] Server 'plugin:Presentations:office' connected — no instructions pro...
[MCP] Server 'plugin:Presentations:office' connected — no instructions provided.
[MCP] Server 'plugin:apollographql-skills:graphos-tools' connected — no instructions provided.
[MCP] Server 'plugin:apollographql-skills:graphos-tools' provided instructions (1159 chars): 
[MCP] Server 'plugin:chrome-devtools-mcp:chrome-devtools' connected — no instructions provided.
[MCP] Server 'plugin:computer-use:computer-use' connected — no instructions provided.
[MCP] Server 'plugin:playwright:playwright' connected — no instructions provided.
[MCP] Server 'plugin:project-explorer:project-explorer' connected — no instructions provided.
[MCP] Server 'plugin:qoder-context:qoder-context' connected — no instructions provided.
[MCP] Server 'plugin:qoder-qmind:qoder-qmind' connected — no instructions provided.
[MCP] Server 'plugin:sites:sites' connected — no instructions provided.
[MCP] Server 'qca' connected — no instructions provided.
[MCP] Server 'sciverse' connected — no instructions provided.
```

→ `plugin:Presentations:office` 就是 `"${QODER_PLUGIN_ROOT}/runtime/server.cjs"` 那一条，stdio 子进程拉起成功、12 个工具全部注册。**`${QODER_PLUGIN_ROOT}` 在 mcp.json 里被宿主展开，这不是推断，是跑通了。** 第一方 `plugin:qoder-context:qoder-context` 同理。

### E9 — 反向运行时证据：`hooks.json` 里的**相对路径是坏的**（本任务最重要的意外发现）

题面「已知事实」说 quality-guardian 用 `"command": "node hooks/check-ui-anti-patterns.js"` 证明了相对路径。**它确实这么写了，但它跑失败了。** 宿主日志：

Run:

```bash
cd "C:/Users/Administrator/.qoder/logs/runs"
grep -rl 'hooks/post-task-reminder.js' 2026-09-2*/*.log | head -1
grep -n -A14 'Hook \[node hooks/post-task-reminder.js\] stderr' 2026-09-20T00-46-58-366+08-00-zmtrvx-p55772/qodercli.log | head -40
grep -rhoE '.{0,60}(Cannot find module.{0,90}hooks.(check-ui-anti-patterns|post-task-reminder)\.js).{0,20}' 2026-09-2*/*.log 2026-09-19*/*.log | sort -u | head -6
```

Output（原样）:

```
log: 2026-09-20T00-46-58-366+08-00-zmtrvx-p55772/qodercli.log
533:2026-09-20T00:47:47.200+08:00 WARN  debug.message Hook [node hooks/post-task-reminder.js] stderr:
534-node:internal/modules/cjs/loader:1568
535-  throw err;
536-  ^
537-
538-Error: Cannot find module 'D:\ai\agent学习\虚拟人智能体开发-refactor\hooks\post-task-reminder.js'
539-    at Module._resolveFilename (node:internal/modules/cjs/loader:1564:15)
540-    at wrapResolveFilename (node:internal/modules/cjs/loader:1118:27)
541-    at defaultResolveImplForCJSLoading (node:internal/modules/cjs/loader:1142:10)
542-    at resolveForCJSWithHooks (node:internal/modules/cjs/loader:1169:12)
543-    at Module._load (node:internal/modules/cjs/loader:1341:5)
544-    at wrapModuleLoad (node:internal/modules/cjs/loader:261:19)
545-    at Module.executeUserEntryPoint [as runMain] (node:internal/main/run_main_module:154:5)
546-    at node:internal/main/run_main_module:33:47 {
547-  code: 'MODULE_NOT_FOUND',
```

```
Error: Cannot find module 'D:\ai\FDE\hooks\post-task-reminder.js'
Error: Cannot find module 'D:\ai\agent学习\虚拟人智能体开发-refactor\hooks\check-ui-anti-patterns.js'
Error: Cannot find module 'D:\ai\agent学习\虚拟人智能体开发-refactor\hooks\post-task-reminder.js'
Error: Cannot find module 'D:\ai\claude code\skill开发\hooks\check-ui-anti-patterns.js'
Error: Cannot find module 'D:\ai\claude code\skill开发\hooks\post-task-reminder.js'
Error: Cannot find module 'D:\ai\latex\hooks\check-ui-anti-patterns.js'
```

→ 决定性：**相对路径不是解析到插件根，而是解析到当前工作区 cwd**。所以在 `~/.qoder/.../quality-guardian/1.0.0/` 里根本不存在的 `hooks/…` 被拿去工作区找，`MODULE_NOT_FOUND`。注意出错的工作区路径里同时含**空格**（`D:\ai\claude code\skill开发`）和**中文目录名**——正是本项目的主战场，这条要特别记下来。

### E10 — 正向运行时证据：用 `${QODER_PLUGIN_ROOT}` 的 hook 成功

Run:

```bash
cd "C:/Users/Administrator/.qoder/logs/runs"
grep -rhoE '.{0,80}plugin_id=.quality-guardian[^ ]*.{0,160}' 2026-09-2*/*.log | sort -u | head -6
grep -rhoE '.{0,120}(SessionStart:startup|run-hook\.cmd).{0,140}' 2026-09-20T14-08-17*/qodercli.log | sort -u | head -6
```

Output（原样，节选）:

```
 hook_index=2 total_hooks=2 display_text="node hooks/check-ui-anti-patterns.js" plugin_id="quality-guardian@qoder-marketplace" plugin_root="C:\\Users\\Administrator\\.qoder\\plugins\\cache\\qoder-marketplace\\quality-guardian\\1.0.0"
nt_name="PreToolUse" source="plugins" success=false duration_ms=192 exit_code=1 plugin_id="quality-guardian@qoder-marketplace" plugin_root="C:\\Users\\Administrator\\.qoder\\plugins\\cache\\qoder-marketplace\\quality-guardian\\1.0.0"
 INFO  [...] hook.started hook_name="SessionStart:startup" hook_event_name="SessionStart" source="plugins" hook_index=2 total_hooks=3 display_text="\"${QODER_PLUGIN_ROOT}/hooks/run-hook.cmd\" sessi
INFO  [...] hook.finished hook_name="SessionStart:startup" hook_event_name="SessionStart" source="plugins" success=true duration_ms=1088 exit_code=0 plugin_id="superpowers@qoder-marketplace" plugin
```

要点，三点都在同一份日志里：

- 宿主**另外**用 `plugin_root="C:\\Users\\...\\quality-guardian\\1.0.0"` 字段把插件根告诉了我们——也就是说插件根是**已知量**，但相对路径写法**并没有**用到它（E9 已证）。
- `display_text` 打印的是**命令模板原文**（`${QODER_PLUGIN_ROOT}` 原样显示），所以「日志里看到 `${QODER_PLUGIN_ROOT}` 字样」**不能**当作「宿主没替换」的证据。我在 8/30 老日志里看到的 `Hook execution failed ... (hook: ${QODER_PLUGIN_ROOT}/bin/qoder-context.cmd): Error: spawn EINVAL` 就**不是**变量没展开——查 8 月那版配置原文，它用的是 `"command": "cmd.exe"` + `args:["/d","/c","${QODER_PLUGIN_ROOT}/bin/qoder-context.cmd", ...]`，`spawn EINVAL` 是把 `.cmd` 直接当 executable 启的 Windows 侧问题。**这条我一度想写成「变量不支持」，查证后撤回，不成立。**
- `superpowers` 的 `"${QODER_PLUGIN_ROOT}/hooks/run-hook.cmd"` → `success=true duration_ms=1088 exit_code=0`。变量路径**通**。

对照小结（相对 vs 变量，全部为 hooks.json 侧的实测）：

| 插件 | 写法 | 实测 |
|---|---|---|
| quality-guardian 1.0.0 | `node hooks/x.js`（相对） | `success=false exit_code=1`，`MODULE_NOT_FOUND`，路径拼到工作区 |
| superpowers 6.3.0 | `"${QODER_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start` | `success=true exit_code=0` |
| superun-creation 0.8.5 | `sh "${QODER_PLUGIN_ROOT}/scripts/mode-gate.sh"` | 有 hook.started 记录，未见到失败告警（**不作为成功证据**，见「无证据」） |
| qoder-context 1.0.51（第一方） | `cmd.exe` + args `["/d","/c","${QODER_PLUGIN_ROOT}/bin/qoder-context.cmd", …]` | 配置在用；见 E9 的 spawn 教训 |

vercel 0.49.1 的 hooks 原文（**带引号**包住变量展开，这是路径含空格时的写法）：

```json
          {
            "type": "command",
            "command": "node \"${QODER_PLUGIN_ROOT}/hooks/session-start-seen-skills.mjs\""
          },
```

### E11 — `${PLUGIN_DATA}` 是数据目录，不是插件根（题面警告成立）

Run:

```bash
ls -la "C:/Users/Administrator/.qoder/plugins/data/" | head -20
ls -R "C:/Users/Administrator/.qoder/plugins/data/chrome-devtools-mcp-qoder-marketplace" | head -12
```

Output（原样）:

```
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:16 Presentations-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:18 apollographql-skills-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:17 chrome-devtools-mcp-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Aug 30 22:39 computer-use-inline
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:19 playwright-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:18 postman-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:18 product-management-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:18 project-explorer-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep  4 18:59 qoder-computer-control
drwxr-xr-x 1 Administrator 197121 0 Sep 18 14:16 qoder-context-qoderapp-bundler
drwxr-xr-x 1 Administrator 197121 0 Sep  4 18:59 qoder-knowledge-center
drwxr-xr-x 1 Administrator 197121 0 Aug 30 22:36 qoder-qmind-inline
drwxr-xr-x 1 Administrator 197121 0 Aug 30 22:36 qoder-search
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:22 quality-guardian-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Aug 30 22:44 security-scan
drwxr-xr-x 1 Administrator 197121 0 Sep 18 14:06 superpowers-qoder-marketplace
drwxr-xr-x 1 Administrator 197121 0 Sep 19 23:18 superun-creation-qoder-marketplace
```

```
C:/Users/Administrator/.qoder/plugins/data/chrome-devtools-mcp-qoder-marketplace:
```

（后者是**空目录**——印证 E7：`${PLUGIN_DATA}` 那条 `mcp.json` 从未被加载，否则 `npx --prefix` 会在里面装东西。）

→ `${PLUGIN_DATA}` = `plugins/data/<plugin>-<market>`，和插件根 `plugins/cache/<market>/<plugin>/<version>` **是两个不同位置**。绝不能拿它当插件根用。

### E12 — `installed_plugins_v2.json` 里的 installPath（绝对路径从哪来）

Run:

```bash
cd "C:/Users/Administrator/.qoder/plugins"
python -c "import json,io; d=json.load(io.open('installed_plugins_v2.json',encoding='utf-8')); print(json.dumps(d, ensure_ascii=False, indent=1)[:2500])"
```

Output（原样，节选）:

```json
{
 "version": 2,
 "plugins": {
  "Presentations@qoder-marketplace": [
   {
    "scope": "user",
    "installPath": "C:\\Users\\Administrator\\.qoder\\plugins\\cache\\qoder-marketplace\\Presentations\\0.1.1",
    "version": "0.1.1",
    "installedAt": "2026-09-19T15:16:29.962Z",
    "marketId": "Presentations",
    "displayName": "PPT"
   }
  ],
```

→ 宿主自己在注册表里维护 `installPath`，运行时以 `plugin_root` 传给解析器。**这说明「安装时把绝对路径烧进 mcp.json」既不必要也不可行**——插件目录带版本号（`...\Presentations\0.1.1`），升级即换路径，写死的绝对路径下次升级就失效。`absolute-only` 方案被这条否掉。

### 脱敏声明

扫描 `C:\Users\Administrator\.qoder` 时命中过一个含密钥的配置文件 `C:\Users\Administrator\.qoder\mcp-router.json`（顶层字段为 `schemaVersion / pid / baseUrl / apiKey / startedAt`）。我**只读取了字段名、未打印任何字段值**，且确认它不含插件 MCP 配置（探测 `mcpServers` / `QODER_PLUGIN_ROOT` / `server.cjs` 均为 `False`，文件 148 字节），故与本题无关。本文档**不含任何 API key / token**。E6 中 `qoder-context/mcp.json` 的 `env_vars` 列出的只是**变量名**（`QODER_HOME` 等），不含值，因此原样保留。E1–E12 中其余输出均无人工凭证。

---

## 结论

### 问题 1：有没有插件的 `command` 指向插件内部文件？用的是相对路径还是 `${...}` 变量？

**有，2 例；两例都用 `${QODER_PLUGIN_ROOT}`，0 例用相对路径。** 原文（E1 / E6 / E4）:

```
./Presentations/0.1.1/.mcp.json:6:        "${QODER_PLUGIN_ROOT}/runtime/server.cjs"
./qoderapp-bundler\qoder-context\1.0.51.fa026ec3\mcp.json         qoder-context  ${QODER_NODE_RUNTIME}  ${QODER_PLUGIN_ROOT}/runtime/qoder-search.bundle.mjs
```

补充：第一方 `qoder-context` 还在 **`env` 值**里用了它（`"QODER_SEARCH_RIPGREP_PATH": "${QODER_PLUGIN_ROOT}/bin/rg.exe"`，E6），所以 `args` 和 `env` 两处都会展开。`command` 字段本身宿主也支持变量（两例的 `command` 都是 `${QODER_NODE_RUNTIME}`）。

变量名的准确拼写是 **`QODER_PLUGIN_ROOT`**（带 `QODER_` 前缀），全文 45 次命中；不带前缀的 `${PLUGIN_ROOT}` 只出现在第三方 README 里讲 Hermes/Codex 宿主，**在 Qoder 读的任何配置里出现 0 次**（E5）。`${CURSOR_PLUGIN_ROOT}` 是 Cursor 的，不适用。

### 问题 2：`hooks.json` 已确证相对插件根 —— `mcp.json` 是否同样支持？

**题面这条前提本身是错的，需要纠正。** `hooks.json` 的相对路径**并没有**被确证可用——它只是被*写*成了那样：

1. `hooks.json` 的相对路径**实测失败**：E9 的 `Cannot find module 'D:\ai\claude code\skill开发\hooks\check-ui-anti-patterns.js'`。宿主把 `node hooks/x.js` 按**工作区 cwd** 解析，不按插件根。quality-guardian 那两个 hook 在本机每次 Stop/PreToolUse 都 `exit_code=1`（E10），只是非阻塞所以没人察觉。改用 `${QODER_PLUGIN_ROOT}` 的 superpowers 则是 `success=true exit_code=0`。
2. 换句话说，本机对「插件根相对路径」的**唯一**确证，是 `plugin.json` 里 `"mcpServers": "./.mcp.json"` 这类**清单指针**字段（E7）；`command`/`args` 层面**没有任何一例**这么做、也没有任何一例被证明这么做可行。
3. 对 `mcp.json` 而言：**「相对路径可用」= 无证据**（0 例，且同构场景的 hooks 侧是反例）；**「`${QODER_PLUGIN_ROOT}` 可用」= 有直接正向证据**，且不只是配置文件里写着，是 E8 的 `[MCP] Server 'plugin:Presentations:office' connected` + 12 个工具注册成功，也就是**同一份配置在本机同一宿主版本上真跑通了 stdio 子进程拉起**。

因此本题**不需要走「无证据 → 按 var 方案兜底」**那条退路：var 方案本身就是有直接证据的那一方。

### 问题 3：最终选定值

证据行号索引：`command`/`args` 用变量的配置原文 = E1 第 8–9 行、E4 表第 1 行与第 16–19 行、E6 前两块；运行时连通 = E8；相对路径反例 = E9 全段、E10 第 2 行；变量正例 = E10 第 4 行；变量名普查 = E5；数据目录非插件根 = E11；绝对路径不可行 = E12。

DECISION: ${QODER_PLUGIN_ROOT}

---

## 交给 Task 4 的硬性写法（照抄即可，不必回读上面的 grep）

```json
{
  "mcpServers": {
    "deep-research-ultra": {
      "type": "stdio",
      "command": "python",
      "args": ["${QODER_PLUGIN_ROOT}/mcp/server.py"],
      "timeout": 120000
    }
  }
}
```

- 插件根路径**只能**写成 `${QODER_PLUGIN_ROOT}/...`，且**放在 `args` 数组里**。禁止相对路径（`mcp/server.py`）、禁止 `${PLUGIN_ROOT}`、禁止 `${PLUGIN_DATA}`、禁止写死绝对路径。
- `args` 是数组，宿主不做 shell 分词，所以**不需要**像 `hooks.json` 那样给变量加转义引号（vercel 那种 `"node \"${...}\""` 是单字符串 `command` 的写法，别照搬进 args）。这正好解决路径含空格/中文的问题。
- Stop hook（`hooks/hooks.json`）同理：写成 `python "${QODER_PLUGIN_ROOT}/hooks/gate.py"`，**不要**写 `python hooks/gate.py`（后者就是 quality-guardian 那个 bug）。若要用 `.cmd`/`.bat`，照第一方 qoder-context 的 `cmd.exe` + args 形式，别把 `.cmd` 直接放进 `command`（E10 的 `spawn EINVAL`）。
- 清单文件名：`.mcp.json` 或 `mcp.json` **都可以**。自动发现已被两例证实：第一方 `qoder-context` 的 `plugin.json` **只有** `name/displayName/version/description` 四个字段、**没有** `mcpServers`，而它根目录的 `mcp.json` 连上了（E8 `plugin:qoder-context:qoder-context connected`）；`quality-guardian` 的 plugin.json 同样没有 `hooks` 字段，而 `hooks/hooks.json` 每次会话都被执行（E9 的失败记录本身就是它被加载的证据）。**但仍建议在 `.qoder-plugin/plugin.json` 里显式写 `"mcpServers": "./mcp.json"` 和 `"hooks": "./hooks/hooks.json"`**——marketplace 里能跑通的第三方插件全都显式声明了（E7），显式声明比依赖约定更安全。
- 上述「文件名/声明」结论只解决加载，**路径写法的结论只有一个**：插件内文件一律用 `${QODER_PLUGIN_ROOT}`。

## 无证据项（诚实标注 + 我选的兜底）

1. **`mcp.json` 里相对路径是否可用：无证据。** 0 例插件这么写；同构的 hooks 侧反而实测失败。兜底：用 `${QODER_PLUGIN_ROOT}`（有直接正向证据，见问题 2）。
2. **`mcp.json` 与 `.mcp.json` 同名共存时的优先级：无证据。** chrome-devtools 两份都在，但 plugin.json 只声明 `./.mcp.json`，且 `${PLUGIN_DATA}` 的 `mcp.json` 所在数据目录为空（E7/E11），无法区分「谁赢了」还是「只加载了被声明的那个」。兜底：Task 4 **只写一个文件**并在 plugin.json 里声明，绕开该问题。
3. **`superun-creation` 的变量路径 hook 是否真的成功：无证据。** 只见 `hook.started`，未见明确 `success=true`。兜底：不引用它作正向证据，改用 E10 里 superpowers 那条明确的 `success=true exit_code=0`。
4. **Python 解释符怎么给：无配置证据，但我实测了 PATH。** 本机 **0 个**插件用 python 起 MCP（E4 全量盘点）。宿主自带变量只有 Node：不存在 `${QODER_PYTHON_RUNTIME}` 之类（Run: `cd "C:/Users/Administrator/.qoder" && grep -rl -e 'QODER_PYTHON' -e 'PYTHON_RUNTIME' settings.json plugins/ mcp-router.json` → 输出为空；注意扫描范围是这些文件，不含 `logs/`）。实测本机会话 PATH：

   ```bash
   which python; python --version; which py; py --version
   ```

   ```
   /d/Miniconda3/python
   Python 3.13.5
   --- py launcher ---
   which: no py in (...)
   /usr/bin/bash: line 1: py: command not found
   ```

   → `python` 可用（Miniconda 3.13.5），**`py` 启动器不存在**。所以 `"command": "python"` 在本机成立，但**这是本机环境，不是宿主保证**：宿主 spawn MCP 子进程时的 PATH 是否等于我这个 shell 的 PATH，尚未实测。兜底：Task 5 第一步就验 `python` 能否被宿主启起来；若失败，改用 `${QODER_NODE_RUNTIME}` 包一层启动器（第一方路子），**不得**因为「配置照着模板写了」就宣布 Task 5 通过。
5. **`${QODER_PLUGIN_ROOT}` 是否在 `cwd` 字段展开：无证据**——本机所有清单都没有 `cwd` 字段（Run: `cd "C:/Users/Administrator/.qoder/plugins/cache" && grep -rn '"cwd"' --include="mcp.json" --include=".mcp.json" .` → 输出为空）。兜底：Task 4 不要依赖 `cwd`；`server.py` 内部用 `__file__` 自己定位。

## 第四选项：brief 没列，但证据里确实存在（记录以免 Task 4 误用）

上面第 4 条 `which py` 打出的完整 PATH 里，暴露了宿主会**把插件的 `bin/` 目录注入 PATH**：

```
PATH=...:/c/Users/Administrator/.qoder/plugins/cache/qoderapp-bundler/qoder-context/1.0.51.fa026ec3/bin:/c/Users/Administrator/.qoder/plugins/cache/qoder-marketplace/gstack/1.58.5/bin:/c/Users/Administrator/.qoder/plugins/cache/qoder-marketplace/ard-kit/0.19.6/bin:...
```

而 `ard-kit/0.19.6/bin/` 里确实是 `ard-catalogize  ard-mcp  ard-registry  ard-verify` 这类裸可执行文件。于是理论上存在第 4 种写法：**把启动器放进插件 `bin/`，`mcp.json` 里只写裸名**（像 `npx`、`weather-mcp` 那样靠 PATH 解析）。**不采用**，三条理由：(a) Qoder 侧 0 例插件 mcp.json 依赖此机制（E4）；(b) 插件 `bin/` 里没有任何 `plugin.json` 字段声明它（grep `"bin"` 命中 0，只有 `"commands"`），纯靠约定；(c) ard-kit 自己的 README 写明其 `bin/ard-*` 是 `#!/bin/sh` 脚本，「Windows cannot exec them」——本机正是 Windows。此路径仅在 `python` 起不来时作为 Plan B 记档，且需 Task 5 实测后才能采信。

## 尚未验证（留给 Task 5）

以上是「别人怎么写、宿主怎么对待别人的写法」的观察性证据，**不是**对本插件的实测。本插件自己的 `.mcp.json` 是否连得上，必须由 Task 5 的宿主侧实测出结论。
