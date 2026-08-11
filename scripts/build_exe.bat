@echo off
chcp 65001 >nul
REM 一键构建 EXE：安装依赖并调用 PyInstaller spec 配置打包
echo ==========================================
echo  英雄联盟违规标记查询工具 - EXE 构建
echo ==========================================

echo [1/2] 安装依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

echo [2/2] 开始打包...
pyinstaller --noconfirm LoLMatchQuery.spec
if errorlevel 1 (
    echo 打包失败，请查看上方错误信息
    pause
    exit /b 1
)

echo.
echo 构建完成！产物: dist\LoLMatchQuery.exe
pause
