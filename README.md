# 英雄联盟违规标记查询工具 (LoLMatchQuery)

基于 **LCU（League Client Update）本地接口** 的英雄联盟辅助工具：自动监控对局阶段，在选人（BP）阶段展示双方玩家信息（英雄、位置、召唤师技能、Riot ID），支持违规记录查询与违规标记。

> ⚠️ **免责声明**
> - 本工具仅**读取**英雄联盟客户端的本地接口数据，**不操作游戏、不注入、不修改任何数据**，仅供学习交流使用。
> - 本项目与 Riot Games 及腾讯游戏无关，为第三方非官方工具。
> - 违规标记服务为作者自建后端（`https://ffmy.top/api`），使用即视为同意将举报数据提交至该服务。
> - 本项目基于 Apache License 2.0 开源：可自由使用、修改和分发（包括商业用途），请保留版权与许可声明。

## 功能特性

- 🎮 **对局阶段自动监控**：通过 LCU WebSocket 实时订阅客户端事件（选人 / 进游戏 / 对局中 / 结算）
- 👥 **选人阶段信息展示**：双方队伍玩家卡片（英雄头像、位置、召唤师技能、Riot ID、隐藏玩家识别），换英雄时就地更新头像与英雄名，避免卡片重建闪烁
- 📊 **对局中信息补齐**：进入游戏后自动拉取全体玩家信息（gameflow session + 战绩接口双数据源）
- 🏷️ **违规记录查询**：批量查询对局全员违规记录，红框标注违规玩家，点击查看违规明细
- 🚨 **违规标记**：选择违规类型（挂机 / 送人头 / 言语辱骂等 15 类）对玩家发起标记
- 🔍 **召唤师搜索**：通过完整 Riot ID（游戏名#TAG）搜索召唤师并查询其违规记录
- 🖼️ **英雄头像本地缓存**：Data Dragon CDN 下载头像并缓存至 `~/.lol_helper/icons/`，启动快、不重复下载
- 📱 **响应式界面**：窗口缩放自动切换队伍面板并排 / 堆叠布局
- 🤖 **AI Agent 接入（AgentQuay）**：把召唤师搜索、违规查询/标记等能力暴露为标准 MCP 工具，AI Agent（zcode / opencode / codex / Claude Desktop …）可直接调用，危险操作需用户确认

## 运行环境

- Windows 10/11
- Python 3.10+（仅源码运行需要；普通用户可直接使用打包好的 exe）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动（需先打开英雄联盟客户端并登录）
cd src
python -m lol_match_query
```

或安装为命令行应用：

```bash
pip install .
lol-match-query
```

启动后点击 **「启动工具」** 即可开始监控；进入选人阶段后自动显示双方队伍信息。

## 构建 EXE

```bash
# 方式一：一键脚本（自动安装依赖并打包）
scripts\build_exe.bat

# 方式二：手动执行
pip install -r requirements-dev.txt
pyinstaller --noconfirm LoLMatchQuery.spec
```

产物输出至 `dist/LoLMatchQuery.exe`（单文件、免安装、含图标）。

## 🤖 AI Agent 接入（AgentQuay）

应用启动后即自动接入 [AgentQuay](https://github.com/wenbaow/agentquay)：SDK 零安装地
拉起内嵌 Bridge，把本应用的方法暴露为标准 **MCP（Streamable HTTP）** 工具。任何支持 MCP
的 AI Agent（zcode / opencode / codex / Claude Desktop …）指向
`http://127.0.0.1:19846/mcp` 即可发现并调用：

| MCP 工具名（`lol-match-query_xxx`） | 作用 | 危险操作 |
|---|---|---|
| `search_summoner` | 通过完整 Riot ID（游戏名#TAG）搜索召唤师 | 否 |
| `query_violation_count` | 查询玩家违规记录总次数 | 否 |
| `get_violation_types` | 查询 15 类违规类型代码对照表 | 否 |
| `report_violation` | 举报玩家违规行为（需用户在确认弹窗中批准） | **是** |

- **零安装**：无需手动装 Bridge，SDK 首次连接自动拉起内嵌二进制并自动管理生命周期；
  也可手动装系统服务让多应用长期共享（见 AgentQuay 文档）。
- **极简接入**：直接在 `MatchMonitorService` / `ViolationClient` 的方法上加 `@agent_tool`
  注解，无需额外包装层，符合 AgentQuay「加注解即暴露」的设计理念。
- **SDK 依赖来源**：`agentquay-sdk` 已发布到 [PyPI](https://pypi.org/project/agentquay-sdk/)，
  `requirements.txt` / `pyproject.toml` 中直接按包名声明（`agentquay-sdk>=0.3.0`），
  开箱即可安装，无需访问 GitHub。

## 项目结构

```
lol-match-query/
├── src/lol_match_query/
│   ├── app.py               # 应用入口（PyInstaller 入口脚本 / 图标解析）
│   ├── __main__.py          # python -m lol_match_query 入口
│   ├── logging_utils.py     # 滚动日志配置（~/.lol_helper/logs/app.log）
│   ├── lcu/
│   │   ├── client.py        # LCUClient：传输层（进程发现 / HTTP / WebSocket / 原始事件）
│   │   ├── connection.py    # LCU 进程发现与 WebSocket 客户端构造
│   │   ├── events.py        # 传输层与 service 层共享的事件/URI 常量
│   │   ├── parser.py        # 对局数据解析纯函数（选人 / gameflow / 战绩）
│   │   └── regions.py       # 大区 / platformId 映射
│   ├── services/
│   │   ├── match_monitor.py # MatchMonitorService：阶段状态机 / 缓存 / 事件源
│   │   ├── violation.py     # ViolationClient：违规标记后端 API 客户端（@agent_tool 注解）
│   │   └── champions.py     # ChampionDataProvider：英雄头像/名称 CDN 缓存
│   ├── gui/
│   │   ├── app.py           # MatchQueryGUI 主窗口（渲染 / 监控控制）
│   │   ├── player_card.py   # PlayerCardMixin：玩家卡片组件逻辑
│   │   ├── dialogs.py       # DialogMixin：搜索 / 举报 / 违规详情对话框
│   │   ├── utils.py         # GUI 通用纯函数（安全数值转换、违规详情格式化）
│   │   └── agent_ui.py      # AgentUIMixin：AgentQuay 接入（确认弹窗 / 生命周期管理）
│   └── assets/app_icon.ico  # 应用图标（随包安装）
├── tests/                   # pytest 单元测试（解析 / 大区 / 工具函数 / 监控服务）
├── scripts/build_exe.bat    # 一键打包脚本
├── LoLMatchQuery.spec       # PyInstaller 打包配置
├── pyproject.toml           # 项目元数据、依赖与 pytest/ruff 配置
├── requirements.txt         # 运行时依赖
└── requirements-dev.txt     # 开发 / 测试 / 打包依赖
```

## 工作原理

GUI 与 Agent 均通过 `MatchMonitorService` 访问对局状态：service 持有阶段状态机与缓存，发布
`phase_changed` / `match_updated` / `display_cleared` / `account_updated` 事件；`LCUClient`
只负责进程发现、HTTP 与 WebSocket 传输，不再直接暴露给 UI/Agent。

工具通过扫描 `LeagueClientUx.exe` 进程命令行参数获取本地接口的端口与 token，然后：

1. 建立 **HTTPS 连接**（`wss://127.0.0.1:<port>/`，WAMP 子协议）订阅客户端 JSON API 事件
2. 监听 `/lol-gameflow/v1/gameflow-phase` 事件跟踪对局阶段（选人 / 对局中 / 结算）
3. 选人阶段解析 `/lol-champ-select/v1/session` 数据，展示双方玩家信息
4. 进入游戏后从 gameflow session / 战绩接口（`/lol-match-history/v1/games/{gameId}`）补齐全员信息
5. 违规数据通过自建后端 API 批量查询与标记

> 仅调用英雄联盟客户端自身的本地接口（与官方客户端同源），无需任何外部抓包或注入。

## 常见问题

**Q: 点击「启动工具」提示未找到客户端？**
A: 请确认已完整启动英雄联盟客户端并登录进入大厅（`LeagueClientUx.exe` 进程存在）。

**Q: 对局中玩家信息不显示？**
A: 读条 / 加载阶段 gameData 可能尚未就绪，工具会自动轮询（最多 90 秒）；也可点击「刷新信息」手动触发。

**Q: 英雄头像不显示？**
A: 首次使用需从 Data Dragon CDN 下载头像，网络受限时可能失败；已下载的头像会缓存到 `~/.lol_helper/icons/`，损坏的缓存会自动删除并重新下载。

**Q: 出问题时日志在哪里？**
A: 日志写入 `~/.lol_helper/logs/app.log`（滚动保留 3 份）。需要更详细的调试日志时，设置环境变量 `LOLMQ_DEBUG=1` 后启动。

## 开发与测试

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check src tests
```

解析层（`lcu/parser.py`）、大区映射和 GUI 纯函数均有单元测试，运行时不需要启动英雄联盟客户端。

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源，允许商业使用；Copyright 2026 王文豹。
