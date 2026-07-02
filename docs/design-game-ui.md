# 游戏内 UI — 设计规格

> **上级文档：** [neo-design.md](neo-design.md) §4.3、§9  
> **关联文档：** [design-game-rules.md](design-game-rules.md)（阶段与数据）、[design-game-network.md](design-game-network.md)（state 字段与 SyncScheduler）  
> **参考实现：** [`ref/static/index.html`](../ref/static/index.html)（布局借鉴，双色 HP 废弃）

---

## 1. 设计目标

- **统一 N 人 UI**：不保留 ref 红蓝双栏特例；`N=2` 时排行榜仅 2 行
- 排行榜取代 RED/BLUE 区域，按 HP 排序
- 揭晓前：只见自己 pin + 已提交人数
- 观战、Debug 为同一页面的模式变体（URL 参数 + `state.debug`）

---

## 2. 技术栈建议

| 选项 | 决定 |
|------|------|
| 结构 | 左右分栏（延续 ref 信息密度） |
| 构建 | **推荐** Vite + vanilla ES modules |
| 备选 | 单文件 HTML（零构建，N 人列表与 sync 模块难维护） |

### 2.1 模块划分

| 文件 | 职责 |
|------|------|
| `game.html` | 壳、布局、URL 解析（`room`, `player_id`, `observe`） |
| `sync.js` | SyncScheduler（见 network 文档） |
| `map.js` | 地图点击、pin、SVG 连线 |
| `leaderboard.js` | 排行榜渲染、高亮自己 |
| `hud.js` | 回合、计时、倍率、主按钮 |
| `debug-panel.js` | 滚动日志、debug 控制钮 |
| `styles.css` | 布局与 pin 样式 |

---

## 3. 页面布局

```
+---------------------------+---------------------------+
|                           |  Round 3/16    [timer]   |
|                           |  Damage mult: 2.0x        |
|      Map (map.jpg)        +---------------------------+
|      + pins + SVG lines   |  LEADERBOARD              |
|                           |  (scroll if N>6)          |
|                           +---------------------------+
|                           |  [Ref Map]                |
|                           |  +---------------------+  |
|                           |  |   question image    |  |
|                           |  +---------------------+  |
|                           |  [ Submit ] / [ Next ]    |
+---------------------------+---------------------------+
|  [观战中 banner]  (observe only)                      |
|  [Debug log panel - collapsible]  (debug only)        |
+-------------------------------------------------------+
```

- 左栏约 50–55% 宽：地图保持可交互（阶段限制见 §5）
- 右栏：HUD → 排行榜 → 参考图按钮 → 题目图 → 主按钮

---

## 4. 地图与 Pin

### 4.1 坐标

点击地图 → 归一化 `(lat, lon)` → `POST place_guess`（[design-game-network.md](design-game-network.md)）

### 4.2 Pin 样式

| 对象 | 形状 | 颜色 |
|------|------|------|
| 玩家 guess | 圆形 | `config.pin_colors[slot % 10]` |
| 自己 | 圆形 + 可选描边加粗 | 同上；与排行榜行左侧色条一致 |
| 标准答案 | **菱形** | `#57EE55`（绿色，固定，不占 10 色序列） |

### 4.3 可见性

| 阶段 | 自己 pin | 他人 pin | 答案 pin | SVG 连线 |
|------|----------|----------|----------|----------|
| `guess` | 有则显示 | 隐藏 | 隐藏 | 无 |
| `reveal` | 显示 | 显示 | 显示 | guess→answer |
| `agree_next` | 同 reveal | 同 reveal | 显示 | 保留 |
| `game_over` | 同 reveal | 同 reveal | 显示 | 保留 |

连线颜色与对应玩家 pin 颜色一致；`vector-effect: non-scaling-stroke`（同 ref）。

### 4.4 已提交提示

Guess 阶段在排行榜上方或地图角标显示：

```text
已提交: {submitted_count} / {player_count}
```

不显示他人坐标。

---

## 5. 排行榜

### 5.1 数据源

`state.game_mode`（`hp` \| `points`）；`state.players`（含 `rank`、`hp`/`score`、`round_damage`/`round_score`）

### 5.2 排序与展示

- **hp 模式**：按 `hp` 降序；显示 HP 数值
- **points 模式**：按 `score` 降序；显示累计积分

### 5.3 阶段差异

| 阶段 | hp 模式 | points 模式 |
|------|---------|-------------|
| `guess` | 可选 `✓`；不显示回合结算 | 同左 |
| `reveal` / `agree_next` | `-{round_damage}` 红色 | `+{round_score}` 绿色 |
| `game_over` | `#rank` + `rounds_survived` | `#rank` |

每行：色条、`player_id`、主数值（HP 或 Score）、`(AFK)`、**自己行**背景 `#e8e8e8`。

### 5.4 N 较大时

- 排行榜区域 `max-height` + 纵向滚动
- 自己行滚动时 `position: sticky` 置顶（可选增强）

---

## 6. HUD 与主按钮

### 6.1 顶栏

| 元素 | 字段 |
|------|------|
| 回合 | `round` / `total_rounds` |
| 倒计时 | `phase_remaining_seconds`（本地每秒 -1，每次 state 刷新重同步） |
| 伤害/积分倍率 | `dmg_mult`（hp 显示 Damage Multiplier，points 显示 Score Multiplier） |

### 6.2 主按钮状态机

| `phase` | 文案 | enabled | 动作 |
|---------|------|---------|------|
| `guess` | Submit | 未 `answered` 且有 coord | `POST submit` |
| `guess` | Submit | 已 answered | disabled |
| `agree_next` | Next | 未 `ready_next` | `POST agree_next` |
| `agree_next` | Next | 已 ready | disabled |
| `reveal` | — | 隐藏或 disabled | — |
| `game_over` | — | — | — |

点击后立即 `disabled`，失败时恢复（同 ref）。

### 6.3 参考地图

沿用 ref：`ref_map.jpg` modal，Esc / 点击遮罩关闭。

---

## 7. 阶段态 UI 总表

| phase | 地图点击 | 主按钮 | 排行榜 | 题目图 |
|-------|----------|--------|--------|--------|
| guess | 可标点（未 submit） | Submit | submitted_count + HP | 显示 |
| reveal | 禁止 | 无 | HP + 本轮 damage | 显示 |
| agree_next | 禁止 | Next | HP + 本轮 damage | 显示 |
| game_over | 禁止 | 无 | 最终 rankings | 显示 |

---

## 8. 观战 UI

**进入：** `?observe=1`（大厅 Observe 跳转）

| 项目 | 行为 |
|------|------|
| 顶栏 | 黄色/灰色条：「观战中 — 只读」 |
| Submit / Next | 隐藏 |
| 地图 | 不响应点击 |
| 排行榜 / 题目 | 正常展示 |
| Pin / 揭晓 | 与玩家相同（全员可见在 reveal 后） |
| SSE / fetchState | 正常订阅 |

观战者 **不** 出现在 `players` 排行榜中（无自己行高亮）。

---

## 9. Debug 模式

**启用：** 服务端 `debug.enabled` 或 `--debug`；响应 `state.debug === true`

### 9.1 滚动日志窗

- 位置：页面底部，默认折叠，可拖拽高度
- 内容：最新 200 条；每条 `{ time, level, message }`
- 来源：客户端 SyncScheduler 事件 + 服务端 `debug_log` 数组（可选 API 字段）
- 自动滚动到底部（可暂停）

### 9.2 地图标定（题库用）

- 地图**可点击**标点
- **仅渲染自己的 pin**（即使 debug 也不显示他人）
- 点击后在日志窗或坐标旁显示：`lat, lon`（3 位小数）
- 仍调用 `place_guess` 或仅本地预览（实现二选一：**推荐** 走 API 以便服务端日志一致）

### 9.3 Debug 控制钮（仅 debug）

| 按钮 | API |
|------|-----|
| Prev round | `POST /api/prev_round` |
| Next round | `POST /api/next_round` |
| Force reveal | `GET /api/reveal` |

显示 guess 坐标文本（仅自己的），同 ref debug 区。

---

## 10. 终局弹层

| 元素 | 内容 |
|------|------|
| 标题 | `Game Over` |
| 主体 | `rankings` 列表：名次、player_id、HP、存活轮数 |
| 同 rank | 并列显示相同名次徽章 |
| 按钮 | 「回大厅」→ `/lobby` |

**不**使用 ref 单一 `winner` / `DISCONNECTED` 终局（断线不结束整场）；若全员 AFK 等极端情况仍按 rankings 展示。

---

## 11. 入口与 URL

| 参数 | 必填 | 说明 |
|------|------|------|
| `room` | 是 | |
| `player_id` | 是 | |
| `observe` | 否 | `1` 为观战 |

缺参 → 重定向 `/lobby`。

**初始化：**

1. 解析 URL
2. `SyncScheduler.connect(room, player_id)`
3. 首屏 `fetchState` → `updateUI`

---

## 12. 无障碍与 i18n

- 显示名：直接使用 `player_id` 字符串
- 地点名、题目 comment：保持中文（来自 CSV）
- 按钮与 phase 文案：v1 英文（与 ref 一致）或后续 i18n 表

---

## 13. 与 ref UI 对照

| ref | Neo |
|-----|-----|
| Blue/Red 两列 HP | 排行榜 N 行 |
| 双色 pin | 10 色 + 绿菱形答案 |
| `opponent_left` 弹窗 | 无；AFK 标签 |
| 单文件 728 行 | 多模块 + Vite |
| 无观战 | observe banner |
| console.log | debug 滚动窗 |

---

*参见 [design-game-network.md](design-game-network.md)、[design-lobby.md](design-lobby.md)*
