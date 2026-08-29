# VBot 路线桥接契约

PoopSense 只允许调用经过现场验证的**命名路线**，不会让大模型直接发布
`/vel_cmd` 或任意目标点。后端通过一个运行在 VBot ROS 2 通信域旁的 HTTP
桥接服务启动路线并轮询到站结果。

## 必须实现的桥接接口

### 健康检查

`GET /health`

```json
{"status": "ok", "connected": true}
```

只有 `connected=true` 时，PoopSense 才允许机械臂开始取杯。

### 启动白名单路线

`POST /api/routes/{route_name}/start`

```json
{
  "source": "poopsense",
  "require_arrival_feedback": true
}
```

返回：

```json
{"task_id": "vbot_route_001", "status": "running"}
```

未知路线必须拒绝，不能把 `route_name` 当成 shell 命令或任意 ROS 表达式执行。

### 查询路线任务

`GET /api/tasks/{task_id}`

运行中：

```json
{"task_id": "vbot_route_001", "status": "running", "progress": 0.55}
```

到站：

```json
{"task_id": "vbot_route_001", "status": "arrived", "progress": 1.0}
```

失败状态使用 `failed`、`stopped` 或 `cancelled`，并可附带 `error` 字段。

### 停止路线

`POST /api/tasks/{task_id}/stop`

停止请求必须同时取消 ROS 2 导航 Goal，并向底盘发送安全停止。

## PoopSense 配置

```powershell
$env:POOPSENSE_VBOT_BRIDGE_ENABLED="true"
$env:POOPSENSE_VBOT_BRIDGE_URL="http://192.168.126.2:8765"
$env:POOPSENSE_VBOT_ROUTE_NAME="poopsense_water_delivery"
$env:POOPSENSE_VBOT_ROUTE_TIMEOUT_SECONDS="180"
$env:POOPSENSE_ROBOT_HANDOVER_TIMEOUT_SECONDS="60"
```

完整递水任务还要求额外录入 `transport_safe` 姿态。该姿态必须让机械臂收拢、
杯子保持直立，并适合机器狗移动；不能因为“提起位”已经录入就自动复用。
安全运输位缺失、桥接未启用或桥接离线时，任务都会在任何机械臂动作发生前拒绝。

## VBot 现场识别步骤

1. 使用 VBot 的 Type-C/有线开发口连接电脑。
2. 将开发网卡设置为设备要求的固定网段，并先确认能访问 VBot 计算主板。
3. 进入板载 Ubuntu 22.04 / ROS 2 Humble 环境。
4. 执行以下只读命令，确认当前固件真实开放的接口名称：

```bash
ros2 action list -t
ros2 service list -t
ros2 topic list -t
```

5. 找出当前已录制路线对应的 Action/Service、路线标识和到站反馈。
6. 将其映射为本文的四个 HTTP 接口，再启用 PoopSense VBot Bridge。

VBot 官方公开消息仓库包含 `function_msgs/action/GoalNav.action`、
`function_msgs/action/RcpTask.action`、`function_msgs/srv/NavigateToTarget.srv`
等定义，但实际 Action/Service 名称以及已录制路线的保存方式必须以这台设备
运行中的 `ros2 ... list -t` 输出为准，不能猜测。

参考：

- https://github.com/VitaDynamics/vbot_ros2_msgs
- https://forum.vbot.cn/t/topic/103
- https://forum.vbot.cn/t/vbot-00/87

## 安全要求

- 桥接服务只监听 VBot 开发网段，不暴露到公网。
- 只允许预先配置的路线名称。
- 路线开始前确认机械臂处于安全运输位。
- 路线失败或超时时，不允许继续执行递水姿态。
- 急停必须同时停止 VBot 与机械臂。
- 如果机械臂控制 USB、电源或网线仍连接桌面电脑，禁止让 VBot 移动，避免线缆拖拽。
