# 开发指南：文件修改后的生效方式

## 项目架构说明

本项目在本地运行，所有文件直接修改即可。

## 文件修改后的操作指南

### 1. 只需刷新浏览器（硬刷新）

**适用文件：**
- `static/index.html` - 前端 HTML
- `static/*.css` - 样式文件
- `static/*.js` - JavaScript 文件（如果有）

**操作：**
```bash
# 浏览器中按 Ctrl+F5 (Windows/Linux) 或 Cmd+Shift+R (Mac)
# 或清除浏览器缓存
```

**原因：** FastAPI 通过 `StaticFiles` 直接服务静态文件，修改后立即生效。但浏览器可能缓存旧文件，需要硬刷新。

**注意：** 如果使用 `uvicorn --reload` 运行，修改 Python 代码后会自动重新加载。

---

### 2. 需要重启服务器（Docker 容器）

**适用文件：**
- `app/**/*.py` - 所有 Python 代码文件
  - `app/main.py` - 主应用文件
  - `app/routers/*.py` - API 路由
  - `app/services/**/*.py` - 服务层代码
  - `app/models.py` - 数据模型
  - `app/database.py` - 数据库配置
  - `app/config.py` - 配置文件
- `scripts/*.py` - 脚本文件（如果被 Python 模块导入）

**操作：**
```bash
# 如果使用 uvicorn --reload，会自动重新加载
# 否则需要重启服务器：按 Ctrl+C 停止，然后重新运行
python -m app.main
# 或
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**原因：** Python 的模块导入机制会缓存已导入的模块。修改后的代码需要重新加载到运行中的进程。

**特殊情况：**
- 如果修改了 `requirements.txt`，需要重新安装依赖：
  ```bash
  pip install -r requirements.txt
  ```

---

### 3. 需要清除 Python 缓存 + 重启服务器

**适用场景：**
- 删除 Python 文件后
- 重命名 Python 文件/类/函数后
- 修改了 `__init__.py` 中的导入

**操作：**
```bash
# 清除 Python 缓存
find app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find app -name "*.pyc" -delete

# 重启服务器
# 按 Ctrl+C 停止，然后重新运行
python -m app.main
```

**原因：** Python 会缓存编译后的 `.pyc` 文件，删除或重命名文件后，缓存可能仍然存在。

---

### 4. 数据文件（无需操作）

**适用文件：**
- `data/html/**/*.html` - 文章 HTML 文件
- `data/logs/*.log` - 日志文件
- `data/articles.db` - 数据库文件

**操作：** 无需任何操作，修改后立即生效

---

## 快速参考表

| 文件类型 | 修改后需要 | 命令 |
|---------|-----------|------|
| `static/*.html` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `static/*.css` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `static/*.js` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `app/**/*.py` | 重启服务器（或使用 --reload） | `python -m app.main` 或 `uvicorn --reload` |
| `scripts/*.py` | 重启服务器（如果被导入） | `python -m app.main` |
| `requirements.txt` | 重新安装依赖 + 重启 | `pip install -r requirements.txt` |
| `data/**/*` | 无需操作 | - |

---

## 常见场景

### 场景 1：修改前端 HTML/CSS
```bash
# 1. 修改 static/index.html
# 2. 浏览器硬刷新（Ctrl+F5）
# ✅ 完成
```

### 场景 2：修改 Python 代码（如添加新的 scraper）
```bash
# 1. 修改 app/services/scrapers/aeon.py
# 2. 如果使用 --reload，会自动重新加载
#    否则需要重启服务器（按 Ctrl+C，然后重新运行）
python -m app.main

# 3. 验证
# 查看日志或访问 http://localhost:8000
# ✅ 完成
```

### 场景 3：删除或重命名 Python 文件
```bash
# 1. 删除/重命名文件
# 2. 清除缓存
find app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 3. 重启服务器
# 按 Ctrl+C 停止，然后重新运行
python -m app.main
# ✅ 完成
```

### 场景 4：添加新的 Python 依赖
```bash
# 1. 修改 requirements.txt
# 2. 重新安装依赖
pip install -r requirements.txt

# 3. 重启服务器
# 按 Ctrl+C 停止，然后重新运行
python -m app.main
# ✅ 完成
```

---

## 验证修改是否生效

### 验证 Python 代码
```bash
# 测试导入
python -c "from app.services.scrapers import AeonScraper; print('OK')"
```

### 验证静态文件
```bash
# 检查文件内容
cat static/index.html | grep "aeon"
```

### 查看服务器日志
```bash
# 实时查看日志
tail -f data/logs/articles.log

# 查看最近 50 行
tail -n 50 data/logs/articles.log
```

---

## 注意事项

1. **Python 模块缓存**：Python 不会自动重新加载已导入的模块。必须重启进程或使用 `uvicorn --reload`。

2. **浏览器缓存**：静态文件修改后，浏览器可能使用缓存版本。使用硬刷新（Ctrl+F5）强制重新加载。

3. **热重载**：开发时可以使用 `uvicorn --reload` 实现自动重新加载：
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

4. **数据库迁移**：如果修改了数据模型，可能需要运行迁移脚本（本项目使用 SQLite，通常不需要）。

5. **环境变量**：修改环境变量需要重启服务器才能生效。

