# ============================================================
# 项目初始化脚本
# 用法：.\init.ps1
# ============================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  淘宝竞品价格监控系统 - 初始化" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$PROJECT_ROOT = $PSScriptRoot

# ============================================================
# 1. 检查 Python
# ============================================================
Write-Host "[1/5] 检查 Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "   Python 未安装，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}

# ============================================================
# 2. 安装依赖
# ============================================================
Write-Host "[2/5] 安装 Python 依赖..." -ForegroundColor Yellow
if (Test-Path "$PROJECT_ROOT\requirements.txt") {
    pip install -r "$PROJECT_ROOT\requirements.txt"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ 依赖安装成功" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 依赖安装失败" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  ✗ requirements.txt 不存在" -ForegroundColor Red
    exit 1
}

# ============================================================
# 3. 创建目录结构
# ============================================================
Write-Host "[3/5] 创建目录结构..." -ForegroundColor Yellow
$dirs = @(
    "$PROJECT_ROOT\project\runtime\product_raw",
    "$PROJECT_ROOT\project\runtime\product_clean",
    "$PROJECT_ROOT\project\runtime\reports",
    "$PROJECT_ROOT\project\runtime\logs"
)
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  ✓ 创建 $dir" -ForegroundColor Green
    } else {
        Write-Host "  ✓ $dir 已存在" -ForegroundColor Gray
    }
}

# ============================================================
# 4. 检查配置文件
# ============================================================
Write-Host "[4/5] 检查配置文件..." -ForegroundColor Yellow
$configFiles = @(
    "project\config\api_config.json",
    "project\config\database.json",
    "project\config\promo_dates.json"
)
foreach ($file in $configFiles) {
    $fullPath = "$PROJECT_ROOT\$file"
    if (Test-Path $fullPath) {
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $file 不存在" -ForegroundColor Red
    }
}

# ============================================================
# 5. 数据库初始化提示
# ============================================================
Write-Host "[5/5] 数据库初始化..." -ForegroundColor Yellow
$initSql = "$PROJECT_ROOT\project\config\init_database_v0.sql"
if (Test-Path $initSql) {
    Write-Host "  请手动执行以下命令初始化数据库：" -ForegroundColor Yellow
    Write-Host "  mysql -u root -p < $initSql" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  或打开 MySQL Workbench 执行 $initSql" -ForegroundColor Cyan
} else {
    Write-Host "  ✗ init_database_v0.sql 不存在" -ForegroundColor Red
}

# ============================================================
# 完成
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  初始化完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步：" -ForegroundColor Yellow
Write-Host "  1. 编辑 project\config\database.json 配置数据库" -ForegroundColor White
Write-Host "  2. 编辑 project\config\api_config.json 配置 API Token" -ForegroundColor White
Write-Host "  3. 运行影刀流程" -ForegroundColor White
Write-Host ""
