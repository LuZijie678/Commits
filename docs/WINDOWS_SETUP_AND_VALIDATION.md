# Windows 本机运行指南

本项目的历史命令、Homebrew Python 路径、`scutil` 代理读取方式和 `/private/tmp` 目录表明以前至少在 macOS 上运行过；不能仅凭这些记录断定它从未在 Linux 上运行。根目录 `Makefile` 和 Step1 的 `.sh` 脚本仍是 Unix/Bash 入口，原样放进 PowerShell 不会运行。

以下命令在仓库根目录的 **PowerShell** 执行，使用已经安装在 `.venv` 的 Python。路径包含空格时也请保留引号。不要把 API 密钥写入 Git 跟踪的配置文件。

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $python --version
git --version
& $python scripts/check_dataset_readiness.py --output tmp/windows_asset_status.json
& $python -m pytest -q tests/mica tests/generation code/step1/tests code/step2/tests
```

`scripts/check_dataset_readiness.py` 是数据就绪检查，不代表模型训练或真实 API 生成已经完成。截至 2026-09-28，本机 `.venv` 使用 Python 3.12.14，已安装的直接依赖版本记录在根目录 `requirements-windows.txt`。如需在新机器重建，先用 Python 3.12 创建 `.venv`，再按下面的命令安装并运行上面的测试；该文件不是完整传递依赖锁，实际运行前仍须重新验证。Git 必须在 `PATH` 中，Step1 可能需要 GitHub 网络访问；DeepSeek 真实调用、模型下载和 GPU 训练还取决于密钥、网络及硬件。这些条件需要分阶段验证，不应凭单元测试通过就认定端到端可复现。

本机此前的安装失败是因为进程中的三个代理变量都指向失效的 `127.0.0.1:9`。直接访问 PyPI 已验证可用；只在需要安装的 PowerShell 会话中清空这些失效变量即可，不必更改系统代理：

```powershell
$env:HTTP_PROXY = ''; $env:HTTPS_PROXY = ''; $env:ALL_PROXY = ''
& $python -m pip install --index-url https://pypi.org/simple -r requirements-windows.txt
& $python -m pip check
```

## Step1

只检查入口，不会重跑实验：

```powershell
Push-Location code/step1
& $python -m src.pipeline.run_step1 --help
Pop-Location
```

确实要重跑 Step1 时，从仓库根目录执行下面的跨平台包装器。它继承当前 Python，使用与 `.sh` 脚本相同的默认参数、环境变量和 `code/step1` 工作目录。正式运行可能耗时、访问网络并产生新输出；已存在的正式结果无需为继续 Step2 而重跑。

```powershell
& $python code/step1/scripts/run_step1_strategy_compare.py
```

如果要调整运行名，可先设置 `$env:RUN_NAME = 'my_windows_run'`；其他可调环境变量见 `code/step1/scripts/run_step1_strategy_compare.sh`，PowerShell 会传给 Python 包装器。

## Step1 到 Step2 桥接与预检

先准备本机配置；只有需要真实 API 调用时才填入自己的 `deepseek_api_key`。本机配置文件由 `.gitignore` 排除，不应提交。

```powershell
if (-not (Test-Path code/step2/configs/step2_runtime_config.local.json)) { Copy-Item code/step2/configs/step2_runtime_config.json code/step2/configs/step2_runtime_config.local.json }
New-Item -ItemType Directory -Force -Path tmp/matplotlib | Out-Null
$env:MPLCONFIGDIR = (Resolve-Path tmp/matplotlib).Path
Push-Location code/step2
& $python tools/export_step1_to_step2_source.py --input ../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv --output ../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv --manifest ../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json
& $python code/construct_simple_two_intent.py --preflight --output-dir ../../tmp/windows_step2_preflight --config configs/step2_runtime_config.local.json
Pop-Location
```

这里把预检报告写入忽略跟踪的 `tmp/`，避免诊断运行覆盖正式交付报告。`--preflight` 默认不要求真实 API 连通性，但仍检查 API 密钥是否存在；如要实际检查连通性，另外传入 `--preflight-api-ping`，这会触发网络请求。截至 2026-09-28，本机未提供 DeepSeek 密钥的预检结果为：数据、few-shot、正式资产、评分依赖、输出均通过，仅生成器因缺少密钥而不通过。`bert-score` 可导入不等于 `roberta-large` 模型已下载。Windows 不使用 macOS 的 `scutil`/`emit_proxy_env.py`；需要代理时，在当前 PowerShell 会话设置 `HTTP_PROXY`/`HTTPS_PROXY`，由 Python 网络库读取。不要把代理账号密码或 API 密钥提交。

## 其他入口

Step2 的 mock 调试与 full-scale 规划可以直接从 `code/step2` 调用，不需要 `make`：

```powershell
Push-Location code/step2
& $python code/construct_simple_two_intent.py --debug-mock-generator --config configs/step2_from_step1_source_config.json
& $python code/run_step2_fullscale_sharded.py --config configs/step2_fullscale_config.json --output-root outputs/step2_fullscale_current --plan-only
Pop-Location
```

不要把 mock 或 `--plan-only` 的成功当成真实生成成功。真实调用前先核对 `docs/CURRENT_STATUS.md` 与正式数据/模型阶段门，确认自己有数据发布与 API 使用权限。历史文档里的 macOS 路径和命令只反映当时机器，不能直接复制到 Windows。
