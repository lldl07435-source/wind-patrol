# 风巡智航 · 多风环境无人机巡检系统

维护版1.1.1：Python仿真、账户注册与登录、个人任务库、资产缺陷流转和配对实验。

## 运行

```text
python -m pip install -r requirements.txt
python app.py
```

打开提示地址，注册后使用。完整步骤见 docs/多用户使用与部署说明.md。旧的单用户数据库保留在原目录，可在停服后导入指定空账户。在线使用需要Python后端和持久磁盘。Docker及Render配置已准备。

```text
python manage.py test portal
python 账户实际验收.py
```

测试采用独立数据目录，不写入已有任务库。源码使用MIT许可；原始申请材料和真实用户数据不包含在源码发布包。仿真用于算法与流程验证，真实飞机测试应另记录。
