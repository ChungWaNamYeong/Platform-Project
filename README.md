# Stego Platform Project

    branchtest
    
本项目是一个信息隐藏教学平台的基础骨架，包含：

- `stego_backend`：Django 后端（含 `Student` 扩展用户模型）
- `stego_frontend`：Streamlit 前端示例页面
- `docker-compose.yml`：一键启动 Django + Streamlit

## 目录结构

```text
.
├─ stego_backend/
│  ├─ manage.py
│  ├─ stego_backend/
│  │  ├─ settings.py
│  │  ├─ urls.py
│  │  ├─ asgi.py
│  │  └─ wsgi.py
│  └─ users/
│     ├─ models.py
│     ├─ admin.py
│     └─ migrations/
├─ stego_frontend/
│  └─ app.py
├─ docker-compose.yml
└─ requirements.txt
```

## 启动方式（Docker 推荐）

在项目根目录执行：

```bash
docker compose up --build
```

启动后访问：

- Django: [http://localhost:8000](http://localhost:8000)
- Streamlit: [http://localhost:8501](http://localhost:8501)

## 本地启动（可选）

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 初始化数据库并启动 Django：

```bash
python stego_backend/manage.py migrate
python stego_backend/manage.py runserver
```

3. 新开一个终端，启动 Streamlit：

```bash
streamlit run stego_frontend/app.py
```

## 说明

- Django 已配置 `AUTH_USER_MODEL = "users.Student"`，用于扩展学生用户信息。
- 后续可在 `stego_frontend/app.py` 中调用 Django API，实现教学实验交互。
