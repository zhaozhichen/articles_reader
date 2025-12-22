# 开发指南：文件修改后的生效方式

## 项目架构说明

本项目使用 Docker 容器运行，以下目录通过 **volume 挂载**（修改后立即同步到容器）：
- `app/` → `/app/app` (Python 应用代码)
- `static/` → `/app/static` (前端静态文件)
- `scripts/` → `/app/scripts` (脚本文件)
- `data/` → `/app/data` (数据文件)

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
# 重启容器
docker restart ktizo-articles

# 查看日志确认启动成功
docker logs ktizo-articles --tail 20
```

**原因：** Python 的模块导入机制会缓存已导入的模块。即使文件通过 volume 挂载，修改后的代码不会自动重新加载到运行中的进程。

**特殊情况：**
- 如果修改了 `requirements.txt`，需要重新构建镜像：
  ```bash
  docker build -t articles:latest .
  docker compose up -d articles  # 或重启容器
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
docker exec ktizo-articles find /app/app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
docker exec ktizo-articles find /app/app -name "*.pyc" -delete

# 重启容器
docker restart ktizo-articles
```

**原因：** Python 会缓存编译后的 `.pyc` 文件，删除或重命名文件后，缓存可能仍然存在。

---

### 4. 数据文件（无需操作）

**适用文件：**
- `data/html/**/*.html` - 文章 HTML 文件
- `data/logs/*.log` - 日志文件
- `data/articles.db` - 数据库文件

**操作：** 无需任何操作，修改后立即生效（因为通过 volume 挂载）

---

## 快速参考表

| 文件类型 | 修改后需要 | 命令 |
|---------|-----------|------|
| `static/*.html` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `static/*.css` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `static/*.js` | 刷新浏览器（硬刷新） | `Ctrl+F5` 或 `Cmd+Shift+R` |
| `app/**/*.py` | 重启容器 | `docker restart ktizo-articles` |
| `scripts/*.py` | 重启容器（如果被导入） | `docker restart ktizo-articles` |
| `requirements.txt` | 重建镜像 + 重启 | `docker build -t articles:latest .` |
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
# 1. 修改 app/services/scrapers/atlantic.py
# 2. 重启容器
docker restart ktizo-articles

# 3. 验证
docker logs ktizo-articles --tail 20
# ✅ 完成
```

### 场景 3：删除或重命名 Python 文件
```bash
# 1. 删除/重命名文件
# 2. 清除缓存
docker exec ktizo-articles find /app/app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# 3. 重启容器
docker restart ktizo-articles
# ✅ 完成
```

### 场景 4：添加新的 Python 依赖
```bash
# 1. 修改 requirements.txt
# 2. 重建镜像
docker build -t articles:latest .

# 3. 重启容器（使用新镜像）
docker compose up -d articles
# 或
docker restart ktizo-articles
# ✅ 完成
```

---

## 验证修改是否生效

### 验证 Python 代码
```bash
# 在容器中测试导入
docker exec ktizo-articles python -c "from app.services.scrapers import AtlanticScraper; print('OK')"
```

### 验证静态文件
```bash
# 检查文件是否在容器中
docker exec ktizo-articles cat /app/static/index.html | grep "atlantic"
```

### 查看服务器日志
```bash
# 实时查看日志
docker logs -f ktizo-articles

# 查看最近 50 行
docker logs ktizo-articles --tail 50
```

---

## 注意事项

1. **Python 模块缓存**：即使文件通过 volume 挂载，Python 不会自动重新加载已导入的模块。必须重启进程。

2. **浏览器缓存**：静态文件修改后，浏览器可能使用缓存版本。使用硬刷新（Ctrl+F5）强制重新加载。

3. **热重载**：本项目没有配置热重载（如 `uvicorn --reload`），因为生产环境不需要。开发时可以考虑添加。

4. **数据库迁移**：如果修改了数据模型，可能需要运行迁移脚本（本项目使用 SQLite，通常不需要）。

5. **环境变量**：修改环境变量需要重启容器才能生效。

