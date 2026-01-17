# 目录结构说明

## 新的文件组织方式

文章 HTML 文件现在按照以下结构组织：

```
data/html/
├── en/          # 英文文章目录
│   ├── 2025-12-17_culture_author_title.html
│   └── ...
└── zh/          # 中文翻译目录
    ├── 2025-12-17_culture_author_title.html  (与英文同名)
    └── ...
```

### 关键特性

1. **文件名相同**：中英文版本使用相同的文件名
2. **目录分离**：英文文件在 `/en` 目录，中文文件在 `/zh` 目录
3. **自动匹配**：系统自动根据文件名匹配中英文版本

## 文件命名格式

文件名格式（新格式，包含source标识符）：
```
YYYY-MM-DD_source_category_author_title.html
```

示例：
- `2025-12-19_aeon_essays_author_title.html`
- `2025-06-30_nautilus_science_author_title.html`

**Source标识符**：
- `aeon` - Aeon 文章
- `nautilus` - Nautilus 文章
- `wechat` - 公众号文章
- `xiaoyuzhou` - 小宇宙文章

**注意**：
- 中文文件使用相同的文件名，存储在 `/zh` 目录中
- 系统同时支持旧格式（向后兼容），但新保存的文件将使用新格式

## 数据库存储

数据库中的路径格式：
- `html_file_en`: `en/filename.html`
- `html_file_zh`: `zh/filename.html`

## 使用方法

### 手动上传文件

1. **英文文件**：上传到 `/home/tensor/projects/articles/data/html/en/`
2. **中文文件**：上传到 `/home/tensor/projects/articles/data/html/zh/`
3. **文件名**：确保中英文文件使用相同的文件名

### 导入文章

#### 方法1：自动导入（推荐）

**服务器启动时自动导入**：
- 服务器启动时会自动检查并导入所有未导入的文章（包括手动添加的，无论日期）
- 无需任何操作，手动添加的文章会在服务器重启后自动出现

#### 方法2：通过前端界面导入

**手动上传文件后立即导入**：
1. 将HTML文件上传到 `/home/tensor/projects/articles/data/html/en/` 目录
2. 在前端界面点击"导入文章"按钮
3. 文章会自动导入到数据库并显示在列表中

#### 方法3：通过API手动触发导入

```bash
# 使用curl
curl -X POST http://localhost:8000/api/articles/import
```

#### 方法4：通过命令行脚本

```bash
cd /path/to/articles_public
python scripts/import_from_subdirs.py
```

**注意**：
- 通过URL添加文章（前端"手动添加文章"功能）会自动触发导入，无需手动操作
- 如果直接上传文件到目录，可以等待服务器重启自动导入，或立即点击"导入文章"按钮

### 移动现有文件

如果已有文件在旧位置，可以使用移动脚本：

```bash
cd /path/to/articles_public
python3 scripts/move_to_subdirs.py --source-dir data/html
```

这个脚本会：
- 将非 `zh_` 开头的文件移动到 `en/` 目录
- 将 `zh_` 开头的文件移动到 `zh/` 目录（并移除 `zh_` 前缀）

## 前端行为

- **默认语言**：中文（`zh`）
- **卡片标题**：根据全局语言设置显示中文或英文标题
- **文章内容**：根据选择的语言从对应目录加载

## 后端 API

API 会根据 `lang` 参数从正确的子目录读取文件：
- `lang=en` → 从 `/en` 目录读取
- `lang=zh` → 从 `/zh` 目录读取

## 定时任务

定时任务会自动将文件保存到正确的目录：
- 英文文件 → `data/html/en/`
- 中文翻译 → `data/html/zh/`（相同文件名）

