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
- 🪟 **桌面悬浮层**：跟随客户端窗口贴在旁边，选人 / 加载 / 对局中直接看到双方玩家的违规次数，不用切出游戏；可拖拽、可关闭，仅在前台时显示
- 🏷️ **违规记录查询**：批量查询对局全员违规记录，红框标注违规玩家，点击查看违规明细
- ⌨️ **全局热键速查**：复制 Riot ID 后按 `Ctrl+Alt+Q`，鼠标旁直接弹出总违规次数与分类型明细，不用切回主窗口
- 🚨 **违规标记**：选择违规类型（挂机 / 送人头 / 言语辱骂等 15 类）对玩家发起标记
- 🔍 **召唤师搜索**：通过完整 Riot ID（游戏名#TAG）搜索召唤师并查询其违规记录
- 🖼️ **英雄头像本地缓存**：Data Dragon CDN 下载头像并缓存至 `~/.lol_helper/icons/`，启动快、不重复下载
- 📱 **响应式界面**：窗口缩放自动切换队伍面板并排 / 堆叠布局

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

## 🪟 悬浮层（跟随客户端）

不想切出游戏看标记？悬浮层会把当前对局玩家的违规次数直接贴在客户端旁边：

- **开启 / 关闭**：按钮栏「悬浮层: 开 / 关」，默认开启；状态记在 `~/.lol_helper/config.json`。
- **选人阶段**：贴客户端窗口右侧显示双方队伍与「违规 N 次」，右侧空间不足会自动换到左侧。
- **加载 / 对局中**：优先贴游戏窗口右侧（全屏时贴右上角），沿用选人缓存并补齐 10 人。
- **自动查询**：进入选人 / 加载 / 对局后自动批量查询一次，结果同时刷新主窗口卡片。
- **只在前台显示**：客户端或游戏不在前台时自动隐藏，不会盖在浏览器、聊天窗口上。
- **拖动**：按住顶部标题区拖动即可换位置，位置相对客户端窗口保存；点 `×` 关闭。

> ⚠️ **限制**
> - **独占全屏看不到**：Windows 顶层悬浮窗无法覆盖独占全屏，请用窗口化 / 无边框全屏。
> - 客户端窗口最大化时，悬浮层会压在客户端右侧，拖到顺手的位置即可。
> - 敌方玩家名字在选人阶段通常是隐藏的（接口限制），要等读条 / 进游戏后才能显示完整 10 人。
> - 悬浮层只是 Win32 顶层窗口 + LCU 事件，**不注入、不修改客户端**。

## ⌨️ 全局热键速查

看到可疑玩家时，在客户端里复制他的 Riot ID（形如 `名字#TAG`），按 **`Ctrl+Alt+Q`**：

- 鼠标旁弹出结果卡片：**总违规次数 + 分类型明细**（挂机 / 送人头 / 辱骂 …），不抢焦点、不切窗口。
- 剪贴板不是有效 Riot ID 时，卡片显示 2.8 秒提示后自动消失；点 `×` 可手动关闭。
- 需要先在主窗口点 **「启动工具」**（热键查询走的是同一个 LCU 连接）。

**自定义热键**：编辑 `~/.lol_helper/config.json` 后重启：

```json
{
  "hotkey_enabled": true,
  "hotkey": "ctrl+alt+q"
}
```

修饰键支持 `ctrl` / `alt` / `shift` / `win`，主键支持 `a-z`、`0-9`、`f1-f12`。热键被其它程序占用时，主窗口「发起违规标记」按钮右侧会显示红色提示，换个组合即可。

> 热键通过 Windows `RegisterHotKey` 系统级注册，不装键盘钩子、不注入游戏；结果卡片同样是置顶、不抢焦点的小窗口。

## 构建 EXE

```bash
# 方式一：一键脚本（自动安装依赖并打包）
scripts\build_exe.bat

# 方式二：手动执行
pip install -r requirements-dev.txt
pyinstaller --noconfirm LoLMatchQuery.spec
```

产物输出至 `dist/LoLMatchQuery.exe`（单文件、免安装、含图标）。

## 项目结构

```
lol-match-query/
├── src/lol_match_query/
│   ├── app.py               # 应用入口（PyInstaller 入口脚本 / 图标解析）
│   ├── __main__.py          # python -m lol_match_query 入口
│   ├── config.py            # 界面偏好持久化（~/.lol_helper/config.json）
│   ├── logging_utils.py     # 滚动日志配置（~/.lol_helper/logs/app.log）
│   ├── lcu/
│   │   ├── client.py        # LCUClient：传输层（进程发现 / HTTP / WebSocket / 原始事件）
│   │   ├── connection.py    # LCU 进程发现与 WebSocket 客户端构造
│   │   ├── events.py        # 传输层与 service 层共享的事件/URI 常量
│   │   ├── parser.py        # 对局数据解析纯函数（选人 / gameflow / 战绩）
│   │   └── regions.py       # 大区 / platformId 映射
│   ├── services/
│   │   ├── match_monitor.py # MatchMonitorService：阶段状态机 / 缓存 / 事件源
│   │   ├── violation.py     # ViolationClient：违规标记后端 API 客户端
│   │   └── champions.py     # ChampionDataProvider：英雄头像/名称 CDN 缓存
│   ├── gui/
│   │   ├── app.py           # MatchQueryGUI 主窗口（渲染 / 监控控制）
│   │   ├── player_card.py   # PlayerCardMixin：玩家卡片组件逻辑
│   │   ├── dialogs.py       # DialogMixin：搜索 / 举报 / 违规详情对话框
│   │   ├── overlay.py       # OverlayController/OverlayWindow：跟随窗口的悬浮层
│   │   ├── overlay_model.py # 悬浮层展示模型与贴靠定位（纯函数）
│   │   ├── quick_lookup.py  # 热键速查：结果卡片 + 剪贴板查询流程
│   │   ├── quick_lookup_model.py # Riot ID 解析 / 结果摘要 / 卡片定位（纯函数）
│   │   ├── hotkey.py        # RegisterHotKey 全局热键 + 热键字符串解析
│   │   ├── win32.py         # Win32 窗口查找 / 工作区 / 前台 / 光标
│   │   └── utils.py         # GUI 通用纯函数（安全数值转换、违规详情格式化）
│   └── assets/app_icon.ico  # 应用图标（随包安装）
├── tests/                   # pytest 单元测试（解析 / 大区 / 工具函数 / 监控服务）
├── scripts/build_exe.bat    # 一键打包脚本
├── LoLMatchQuery.spec       # PyInstaller 打包配置
├── pyproject.toml           # 项目元数据、依赖与 pytest/ruff 配置
├── requirements.txt         # 运行时依赖
└── requirements-dev.txt     # 开发 / 测试 / 打包依赖
```

## 工作原理

GUI 通过 `MatchMonitorService` 访问对局状态：service 持有阶段状态机与缓存，发布
`phase_changed` / `match_updated` / `display_cleared` / `account_updated` 事件；`LCUClient`
只负责进程发现、HTTP 与 WebSocket 传输，不直接暴露给 UI。

工具通过扫描 `LeagueClientUx.exe` 进程命令行参数获取本地接口的端口与 token，然后：

1. 建立 **HTTPS 连接**（`wss://127.0.0.1:<port>/`，WAMP 子协议）订阅客户端 JSON API 事件
2. 监听 `/lol-gameflow/v1/gameflow-phase` 事件跟踪对局阶段（选人 / 对局中 / 结算）
3. 选人阶段解析 `/lol-champ-select/v1/session` 数据，展示双方玩家信息
4. 进入游戏后从 gameflow session / 战绩接口（`/lol-match-history/v1/games/{gameId}`）补齐全员信息
5. 违规数据通过自建后端 API 批量查询与标记
6. 悬浮层订阅同一批事件，用 Win32 读取客户端 / 游戏窗口位置与前台状态，只在目标窗口前台时贴靠显示
7. 热键速查用 `RegisterHotKey` 监听全局热键，读取剪贴板里的 Riot ID 后走同一套搜索 / 违规接口，结果显示在鼠标旁的卡片里

> 仅调用英雄联盟客户端自身的本地接口（与官方客户端同源），无需任何外部抓包或注入。

## 常见问题

**Q: 点击「启动工具」提示未找到客户端？**
A: 请确认已完整启动英雄联盟客户端并登录进入大厅（`LeagueClientUx.exe` 进程存在）。

**Q: 对局中玩家信息不显示？**
A: 读条 / 加载阶段 gameData 可能尚未就绪，工具会自动轮询（最多 90 秒）；也可点击「刷新信息」手动触发。

**Q: 英雄头像不显示？**
A: 首次使用需从 Data Dragon CDN 下载头像，网络受限时可能失败；已下载的头像会缓存到 `~/.lol_helper/icons/`，损坏的缓存会自动删除并重新下载。

**Q: 悬浮层不显示？**
A: 先确认按钮栏是「悬浮层: 开」；悬浮层只在英雄联盟客户端或游戏窗口处于前台时显示（切到浏览器会自动隐藏）；独占全屏下 Windows 顶层窗口无法覆盖，请改用窗口化 / 无边框全屏。怀疑位置跑偏时，可删除 `~/.lol_helper/config.json` 里的 `overlay_offset` 恢复默认。

**Q: 按了速查热键没反应？**
A: 先确认主窗口已点「启动工具」；再看「发起违规标记」右侧是否显示红色注册失败提示（说明 `Ctrl+Alt+Q` 被其它软件占用，改 `~/.lol_helper/config.json` 里的 `hotkey` 后重启）；剪贴板里要是完整 Riot ID（`名字#TAG`），只复制名字或 TAG 会提示无效。

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
