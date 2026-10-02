"""界面目录。每项只描述当前程序实际提供的功能。"""
def full_catalogue():
    return [
        {
            "module": "simulation",
            "title": "多风任务仿真",
            "capabilities": ["稳风与周期阵风", "相关随机紊流", "风估计", "位置控制与风前馈", "航点状态转换", "球形障碍物碰撞判定"],
            "source": "quadrotor_patrol_simulation.py",
        },
        {
            "module": "records",
            "title": "工程主题记录",
            "capabilities": ["人工录入", "字段校验", "SQLite 保存", "按页面筛选与统计"],
            "source": "engineering_store.py",
        },
        {
            "module": "workflow",
            "title": "资产与复核流程",
            "capabilities": ["资产登记", "缺陷记录", "人工复核", "工单状态转换"],
            "source": "workflow.py",
        },
        {
            "module": "analysis",
            "title": "任务结果分析",
            "capabilities": ["轨迹与事件导出", "任务指标计算", "配对任务比较"],
            "source": "analysis.py, comparison.py, repository.py",
        },
    ]
