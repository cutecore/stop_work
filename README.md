# Stop Work

桌面上的一块电量卡片。操作耗电，停手充电。

- 连续操作 **15 分钟**，电量从满到空
- 停手 **30 分钟**，电量从空到满
- 停手大约 3 秒后才开始充电，短暂停顿仍算在使用
- 电量耗尽之后仍可继续操作，卡片会闪烁告警
- 右键卡片，或右键托盘图标，选择 QUIT 退出
- 再次启动会回到上次的电量和位置

状态写在 `%APPDATA%\StopWork\state.json`。同一时间只能开一个窗口。

## 运行

Windows，Python 3.10 或更高。

双击 `start.bat`。也可以：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe main.py
```

## 打包

双击 `build.bat`。完成后运行 `dist\StopWork.exe`。

## 测试

```bat
.venv\Scripts\python.exe -m unittest tests.test_engine
```
